"""ORM テーブル定義（message_records）.

MessageRecord の永続化テーブル. email/analysis は pydantic を JSON 列へ
そのまま格納する（プロバイダ非依存スキーマを崩さない）. 一方,
SQL レベルでの絞り込み・並べ替えに使う is_unread / received_at /
triage_score / state は非正規化した実列として持つ（JSON パスへの
DB 依存クエリを避け, SQLite/Postgres 双方で同一に動かすため）.
"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.repositories.db import Base


class MessageRecordORM(Base):
    __tablename__ = "message_records"

    message_id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[dict] = mapped_column(JSON, nullable=False)
    analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    state: Mapped[str] = mapped_column(String, nullable=False, default="unhandled")
    triage_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    urgency_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    # 絞り込み・並べ替え用の非正規化列（email から複写）.
    is_unread: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 絞り込み・プロバイダフィルタ用の非正規化列（email.provider から複写）.
    provider: Mapped[str] = mapped_column(
        String, nullable=False, default="gmail", index=True
    )
    # アカウントフィルタ用（受信アカウントのメールアドレス）.
    account_address: Mapped[str] = mapped_column(
        String, nullable=False, default="", server_default="", index=True
    )
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AccountConfigORM(Base):
    """アカウント設定テーブル（Gmail / 将来 Slack・Outlook）.

    PoC: credential（アプリパスワード等）は平文保存.
    本番環境では必ず暗号化すること（Fernet / SQLCipher 等）.
    DB ファイル（data/SaikoLook.db）は .gitignore 済みのため, ローカル PoC では許容.
    """

    __tablename__ = "account_configs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    provider: Mapped[str] = mapped_column(String, nullable=False, index=True)
    label: Mapped[str] = mapped_column(String, nullable=False)
    address: Mapped[str] = mapped_column(String, nullable=False)
    credential: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    auth_type:     Mapped[str]            = mapped_column(String, nullable=False, default="imap")
    refresh_token: Mapped[str | None]     = mapped_column(String, nullable=True)
    access_token:  Mapped[str | None]     = mapped_column(String, nullable=True)
    token_expiry:  Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scopes:        Mapped[str | None]     = mapped_column(String, nullable=True)
    auth_status:   Mapped[str]            = mapped_column(String, nullable=False, default="ok")
    last_history_id: Mapped[str | None]  = mapped_column(String, nullable=True)
