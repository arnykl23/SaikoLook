"""Gmail IMAP 取得アダプタ（MessageSource 実装）.

Google Cloud / OAuth 不要. 2段階認証を有効にしたうえで発行した
「アプリパスワード」と Gmail アドレスを使い, IMAP で受信トレイの最新メールを
取得して共通スキーマ EmailMessage の列へ正規化する.

読み取り専用を死守する:
- SELECT は readonly=True, 本文は BODY.PEEK[] で取得し既読フラグを立てない.
- 送信・書込み権限は一切使わない.

軽量取得を守る:
- SELECT 応答の EXISTS（総件数）から末尾 limit 件だけを位置指定で取得し,
  全件 SEARCH や巨大メール全文の取得をしない.
- 1通あたり先頭 preview_bytes のみ取得する.
- 接続・ログイン・取得に timeout を付け, ワーカーが固まらないようにする.

このクラスはステートレスに動く: list_recent は呼び出しごとに接続し,
メソッド内の finally で必ず logout する（接続リークなし）. close() は no-op.
"""

import email
import email.message
import imaplib
import re
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

from app.models import EmailMessage

SNIPPET_LIMIT = 120  # snippet（プレビュー）の最大文字数


def _decode(value: str | None) -> str:
    """MIME エンコードされたヘッダ値をデコードする. 失敗時は原文を返す."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _decode_payload(part: email.message.Message) -> str:
    """part のペイロードを文字コードを考慮してデコードする."""
    payload = part.get_payload(decode=True) or b""
    charset = part.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _html_to_text(html: str) -> str:
    """HTML メール本文を素テキスト化する（外部由来データ; 解釈はしない）."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text(separator="\n")


def _extract_body(msg: email.message.Message) -> str:
    """本文テキストを取り出す. text/plain を優先し, 無ければ text/html を素テキスト化する.

    添付（filename 付き part）は無視する. 改行は保持する（LLM 入力で構造が読めるように）.
    """
    if not msg.is_multipart():
        text = _decode_payload(msg)
        if msg.get_content_type() == "text/html":
            return _html_to_text(text)
        return text

    plain = ""
    html = ""
    for part in msg.walk():
        if part.get_content_maintype() == "multipart" or part.get_filename():
            continue
        ctype = part.get_content_type()
        if ctype == "text/plain" and not plain:
            plain = _decode_payload(part)
        elif ctype == "text/html" and not html:
            html = _decode_payload(part)

    if plain:
        return plain
    if html:
        return _html_to_text(html)
    return ""


class GmailImapSource:
    """Gmail を IMAP + アプリパスワードで取得する MessageSource 実装."""

    def __init__(
        self,
        address: str,
        app_password: str,
        *,
        host: str = "imap.gmail.com",
        port: int = 993,
        timeout: int = 10,
        preview_bytes: int = 16384,
        max_body_chars: int = 4000,
    ) -> None:
        # 認証情報はインスタンスに保持するだけで, ログ・例外メッセージには載せない.
        self._address = address
        self._app_password = app_password
        self._host = host
        self._port = port
        self._timeout = timeout
        self._preview_bytes = preview_bytes
        self._max_body_chars = max_body_chars

    def _connect(self) -> imaplib.IMAP4_SSL:
        if not self._address or not self._app_password:
            raise RuntimeError(
                "環境変数 GMAIL_ADDRESS / GMAIL_APP_PASSWORD が未設定です "
                "(secrets/gmail.env を確認してください)。"
            )
        # timeout を付け, 接続/ログインが固まってもワーカーが無限に詰まらないように.
        imap = imaplib.IMAP4_SSL(self._host, self._port, timeout=self._timeout)
        try:
            imap.login(self._address, self._app_password)
        except imaplib.IMAP4.error as e:
            # 例外メッセージに資格情報を載せない.
            raise RuntimeError(
                f"ログイン失敗: {e} / 2段階認証とアプリパスワードを確認してください。"
            )
        return imap

    def _build_message(self, descriptor: bytes, raw: bytes) -> EmailMessage:
        # FETCH 応答の記述子から UID と既読状態を取り出す.
        uid_match = re.search(rb"UID (\d+)", descriptor)
        uid = uid_match.group(1).decode() if uid_match else ""
        is_unread = b"\\Seen" not in descriptor

        msg = email.message_from_bytes(raw)
        try:
            received = parsedate_to_datetime(msg.get("Date"))
        except Exception:
            received = None

        to = [a.strip() for a in _decode(msg.get("To")).split(",") if a.strip()]

        body = _extract_body(msg)
        snippet = " ".join(body.split())[:SNIPPET_LIMIT]  # 改行・連続空白を畳む
        # body_text は LLM 入力用. 先頭のみに制限してコスト・漏洩面を抑える.
        body_text = body[: self._max_body_chars] if body else None

        return EmailMessage(
            id=uid,
            provider="gmail",
            subject=_decode(msg.get("Subject")),
            sender=_decode(msg.get("From")),
            to=to,
            received_at=received,
            snippet=snippet,
            is_unread=is_unread,
            body_text=body_text,
        )

    def list_recent(self, limit: int = 10) -> list[EmailMessage]:
        """受信トレイの最新メールを新しい順で返す（読み取り専用）."""
        imap = self._connect()
        try:
            # SELECT 応答に総件数(EXISTS)が入る. これを使い, 全件 SEARCH せず
            # 末尾(=最新) limit 件だけを位置指定で取得する（大きい受信箱でも軽量）.
            status, data = imap.select("INBOX", readonly=True)
            if status != "OK":
                raise RuntimeError(f"INBOX を開けませんでした: {data}")
            total = int(data[0]) if data and data[0] else 0
            if total == 0:
                return []

            start = max(1, total - limit + 1)
            seq_set = f"{start}:{total}"  # 末尾 limit 件のシーケンス範囲（このセッション内限定）
            # UID も同時取得して安定IDにする. 先頭 preview_bytes のみ・PEEK で既読化しない.
            status, msg_data = imap.fetch(
                seq_set, f"(UID FLAGS BODY.PEEK[]<0.{self._preview_bytes}>)"
            )
            if status != "OK":
                raise RuntimeError("メールの取得に失敗しました。")

            results = [
                self._build_message(item[0] or b"", item[1])
                for item in msg_data
                if isinstance(item, tuple)
            ]
            results.reverse()  # シーケンス昇順 → 新しい順に
            return results
        finally:
            try:
                imap.logout()
            except Exception:
                pass

    def close(self) -> None:
        """接続を都度開閉する実装のため no-op（list_recent が必ず logout する）."""
        return None
