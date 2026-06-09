"""Gmail スモールステップ PoC.

最新の受信メール数件の「件名・差出人・日時・スニペット」を取得して表示するだけ。
認証は OAuth (インストール済みアプリ) フロー。コンテナ内でローカルサーバを立て、
ホストのブラウザで同意 → token_gmail.json にキャッシュする。
"""

import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# 読み取り専用スコープ（送信権限は付けない）
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

SECRETS_DIR = "/app/secrets"
CREDENTIALS_PATH = os.path.join(SECRETS_DIR, "gmail_credentials.json")
TOKEN_PATH = os.path.join(SECRETS_DIR, "token_gmail.json")

# コンテナ内でローカルサーバを立てるポート（docker-compose で公開済み）
OAUTH_PORT = 8080
MAX_RESULTS = 10


def get_credentials() -> Credentials:
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_PATH):
                raise SystemExit(
                    f"クレデンシャルがありません: {CREDENTIALS_PATH}\n"
                    "Google Cloud で作成した OAuth クライアント(デスクトップアプリ)の "
                    "JSON を secrets/gmail_credentials.json に置いてください。"
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            # host=localhost: ブラウザに見せる URL / bind_addr=0.0.0.0: コンテナ内で待受
            print(
                "\n==> 表示される URL をホストのブラウザで開いて認証してください "
                "(リダイレクトは http://localhost:8080 に戻ります)\n"
            )
            creds = flow.run_local_server(
                host="localhost",
                bind_addr="0.0.0.0",
                port=OAUTH_PORT,
                open_browser=False,
            )
        with open(TOKEN_PATH, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        print(f"==> トークンを保存しました: {TOKEN_PATH}")

    return creds


def header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def main() -> None:
    creds = get_credentials()
    service = build("gmail", "v1", credentials=creds)

    resp = (
        service.users()
        .messages()
        .list(userId="me", maxResults=MAX_RESULTS, labelIds=["INBOX"])
        .execute()
    )
    messages = resp.get("messages", [])
    if not messages:
        print("受信トレイにメールが見つかりませんでした。")
        return

    print(f"\n===== 受信トレイ 最新 {len(messages)} 件 =====\n")
    for i, m in enumerate(messages, 1):
        msg = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=m["id"],
                format="metadata",
                metadataHeaders=["Subject", "From", "Date"],
            )
            .execute()
        )
        hs = msg.get("payload", {}).get("headers", [])
        unread = "UNREAD" in msg.get("labelIds", [])
        print(f"[{i}] {'●未読' if unread else '  既読'}  {header(hs, 'Date')}")
        print(f"    From   : {header(hs, 'From')}")
        print(f"    Subject: {header(hs, 'Subject')}")
        print(f"    Snippet: {msg.get('snippet', '')[:120]}")
        print()


if __name__ == "__main__":
    main()
