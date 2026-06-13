"""Gmail OAuth 2.0 フローのエンドポイント.

GET  /auth/gmail/start?label=<>&address=<>   認可 URL 発行
GET  /auth/gmail/callback?code=<>&state=<>   コールバック受信 → 302 リダイレクト
POST /auth/gmail/{account_id}/reauth         期限切れアカウントの再接続 URL 発行
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from googleapiclient.discovery import build

from app.api.deps import get_account_repo, get_oauth_service, get_settings
from app.config import Settings
from app.repositories.account_repository import AccountRepository
from app.services.oauth_gmail import OAuthGmailService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth/gmail", tags=["oauth"])


@router.get("/start")
def start_oauth(
    label: str,
    address: str,
    service: OAuthGmailService = Depends(get_oauth_service),
    settings: Settings = Depends(get_settings),
) -> dict:
    if not settings.gmail_oauth_client_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GMAIL_OAUTH_CLIENT_ID が未設定です（secrets/gmail.env を確認）",
        )
    auth_url, state = service.generate_auth_url(label=label, address=address)
    return {"auth_url": auth_url, "state": state}


@router.get("/callback")
def oauth_callback(
    code: str,
    state: str,
    request: Request,
    service: OAuthGmailService = Depends(get_oauth_service),
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
        token_info = service.exchange_code(code, flow=state_data.get("flow"))
    except Exception:
        logger.exception("OAuth code 交換に失敗 (state=%s)", state)
        return RedirectResponse(f"{settings.frontend_url}/?oauth_error=exchange_failed")

    address = state_data.get("address", "")
    if not address:
        try:
            from google.auth.transport.requests import Request as GRequest

            creds = service.build_credentials(token_info["refresh_token"])
            creds.refresh(GRequest())
            gmail_service = build("gmail", "v1", credentials=creds)
            profile = gmail_service.users().getProfile(userId="me").execute()
            address = profile.get("emailAddress", "")
        except Exception:
            logger.exception("Gmail プロフィール取得失敗（address は空のまま）")

    repo.create_oauth(
        provider="gmail",
        label=state_data.get("label", address or "gmail"),
        address=address,
        refresh_token=token_info["refresh_token"],
        access_token=token_info.get("access_token"),
        token_expiry=token_info.get("token_expiry"),
        scopes=token_info.get("scopes", ""),
    )
    return RedirectResponse(f"{settings.frontend_url}/?oauth_success=1")


@router.post("/{account_id}/reauth")
def reauth_account(
    account_id: str,
    service: OAuthGmailService = Depends(get_oauth_service),
    repo: AccountRepository = Depends(get_account_repo),
    settings: Settings = Depends(get_settings),
) -> dict:
    account_orm = repo.get_by_id(account_id)
    if account_orm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="アカウントが見つかりません",
        )
    if not settings.gmail_oauth_client_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GMAIL_OAUTH_CLIENT_ID が未設定です",
        )
    auth_url, state = service.generate_auth_url(
        label=account_orm.label, address=account_orm.address
    )
    return {"auth_url": auth_url, "state": state}
