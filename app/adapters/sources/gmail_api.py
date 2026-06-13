"""Gmail API v1 MessageSource アダプタ.

OAuth 2.0 Credentials を使って Gmail API v1 でメールを取得する.
既存 GmailImapSource と同じ MessageSource プロトコルを実装する.

読み取り専用スコープ（gmail.readonly）のみ使用.
users.messages.get は既読化しない（modify 操作は行わない）.
"""
import base64
import logging
from datetime import datetime, timezone
from email.header import decode_header
from email.utils import parsedate_to_datetime

import google.auth.exceptions
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.models import EmailMessage

logger = logging.getLogger(__name__)

_TOKEN_URI = "https://oauth2.googleapis.com/token"
_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailApiSource:
    def __init__(
        self,
        refresh_token: str,
        client_id: str,
        client_secret: str,
        account_id: str,
        account_repo,
        max_body_chars: int = 4000,
    ) -> None:
        self._refresh_token = refresh_token
        self._client_id = client_id
        self._client_secret = client_secret
        self._account_id = account_id
        self._account_repo = account_repo
        self._max_body_chars = max_body_chars

    @property
    def address(self) -> str:
        """取得元アドレス（ingestion.py の account_address 埋め込み用）．OAuth では acc["address"] を使うため空文字を返す．"""
        return ""

    def list_recent(self, limit: int = 10) -> list[EmailMessage]:
        """Gmail API v1 で受信トレイを取得して EmailMessage のリストを返す（読み取り専用）．"""
        try:
            service = self._build_service()
        except google.auth.exceptions.RefreshError:
            logger.warning("Gmail OAuth token 失効 (account_id=%s)", self._account_id)
            self._account_repo.set_auth_status(self._account_id, "reauth_required")
            raise

        resp = (
            service.users()
            .messages()
            .list(userId="me", maxResults=limit, labelIds=["INBOX"])
            .execute()
        )
        messages = resp.get("messages", [])
        results = []
        for m in messages:
            try:
                results.append(self._fetch_message(service, m["id"]))
            except Exception:
                logger.exception(
                    "メール取得失敗 (id=%s, account=%s)", m["id"], self._account_id
                )
        return results

    def close(self) -> None:
        """no-op（HTTP セッションは GC に任せる）．"""
        pass

    def _build_service(self):
        creds = Credentials(
            token=None,
            refresh_token=self._refresh_token,
            token_uri=_TOKEN_URI,
            client_id=self._client_id,
            client_secret=self._client_secret,
            scopes=_SCOPES,
        )
        creds.refresh(Request())
        return build("gmail", "v1", credentials=creds)

    def _fetch_message(self, service, message_id: str) -> EmailMessage:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        headers = {
            h["name"].lower(): h["value"]
            for h in msg.get("payload", {}).get("headers", [])
        }
        body = self._extract_body(msg.get("payload", {}))
        received_at = None
        if "date" in headers:
            try:
                received_at = parsedate_to_datetime(headers["date"])
            except Exception:
                pass

        return EmailMessage(
            id=message_id,
            provider="gmail",
            subject=self._decode_header_str(headers.get("subject", "")),
            sender=headers.get("from", ""),
            to=[t.strip() for t in headers.get("to", "").split(",") if t.strip()],
            received_at=received_at,
            snippet=msg.get("snippet", "")[:200],
            is_unread="UNREAD" in msg.get("labelIds", []),
            body_text=body[: self._max_body_chars] if body else None,
        )

    def _extract_body(self, payload: dict) -> str:
        if payload.get("mimeType") == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
            return ""
        for part in payload.get("parts", []):
            result = self._extract_body(part)
            if result:
                return result
        return ""

    def _decode_header_str(self, raw: str) -> str:
        parts = decode_header(raw)
        return "".join(
            t.decode(enc or "utf-8", errors="replace") if isinstance(t, bytes) else t
            for t, enc in parts
        )
