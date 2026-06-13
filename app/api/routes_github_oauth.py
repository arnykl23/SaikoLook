"""GitHub OAuth 2.0 フローのエンドポイント.

GET  /auth/github/start?label=<>             認可 URL 発行
GET  /auth/github/callback?code=<>&state=<>  コールバック受信 → 302 リダイレクト
POST /auth/github/{account_id}/reauth        失効アカウントの再接続 URL 発行

OAuth App（classic・notifications scope）の web flow. Gmail 版（routes_oauth.py）を
複製したもの. GitHub は PKCE 不要・refresh token 非発行のため, callback で
access_token のみを保存し, address は GET /user の login で確定する.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from app.api.deps import get_account_repo, get_github_oauth_service, get_settings
from app.config import Settings
from app.repositories.account_repository import AccountRepository
from app.services.oauth_github import OAuthGithubService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth/github", tags=["oauth"])


@router.get("/start")
def start_oauth(
    label: str,
    service: OAuthGithubService = Depends(get_github_oauth_service),
    settings: Settings = Depends(get_settings),
) -> dict:
    if not settings.github_oauth_client_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GITHUB_OAUTH_CLIENT_ID が未設定です（secrets/github.env を確認）",
        )
    auth_url, state = service.generate_auth_url(label=label)
    return {"auth_url": auth_url, "state": state}


@router.get("/callback")
def oauth_callback(
    code: str,
    state: str,
    request: Request,
    service: OAuthGithubService = Depends(get_github_oauth_service),
    repo: AccountRepository = Depends(get_account_repo),
    settings: Settings = Depends(get_settings),
):
    state_data = service.pop_state(state)
    if state_data is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="state が無効または期限切れです",
        )

    try:
        token_info = service.exchange_code(code)
    except Exception as _exc:
        import traceback
        print(f"[DEBUG] exchange_code failed: {_exc}", flush=True)
        print(traceback.format_exc(), flush=True)
        logger.exception("GitHub OAuth code 交換に失敗 (state=%s)", state)
        return RedirectResponse(f"{settings.frontend_url}/?oauth_error=exchange_failed")

    access_token = token_info["access_token"]
    try:
        address = service.fetch_user_login(access_token)
    except Exception:
        logger.exception("GitHub ユーザー情報取得失敗（address は空のまま）")
        address = ""

    repo.create_oauth(
        provider="github",
        label=state_data.get("label", address or "github"),
        address=address,
        refresh_token="",  # GitHub OAuth App は refresh token を発行しない
        access_token=access_token,
        token_expiry=None,
        scopes=token_info.get("scopes", ""),
    )
    return RedirectResponse(f"{settings.frontend_url}/?oauth_success=1")


@router.post("/{account_id}/reauth")
def reauth_account(
    account_id: str,
    service: OAuthGithubService = Depends(get_github_oauth_service),
    repo: AccountRepository = Depends(get_account_repo),
    settings: Settings = Depends(get_settings),
) -> dict:
    account_orm = repo.get_by_id(account_id)
    if account_orm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="アカウントが見つかりません",
        )
    if not settings.github_oauth_client_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GITHUB_OAUTH_CLIENT_ID が未設定です",
        )
    auth_url, state = service.generate_auth_url(label=account_orm.label)
    return {"auth_url": auth_url, "state": state}
