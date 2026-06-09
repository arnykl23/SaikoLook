"""永続化層（Repository ポートの具象実装）.

build_repository が settings.database_url で engine を構築・テーブル初期化し,
Repository 実装（SqlRepository）を返す. 上位層は build_repository と
Repository ポートだけに依存し, SQLAlchemy の詳細を知らない.
"""

from app.config import Settings
from app.ports.repository import Repository
from app.repositories.db import configure_engine, init_db
from app.repositories.sql_repository import SqlRepository

__all__ = ["build_repository", "SqlRepository"]


def build_repository(settings: Settings) -> Repository:
    """settings.database_url で engine を構築・初期化し Repository を返す."""
    configure_engine(settings.database_url)
    init_db()
    return SqlRepository()
