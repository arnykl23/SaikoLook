"""Slack Web API 取得アダプタ（MessageSource 実装）.

Slack App の Bot User OAuth Token（`xoxb-...`）を使い, Bot が参加している
チャンネル・DM の最新メッセージを取得して共通スキーマ EmailMessage の列へ
正規化する.

読み取り専用を死守する:
- 付与を求めるスコープは `*:history` / `*:read` / `users:read` のみ.
- 投稿・編集・削除等の書き込み系 API は一切呼ばない.

軽量取得を守る:
- 対象チャンネル数を max_channels で上限する.
- 各チャンネルの conversations.history は limit 件のみ取得する.
- 1件あたり先頭 max_body_chars のみ LLM 入力用に保持する.
"""

from datetime import datetime, timezone

import httpx

from app.models import EmailMessage

SNIPPET_LIMIT = 120  # snippet（プレビュー）の最大文字数
_BASE_URL = "https://slack.com/api"


class SlackApiSource:
    """Slack を Web API + Bot Token で取得する MessageSource 実装."""

    def __init__(
        self,
        token: str,
        address: str,
        *,
        max_body_chars: int = 4000,
        max_channels: int = 20,
        timeout: int = 10,
    ) -> None:
        # 認証情報はインスタンスに保持するだけで, ログ・例外メッセージには載せない.
        self._token = token
        self._address = address
        self._max_body_chars = max_body_chars
        self._max_channels = max_channels
        self._timeout = timeout

    @property
    def address(self) -> str:
        return self._address

    @staticmethod
    def verify_credentials(token: str, *, timeout: int = 10) -> None:
        """auth.test で Bot Token を検証する. 失敗時は RuntimeError を投げる."""
        try:
            resp = httpx.post(
                f"{_BASE_URL}/auth.test",
                headers={"Authorization": f"Bearer {token}"},
                timeout=timeout,
            )
            data = resp.json()
        except httpx.HTTPError as e:
            raise RuntimeError(f"Slack API へ接続できませんでした: {e}")
        if not data.get("ok"):
            raise RuntimeError(
                f"認証に失敗しました（{data.get('error', 'unknown_error')}）。"
                "Bot User OAuth Token を確認してください。"
            )

    def _request(self, endpoint: str, params: dict) -> dict:
        if not self._token:
            raise RuntimeError("Slack Bot Token が未設定です。")
        try:
            resp = httpx.get(
                f"{_BASE_URL}/{endpoint}",
                headers={"Authorization": f"Bearer {self._token}"},
                params=params,
                timeout=self._timeout,
            )
            data = resp.json()
        except httpx.HTTPError as e:
            raise RuntimeError(f"Slack API へ接続できませんでした: {e}")
        if not data.get("ok"):
            raise RuntimeError(f"Slack API エラー: {data.get('error', 'unknown_error')}")
        return data

    def _list_channels(self) -> list[dict]:
        data = self._request(
            "conversations.list",
            {
                "types": "public_channel,private_channel,im",
                "exclude_archived": "true",
                "limit": 200,
            },
        )
        # public_channel/private_channel は is_member で Bot 参加チャンネルのみに絞る.
        # im には is_member が無いので残す.
        return [c for c in data.get("channels", []) if c.get("is_member", True)]

    def _resolve_sender(self, user_id: str) -> str:
        if not user_id:
            return ""
        try:
            data = self._request("users.info", {"user": user_id})
        except RuntimeError:
            return user_id
        user = data.get("user", {})
        profile = user.get("profile", {})
        return profile.get("real_name") or user.get("real_name") or user.get("name") or user_id

    def _build_message(self, channel: dict, msg: dict, sender: str) -> EmailMessage:
        ts = msg.get("ts", "0")
        text = msg.get("text", "")
        try:
            received = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except (ValueError, OSError):
            received = None

        if channel.get("is_im"):
            channel_label = f"DM: {sender}" if sender else "DM"
        else:
            channel_label = "#" + (channel.get("name") or channel.get("id", ""))

        snippet = " ".join(text.split())[:SNIPPET_LIMIT]  # 改行・連続空白を畳む
        # body_text は LLM 入力用. 先頭のみに制限してコスト・漏洩面を抑える.
        body_text = text[: self._max_body_chars] if text else None

        return EmailMessage(
            id=f"{channel.get('id', '')}-{ts}",
            provider="slack",
            subject=channel_label,
            sender=sender,
            to=[channel_label],
            received_at=received,
            snippet=snippet,
            is_unread=True,
            body_text=body_text,
        )

    def list_recent(self, limit: int = 10) -> list[EmailMessage]:
        """参加チャンネル横断で最新メッセージを新しい順で返す（読み取り専用）."""
        channels = self._list_channels()

        pairs: list[tuple[dict, dict]] = []
        for channel in channels[: self._max_channels]:
            try:
                history = self._request(
                    "conversations.history", {"channel": channel["id"], "limit": limit}
                )
            except RuntimeError:
                continue
            for msg in history.get("messages", []):
                if msg.get("subtype"):
                    # join/leave 等のシステムメッセージは除外.
                    continue
                pairs.append((channel, msg))

        # ts（Unix time の文字列）で新しい順に並べ, 上位 limit 件のみ採用.
        pairs.sort(key=lambda p: float(p[1].get("ts", "0")), reverse=True)
        top = pairs[:limit]

        sender_cache: dict[str, str] = {}
        results = []
        for channel, msg in top:
            user_id = msg.get("user", "")
            if user_id not in sender_cache:
                sender_cache[user_id] = self._resolve_sender(user_id)
            results.append(self._build_message(channel, msg, sender_cache[user_id]))
        return results

    def close(self) -> None:
        """接続を都度開閉する実装のため no-op."""
        return None
