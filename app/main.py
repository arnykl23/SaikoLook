"""ReplyGuard API.

全層（取得・分析・採点・永続化・通知）を lifespan で結線し FastAPI で公開する.
PoC 時代の GET /emails / GET /health の形は後方互換で維持する. ドメイン例外を
HTTP ステータスへ写像し, 周期取り込みを APScheduler で回す.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.adapters.sources import build_source
from app.analysis.factory import build_analyzer
from app.api import routes_emails, routes_messages
from app.config import get_settings
from app.notify.factory import build_notifier
from app.ports.errors import ConflictError, NotFoundError, TransitionError
from app.repositories import build_repository
from app.scheduler import start_scheduler
from app.services.ingestion import IngestionService
from app.services.state_service import StateService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # 認証を有効化するなら署名鍵が必須（弱い既定で起動させない）.
    if settings.auth_enabled and not settings.jwt_secret:
        raise RuntimeError(
            "auth_enabled=True には JWT_SECRET の設定が必須です"
        )

    repo = build_repository(settings)          # init_db 込み
    source = build_source(settings)
    analyzer = build_analyzer(settings)
    notifier = build_notifier(settings)
    ingestion = IngestionService(source, analyzer, repo, notifier, settings)
    state_service = StateService(repo)

    app.state.settings = settings
    app.state.repo = repo
    app.state.source = source
    app.state.analyzer = analyzer
    app.state.notifier = notifier
    app.state.ingestion = ingestion
    app.state.state_service = state_service
    app.state.scheduler = None

    if settings.ingest_on_startup:
        try:
            ingestion.run_once()
        except Exception:
            logger.exception("起動時の取り込みに失敗（アプリは継続）")

    if settings.scheduler_enabled:
        app.state.scheduler = start_scheduler(ingestion, settings)

    try:
        yield
    finally:
        if app.state.scheduler is not None:
            app.state.scheduler.shutdown(wait=False)
        try:
            source.close()
        except Exception:
            logger.exception("source.close に失敗")


app = FastAPI(title="ReplyGuard API", version="0.2.0", lifespan=lifespan)

# CORS は許可 origin を明示（ワイルドカード禁止）. 別オリジンの悪意あるサイトから
# 受信トレイのプレビューを読まれないよう, フロントの origin だけ許可する.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().origins_list,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.exception_handler(NotFoundError)
async def _not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ConflictError)
async def _conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "detail": str(exc),
            "expected_version": exc.expected,
            "actual_version": exc.actual,
        },
    )


@app.exception_handler(TransitionError)
async def _transition_handler(
    request: Request, exc: TransitionError
) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(routes_emails.router)
app.include_router(routes_messages.router)
