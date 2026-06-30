"""デモ用メール送信スクリプト.

secrets/gmail.env の認証情報を送信元として使い,
RECIPIENT 宛てにサンプルメールを送る.

使い方:
    python scripts/send_demo_emails.py

送信先を変えたい場合:
    DEMO_RECIPIENT=other@example.com python scripts/send_demo_emails.py
"""

import os
import smtplib
import sys
import time
from email.mime.text import MIMEText
from pathlib import Path

# --- 認証情報の読み込み ---

def _load_env(path: str) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            result[key.strip()] = val.strip()
    except FileNotFoundError:
        pass
    return result

_env = _load_env("secrets/gmail.env")
_env.update(_load_env("secrets/app.env"))

SENDER   = os.environ.get("DEMO_SENDER")   or _env.get("GMAIL_ADDRESS", "")
PASSWORD = os.environ.get("DEMO_PASSWORD") or _env.get("GMAIL_APP_PASSWORD", "")
RECIPIENT = os.environ.get("DEMO_RECIPIENT", "teamsaikorodemo@gmail.com")

if not SENDER or not PASSWORD:
    print("エラー: 送信元アドレスとアプリパスワードが必要です。")
    print("  secrets/gmail.env に GMAIL_ADDRESS / GMAIL_APP_PASSWORD を設定するか,")
    print("  DEMO_SENDER / DEMO_PASSWORD 環境変数で指定してください。")
    sys.exit(1)

# --- サンプルメール定義 ---

DEMO_EMAILS = [
    {
        "subject": "【至急】プロジェクト提案書の確認をお願いします",
        "body": (
            "お世話になっております。山田です。\n\n"
            "添付の提案書について、本日中にご確認とご返信をいただけますでしょうか。\n"
            "明日の朝イチでクライアントに提出予定のため、期限までにご対応をお願いします。\n\n"
            "よろしくお願いいたします。"
        ),
    },
    {
        "subject": "契約書の最終確認と承認をお願いします",
        "body": (
            "お疲れ様です。\n\n"
            "先日お話しした契約書の最終版を添付します。\n"
            "2024-07-31 までにご承認いただく必要があります。\n"
            "ご不明点があればご返信ください。\n\n"
            "よろしくお願いします。"
        ),
    },
    {
        "subject": "新しいデバイスからのログイン通知",
        "body": (
            "セキュリティアラート\n\n"
            "お客様のアカウントへ新しいデバイスからサインインがありました。\n"
            "日時: 2024-07-15 03:42 JST\n"
            "場所: 不明\n\n"
            "心当たりがない場合は、すぐにパスワードを変更してください。\n"
            "2段階認証の設定も推奨します。"
        ),
    },
    {
        "subject": "【セール情報】今週末限定！最大50%オフキャンペーン開催中",
        "body": (
            "メルマガ会員の皆様へ\n\n"
            "今週末限定のビッグセールを開催中です！\n"
            "人気商品が最大50%オフ！この機会をお見逃しなく。\n\n"
            "配信停止はこちらから: unsubscribe@example.com\n"
            "※このメールはno-replyアドレスから送信されています。"
        ),
    },
    {
        "subject": "来週の定例会議の議事録共有",
        "body": (
            "チームの皆さん\n\n"
            "先週の定例会議の議事録をお送りします。\n\n"
            "【主な決定事項】\n"
            "・Q3のロードマップを承認\n"
            "・次回レビューは8月予定\n\n"
            "次回の定例は来週月曜10時を予定しています。\n"
            "ご確認ください。"
        ),
    },
]

# フィードバック検証用（元のメールと似ているが別文面）
SIMILAR_EMAILS = [
    {
        "subject": "業務委託契約書の内容確認と承認依頼",
        "body": (
            "お世話になっております。\n\n"
            "業務委託契約書の最新版をお送りします。\n"
            "内容をご確認のうえ、今月末までにご承認をいただけますでしょうか。\n"
            "ご質問があればお気軽にお問い合わせください。\n\n"
            "よろしくお願いいたします。"
        ),
    },
    {
        "subject": "不審なサインインが検出されました",
        "body": (
            "セキュリティに関する重要なお知らせ\n\n"
            "お客様のアカウントで通常と異なる場所からのサインインが検出されました。\n"
            "心当たりがない場合は、パスワードを今すぐ変更し、\n"
            "2段階認証を有効にしてください。\n\n"
            "ご不明な点はサポートまでお問い合わせください。"
        ),
    },
]


def send(subject: str, body: str) -> None:
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = SENDER
    msg["To"] = RECIPIENT

    with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(SENDER, PASSWORD)
        smtp.sendmail(SENDER, [RECIPIENT], msg.as_bytes())


def _send_batch(mails: list[dict]) -> None:
    for i, mail in enumerate(mails, 1):
        print(f"[{i}/{len(mails)}] {mail['subject']} ... ", end="", flush=True)
        try:
            send(mail["subject"], mail["body"])
            print("OK")
        except Exception as e:
            print(f"失敗: {e}")
        if i < len(mails):
            time.sleep(1)


def main() -> None:
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "demo"

    print(f"送信元: {SENDER}")
    print(f"送信先: {RECIPIENT}")

    if mode == "similar":
        print(f"送信件数: {len(SIMILAR_EMAILS)} 件（フィードバック検証用）\n")
        _send_batch(SIMILAR_EMAILS)
    else:
        print(f"送信件数: {len(DEMO_EMAILS)} 件\n")
        _send_batch(DEMO_EMAILS)

    print("\n完了。SaikoLook で ingest を実行してください。")


if __name__ == "__main__":
    main()
