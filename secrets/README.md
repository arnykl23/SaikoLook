# secrets/ — 秘密情報の置き場（commit 厳禁）

このディレクトリには API キー・パスワード・トークンなどの**実値**を置く.
`.gitignore` で実値ファイルは全て除外され, `*.example` と本 README のみが
追跡される（`.gitignore` の `secrets/*` ＋ `!secrets/*.example` ＋ `*.env` ルール）.

## ファイル一覧

| ファイル | 役割 | commit |
|---|---|---|
| `gmail.env` | Gmail IMAP のアドレス＋アプリパスワード（**必須**） | ✗ 厳禁 |
| `gmail.env.example` | gmail.env の雛形 | ✓ 追跡 |
| `app.env` | DB/認証/LLM/通知の **任意** 上書き設定 | ✗ 厳禁 |
| `app.env.example` | app.env の雛形（全項目の説明つき） | ✓ 追跡 |

## セットアップ

```bash
cp secrets/gmail.env.example secrets/gmail.env   # 必須: Gmail 認証
cp secrets/app.env.example   secrets/app.env     # 任意: 上書きする時だけ
```

- `gmail.env`: `GMAIL_ADDRESS` と `GMAIL_APP_PASSWORD`（2段階認証で発行した16桁）を埋める.
- `app.env`: 何も埋めなくても baseline は動く（SQLite＋スタブ分析＋ログ通知＋認証無効）.
  Supabase・実 LLM・メール/Slack 通知・認証を使う時だけ該当項目を有効化する.

## 設定の読まれ方

`app/config.py` の `Settings` が `gmail.env` → `app.env` の順で読み込み, 後者が前者を
上書きする. Docker では `docker/docker-compose.yml` の `env_file` でコンテナ環境変数に
注入される（`app.env` は `required: false`＝無くてもエラーにならない）.

## セキュリティ（厳守）

- 実値（`gmail.env` / `app.env`）を **commit しない・外部送信しない・チャットに貼らない**.
- 値はコードにハードコードせず, 必ずこのディレクトリ経由で読む.
- 漏洩が疑われる鍵・パスワードは即ローテーション（無効化・再発行）する.
- 読み取り専用スコープを死守する（Gmail は IMAP `BODY.PEEK`＝既読化しない / 送信権限は付けない）.
