# ReplyGuard — 起動手順（仮運用 / 開発）

メッセージ統合管理・対応漏れ防止システム（PoC）。Gmail を取得し，LLM が重要度・対応要否・タスクの重さを判定，未対応を検知してダッシュボードへ集約する。

- 構成・方針の詳細は `CLAUDE.md`，PoC スコープは `docs/poc-email-ingestion.md`，最終形は `docs/architecture.html`。
- 既定はオフラインで完結する（LLM 実呼び出し・外部通知・Postgres は任意のアップグレード）。

---

## いま私（あなた）がすべきこと（仮で動かす最短手順）

現状: `secrets/gmail.env` 設定済み・`docker-api-1` 起動中（`127.0.0.1:8000`）・フロント依存導入済み。よってダッシュボードを上げるだけで一通り確認できる。

1. フロントを起動する（API はすでに稼働中）

   ```bash
   docker compose -f docker/docker-compose.yml --profile frontend up frontend
   ```

2. ブラウザで開く

   - ダッシュボード: http://localhost:5173
   - API 直接確認: http://localhost:8000/health → `{"status":"ok"}`，http://localhost:8000/messages

3. 動作を一通り触る

   - 「更新」操作（`POST /ingest`）でメールを取り込み，トリアージ高い順に並ぶことを確認。
   - 各カードの状態ボタン（in_progress / done / snoozed / dismissed）で状態遷移。
   - 同じカードを古いバージョンで二重更新すると 409（楽観ロック）になりリロードを促される。

4. 仮運用を止める

   ```bash
   docker compose -f docker/docker-compose.yml down
   ```

> メールは取得のみ（IMAP `BODY.PEEK`＝既読化しない）。送信・書込み権限は持たない。取り込んだメールはローカル SQLite（`data/replyguard.db`，git 非追跡）にのみ保存される。

---

## ゼロから動かす（新しい環境 / チームメンバー向け）

### 前提

- Docker（推奨）。または Python 3.10+ と Node.js 20+。
- Gmail のアプリパスワード（2段階認証を有効化のうえ https://myaccount.google.com/apppasswords で16桁を発行）。

### 1. 秘密情報を用意する（コミット厳禁・各自のローカルのみ）

```bash
cp secrets/gmail.env.example secrets/gmail.env
# secrets/gmail.env を編集し，自分の Gmail アドレスとアプリパスワードを記入
#   GMAIL_ADDRESS=you@gmail.com
#   GMAIL_APP_PASSWORD=（16桁）
```

LLM 実呼び出し・SMTP/Slack 通知・Postgres を使う場合のみ，追加で:

```bash
cp secrets/app.env.example secrets/app.env
# 必要な項目だけコメントを外して記入（ANTHROPIC_API_KEY 等）
```

> `secrets/gmail.env` と `secrets/app.env` は `.gitignore` 済み。リポジトリには `*.example` と `README.md` だけが入る。DB 接続情報・API キーは決してコミットせず，共有が必要なときはチャットやシークレットマネージャで個別に配る。

### 2. 起動（Docker）

```bash
# API（バックエンド）
docker compose -f docker/docker-compose.yml up api
# 別ターミナルでフロント（または同時起動: 下の full プロファイル）
docker compose -f docker/docker-compose.yml --profile frontend up frontend
```

API ＋ フロント ＋ Postgres をまとめて上げる場合:

```bash
docker compose -f docker/docker-compose.yml --profile full up
```

### 3. 起動（Docker を使わずローカルで）

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
mkdir -p data            # ★ SQLite 保存先。data/ は git 非追跡のため手動で作る
uvicorn app.main:app --reload --port 8000
```

フロント:

```bash
cd frontend
cp .env.example .env     # VITE_API_BASE=http://localhost:8000
npm install
npm run dev
```

---

## データベースについて

- 既定は **ローカル SQLite**（`sqlite:///./data/replyguard.db`）。資格情報は不要で，各自が自分のローカル DB を持つ。スキーマは起動時に自動作成される。
- 共有 Postgres へ切り替える場合は `secrets/app.env` に `DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/replyguard` を設定する（このファイルは非コミット）。`--profile pg` または `full` でローカル Postgres コンテナを併用できる。
- メール本文は個人情報を含むため，DB ファイル（`*.db`）は `.gitignore` 済みでコミットしない。

## 設定の主な項目（`secrets/app.env`・すべて任意）

| 項目 | 既定 | 用途 |
|---|---|---|
| `ANALYZER` | `stub` | `gemini` / `anthropic` / `openai` で LLM 分析を使う（要 API キー，未設定なら stub にフォールバック）。分析は 1 メールにつき生涯 1 回だけ呼び，以降は保存済み結果を再利用する（従量課金の抑制） |
| `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | 未設定 | LLM 分析の鍵（Gemini は無料枠あり） |
| `LLM_MODEL` | 空（プロバイダ別既定） | 空なら自動（gemini→`gemini-2.5-flash-lite` 最安） |
| `NOTIFIER` | `log` | `email` / `slack` で通知を実送信（要 SMTP/Webhook 設定） |
| `AUTH_ENABLED` | `false` | `true` で JWT 認証を有効化（`JWT_SECRET` 必須） |
| `DATABASE_URL` | ローカル SQLite | Postgres へ切替時に指定 |
| `SCHEDULER_ENABLED` | `true` | 定期取り込み（`INGEST_INTERVAL_SECONDS`，既定300秒） |

## テスト

```bash
source .venv/bin/activate
pytest -q                                  # ユニット（105件）
PYTHONPATH=. python tests/_smoke_e2e.py    # オフライン e2e スモーク
```
