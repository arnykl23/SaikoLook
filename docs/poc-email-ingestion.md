# ReplyGuard PoC 方針 — メール取得機能（Outlook / Gmail）

> 最終ゴール: **メール見落とし防止アプリ**。Outlook / Gmail を統合し、LLM が
> 各メールの「重要度」「タスクの重さ」などを推定し、ダッシュボードに統合表示する Web サイト。
>
> このドキュメントは、その第一歩である **「メール本文を取ってくる PoC」** の方針。
> 前提: **ハッカソン / スピード最優先**。完璧さより「動いて見せられる」を優先する。

---

## 1. PoC のゴール（スコープ）

PoC で達成すること:

1. Gmail と Outlook の両方から **受信メールの一覧と本文を取得**できる。
2. 取得したメールを **プロバイダ非依存の共通スキーマ**に正規化する。
3. 正規化結果を **JSON で出力 / FastAPI のエンドポイントで返す**。

PoC では **やらない**（次フェーズに回す）:

- LLM による重要度・タスク推定（インターフェースだけ用意）
- 本格的な Web ダッシュボード UI
- マルチユーザ / 永続 DB / 本番デプロイ
- リアルタイム同期（Webhook / push 通知）

---

## 2. 技術選定（決め打ち）

| 項目 | 採用 | 理由（スピード観点） |
|------|------|----------------------|
| 言語/FW | **Python 3.11+ / FastAPI** | LLM 連携・両プロバイダの公式 SDK が最速で揃う。`uvicorn` で即起動。 |
| Gmail | **Gmail API**（`google-api-python-client` + `google-auth-oauthlib`） | quickstart がトークン保存まで面倒を見てくれる。IMAP より構造化データが楽。 |
| Outlook/Microsoft | **Microsoft Graph API**（`msal`） | 個人/法人どちらのアカウントも対応。device code flow が実装最速。 |
| 認証保存 | **ローカルファイル**（`token_*.json`） | PoC なので暗号化や DB は不要。`.gitignore` で除外。 |
| パッケージ管理 | `uv` もしくは `pip` + `requirements.txt` | こだわらない。手元に合わせる。 |

### なぜ IMAP ではなく公式 API か

- Gmail の IMAP は **2FA + アプリパスワード**が必須（素の ID/PW は不可）。
- Outlook（Microsoft）は**個人アカウントの Basic 認証を廃止**済みで、結局 OAuth が必要。
- どちらにせよ OAuth が要るなら、**構造化データ・添付・スレッドが扱いやすい公式 API** の方が PoC でも本番でも速い。

---

## 3. 共通データスキーマ

プロバイダ差を吸収する正規化モデル。これを LLM 層・UI 層の唯一の入力にする。

```python
# app/models.py
from datetime import datetime
from pydantic import BaseModel

class Attachment(BaseModel):
    filename: str
    mime_type: str
    size: int | None = None

class EmailMessage(BaseModel):
    id: str                  # プロバイダ内のメッセージID
    provider: str            # "gmail" | "outlook"
    thread_id: str | None    # スレッド/会話ID
    subject: str
    sender: str              # "Name <addr>"
    to: list[str]
    cc: list[str] = []
    received_at: datetime
    snippet: str             # プレビュー用の短い本文
    body_text: str           # プレーンテキスト本文（HTML はテキスト化）
    is_unread: bool
    labels: list[str] = []   # Gmail label / Outlook category 相当
    attachments: list[Attachment] = []
```

> LLM が後段で読むのは `subject` / `body_text` / `sender` / `received_at` が中心。
> ここを揃えておけば LLM 層・UI 層はプロバイダを意識しなくて済む。

---

## 4. アーキテクチャ / ディレクトリ構成

各プロバイダは共通インターフェース `MailSource` を実装する。追加プロバイダもこれに乗せるだけ。

```
ReplyGuard/
├── docs/
│   └── poc-email-ingestion.md      # 本ドキュメント
├── app/
│   ├── main.py                     # FastAPI エントリ
│   ├── models.py                   # EmailMessage 等の共通スキーマ
│   ├── sources/
│   │   ├── base.py                 # MailSource インターフェース
│   │   ├── gmail.py                # Gmail API 実装
│   │   └── outlook.py              # Microsoft Graph 実装
│   └── llm/
│       └── analyzer.py             # 重要度/タスク推定（PoCはスタブ）
├── secrets/                        # OAuth クレデンシャル（.gitignore）
│   ├── gmail_credentials.json
│   ├── token_gmail.json
│   └── token_outlook.json
├── requirements.txt
└── .gitignore
```

```python
# app/sources/base.py
from abc import ABC, abstractmethod
from app.models import EmailMessage

class MailSource(ABC):
    @abstractmethod
    def authenticate(self) -> None: ...

    @abstractmethod
    def list_recent(self, limit: int = 20) -> list[EmailMessage]:
        """最近の受信メールを共通スキーマで返す。"""
```

---

## 5. 認証セットアップ手順（事前準備）

ここが PoC で唯一つまずきやすい所。**当日までに各自で済ませておくと速い。**

### 5.1 Gmail（Google Cloud）

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクト作成。
2. 「Gmail API」を有効化。
3. OAuth 同意画面を作成 → **テストユーザに自分の Gmail を追加**（公開審査は不要）。
4. 認証情報 → OAuth クライアント ID（種類: **デスクトップ アプリ**）を作成。
5. `credentials.json` をダウンロードし `secrets/gmail_credentials.json` に配置。
6. スコープは読み取りのみ: `https://www.googleapis.com/auth/gmail.readonly`

初回実行時にブラウザが開き、`token_gmail.json` が自動生成される（以降は再ログイン不要）。

### 5.2 Outlook（Microsoft Entra / Azure AD）

1. [Azure Portal](https://portal.azure.com/) → 「アプリの登録」で新規登録。
2. サポートされるアカウント: **個人 + 職場/学校（マルチテナント + personal）** を選ぶと検証が楽。
3. API のアクセス許可 → Microsoft Graph → 委任(Delegated): `Mail.Read`, `User.Read`。
4. 認証 → 「パブリック クライアント フロー」を**有効化**（device code flow に必要）。
5. アプリの **クライアント ID** を控える（device code flow なのでシークレット不要）。

実行時にターミナルへ「このコードを https://microsoft.com/devicelogin に入力」と出るので、それで認証 → `token_outlook.json` をキャッシュ。

> **時短Tips**: 当日は「どちらか一方が動けばデモ可」。Gmail の方が手順が軽いので**まず Gmail を通す**のを推奨。Outlook は並行 or 後回し。

---

## 6. 実装の進め方（タイムボックス）

ハッカソン向けに、各ステップを「動く状態」で刻む。

| 順 | 内容 | 目安 | 完了条件 |
|----|------|------|----------|
| 1 | リポジトリ/依存セットアップ、`models.py` 作成 | 30分 | `uvicorn` が起動する |
| 2 | **Gmail 認証 + 一覧取得**（`list_recent`） | 60分 | 自分の受信トレイ最新20件が JSON で出る |
| 3 | Gmail 本文・スニペットの正規化 | 30分 | `body_text` にテキスト本文が入る |
| 4 | FastAPI に `GET /emails?provider=gmail` | 20分 | ブラウザ/curl で JSON 取得 |
| 5 | **Outlook 認証 + 一覧/本文取得** | 60分 | `provider=outlook` でも JSON が出る |
| 6 | 両者をマージして `GET /emails`（統合一覧） | 30分 | 受信日時降順で混在表示 |
| 7 | （余力）LLM スタブを差し込み `importance` 付与 | — | 次フェーズへの足がかり |

> 最低ライン（MVP）は **ステップ4まで**。そこまでで「メールを取れている」デモは成立する。

---

## 7. API イメージ（PoC）

```
GET /emails?provider=gmail&limit=20     # Gmail のみ
GET /emails?provider=outlook&limit=20   # Outlook のみ
GET /emails?limit=40                    # 両方をマージ、受信日時降順
```

レスポンス例:

```json
[
  {
    "id": "18f...",
    "provider": "gmail",
    "subject": "請求書の確認のお願い",
    "sender": "経理部 <keiri@example.com>",
    "received_at": "2026-06-08T09:12:00+09:00",
    "snippet": "添付の請求書をご確認のうえ…",
    "is_unread": true,
    "attachments": [{"filename": "invoice.pdf", "mime_type": "application/pdf"}]
  }
]
```

---

## 8. 次フェーズへの接続（PoC では設計のみ）

PoC のアウトプット（`EmailMessage` の配列）が、そのまま次フェーズの入力になる。

- **LLM 分析層** (`app/llm/analyzer.py`): `EmailMessage` を受け取り
  `importance: 1-5`, `task_weight`, `deadline?`, `summary`, `suggested_action` を付与。
  - モデルは最新の Claude（例: `claude-opus-4-8` / `claude-sonnet-4-6`）を想定。
  - PoC ではスタブ（固定値 or ルールベース）にして、後で差し替え可能なように。
- **ダッシュボード**: 重要度・締切順で並べ替え、「見落とし候補（未読×高重要度）」を強調。
- **永続化**: PoC のメモリ保持 → 後で SQLite/Postgres へ。

---

## 9. リスク / 注意点

- **OAuth 同意画面のハマり**: Gmail はテストユーザ未追加だとログインで弾かれる。事前確認必須。
- **スコープは読み取りのみ**（`gmail.readonly` / `Mail.Read`）。PoC で送信権限は不要・付けない。
- **レート制限**: PoC の取得件数（20〜40件）なら問題なし。大量取得はしない。
- **HTML メール**: 本文は HTML が多い。`body_text` 化に `BeautifulSoup` 等で簡易テキスト抽出。
- **秘密情報**: `secrets/`, `token_*.json`, `credentials.json` は必ず `.gitignore`。コミット厳禁。

---

## 10. 依存パッケージ（叩き台）

```
fastapi
uvicorn[standard]
pydantic
# Gmail
google-api-python-client
google-auth-oauthlib
# Outlook (Microsoft Graph)
msal
requests
# 本文テキスト化
beautifulsoup4
```
