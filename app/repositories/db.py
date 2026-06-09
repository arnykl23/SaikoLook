"""DB 基盤（engine / SessionLocal / Base / init_db）.

SQLAlchemy 2.0 の宣言基底 Base と, 既定設定から構築した engine・SessionLocal を
公開する. build_repository が settings.database_url で engine を差し替えられるよう,
configure_engine() は SessionLocal の識別子を保ったまま bind を貼り替える
（デフォルト引数 session_factory=SessionLocal の契約を壊さないため）.

SQLite（PoC 既定）/ Postgres（Supabase）双方を同一コードで扱う.
"""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings

Base = declarative_base()


def _is_memory_sqlite(url: str) -> bool:
    return url.startswith("sqlite") and (":memory:" in url or url == "sqlite://")


def _engine_kwargs(url: str) -> dict:
    if not url.startswith("sqlite"):
        return {}
    # SQLite は別スレッドからの利用を許可. in-memory は StaticPool で
    # 単一コネクションを共有し, セッションを跨いでも同じ DB を見せる.
    kwargs: dict = {"connect_args": {"check_same_thread": False}}
    if _is_memory_sqlite(url):
        kwargs["poolclass"] = StaticPool
    return kwargs


def _ensure_sqlite_dir(url: str) -> None:
    prefix = "sqlite:///"
    if not url.startswith(prefix) or _is_memory_sqlite(url):
        return
    path = url[len(prefix):]
    if path:
        parent = Path(path).parent
        if parent and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)


def _make_engine(url: str) -> Engine:
    _ensure_sqlite_dir(url)
    return create_engine(url, future=True, **_engine_kwargs(url))


engine: Engine = _make_engine(get_settings().database_url)
SessionLocal = sessionmaker(
    bind=engine, autoflush=False, expire_on_commit=False, future=True
)


def configure_engine(database_url: str) -> Engine:
    """engine を差し替え, SessionLocal を新 engine へ再バインドする.

    SessionLocal の識別子は維持するため, 既存の import 参照やデフォルト引数は
    そのまま新 engine を使う.
    """
    global engine
    engine = _make_engine(database_url)
    SessionLocal.configure(bind=engine)
    return engine


def init_db() -> None:
    """テーブルを作成する（Base.metadata.create_all）. 冪等."""
    # ORM を import して Base にテーブルを登録してから作成する.
    import app.repositories.orm  # noqa: F401

    Base.metadata.create_all(bind=engine)
