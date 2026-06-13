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

    def get_by_id(self, account_id: str) -> "AccountConfigORM | None":
        with self._session_factory() as session:
            return session.get(AccountConfigORM, account_id)

    def list_all(self) -> list[AccountConfig]:
        """レスポンス用（認証情報を含まない）."""
        stmt = select(AccountConfigORM).order_by(AccountConfigORM.created_at)
        with self._session_factory() as session:
            rows = session.execute(stmt).scalars().all()
            return [
                AccountConfig(
                    id=r.id, provider=r.provider, label=r.label,
                    address=r.address, auth_type=r.auth_type, auth_status=r.auth_status,
                    created_at=r.created_at,
                )
                for r in rows
            ]

    def list_for_ingest(self) -> list[dict]:
        """取り込み用（credential 含む）. 戻り値はログに出さないこと（LLM02 対策）."""
        stmt = select(AccountConfigORM)
        with self._session_factory() as session:
            rows = session.execute(stmt).scalars().all()
            return [
                {
                    "id": r.id,
                    "provider": r.provider,
                    "address": r.address,        # 既存キー — 残す
                    "credential": r.credential,  # 既存キー — 残す
                    "auth_type": r.auth_type or "imap",
                    "refresh_token": r.refresh_token,
                    "access_token": r.access_token,
                    "auth_status": r.auth_status or "ok",
                }
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
                id=orm.id, provider=orm.provider, label=orm.label,
                address=orm.address,
                auth_type="imap",
                auth_status="ok",
                created_at=orm.created_at,
            )

    def create_oauth(
        self, *, provider: str, label: str, address: str,
        refresh_token: str, access_token: str | None = None,
        token_expiry: "datetime | None" = None, scopes: str = "",
        auth_status: str = "ok",
    ) -> AccountConfig:
        now = _utcnow_naive()
        orm = AccountConfigORM(
            id=str(uuid.uuid4()),
            provider=provider,
            label=label,
            address=address,
            credential="",
            auth_type="oauth",
            refresh_token=refresh_token,
            access_token=access_token,
            token_expiry=token_expiry,
            scopes=scopes,
            auth_status=auth_status,
            created_at=now,
        )
        with self._session_factory() as session:
            session.add(orm)
            session.commit()
            return AccountConfig(
                id=orm.id, provider=orm.provider, label=orm.label,
                address=orm.address, auth_type=orm.auth_type, auth_status=orm.auth_status,
                created_at=orm.created_at,
            )

    def upsert_github_oauth(
        self, *, label: str, address: str, access_token: str, scopes: str,
    ) -> AccountConfig:
        """GitHub アカウントを upsert（既存なら上書き、なければ作成）."""
        stmt = select(AccountConfigORM).where(AccountConfigORM.provider == "github")
        with self._session_factory() as session:
            row = session.execute(stmt).scalars().first()
            if row is not None:
                row.label = label
                row.address = address
                row.access_token = access_token
                row.scopes = scopes
                row.auth_status = "ok"
                session.commit()
                return AccountConfig(
                    id=row.id, provider=row.provider, label=row.label,
                    address=row.address, auth_type=row.auth_type, auth_status=row.auth_status,
                    created_at=row.created_at,
                )
            now = _utcnow_naive()
            orm = AccountConfigORM(
                id=str(uuid.uuid4()),
                provider="github",
                label=label,
                address=address,
                credential="",
                auth_type="oauth",
                refresh_token="",
                access_token=access_token,
                token_expiry=None,
                scopes=scopes,
                auth_status="ok",
                created_at=now,
            )
            session.add(orm)
            session.commit()
            return AccountConfig(
                id=orm.id, provider=orm.provider, label=orm.label,
                address=orm.address, auth_type=orm.auth_type, auth_status=orm.auth_status,
                created_at=orm.created_at,
            )

    def update_oauth_tokens(
        self, account_id: str, *, refresh_token: str,
        access_token: "str | None", token_expiry: "datetime | None", scopes: str,
    ) -> None:
        with self._session_factory() as session:
            row = session.get(AccountConfigORM, account_id)
            if row is None:
                return
            row.refresh_token = refresh_token
            row.access_token = access_token
            row.token_expiry = token_expiry
            row.scopes = scopes
            row.auth_status = "ok"
            session.commit()

    def set_auth_status(self, account_id: str, auth_status: str) -> None:
        with self._session_factory() as session:
            row = session.get(AccountConfigORM, account_id)
            if row is None:
                return
            row.auth_status = auth_status
            session.commit()

    def get_history_id(self, account_id: str) -> str | None:
        """Gmail History API カーソル（last_history_id）を取得する."""
        with self._session_factory() as session:
            row = session.get(AccountConfigORM, account_id)
            return row.last_history_id if row is not None else None

    def set_history_id(self, account_id: str, history_id: str) -> None:
        """Gmail History API カーソルを保存する. 対象が無ければ no-op."""
        with self._session_factory() as session:
            row = session.get(AccountConfigORM, account_id)
            if row is None:
                return
            row.last_history_id = history_id
            session.commit()

    def delete(self, account_id: str) -> bool:
        """削除. 見つかった場合 True, なければ False."""
        with self._session_factory() as session:
            row = session.get(AccountConfigORM, account_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
        return True
