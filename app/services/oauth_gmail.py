"""Gmail OAuth 2.0 フローサービス.

認可 URL 生成・state 管理・code→token 交換・token refresh を担う.
Web アプリ向け Flow を使う（InstalledAppFlow とは別物）.

Electron 化時の差し替え点:
- generate_auth_url / callback 受信部分をカスタムスキーム対応に置き換える
- このファイルの __init__ / pop_state / exchange_code は変更不要
"""
import time

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_TOKEN_URI = "https://oauth2.googleapis.com/token"


class OAuthGmailService:
    _STATE_TTL = 600  # 10 分（秒）

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._pending_states: dict[str, dict] = {}

    def generate_auth_url(self, label: str, address: str) -> tuple[str, str]:
        """認可 URL と state を生成．state → {label, address, ts} を in-memory キャッシュ．"""
        flow = self._make_flow()
        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        self._pending_states[state] = {"label": label, "address": address, "ts": time.monotonic()}
        return auth_url, state

    def pop_state(self, state: str) -> dict | None:
        """state を検証して削除．期限切れ / 不明なら None．"""
        entry = self._pending_states.pop(state, None)
        if entry is None:
            return None
        if time.monotonic() - entry["ts"] > self._STATE_TTL:
            return None
        return entry

    def exchange_code(self, code: str) -> dict:
        """code をトークンに交換して {refresh_token, access_token, token_expiry, scopes} を返す．"""
        flow = self._make_flow()
        flow.fetch_token(code=code)
        creds = flow.credentials
        return {
            "refresh_token": creds.refresh_token,
            "access_token": creds.token,
            "token_expiry": creds.expiry,
            "scopes": " ".join(sorted(creds.scopes or [])),
        }

    def build_credentials(self, refresh_token: str) -> Credentials:
        """保存済み refresh_token から Credentials を構築する（GmailApiSource 用）．"""
        return Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=_TOKEN_URI,
            client_id=self._client_id,
            client_secret=self._client_secret,
            scopes=SCOPES,
        )

    def _make_flow(self) -> Flow:
        client_config = {
            "web": {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "redirect_uris": [self._redirect_uri],
                "auth_uri": _AUTH_URI,
                "token_uri": _TOKEN_URI,
            }
        }
        return Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=self._redirect_uri)
