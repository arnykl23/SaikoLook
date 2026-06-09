"""アカウント設定リポジトリ.

Gmail / 将来 Slack・Outlook のアカウント設定を SQLite に保存する.
credential（アプリパスワード等）は PoC のため平文保存.
本番環境では必ず暗号化すること（Fernet / SQLCipher 等）.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.models import AccountConfig
from app.repositories import db
from app.repositories.orm import AccountConfigORM


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AccountRepository:
    """アカウント設定の永続化."""

    def __init__(self, session_factory=None) -> None:
        self._session_factory = session_factory or db.SessionLocal

    def list_all(self) -> list[AccountConfig]:
        """レスポンス用（認証情報を含まない）."""
        stmt = select(AccountConfigORM).order_by(AccountConfigORM.created_at)
        with self._session_factory() as session:
            rows = session.execute(stmt).scalars().all()
            return [
                AccountConfig(
                    id=r.id, provider=r.provider, label=r.label, created_at=r.created_at
                )
                for r in rows
            ]

    def list_for_ingest(self) -> list[dict]:
        """取り込み用（credential 含む）. 戻り値はログに出さないこと（LLM02 対策）."""
        stmt = select(AccountConfigORM)
        with self._session_factory() as session:
            rows = session.execute(stmt).scalars().all()
            return [
                {"provider": r.provider, "address": r.address, "credential": r.credential}
                for r in rows
            ]

    def create(
        self, *, provider: str, label: str, address: str, credential: str
    ) -> AccountConfig:
        now = _utcnow_naive()
        orm = AccountConfigORM(
            id=str(uuid.uuid4()),
            provider=provider,
            label=label,
            address=address,
            credential=credential,
            created_at=now,
        )
        with self._session_factory() as session:
            session.add(orm)
            session.commit()
            return AccountConfig(
                id=orm.id, provider=orm.provider, label=orm.label, created_at=orm.created_at
            )

    def delete(self, account_id: str) -> bool:
        """削除. 見つかった場合 True, なければ False."""
        with self._session_factory() as session:
            row = session.get(AccountConfigORM, account_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
        return True
