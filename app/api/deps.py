"""API 層の依存性注入.

lifespan で app.state に組んだ各層（settings/repo/ingestion/state_service）を
ルートへ供給する. 取得は app.state からのみ行い, グローバル状態を増やさない.
require_auth は auth_enabled に応じて Bearer 検証 or 素通りを返す.
"""

import jwt
from fastapi import Depends, Header, HTTPException, Request, status

from app.api.auth import decode_token
from app.config import Settings
from app.ports import Repository
from app.repositories.account_repository import AccountRepository
from app.services.ingestion import IngestionService
from app.services.oauth_gmail import OAuthGmailService
from app.services.state_service import StateService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_repo(request: Request) -> Repository:
    return request.app.state.repo


def get_ingestion(request: Request) -> IngestionService:
    return request.app.state.ingestion


def get_state_service(request: Request) -> StateService:
    return request.app.state.state_service


def get_account_repo(request: Request) -> AccountRepository:
    return request.app.state.account_repo


def get_oauth_service(request: Request) -> OAuthGmailService:
    return request.app.state.oauth_service


def require_auth(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    """保護ルートの認証依存.

    auth_enabled=False なら素通り. True なら Authorization: Bearer <token> を
    要求し, JWT を検証する. 失敗は 401.
    """
    settings: Settings = request.app.state.settings
    if not settings.auth_enabled:
        return

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="認証が必要です",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization[len("Bearer ") :].strip()
    try:
        decode_token(settings, token)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="トークンが無効です",
            headers={"WWW-Authenticate": "Bearer"},
        )


# 保護ルートに付ける共通依存（戻り値は使わない）.
AuthDep = Depends(require_auth)
