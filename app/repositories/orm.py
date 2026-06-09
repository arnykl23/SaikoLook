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
    # 絞り込み・並べ替え用の非正規化列（email から複写）.
    is_unread: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
