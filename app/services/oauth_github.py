"""GitHub OAuth App フローサービス.

認可 URL 生成・state 管理（CSRF 対策）・code→token 交換・ユーザー login 取得を担う.
Gmail 版（oauth_gmail.py）と異なり，GitHub は client_secret 方式（PKCE 不要）であるため
httpx 直叩きで実装する.

セキュリティ要件:
- client_secret はログ・例外メッセージに出力しない
- state は secrets.token_urlsafe(32) で CSRF 対策（推測不可能な 256 bit エントロピー）
- _pending_states は in-memory のみ（再起動で消える。PoC 方針）
"""
import secrets
import time
from urllib.parse import urlencode

import httpx


class OAuthGithubService:
    _STATE_TTL = 600  # 秒（10分）
    _AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
    _TOKEN_URL = "https://github.com/login/oauth/access_token"
    _USER_URL = "https://api.github.com/user"
    SCOPES = "notifications"  # read だけに絞る scope は存在しない（書込み混在は運用規律で担保）

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._pending_states: dict[str, dict] = {}

    def generate_auth_url(self, label: str) -> tuple[str, str]:
        """認可 URL と state を生成．state → {label, ts} を in-memory キャッシュ．

        Args:
            label: アカウントに付ける表示名（DB 保存用）．

        Returns:
            (auth_url, state) のタプル．
        """
        state = secrets.token_urlsafe(32)
        self._pending_states[state] = {
            "label": label,
            "ts": time.monotonic(),
        }
        params = urlencode({
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "scope": self.SCOPES,
            "state": state,
        })
        auth_url = f"{self._AUTHORIZE_URL}?{params}"
        return auth_url, state

    def pop_state(self, state: str) -> dict | None:
        """state を検証して削除．期限切れ（TTL 超過）または不明なら None．

        Gmail 版（oauth_gmail.py:48-55）と同一ロジック.
        一度取り出したら _pending_states から削除（リプレイ攻撃防止）.
        """
        entry = self._pending_states.pop(state, None)
        if entry is None:
            return None
        if time.monotonic() - entry["ts"] > self._STATE_TTL:
            return None
        return entry

    def exchange_code(self, code: str) -> dict:
        """authorization code をアクセストークンに交換する.

        Args:
            code: GitHub 認可サーバーから受け取った code パラメータ．

        Returns:
            {"access_token": str, "scopes": str} の dict．

        Raises:
            RuntimeError: access_token がレスポンスに含まれない場合（秘密情報はメッセージに出さない）．
        """
        resp = httpx.post(
            self._TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "code": code,
                "redirect_uri": self._redirect_uri,
            },
            headers={"Accept": "application/json"},
            timeout=10,
        )
        if resp.status_code >= 400:
            # 5xx/HTML エラーページ等. client_secret はメッセージに出さない
            raise RuntimeError(
                f"GitHub token exchange failed: HTTP {resp.status_code}"
            )
        try:
            body = resp.json()
        except ValueError:
            raise RuntimeError("GitHub token exchange failed: 応答が JSON ではありません")
        access_token = body.get("access_token")
        if not access_token:
            # error / error_description は出してよいが client_secret は絶対に出さない
            error = body.get("error", "unknown_error")
            description = body.get("error_description", "")
            raise RuntimeError(
                f"GitHub token exchange failed: {error} — {description}"
            )
        return {
            "access_token": access_token,
            "scopes": body.get("scope", ""),
        }

    def fetch_user_login(self, access_token: str) -> str:
        """GitHub ユーザーの login 名を取得する（address として DB 保存するため）.

        Args:
            access_token: exchange_code で取得したアクセストークン．

        Returns:
            GitHub の login 名（例: "octocat"）．取得失敗時は空文字を返す
            （callback 側で address 空を許容する設計）．
        """
        try:
            resp = httpx.get(
                self._USER_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                },
                timeout=10,
            )
            return resp.json().get("login", "")
        except Exception:
            return ""
