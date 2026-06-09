"""SqlRepository（Repository ポートの SQLAlchemy 実装）.

MessageRecord の冪等 upsert・問い合わせ・楽観ロック付き状態遷移を担う.
SQL は SQLAlchemy 経由で組み立て, 生 SQL 文字列連結はしない（injection 対策）.
本文（個人情報）はログに出さない.

時刻は UTC で扱う. DateTime 列には tz-naive な UTC 値を格納し, 読み出し時に
tzinfo=UTC を再付与して aware な datetime として返す（SQLite が tz を落とすため）.
"""

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from app.domain.fsm import assert_transition
from app.models import AnalysisResult, EmailMessage, MessageRecord, MessageState
from app.ports.errors import ConflictError, NotFoundError
from app.ports.repository import MessageQuery
from app.repositories import db
from app.repositories.orm import MessageRecordORM

_ORDER_COLUMNS = {
    "triage_score": MessageRecordORM.triage_score,
    "received_at": MessageRecordORM.received_at,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_naive_utc(dt: datetime | None) -> datetime | None:
    """aware/naive いずれの datetime も naive UTC へ正規化して列に格納する."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _to_aware_utc(dt: datetime | None) -> datetime | None:
    """列から読んだ naive UTC を aware UTC へ戻す."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_record(orm: MessageRecordORM) -> MessageRecord:
    """ORM 行を pydantic の MessageRecord へ写像する."""
    analysis = (
        AnalysisResult.model_validate(orm.analysis)
        if orm.analysis is not None
        else None
    )
    return MessageRecord(
        message_id=orm.message_id,
        email=EmailMessage.model_validate(orm.email),
        analysis=analysis,
        state=MessageState(orm.state),
        triage_score=orm.triage_score,
        version=orm.version,
        created_at=_to_aware_utc(orm.created_at),
        updated_at=_to_aware_utc(orm.updated_at),
    )


class SqlRepository:
    """Repository ポートの SQLAlchemy 実装."""

    def __init__(self, session_factory: sessionmaker | None = None) -> None:
        # 既定は db.SessionLocal（configure_engine で再バインドされる識別子）を
        # 実行時に解決する. テストや別 DB 接続は session_factory で差し替える.
        self._session_factory = session_factory or db.SessionLocal

    def upsert_messages(self, records: list[MessageRecord]) -> int:
        """message_id をキーに冪等 upsert する. 新規挿入件数を返す.

        既存行の state/version/created_at はユーザー操作を尊重して保持し,
        email/analysis/triage_score/is_unread/received_at/updated_at のみ更新する.
        """
        if not records:
            return 0
        inserted = 0
        now = _to_naive_utc(_utcnow())
        with self._session_factory() as session:
            for record in records:
                existing = session.get(MessageRecordORM, record.message_id)
                email_json = record.email.model_dump(mode="json")
                analysis_json = (
                    record.analysis.model_dump(mode="json")
                    if record.analysis is not None
                    else None
                )
                received_at = _to_naive_utc(record.email.received_at)
                if existing is None:
                    session.add(
                        MessageRecordORM(
                            message_id=record.message_id,
                            email=email_json,
                            analysis=analysis_json,
                            state=record.state.value,
                            triage_score=record.triage_score,
                            is_unread=record.email.is_unread,
                            received_at=received_at,
                            version=record.version,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    inserted += 1
                else:
                    existing.email = email_json
                    existing.analysis = analysis_json
                    existing.triage_score = record.triage_score
                    existing.is_unread = record.email.is_unread
                    existing.received_at = received_at
                    existing.updated_at = now
                    # state / version / created_at は保持.
            session.commit()
        return inserted

    def get(self, message_id: str) -> MessageRecord | None:
        with self._session_factory() as session:
            orm = session.get(MessageRecordORM, message_id)
            return _to_record(orm) if orm is not None else None

    def query(self, q: MessageQuery) -> list[MessageRecord]:
        order_col = _ORDER_COLUMNS.get(q.order_by, MessageRecordORM.triage_score)
        direction = order_col.desc() if q.descending else order_col.asc()
        stmt = select(MessageRecordORM)
        if q.state is not None:
            stmt = stmt.where(MessageRecordORM.state == q.state.value)
        if q.unread_only:
            stmt = stmt.where(MessageRecordORM.is_unread.is_(True))
        # message_id を第2キーにして決定的な順序にする.
        stmt = stmt.order_by(direction, MessageRecordORM.message_id.asc())
        stmt = stmt.limit(q.limit).offset(q.offset)
        with self._session_factory() as session:
            rows = session.execute(stmt).scalars().all()
            return [_to_record(r) for r in rows]

    def update_state(
        self, message_id: str, new_state: MessageState, expected_version: int
    ) -> MessageRecord:
        """状態遷移（楽観ロック）. 更新後のレコードを返す.

        - 対象無し → NotFoundError
        - FSM 上不正な遷移 → TransitionError
        - expected_version != 現在 version → ConflictError
        成功時 version += 1, updated_at を更新する.
        """
        with self._session_factory() as session:
            current = session.get(MessageRecordORM, message_id)
            if current is None:
                raise NotFoundError(f"message_id={message_id} は存在しません")
            assert_transition(message_id, MessageState(current.state), new_state)
            actual_version = current.version
            now = _to_naive_utc(_utcnow())
            stmt = (
                update(MessageRecordORM)
                .where(
                    MessageRecordORM.message_id == message_id,
                    MessageRecordORM.version == expected_version,
                )
                .values(
                    state=new_state.value,
                    version=MessageRecordORM.version + 1,
                    updated_at=now,
                )
            )
            result = session.execute(stmt)
            if result.rowcount == 0:
                session.rollback()
                raise ConflictError(message_id, expected_version, actual_version)
            session.commit()
            refreshed = session.get(MessageRecordORM, message_id)
            return _to_record(refreshed)
