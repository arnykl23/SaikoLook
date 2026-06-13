"""ReplyGuard API.

全層（取得・分析・採点・永続化・通知）を lifespan で結線し FastAPI で公開する.
PoC 時代の GET /emails / GET /health の形は後方互換で維持する. ドメイン例外を
HTTP ステータスへ写像し, 周期取り込みを APScheduler で回す.
"""

import logging
from contextlib import asynccontextmanager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%H:%M:%S",
)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.analysis.factory import build_analyzer
from app.api import (
    routes_accounts,
    routes_emails,
    routes_github_oauth,
    routes_messages,
    routes_oauth,
)
from app.services.oauth_gmail import OAuthGmailService
from app.services.oauth_github import OAuthGithubService
from app.config import get_settings
from app.notify.factory import build_notifier
from app.ports.errors import ConflictError, NotFoundError, TransitionError
from app.repositories import build_repository
from app.repositories.account_repository import AccountRepository
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
    account_repo = AccountRepository()
    analyzer = build_analyzer(settings)
    notifier = build_notifier(settings)
    ingestion = IngestionService(account_repo, analyzer, repo, notifier, settings)
    state_service = StateService(repo)

    app.state.settings = settings
    app.state.repo = repo
    app.state.account_repo = account_repo
    app.state.analyzer = analyzer
    app.state.notifier = notifier
    app.state.ingestion = ingestion
    app.state.state_service = state_service
    app.state.oauth_service = OAuthGmailService(
        client_id=settings.gmail_oauth_client_id,
        client_secret=settings.gmail_oauth_client_secret,
        redirect_uri=settings.gmail_oauth_redirect_uri,
    )
    app.state.github_oauth_service = OAuthGithubService(
        client_id=settings.github_oauth_client_id,
        client_secret=settings.github_oauth_client_secret,
        redirect_uri=settings.github_oauth_redirect_uri,
    )
    app.state.scheduler = None

    # env 変数にアカウントが設定されていて DB に未登録なら自動登録する.
    if settings.gmail_address and settings.gmail_app_password:
        existing_addresses = {a["address"] for a in account_repo.list_for_ingest()}
        if settings.gmail_address not in existing_addresses:
            try:
                account_repo.create(
                    provider="gmail",
                    label=settings.gmail_address,
                    address=settings.gmail_address,
                    credential=settings.gmail_app_password,
                )
                logger.info("env 変数のアカウントを DB に自動登録: %s", settings.gmail_address)
            except Exception:
                logger.exception("env 変数のアカウント自動登録に失敗（起動は継続）")

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


app = FastAPI(title="ReplyGuard API", version="0.2.0", lifespan=lifespan)

# CORS は許可 origin を明示（ワイルドカード禁止）. 別オリジンの悪意あるサイトから
# 受信トレイのプレビューを読まれないよう, フロントの origin だけ許可する.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().origins_list,
    allow_methods=["GET", "POST", "DELETE"],
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
app.include_router(routes_accounts.router)
app.include_router(routes_oauth.router)
app.include_router(routes_github_oauth.router)
