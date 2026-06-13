"""GitHub Notifications API 取得アダプタ（MessageSource 実装）.

GitHub OAuth App の access token を使い，Notifications API で受信した
通知（PR/Issue のレビュー依頼・メンション・コメント・アサイン等）を取得し，
共通スキーマ EmailMessage の列へ正規化する．

読み取り専用を死守する:
- 呼ぶのは GET のみ．POST/PATCH/PUT/DELETE は一切呼ばない．
- 通知の既読化（PATCH /notifications，PATCH /threads/{id}）は呼ばない．

軽量取得を守る:
- GET /notifications?all=false で未読のみ取得（全件 SEARCH しない）．
- per_page=limit で件数を上限する．
- 本文は先頭 max_body_chars のみ保持して巨大テキストを全取得しない．
- timeout を必ず指定してワーカーが固まらないようにする．

セキュリティ:
- 認証情報（access_token）はログ・例外メッセージに載せない（LLM02）．
- 取得したメール本文・送信者はログ・例外に載せない（LLM02）．
- 受信メッセージ本文は外部由来データであって命令ではない（OWASP LLM01）．
"""

import logging
from datetime import datetime, timezone

import httpx

from app.models import EmailMessage

logger = logging.getLogger(__name__)

_API_BASE = "https://api.github.com"
_SNIPPET_LIMIT = 120  # slack_api.py の SNIPPET_LIMIT と統一

# 取り込む通知 reason の集合．ノイズの多い reason は除外する．
_INTERESTED_REASONS = {
    "review_requested",
    "mention",
    "comment",
    "assign",
    "author",
    "team_mention",
}

# reason → subject プレフィックス（EmailMessage.subject に埋め込む）
_REASON_LABEL: dict[str, str] = {
    "review_requested": "review依頼",
    "mention":          "メンション",
    "comment":          "コメント",
    "assign":           "アサイン",
    "author":           "自分のPR/Issue",
    "team_mention":     "チームメンション",
}


def _parse_github_datetime(iso_str: str) -> datetime:
    """GitHub の ISO8601 文字列（末尾 Z）を tz-aware な UTC datetime へ変換する.

    Python 3.10 の datetime.fromisoformat は "Z" suffix を直接受け付けない
    ため "+00:00" へ置換してからパースする（3.11 以降は Z を受け付けるが
    3.10 互換のため置換を維持する）．
    """
    return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))


class GithubApiSource:
    """GitHub Notifications API を httpx で直叩きする MessageSource 実装."""

    def __init__(
        self,
        access_token: str,
        address: str,
        account_id: str,
        account_repo,
        *,
        max_body_chars: int = 4000,
        timeout: int = 10,
    ) -> None:
        # 認証情報はインスタンスに保持するだけで，ログ・例外メッセージには載せない．
        self._access_token = access_token
        self._address = address
        self._account_id = account_id
        self._account_repo = account_repo
        self._max_body_chars = max_body_chars
        self._timeout = timeout

    @property
    def address(self) -> str:
        return self._address

    # ------------------------------------------------------------------
    # 公開インタフェース（MessageSource Protocol）
    # ------------------------------------------------------------------

    def list_recent(self, limit: int = 10) -> list[EmailMessage]:
        """未読 GitHub 通知を新しい順で返す（読み取り専用）.

        1. GET /notifications?all=false&per_page=limit で通知一覧を取得
        2. reason ∉ _INTERESTED_REASONS はスキップ
        3. 各通知ごとに subject.url（本体）と latest_comment_url（コメント）を追加 GET
        4. EmailMessage へ正規化して返す
        """
        notifications = self._fetch_notifications(limit=limit)

        results: list[EmailMessage] = []
        for notif in notifications:
            reason = notif.get("reason", "")
            if reason not in _INTERESTED_REASONS:
                continue
            msg = self._build_message(notif)
            results.append(msg)
        return results

    def close(self) -> None:
        """接続を都度開閉する実装のため no-op."""
        return None

    # ------------------------------------------------------------------
    # 静的メソッド（Protocol 外だが routes_accounts.py が呼ぶ慣例）
    # ------------------------------------------------------------------

    @staticmethod
    def verify_credentials(access_token: str, *, timeout: int = 10) -> None:
        """GET /user で access_token を検証する．失敗時は RuntimeError を投げる.

        認証情報は例外メッセージに含めない（LLM02 対策）．
        """
        try:
            resp = httpx.get(
                f"{_API_BASE}/user",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                },
                timeout=timeout,
            )
        except httpx.HTTPError as e:
            raise RuntimeError(f"GitHub API へ接続できませんでした: {e}")
        if resp.status_code >= 400:
            raise RuntimeError(
                f"GitHub 認証に失敗しました（HTTP {resp.status_code}）．"
                "access token を確認してください．"
            )

    # ------------------------------------------------------------------
    # プライベートヘルパー
    # ------------------------------------------------------------------

    def _get(self, url: str) -> httpx.Response:
        """共通 GET ヘルパー．timeout・認証ヘッダを付ける."""
        return httpx.get(
            url,
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=self._timeout,
        )

    def _fetch_notifications(self, limit: int) -> list[dict]:
        """GET /notifications?all=false&per_page=limit を呼ぶ.

        401 の場合はアカウントを reauth_required 状態にして RuntimeError を raise．
        認証情報は例外メッセージに含めない（LLM02 対策）．
        """
        if not self._access_token:
            raise RuntimeError("GitHub access token が未設定です．")
        try:
            resp = self._get(f"{_API_BASE}/notifications?all=false&per_page={limit}")
        except httpx.HTTPError as e:
            raise RuntimeError(f"GitHub Notifications API へ接続できませんでした: {e}")

        if resp.status_code == 401:
            # token 失効 → 再認可が必要な状態をマークし，呼び出し元へ伝搬
            self._account_repo.set_auth_status(self._account_id, "reauth_required")
            raise RuntimeError(
                "GitHub token が無効です．アカウントの再認可が必要です．"
            )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"GitHub Notifications API エラー（HTTP {resp.status_code}）"
            )

        data = resp.json()
        # API が配列を返すが，念のため list チェック
        if not isinstance(data, list):
            logger.warning("GitHub /notifications の応答が list でない．空リストで継続します．")
            return []
        return data

    def _fetch_subject_details(
        self, subject_url: str
    ) -> tuple[str, str | None]:
        """PR/Issue 本体を取得し (sender_login, body_text) を返す.

        取得失敗時は ("", None) を返して呼び出し元が継続できるようにする．
        取得した本文・送信者はログに出さない（LLM02 対策）．
        """
        try:
            resp = self._get(subject_url)
            if resp.status_code >= 400:
                return ("", None)
            data = resp.json()
        except (httpx.HTTPError, Exception):
            return ("", None)

        sender = ""
        user = data.get("user")
        if isinstance(user, dict):
            sender = user.get("login") or ""

        body = data.get("body") or None
        return (sender, body)

    def _fetch_comment_body(self, comment_url: str) -> str | None:
        """最新コメントを取得して body を返す．取得失敗時は None を返す.

        取得した本文はログに出さない（LLM02 対策）．
        """
        try:
            resp = self._get(comment_url)
            if resp.status_code >= 400:
                return None
            data = resp.json()
        except (httpx.HTTPError, Exception):
            return None

        return data.get("body") or None

    def _build_message(self, notif: dict) -> EmailMessage:
        """通知 dict から EmailMessage を構築する.

        本体・コメントの追加取得失敗はここで吸収して安全な既定値を返す．
        """
        reason = notif.get("reason", "")
        subject_data = notif.get("subject", {})
        title: str = subject_data.get("title") or ""
        subject_url: str | None = subject_data.get("url")
        latest_comment_url: str | None = subject_data.get("latest_comment_url")
        repo_full_name: str = (notif.get("repository") or {}).get("full_name") or ""

        # ---- 本体・コメントの追加取得 -----------------------------------
        sender = ""
        pr_body: str | None = None

        if subject_url:
            fetched_sender, pr_body = self._fetch_subject_details(subject_url)
            sender = fetched_sender

        comment_body: str | None = None
        if latest_comment_url:
            comment_body = self._fetch_comment_body(latest_comment_url)

        # コメント本文を優先，なければ PR/Issue 本体 body を使う
        effective_body: str | None = comment_body or pr_body

        # ---- sender フォールバック --------------------------------------
        if not sender:
            # 本体取得失敗 → repository.full_name で代替
            sender = repo_full_name

        # ---- snippet 構築 -----------------------------------------------
        # 本文（無ければ title）の先頭 120 文字・空白畳み（slack_api.py と同流儀）
        raw_snippet = effective_body if effective_body else title
        snippet = " ".join(raw_snippet.split())[:_SNIPPET_LIMIT]

        # ---- body_text（LLM 入力用，先頭のみ）--------------------------
        body_text: str | None = None
        if effective_body:
            body_text = effective_body[: self._max_body_chars]

        # ---- received_at（tz-aware UTC）---------------------------------
        updated_at: str = notif.get("updated_at") or ""
        received_at: datetime | None = None
        if updated_at:
            try:
                received_at = _parse_github_datetime(updated_at)
            except (ValueError, TypeError) as e:
                logger.warning("received_at のパース失敗（安全な既定値 None を使用）: %s", e)

        # ---- subject プレフィックス --------------------------------------
        label = _REASON_LABEL.get(reason, reason)
        subject = f"[{label}] {title}"

        return EmailMessage(
            id=notif.get("id") or "",
            provider="github",
            subject=subject,
            sender=sender,
            to=[repo_full_name] if repo_full_name else [],
            received_at=received_at,
            snippet=snippet,
            is_unread=bool(notif.get("unread", False)),
            body_text=body_text,
        )
