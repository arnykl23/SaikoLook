"""Gmail メール取得 (IMAP + アプリパスワード版) — 後方互換ファサード.

取得・正規化の本体は app/adapters/sources/gmail_imap.GmailImapSource に移った.
このモジュールは既存の利用箇所（app/main.py の `from app.fetch_gmail_imap import
MAX_RESULTS, fetch_emails` と `python -m app.fetch_gmail_imap` CLI）を壊さないための
薄いファサードとして残す.

Google Cloud / OAuth 不要. 2段階認証を有効にしたうえで発行した
「アプリパスワード」と Gmail アドレスを環境変数で渡す.

必要な環境変数:
  GMAIL_ADDRESS       例: you@gmail.com
  GMAIL_APP_PASSWORD  アプリパスワード(16桁, 空白は入れても可)
"""

import os

from app.adapters.sources.gmail_imap import GmailImapSource
from app.models import EmailMessage

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
IMAP_TIMEOUT = 10  # 秒。接続/ログイン/取得が詰まってワーカーが固まるのを防ぐ
MAX_RESULTS = 10
# 1通あたりの取得上限バイト数。ヘッダはメール先頭にあるので、この範囲で
# 件名/差出人/日付＋本文先頭が取れる。添付込みの巨大メールでも全文は落とさない。
PREVIEW_BYTES = 16384


def _get_credentials() -> tuple[str, str]:
    address = os.environ.get("GMAIL_ADDRESS", "").strip()
    app_password = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    if not address or not app_password:
        raise RuntimeError(
            "環境変数 GMAIL_ADDRESS / GMAIL_APP_PASSWORD が未設定です "
            "(secrets/gmail.env を確認してください)。"
        )
    return address, app_password


def fetch_emails(limit: int = MAX_RESULTS) -> list[EmailMessage]:
    """受信トレイの最新メールを共通スキーマで返す（新しい順）。"""
    address, app_password = _get_credentials()
    source = GmailImapSource(
        address,
        app_password,
        host=IMAP_HOST,
        port=IMAP_PORT,
        timeout=IMAP_TIMEOUT,
        preview_bytes=PREVIEW_BYTES,
    )
    try:
        return source.list_recent(limit=limit)
    finally:
        source.close()


def main() -> None:
    try:
        emails = fetch_emails()
    except RuntimeError as e:
        raise SystemExit(str(e))

    if not emails:
        print("受信トレイにメールが見つかりませんでした。")
        return

    print(f"\n===== 受信トレイ 最新 {len(emails)} 件 =====\n")
    for i, m in enumerate(emails, 1):
        date = m.received_at.isoformat() if m.received_at else ""
        print(f"[{i}] {'●未読' if m.is_unread else '  既読'}  {date}")
        print(f"    From   : {m.sender}")
        print(f"    Subject: {m.subject}")
        print(f"    Snippet: {m.snippet}")
        print()


if __name__ == "__main__":
    main()
