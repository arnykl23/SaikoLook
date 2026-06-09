"""Alembic 環境設定.

DB URL は app.config.Settings.database_url から取得し, alembic.ini には
書かない（秘密情報・接続先をコミットしないため）. メタデータは
app.repositories.db.Base を target にし, ORM を import して登録する.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings
from app.repositories.db import Base
import app.repositories.orm  # noqa: F401  ORM をメタデータへ登録

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# settings から URL を注入（ini には残さない）.
config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        is_sqlite = connection.dialect.name == "sqlite"
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=is_sqlite,  # SQLite の ALTER 制約回避.
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
