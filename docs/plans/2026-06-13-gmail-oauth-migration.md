# Plan: Gmail ログインを IMAP+アプリパスワード → OAuth 2.0 へ移行

- 作成日: 2026-06-13
- 深度: Large
- 状態: approved (2026-06-13 ユーザー承認)
- NEEDS CLARIFICATION 残数: 0

---

## Goal / Why

Gmail のログイン方式を「IMAP + アプリパスワード（16桁手動生成）」から「ブラウザ経由の OAuth 2.0（"Google でログイン"）」へ移行する．ユーザーが GCP コンソールでアプリパスワードを手動発行する手間を解消し，標準的な OAuth フローで Gmail アカウントを接続できるようにする．

---

## Non-goals（やらないこと）

- Google 本番審査（CASA セキュリティアセスメント）— Testing モード（〜100人）のまま運用
- refresh_token の Fernet 暗号化 — PoC では平文 DB 保存（将来チケットとして `DESIGN.md` に残す）
- Electron 化のコード実装 — 切替点メモを計画・コードコメントに明示するのみ
- Outlook / Slack の OAuth 統合フロー設計 — 別計画
- 既存 IMAP アカウントの自動 OAuth 移行ツール — ユーザーが手動で再追加
- refresh_token 7日失効（Testing モード制約）の回避策 — ユーザーが再接続する UX で対処

---

## 現状分析（Phase 1 探索の蒸留）

**関連ファイル（修正対象）**

| ファイル | 役割 |
|---|---|
| `app/repositories/orm.py:48` | `AccountConfigORM` テーブル定義（credential 平文・OAuth 列なし） |
| `app/models.py:81` | `AccountConfig` レスポンス型 / `AccountConfigCreate` リクエスト型 |
| `app/config.py:16` | `Settings`（pydantic-settings）— OAuth 設定フィールドなし |
| `app/repositories/account_repository.py` | CRUD — OAuth トークン操作メソッドなし |
| `app/services/ingestion.py:44` | `_build_sources()` — `auth_type` 分岐なし（常に IMAP） |
| `app/api/routes_accounts.py:36` | `POST /accounts` — `GmailImapSource.verify_credentials` 直呼び |
| `app/main.py` | lifespan で ingestion 結線・router 登録 |
| `app/api/deps.py` | app.state からの DI ヘルパー群 |
| `frontend/src/types.ts` | `AccountConfig` 型（auth_type / auth_status なし） |
| `frontend/src/api.ts:126` | `getAccounts / createAccount / deleteAccount` |
| `frontend/src/components/AccountsModal.vue:84` | アプリパスワード平文 input — OAuth UI なし |
| `frontend/src/App.vue` | ダッシュボード本体 — reauth バナーなし |
| `secrets/gmail.env.example` | GMAIL_APP_PASSWORD のみ記載 |
| `.gitignore` | `token_*.json` パターンなし（`secrets/*` で間接除外のみ） |
| `migrations/versions/20260610_0006_add_account_address.py` | 最新マイグレーション（revision `0006_add_account_address`） |

**新規作成ファイル（Phase 1）**

| ファイル | 役割 |
|---|---|
| `app/services/oauth_gmail.py` | OAuth フローサービス（認可 URL 生成・code→token・refresh） |
| `app/adapters/sources/gmail_api.py` | `MessageSource` 実装（Gmail API v1） |
| `app/api/routes_oauth.py` | OAuth エンドポイント（start / callback / reauth） |
| `migrations/versions/20260613_0007_add_oauth_columns.py` | OAuth 列マイグレーション |
| `tests/test_oauth_gmail_service.py` | OAuthGmailService 単体テスト |
| `tests/test_gmail_api_source.py` | GmailApiSource 単体テスト |
| `tests/test_routes_oauth.py` | routes_oauth 統合テスト |

**既存 OAuth 版 `app/fetch_gmail.py` について**

- `InstalledAppFlow.run_local_server()`（デスクトップアプリ型）を使っており，Web アプリフローとは別物
- SCOPES・トークン保存のロジックは参考にするが，フロー本体は使わない（書き直し）
- Phase 2 で削除

**依存パッケージ**

- `google-api-python-client`・`google-auth-oauthlib` は `requirements.txt` に pin 済み — 追加インストール不要

---

## 前提（ユーザー手動セットアップ — 実装前に確認）

以下は GCP 側の設定であり，コードの実装前に完了している必要がある．

1. GCP プロジェクトが存在し Gmail API が有効化されていること
2. OAuth クライアント ID が **Web アプリケーション** タイプで作成されていること
   - 既存 `fetch_gmail.py` が使うクライアント ID は「デスクトップアプリ」タイプのため，Web フローには別途 Web アプリタイプの作成が必要
3. Authorized redirect URI に `http://127.0.0.1:8000/auth/gmail/callback` が登録されていること
4. Testing モードのユーザーとして自分の Gmail アドレスが登録されていること
5. クライアント ID とクライアントシークレットを `secrets/gmail.env` の `GMAIL_OAUTH_CLIENT_ID` / `GMAIL_OAUTH_CLIENT_SECRET` に設定すること

---

## 設計（合意済みの決定）

### 決定 1: トークン保管先 — DB の `account_configs` テーブルを拡張

- **採用**: `account_configs` に OAuth 列を追加（マイグレーション）．既存 IMAP 行は `auth_type='imap'`，新規 OAuth は `auth_type='oauth'`
- **棄却**: `secrets/token_<id>.json` ファイル保存 — 複数アカウント対応困難・Docker 再起動で消失リスク
- **根拠**: 2026-06-13 ユーザー合意

### 決定 2: OAuth コールバック URL — API サーバに集約

- **採用**: `http://127.0.0.1:8000/auth/gmail/callback` を FastAPI で受ける
- **棄却**: ポート 8080 流用 / フロント受け
- **根拠**: 動線一本化．Electron 化時はここにカスタムスキーム受信を追加するだけ

### 決定 3: IMAP との共存 — `auth_type` 列で識別・Phase2 まで両立

- **採用**: `account_configs.auth_type` で `'imap'` / `'oauth'` を分岐．Phase1 は両方動く
- **棄却**: OAuth 実装と同時に IMAP を停止
- **根拠**: ダウンタイムゼロで移行できる．2026-06-13 ユーザー合意

### 決定 4: refresh_token 失効 UX — ダッシュボードバナー＋アカウント一覧アイコン

- **採用**: `account_configs.auth_status` 列（`'ok'` / `'reauth_required'` / `'revoked'`）．スケジューラが `RefreshError` を捕捉したら `reauth_required` に更新．UI がバナーと「再接続」ボタンを表示
- **棄却**: ログのみ通知 / サイレント停止
- **根拠**: Testing モードで 7 日毎に失効するため，気づき経路が必須

### 決定 5: Electron 化の抽象化 — 薄い集約のみ（YAGNI）

- **採用**: `app/services/oauth_gmail.py` に OAuth フロー全体を集約する（Web ロジックはルートとサービスに留める）．将来 Electron 化時は `routes_oauth.py` のコールバック受信部分をカスタムスキーム対応に差し替えるのみ
- **棄却**: コールバック戦略を Port/Adapter に抽象化
- **根拠**: Electron 化は未定．ポート化のコストに見合う時期ではない

### データ構造・インタフェース

#### `account_configs` テーブル追加列（migration 0007）

```
auth_type    VARCHAR  NOT NULL DEFAULT 'imap'   # 'imap' | 'oauth'
refresh_token VARCHAR  NULLABLE                  # OAuth のみ
access_token  VARCHAR  NULLABLE                  # OAuth のみ（キャッシュ用）
token_expiry  DATETIME NULLABLE                  # access_token の有効期限
scopes        VARCHAR  NULLABLE                  # 空白区切りのスコープ文字列
auth_status   VARCHAR  NOT NULL DEFAULT 'ok'     # 'ok' | 'reauth_required' | 'revoked'
```

既存行のバックフィル: `auth_type='imap'`, `auth_status='ok'`，その他 NULL

#### `AccountConfigORM` 追加 Mapped 列（orm.py）

```python
auth_type:    Mapped[str]           = mapped_column(String, nullable=False, default="imap")
refresh_token: Mapped[str | None]   = mapped_column(String, nullable=True)
access_token:  Mapped[str | None]   = mapped_column(String, nullable=True)
token_expiry:  Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
scopes:        Mapped[str | None]   = mapped_column(String, nullable=True)
auth_status:   Mapped[str]          = mapped_column(String, nullable=False, default="ok")
```

#### `AccountConfig` Pydantic モデル（app/models.py）

```python
class AccountConfig(BaseModel):
    id: str
    provider: str
    label: str
    address: str = ""
    auth_type: str = "imap"       # 追加
    auth_status: str = "ok"       # 追加
    created_at: datetime | None = None
```

#### `AccountRepository` 追加メソッドシグネチャ（account_repository.py）

```python
def get_by_id(self, account_id: str) -> AccountConfigORM | None: ...

def create_oauth(
    self, *, provider: str, label: str, address: str,
    refresh_token: str, access_token: str | None,
    token_expiry: datetime | None, scopes: str, auth_status: str = "ok",
) -> AccountConfig: ...

def update_oauth_tokens(
    self, account_id: str, *, refresh_token: str,
    access_token: str | None, token_expiry: datetime | None, scopes: str,
) -> None: ...

def set_auth_status(self, account_id: str, auth_status: str) -> None: ...

# list_for_ingest の戻り値 dict に以下を追加:
# "id", "auth_type", "refresh_token", "auth_status"
```

#### `Settings` 追加フィールド（config.py）

```python
gmail_oauth_client_id:     str = ""
gmail_oauth_client_secret: str = ""
gmail_oauth_redirect_uri:  str = "http://127.0.0.1:8000/auth/gmail/callback"
frontend_url:              str = "http://localhost:5173"
```

#### `OAuthGmailService` インタフェース（app/services/oauth_gmail.py）

```python
class OAuthGmailService:
    _STATE_TTL: int = 600  # 10 分

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str) -> None: ...

    def generate_auth_url(self, label: str, address: str) -> tuple[str, str]:
        """認可 URL と state を生成．state → {label, address, ts} を in-memory キャッシュ．"""
        ...

    def pop_state(self, state: str) -> dict | None:
        """state を検証して削除．期限切れ / 不明なら None．"""
        ...

    def exchange_code(self, code: str) -> dict:
        """code をトークンに交換して {refresh_token, access_token, token_expiry, scopes} を返す．"""
        ...

    def build_credentials(self, refresh_token: str) -> Credentials:
        """保存済み refresh_token から Credentials を構築（GmailApiSource 用）．"""
        ...
```

- `Flow.from_client_config({"web": {...}}, scopes=SCOPES, redirect_uri=redirect_uri)` を使う
- `authorization_url()` に `access_type="offline"`, `prompt="consent"` を渡す（毎回 refresh_token を発行させる）
- `_pending_states` は `dict[str, dict]` の in-memory dict（サーバ再起動で消える，PoC として許容）

#### `GmailApiSource` インタフェース（app/adapters/sources/gmail_api.py）

```python
class GmailApiSource:
    def __init__(
        self,
        refresh_token: str,
        client_id: str,
        client_secret: str,
        account_id: str,           # auth_status 更新に使う
        account_repo: AccountRepository,
        max_body_chars: int = 4000,
    ) -> None: ...

    def list_recent(self, limit: int = 10) -> list[EmailMessage]:
        """Gmail API v1 で受信トレイを取得して EmailMessage のリストを返す（読み取り専用）．"""
        ...

    @property
    def address(self) -> str:
        """取得元アドレス（ingestion.py の account_address 埋め込み用）．OAuth では acc["address"] を使うため空文字を返す．"""
        return ""

    def close(self) -> None:
        """no-op（HTTP セッションは GC に任せる）．"""
        ...
```

- `google.oauth2.credentials.Credentials(token=None, refresh_token=..., ...)` を構築して `creds.refresh(Request())` で access_token を取得
- `google.auth.exceptions.RefreshError` を捕捉したら `account_repo.set_auth_status(account_id, "reauth_required")` を呼んで re-raise
- `ingestion.py` が `source.address` を参照する箇所では，`GmailApiSource` は `acc["address"]` から取得済みのため，`address` プロパティは空文字で構わない（Task 12 で対処）
- メール取得は `service.users().messages().list` + `.get(format="full")` で本文も取得
- `BODY.PEEK` 相当の対策: Gmail API は既読化しない（API は `users.messages.get` のみで既読化は `modify` が必要）

#### OAuth エンドポイント仕様（routes_oauth.py）

```
GET  /auth/gmail/start?label=<>&address=<>
  → 200: {auth_url: str, state: str}
  → 400: クライアント ID 未設定時

GET  /auth/gmail/callback?code=<>&state=<>
  → 302: {frontend_url}/?oauth_success=1（成功）
  → 400: state 無効 / 期限切れ
  → 302: {frontend_url}/?oauth_error=exchange_failed（code 交換失敗）

POST /auth/gmail/{account_id}/reauth
  → 200: {auth_url: str, state: str}
  → 404: アカウント不明
```

コールバック処理順序:
1. `service.pop_state(state)` → `{label, address}` を取得
2. `service.exchange_code(code)` → `{refresh_token, access_token, token_expiry, scopes}`
3. Gmail API で `users().getProfile(userId='me')` → `emailAddress` を取得（`address` が空なら上書き）
4. `account_repo.create_oauth(...)` で DB に保存
5. `RedirectResponse(f"{settings.frontend_url}/?oauth_success=1")`

#### `app/api/deps.py` 追加 DI

```python
def get_oauth_service(request: Request) -> OAuthGmailService:
    return request.app.state.oauth_service
```

#### `app/main.py` lifespan 追加処理

```python
from app.api import routes_oauth
from app.services.oauth_gmail import OAuthGmailService

# lifespan 内，app.state 設定部分に追加:
app.state.oauth_service = OAuthGmailService(
    client_id=settings.gmail_oauth_client_id,
    client_secret=settings.gmail_oauth_client_secret,
    redirect_uri=settings.gmail_oauth_redirect_uri,
)

# lifespan の yield の後，router 登録に追加:
app.include_router(routes_oauth.router)
```

env 自動登録ロジック（lifespan の `if settings.gmail_address and settings.gmail_app_password`）は IMAP 専用のため，変更不要（Phase 2 で削除）

#### フロントエンド型追加（types.ts）

```typescript
export interface AccountConfig {
  id: string;
  provider: string;
  label: string;
  address: string;
  auth_type: string;    // 追加: 'imap' | 'oauth'
  auth_status: string;  // 追加: 'ok' | 'reauth_required' | 'revoked'
  created_at: string | null;
}

export interface OAuthStartResponse {
  auth_url: string;
  state: string;
}
```

#### フロントエンド API 追加（api.ts）

```typescript
export async function startGmailOAuth(label: string, address: string): Promise<OAuthStartResponse>
  // GET /auth/gmail/start?label=<>&address=<>

export async function reauthGmailAccount(accountId: string): Promise<OAuthStartResponse>
  // POST /auth/gmail/{accountId}/reauth
```

---

## Complexity Tracking（複雑性の正当化台帳）

| 違反 | 正当化 |
|---|---|
| 新しいサービスレイヤ追加（`oauth_gmail.py`）| OAuth フロー（認可 URL 生成・code 交換・state 管理）は複数のルートから使うため，ルートに直書きすると重複する．Electron 化時の差し替え点の局所化にも必要 |
| 新しいアダプタ追加（`gmail_api.py`）| 既存 `MessageSource` ポートの別実装．IMAP と API は I/O 経路が完全に異なるため同一クラスに混ぜると可読性が下がる |
| `account_configs` に 6 列追加 | OAuth トークンセットはアトミックに扱う必要があり，別テーブルより同テーブル拡張が素直 |

---

## タスク分解

> 各タスクは文脈ゼロの実装者へ単体で渡せる粒度（2〜30分）．[P] = 並列可能（ファイル所有が重ならない）．並列可能タスクは全て異なるファイルを所有する．

---

### Task 1: `.gitignore` に `token_*.json` を追加 [P]

- **対象**: `.gitignore`（modify）
- **手順**:
  1. `.gitignore` の既存 `*.token` 行の後に `token_*.json` を追加（`app/fetch_gmail.py` が使う `token_gmail.json` は `secrets/` 内なので既に `secrets/*` でカバーされているが，プロジェクトルートに置かれた場合に備えて追加）
  2. `gmail_credentials.json` は現行 `credentials*.json` パターンにマッチしないため（プレフィックスが `gmail_`），`*credentials*.json` を追記する（ワイルドカードを前に付けることで `gmail_credentials.json` 等のプレフィックス付きも除外）
- **検証**: `git check-ignore -v token_gmail.json` → `.gitignore:N:token_*.json  token_gmail.json`  
  `git check-ignore -v gmail_credentials.json` → `.gitignore` でマッチすること
- **完了条件**: `token_*.json` と `gmail_credentials.json` の両パターンが `.gitignore` で除外されている
- **commit**: `chore: token_*.json と gmail_credentials.json を .gitignore に追加`

---

### Task 2: Alembic マイグレーション — `account_configs` に OAuth 列追加 [P]

- **対象**: `migrations/versions/20260613_0007_add_oauth_columns.py`（create）
- **手順**:
  1. 以下の内容でファイルを作成（`down_revision = "0006_add_account_address"`）

```python
"""account_configs に OAuth 用列を追加.

Revision ID: 0007_add_oauth_columns
Revises: 0006_add_account_address
Create Date: 2026-06-13
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_add_oauth_columns"
down_revision = "0006_add_account_address"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("account_configs") as batch_op:
        batch_op.add_column(sa.Column("auth_type", sa.String(), nullable=False, server_default="imap"))
        batch_op.add_column(sa.Column("refresh_token", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("access_token", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("token_expiry", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("scopes", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("auth_status", sa.String(), nullable=False, server_default="ok"))


def downgrade() -> None:
    with op.batch_alter_table("account_configs") as batch_op:
        for col in ("auth_status", "scopes", "token_expiry", "access_token", "refresh_token", "auth_type"):
            batch_op.drop_column(col)
```

- **検証**: `PYTHONPATH=. alembic upgrade head` → `Running upgrade 0006_add_account_address -> 0007_add_oauth_columns, account_configs に OAuth 用列を追加.` が出力される  
  `PYTHONPATH=. alembic downgrade -1` → downgrade が正常完了
- **完了条件**: `alembic upgrade head` が 0 で終了し，`data/ReplyGuard.db` の `account_configs` テーブルに `auth_type`, `auth_status` 等 6 列が存在する
- **commit**: `feat(db): account_configs に OAuth 用列 6 本を追加するマイグレーション`

---

### Task 3: `app/repositories/orm.py` — AccountConfigORM に OAuth 列追加 [P]

- **対象**: `app/repositories/orm.py`（modify）
- **手順**:
  1. `AccountConfigORM` クラスに以下の `Mapped` 列を追加（`created_at` の後）:

```python
auth_type:     Mapped[str]            = mapped_column(String, nullable=False, default="imap")
refresh_token: Mapped[str | None]     = mapped_column(String, nullable=True)
access_token:  Mapped[str | None]     = mapped_column(String, nullable=True)
token_expiry:  Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
scopes:        Mapped[str | None]     = mapped_column(String, nullable=True)
auth_status:   Mapped[str]            = mapped_column(String, nullable=False, default="ok")
```

  2. `datetime` が未 import なら `from datetime import datetime` を追加

- **検証**: `python -c "from app.repositories.orm import AccountConfigORM; print([c.key for c in AccountConfigORM.__table__.columns])"` → `auth_type`, `refresh_token`, `auth_status` 等が出力される
- **完了条件**: ORM クラスに 6 列が定義されており，インポートエラーなし
- **commit**: `feat(orm): AccountConfigORM に OAuth 列 6 本を追加`

---

### Task 4: `app/models.py` — AccountConfig レスポンス型に auth_type / auth_status を追加 [P]

- **対象**: `app/models.py`（modify）
- **手順**:
  1. `AccountConfig` クラスに `auth_type: str = "imap"` と `auth_status: str = "ok"` フィールドを追加（`address` の後，`created_at` の前）
  2. `AccountConfigCreate` には変更なし（IMAP 用のまま）
- **検証**: `python -c "from app.models import AccountConfig; a = AccountConfig(id='1', provider='gmail', label='t', auth_type='oauth', auth_status='ok'); print(a.auth_type, a.auth_status)"` → `oauth ok`
- **完了条件**: `AccountConfig` に `auth_type` と `auth_status` が含まれ，デフォルト値が正しい
- **commit**: `feat(models): AccountConfig に auth_type / auth_status フィールドを追加`

---

### Task 5: `app/config.py` + `secrets/gmail.env.example` — OAuth 設定フィールド追加 [P]

- **対象**: `app/config.py`（modify），`secrets/gmail.env.example`（modify）
- **手順**:
  1. `app/config.py` の `Settings` クラスに，`# === Gmail（取得・正規化層）===` ブロックの末尾に追記:

```python
# OAuth フロー設定（アプリパスワード方式の代替）
gmail_oauth_client_id:     str = ""
gmail_oauth_client_secret: str = ""
gmail_oauth_redirect_uri:  str = "http://127.0.0.1:8000/auth/gmail/callback"
frontend_url:              str = "http://localhost:5173"
```

  2. `secrets/gmail.env.example` に以下を追記:

```bash
# OAuth 版（アプリパスワードの代わりに使用）
# Web アプリケーションタイプのクライアント ID/シークレット（GCP Console で取得）
# GMAIL_OAUTH_CLIENT_ID=<クライアントID>.apps.googleusercontent.com
# GMAIL_OAUTH_CLIENT_SECRET=GOCSPX-xxxxx
# GMAIL_OAUTH_REDIRECT_URI=http://127.0.0.1:8000/auth/gmail/callback
# FRONTEND_URL=http://localhost:5173
```

- **検証**: `python -c "from app.config import get_settings; get_settings.cache_clear(); s = get_settings(); print(s.gmail_oauth_redirect_uri, s.frontend_url)"` → `http://127.0.0.1:8000/auth/gmail/callback http://localhost:5173`
- **完了条件**: Settings に 4 フィールドが追加され，デフォルト値が正しい
- **commit**: `feat(config): Gmail OAuth フロー用設定フィールドを追加`

---

### Task 6: `app/repositories/account_repository.py` — OAuth 対応メソッド追加

- **対象**: `app/repositories/account_repository.py`（modify）
- **依存**: Task 3（ORM 列が存在すること）
- **手順**:
  1. `get_by_id` メソッドを追加:

```python
def get_by_id(self, account_id: str) -> AccountConfigORM | None:
    with self._session_factory() as session:
        return session.get(AccountConfigORM, account_id)
```

  2. `create_oauth` メソッドを追加（OAuth コールバックで呼ぶ）:

```python
def create_oauth(
    self, *, provider: str, label: str, address: str,
    refresh_token: str, access_token: str | None = None,
    token_expiry: datetime | None = None, scopes: str = "",
    auth_status: str = "ok",
) -> AccountConfig:
    now = _utcnow_naive()
    orm = AccountConfigORM(
        id=str(uuid.uuid4()),
        provider=provider, label=label, address=address,
        credential="",         # OAuth では不要のため空文字
        auth_type="oauth",
        refresh_token=refresh_token,
        access_token=access_token,
        token_expiry=token_expiry,
        scopes=scopes,
        auth_status=auth_status,
        created_at=now,
    )
    with self._session_factory() as session:
        session.add(orm)
        session.commit()
        return AccountConfig(
            id=orm.id, provider=orm.provider, label=orm.label,
            address=orm.address, auth_type=orm.auth_type, auth_status=orm.auth_status,
            created_at=orm.created_at,
        )
```

  3. `update_oauth_tokens` メソッドを追加:

```python
def update_oauth_tokens(
    self, account_id: str, *, refresh_token: str,
    access_token: str | None, token_expiry: datetime | None, scopes: str,
) -> None:
    with self._session_factory() as session:
        row = session.get(AccountConfigORM, account_id)
        if row is None:
            return
        row.refresh_token = refresh_token
        row.access_token = access_token
        row.token_expiry = token_expiry
        row.scopes = scopes
        row.auth_status = "ok"
        session.commit()
```

  4. `set_auth_status` メソッドを追加:

```python
def set_auth_status(self, account_id: str, auth_status: str) -> None:
    with self._session_factory() as session:
        row = session.get(AccountConfigORM, account_id)
        if row is None:
            return
        row.auth_status = auth_status
        session.commit()
```

  5. `list_all` メソッドの戻り値に `auth_type` と `auth_status` を追加:

```python
return [
    AccountConfig(
        id=r.id, provider=r.provider, label=r.label, address=r.address,
        auth_type=r.auth_type, auth_status=r.auth_status, created_at=r.created_at,
    )
    for r in rows
]
```

  6. `list_for_ingest` メソッドの戻り値 dict に `"id"`, `"auth_type"`, `"refresh_token"`, `"auth_status"` を追加（**既存の `"address"`・`"credential"` の 2 キーは残す**。下記は dict リテラル全体の置き換えサンプルであり、6 キー全てを含むこと）:

```python
return [
    {
        "id": r.id,
        "provider": r.provider,
        "address": r.address,       # 既存キー — 残す
        "credential": r.credential, # 既存キー — 残す
        "auth_type": r.auth_type or "imap",
        "refresh_token": r.refresh_token,
        "auth_status": r.auth_status or "ok",
    }
    for r in rows
]
```

  7. `create` メソッドの戻り値に `address=orm.address`, `auth_type="imap"`, `auth_status="ok"` を追加:

```python
return AccountConfig(
    id=orm.id, provider=orm.provider, label=orm.label,
    address=orm.address,   # 追加
    auth_type="imap",      # 追加
    auth_status="ok",      # 追加
    created_at=orm.created_at,
)
```

- **検証**: `pytest tests/test_account_repository.py -q` が全通過，もしくは `python -c "from app.repositories.account_repository import AccountRepository"` でインポートエラーなし
- **完了条件**: 4 メソッドが追加され，既存メソッドも `auth_type` / `auth_status` を返すように更新されている
- **commit**: `feat(repo): AccountRepository に OAuth 対応メソッドと auth_type/auth_status を追加`

---

### Task 7: `app/services/oauth_gmail.py` 新設 [P]

- **対象**: `app/services/oauth_gmail.py`（create）
- **手順**:
  1. 以下の構造でファイルを作成:

```python
"""Gmail OAuth 2.0 フローサービス.

認可 URL 生成・state 管理・code→token 交換・token refresh を担う.
Web アプリ向け Flow を使う（InstalledAppFlow とは別物）.

Electron 化時の差し替え点:
- generate_auth_url / callback 受信部分をカスタムスキーム対応に置き換える
- このファイルの __init__ / pop_state / exchange_code は変更不要
"""
import secrets
import time

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_TOKEN_URI = "https://oauth2.googleapis.com/token"


class OAuthGmailService:
    _STATE_TTL = 600  # 10 分（秒）

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._pending_states: dict[str, dict] = {}

    def generate_auth_url(self, label: str, address: str) -> tuple[str, str]:
        flow = self._make_flow()
        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        self._pending_states[state] = {"label": label, "address": address, "ts": time.monotonic()}
        return auth_url, state

    def pop_state(self, state: str) -> dict | None:
        entry = self._pending_states.pop(state, None)
        if entry is None:
            return None
        if time.monotonic() - entry["ts"] > self._STATE_TTL:
            return None
        return entry

    def exchange_code(self, code: str) -> dict:
        """code をトークンに交換して {refresh_token, access_token, token_expiry, scopes} を返す."""
        flow = self._make_flow()
        flow.fetch_token(code=code)
        creds = flow.credentials
        return {
            "refresh_token": creds.refresh_token,
            "access_token": creds.token,
            "token_expiry": creds.expiry,
            "scopes": " ".join(sorted(creds.scopes or [])),
        }

    def build_credentials(self, refresh_token: str) -> Credentials:
        """保存済み refresh_token から Credentials を構築する（GmailApiSource 用）."""
        return Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=_TOKEN_URI,
            client_id=self._client_id,
            client_secret=self._client_secret,
            scopes=SCOPES,
        )

    def _make_flow(self) -> Flow:
        client_config = {
            "web": {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "redirect_uris": [self._redirect_uri],
                "auth_uri": _AUTH_URI,
                "token_uri": _TOKEN_URI,
            }
        }
        return Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=self._redirect_uri)
```

- **検証**: `python -c "from app.services.oauth_gmail import OAuthGmailService; s = OAuthGmailService('id', 'sec', 'http://localhost:8000/cb'); print('ok')"` → `ok`
- **完了条件**: インポートエラーなし，`OAuthGmailService` の 5 メソッドが全て定義されている
- **commit**: `feat(services): OAuthGmailService 新設（認可 URL 生成・state 管理・code 交換）`

---

### Task 8: `app/adapters/sources/gmail_api.py` 新設 [P]

- **対象**: `app/adapters/sources/gmail_api.py`（create）
- **手順**:
  1. 以下の構造でファイルを作成:

```python
"""Gmail API v1 MessageSource アダプタ.

OAuth 2.0 Credentials を使って Gmail API v1 でメールを取得する.
既存 GmailImapSource と同じ MessageSource プロトコルを実装する.

読み取り専用スコープ（gmail.readonly）のみ使用.
users.messages.get は既読化しない（modify 操作は行わない）.
"""
import base64
import logging
from datetime import datetime, timezone
from email import message_from_bytes
from email.header import decode_header

import google.auth.exceptions
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.models import EmailMessage
from app.repositories.account_repository import AccountRepository

logger = logging.getLogger(__name__)


class GmailApiSource:
    def __init__(
        self,
        refresh_token: str,
        client_id: str,
        client_secret: str,
        account_id: str,
        account_repo: AccountRepository,
        max_body_chars: int = 4000,
    ) -> None:
        self._refresh_token = refresh_token
        self._client_id = client_id
        self._client_secret = client_secret
        self._account_id = account_id
        self._account_repo = account_repo
        self._max_body_chars = max_body_chars

    def list_recent(self, limit: int = 10) -> list[EmailMessage]:
        try:
            service = self._build_service()
        except google.auth.exceptions.RefreshError:
            logger.warning("Gmail OAuth token 失効 (account_id=%s)", self._account_id)
            self._account_repo.set_auth_status(self._account_id, "reauth_required")
            raise

        resp = service.users().messages().list(
            userId="me", maxResults=limit, labelIds=["INBOX"]
        ).execute()
        messages = resp.get("messages", [])
        results = []
        for m in messages:
            try:
                results.append(self._fetch_message(service, m["id"]))
            except Exception:
                logger.exception("メール取得失敗 (id=%s, account=%s)", m["id"], self._account_id)
        return results

    def close(self) -> None:
        pass

    def _build_service(self):
        creds = Credentials(
            token=None,
            refresh_token=self._refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self._client_id,
            client_secret=self._client_secret,
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        )
        creds.refresh(Request())
        return build("gmail", "v1", credentials=creds)

    def _fetch_message(self, service, message_id: str) -> EmailMessage:
        msg = service.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        body = self._extract_body(msg.get("payload", {}))
        received_at = None
        if "date" in headers:
            try:
                from email.utils import parsedate_to_datetime
                received_at = parsedate_to_datetime(headers["date"])
            except Exception:
                pass
        return EmailMessage(
            id=message_id,
            provider="gmail",
            subject=self._decode_header(headers.get("subject", "")),
            sender=headers.get("from", ""),
            to=[t.strip() for t in headers.get("to", "").split(",") if t.strip()],
            received_at=received_at,
            snippet=msg.get("snippet", "")[:200],
            is_unread="UNREAD" in msg.get("labelIds", []),
            body_text=body[: self._max_body_chars] if body else None,
        )

    def _extract_body(self, payload: dict) -> str:
        # まずパート列を再帰的に探索して text/plain を優先
        if payload.get("mimeType") == "text/plain":
            data = payload.get("body", {}).get("data", "")
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace") if data else ""
        for part in payload.get("parts", []):
            result = self._extract_body(part)
            if result:
                return result
        return ""

    def _decode_header(self, raw: str) -> str:
        parts = decode_header(raw)
        return "".join(
            t.decode(enc or "utf-8", errors="replace") if isinstance(t, bytes) else t
            for t, enc in parts
        )
```

- **検証**: `python -c "from app.adapters.sources.gmail_api import GmailApiSource; print('ok')"` → `ok`
- **完了条件**: インポートエラーなし，`MessageSource` プロトコルの `list_recent` と `close` が実装されている
- **commit**: `feat(adapters): GmailApiSource 新設（Gmail API v1 OAuth 版 MessageSource）`

---

### Task 9: `app/api/routes_oauth.py` 新設

- **対象**: `app/api/routes_oauth.py`（create）
- **依存**: Task 5（Settings の `frontend_url` / `gmail_oauth_*` フィールド）, Task 6（`AccountRepository.create_oauth`）, Task 7（`OAuthGmailService`）
- **手順**:
  1. 以下の構造でファイルを作成:

```python
"""Gmail OAuth 2.0 フローのエンドポイント.

GET  /auth/gmail/start?label=<>&address=<>   認可 URL 発行
GET  /auth/gmail/callback?code=<>&state=<>   コールバック受信 → 302 リダイレクト
POST /auth/gmail/{account_id}/reauth         期限切れアカウントの再接続 URL 発行
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from googleapiclient.discovery import build

from app.api.deps import get_account_repo, get_oauth_service, get_settings
from app.repositories.account_repository import AccountRepository
from app.services.oauth_gmail import OAuthGmailService
from app.config import Settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth/gmail", tags=["oauth"])


@router.get("/start")
def start_oauth(
    label: str,
    address: str,
    service: OAuthGmailService = Depends(get_oauth_service),
    settings: Settings = Depends(get_settings),
) -> dict:
    if not settings.gmail_oauth_client_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GMAIL_OAUTH_CLIENT_ID が未設定です（secrets/gmail.env を確認）",
        )
    auth_url, state = service.generate_auth_url(label=label, address=address)
    return {"auth_url": auth_url, "state": state}


@router.get("/callback")
def oauth_callback(
    code: str,
    state: str,
    request: Request,
    service: OAuthGmailService = Depends(get_oauth_service),
    repo: AccountRepository = Depends(get_account_repo),
    settings: Settings = Depends(get_settings),
):
    state_data = service.pop_state(state)
    if state_data is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="state が無効または期限切れです")

    try:
        token_info = service.exchange_code(code)
    except Exception:
        logger.exception("OAuth code 交換に失敗 (state=%s)", state)
        return RedirectResponse(f"{settings.frontend_url}/?oauth_error=exchange_failed")

    # Gmail API でメールアドレスを取得（ユーザー入力 address が空なら上書き）
    address = state_data.get("address", "")
    if not address:
        try:
            creds = service.build_credentials(token_info["refresh_token"])
            from google.auth.transport.requests import Request as GRequest
            creds.refresh(GRequest())
            gmail_service = build("gmail", "v1", credentials=creds)
            profile = gmail_service.users().getProfile(userId="me").execute()
            address = profile.get("emailAddress", "")
        except Exception:
            logger.exception("Gmail プロフィール取得失敗（address は空のまま）")

    repo.create_oauth(
        provider="gmail",
        label=state_data.get("label", address or "gmail"),
        address=address,
        refresh_token=token_info["refresh_token"],
        access_token=token_info.get("access_token"),
        token_expiry=token_info.get("token_expiry"),
        scopes=token_info.get("scopes", ""),
    )
    return RedirectResponse(f"{settings.frontend_url}/?oauth_success=1")


@router.post("/{account_id}/reauth")
def reauth_account(
    account_id: str,
    service: OAuthGmailService = Depends(get_oauth_service),
    repo: AccountRepository = Depends(get_account_repo),
    settings: Settings = Depends(get_settings),
) -> dict:
    account_orm = repo.get_by_id(account_id)
    if account_orm is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="アカウントが見つかりません")
    if not settings.gmail_oauth_client_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="GMAIL_OAUTH_CLIENT_ID が未設定です")
    auth_url, state = service.generate_auth_url(
        label=account_orm.label, address=account_orm.address
    )
    return {"auth_url": auth_url, "state": state}
```

- **検証**: `python -c "from app.api.routes_oauth import router; print(len(router.routes), 'routes')"` → `3 routes`
- **完了条件**: 3 エンドポイントが定義され，インポートエラーなし
- **commit**: `feat(api): Gmail OAuth エンドポイント（start / callback / reauth）を新設`

---

### Task 10: `app/api/deps.py` — `get_oauth_service` DI を追加

- **対象**: `app/api/deps.py`（modify）
- **手順**:
  1. `OAuthGmailService` のインポートを追加:

```python
from app.services.oauth_gmail import OAuthGmailService
```

  2. 既存の `get_account_repo` の後に追加:

```python
def get_oauth_service(request: Request) -> OAuthGmailService:
    return request.app.state.oauth_service
```

- **検証**: `python -c "from app.api.deps import get_oauth_service; print('ok')"` → `ok`
- **完了条件**: `get_oauth_service` が `deps.py` に定義されている
- **commit**: `feat(deps): get_oauth_service DI ヘルパーを追加`

---

### Task 11: `app/main.py` — routes_oauth 登録・OAuthGmailService インスタンス化

- **対象**: `app/main.py`（modify）
- **依存**: Task 9（routes_oauth），Task 7（OAuthGmailService），Task 5（Settings フィールド）
- **手順**:
  1. インポートに追加:

```python
from app.api import routes_oauth
from app.services.oauth_gmail import OAuthGmailService
```

  2. lifespan 内の `app.state.state_service = state_service` の後に追加:

```python
app.state.oauth_service = OAuthGmailService(
    client_id=settings.gmail_oauth_client_id,
    client_secret=settings.gmail_oauth_client_secret,
    redirect_uri=settings.gmail_oauth_redirect_uri,
)
```

  3. ファイル末尾の `app.include_router(routes_accounts.router)` の後に追加:

```python
app.include_router(routes_oauth.router)
```

  4. CORS の `allow_methods` に `"POST"` が含まれているか確認（既に含まれていれば変更不要）

- **検証**: 別ターミナルで `PYTHONPATH=. uvicorn app.main:app --port 8000` を起動してから，このターミナルで `curl -s http://127.0.0.1:8000/openapi.json | python -c "import sys,json; routes=list(json.load(sys.stdin)['paths']); print('/auth/gmail/start' in routes)"` → `True`
- **完了条件**: `/auth/gmail/start`, `/auth/gmail/callback`, `/auth/gmail/{account_id}/reauth` が OpenAPI に現れる
- **commit**: `feat(main): routes_oauth を登録し OAuthGmailService を lifespan で初期化`

---

### Task 12: `app/services/ingestion.py` — auth_type 分岐 + RefreshError ハンドリング

- **対象**: `app/services/ingestion.py`（modify）
- **依存**: Task 6（`list_for_ingest` に `auth_type` / `id` / `refresh_token` / `auth_status` が追加済み），Task 8（`GmailApiSource`）
- **手順**:
  1. インポートを追加:

```python
import google.auth.exceptions
from app.adapters.sources.gmail_api import GmailApiSource
```

  2. `_build_sources` の Gmail 分岐を書き換え:

```python
for acc in accounts:
    if acc.get("auth_status", "ok") not in ("ok", ""):
        logger.warning(
            "アカウントスキップ (auth_status=%s, address=%s)",
            acc.get("auth_status"), acc.get("address"),
        )
        continue
    if acc["provider"] == "gmail":
        auth_type = acc.get("auth_type", "imap")
        if auth_type == "oauth":
            sources.append(
                GmailApiSource(
                    refresh_token=acc["refresh_token"],
                    client_id=self._settings.gmail_oauth_client_id,
                    client_secret=self._settings.gmail_oauth_client_secret,
                    account_id=acc["id"],
                    account_repo=self._account_repo,
                    max_body_chars=self._settings.llm_max_body_chars,
                )
            )
        else:
            sources.append(
                GmailImapSource(
                    acc["address"],
                    acc["credential"],
                    max_body_chars=self._settings.llm_max_body_chars,
                )
            )
    elif acc["provider"] == "slack":
        # 変更なし
        ...
```

  3. `run_once` の `sources = self._build_sources()` 部分の後，各 source の `list_recent` 呼び出しで `google.auth.exceptions.RefreshError` をキャッチして継続するよう，既存の `except Exception` の前に明示ログを追加（`RefreshError` 自体は `GmailApiSource.list_recent` 内で `set_auth_status` を呼んでから re-raise するので，ここでは catch して `continue` する）

```python
try:
    emails = source.list_recent(limit=self._settings.ingest_limit)
except google.auth.exceptions.RefreshError:
    logger.warning("OAuth token 失効のためアカウントをスキップ（UI でリフレッシュ要）")
    continue
except Exception:
    logger.exception("取得失敗（継続）")
    continue
```

- **検証**: `pytest tests/ -q` → 既存テスト全通過（IMAP パスが壊れていないこと）
- **完了条件**: IMAP アカウントはこれまで通り動き，OAuth アカウントは `GmailApiSource` を通す分岐が実装されている
- **commit**: `feat(ingestion): auth_type 分岐で OAuth/IMAP ソースを切り替え・RefreshError をハンドリング`

---

### Task 13: フロント `frontend/src/types.ts` + `frontend/src/api.ts` — OAuth 対応型・API 追加 [P]

- **対象**: `frontend/src/types.ts`（modify），`frontend/src/api.ts`（modify）
- **手順**:
  1. `types.ts` の `AccountConfig` インタフェースに追加:

```typescript
export interface AccountConfig {
  id: string;
  provider: string;
  label: string;
  address: string;
  auth_type: string;    // 'imap' | 'oauth'
  auth_status: string;  // 'ok' | 'reauth_required' | 'revoked'
  created_at: string | null;
}

export interface OAuthStartResponse {
  auth_url: string;
  state: string;
}
```

  2. `api.ts` に以下を追加（`deleteAccount` の後）:

```typescript
export async function startGmailOAuth(
  label: string,
  address: string
): Promise<OAuthStartResponse> {
  const params = new URLSearchParams({ label, address });
  const res = await fetch(`${API_BASE}/auth/gmail/start?${params}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "OAuth 開始に失敗しました.");
  }
  return res.json();
}

export async function reauthGmailAccount(accountId: string): Promise<OAuthStartResponse> {
  const res = await fetch(`${API_BASE}/auth/gmail/${accountId}/reauth`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "再接続 URL の取得に失敗しました.");
  }
  return res.json();
}
```

- **検証**: `cd frontend && npm run typecheck` → TypeScript エラーなし
- **完了条件**: `AccountConfig` に `auth_type` / `auth_status` があり，`startGmailOAuth` と `reauthGmailAccount` が型エラーなく定義されている
- **commit**: `feat(frontend/types,api): OAuth 対応型・API 関数を追加`

---

### Task 14: フロント `frontend/src/components/AccountsModal.vue` — Gmail タブを OAuth フローへ変更

- **対象**: `frontend/src/components/AccountsModal.vue`（modify）
- **依存**: Task 13（`startGmailOAuth`，`OAuthStartResponse` 型）
- **手順**:
  1. `import { startGmailOAuth } from "../api"` を追加
  2. Gmail タブのフォームを変更:
     - `credential` 入力フィールドを削除（Gmail タブでは不要）
     - `credentialLabel` / `credentialPlaceholder` の computed は Gmail 以外（Slack）のみに適用されるよう修正
     - 以下のハンドラを追加:

```typescript
const oauthLoading = ref(false);
const oauthError = ref<string | null>(null);

async function onGoogleConnect(): Promise<void> {
  oauthError.value = null;
  if (!form.value.label.trim()) {
    oauthError.value = "表示名を入力してください.";
    return;
  }
  if (!form.value.address.trim()) {
    oauthError.value = "メールアドレスを入力してください.";
    return;
  }
  oauthLoading.value = true;
  try {
    const { auth_url } = await startGmailOAuth(form.value.label, form.value.address);
    window.location.href = auth_url;  // 同タブで遷移（OAuth 後に frontend_url?oauth_success=1 へ戻る）
  } catch (e) {
    oauthError.value = e instanceof Error ? e.message : "OAuth 開始に失敗しました.";
  } finally {
    oauthLoading.value = false;
  }
}
```

  3. template の Gmail タブ部分: `credential` `<input>` を削除し，「Google で接続」ボタンを追加:

```html
<!-- Gmail タブ内の credential フィールドを削除し，代わりに -->
<button
  type="button"
  class="oauth-btn"
  :disabled="oauthLoading"
  @click="onGoogleConnect"
>
  {{ oauthLoading ? "接続中..." : "Google アカウントで接続" }}
</button>
<p v-if="oauthError" class="error-text">{{ oauthError }}</p>
```

  4. Gmail タブでは `<form>` の `@submit` を経由させない．「Google アカウントで接続」ボタンは `type="button"` で `@click="onGoogleConnect"` に直結し，`onSubmit` を呼ばない構造とする（`onSubmit` 自体は Slack タブで引き続き使用するため削除しない）

  5. スタイル追加（既存 CSS 変数を使用）:

```css
.oauth-btn {
  width: 100%;
  padding: 0.75rem;
  background: var(--color-accent, #4285f4);
  color: white;
  border: none;
  border-radius: var(--radius-md, 8px);
  cursor: pointer;
  font-size: 1rem;
}
.oauth-btn:disabled { opacity: 0.6; cursor: not-allowed; }
```

- **検証**: `cd frontend && npm run build` → ビルドエラーなし  
  ブラウザで AccountsModal を開き，Gmail タブに「Google アカウントで接続」ボタンが表示されることを目視確認
- **完了条件**: Gmail タブで credential フィールドが消え，OAuth ボタンが表示される．Slack タブは credential 入力のまま（変更なし）
- **commit**: `feat(AccountsModal): Gmail タブを OAuth フロー（Google アカウントで接続）に変更`

---

### Task 15: フロント `frontend/src/App.vue` — oauth_success 検出バナー + reauth_required バナー

- **対象**: `frontend/src/App.vue`（modify）
- **依存**: Task 13（`reauthGmailAccount`，`AccountConfig.auth_status`），Task 14（OAuth 後の画面遷移の戻り先）
- **手順**:
  1. `import { reauthGmailAccount } from "./api"` を追加
  2. `onMounted` に以下を追加（URL の `?oauth_success=1` を検出してアカウントリストを更新）:

```typescript
const oauthSuccessBanner = ref(false);

// onMounted 内に追加:
const urlParams = new URLSearchParams(window.location.search);
if (urlParams.get("oauth_success") === "1") {
  oauthSuccessBanner.value = true;
  // URL クリーンアップ（ブラウザ履歴を汚さない）
  window.history.replaceState({}, "", window.location.pathname);
  // アカウントリストを更新（App.vue の既存関数）
  await refreshAccountStatus();
}
```

  3. reauth_required アカウントのリストを computed で取得:

```typescript
const reauthAccounts = computed(() =>
  accountsList.value.filter(a => a.auth_status === "reauth_required")
);
```

  4. template に以下のバナーを追加（メッセージリストの上部）:

```html
<!-- OAuth 成功バナー -->
<div v-if="oauthSuccessBanner" class="banner banner--success">
  Gmail アカウントの接続が完了しました．
  <button @click="oauthSuccessBanner = false">✕</button>
</div>

<!-- reauth_required バナー -->
<div v-if="reauthAccounts.length" class="banner banner--warn">
  {{ reauthAccounts.length }} 件のアカウントで Google 認証の更新が必要です．
  <button
    v-for="acc in reauthAccounts"
    :key="acc.id"
    @click="onReauth(acc.id)"
  >{{ acc.label }} を再接続</button>
</div>
```

  5. `onReauth` ハンドラを追加:

```typescript
async function onReauth(accountId: string): Promise<void> {
  try {
    const { auth_url } = await reauthGmailAccount(accountId);
    window.location.href = auth_url;
  } catch (e) {
    console.error("再接続 URL 取得失敗", e);
  }
}
```

  6. バナースタイル追加（既存 CSS 変数を使用）:

```css
.banner { padding: 0.75rem 1rem; border-radius: var(--radius-md, 8px); margin-bottom: 1rem; display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
.banner--success { background: #d1fae5; color: #065f46; }
.banner--warn    { background: #fef3c7; color: #92400e; }
.banner button   { margin-left: auto; background: transparent; border: 1px solid currentColor; border-radius: 4px; padding: 2px 8px; cursor: pointer; }
```

  7. `accounts` ref が `AccountConfig[]` 型であることを確認（Task 13 で `auth_status` を追加済みのため型エラーが出る場合は修正）

- **注意**: `App.vue` は `accountsList: ref<AccountConfig[]>` を line 156 で保持しており，`refreshAccountStatus()` で取得する．これらの実名を上記コードで使うこと（`accounts` という名前は `AccountsModal.vue` のローカル変数であり `App.vue` では `accountsList`）

- **検証**: `cd frontend && npm run typecheck && npm run build` → エラーなし  
  `?oauth_success=1` を URL に付けてブラウザでアクセスし，緑バナーが表示されることを目視確認
- **完了条件**: oauth_success バナーと reauth_required バナーが表示・消去できる
- **commit**: `feat(App.vue): OAuth 成功バナーと reauth_required 再接続バナーを追加`

---

### Task 16: テスト — `tests/test_oauth_gmail_service.py` 新設 [P]

- **対象**: `tests/test_oauth_gmail_service.py`（create）
- **手順**: 以下のテストケースを実装（実際の Google サーバへの通信は行わない）

```python
from unittest.mock import MagicMock, patch
import time
from app.services.oauth_gmail import OAuthGmailService

def _svc():
    return OAuthGmailService("client_id", "client_secret", "http://localhost:8000/cb")

def test_generate_auth_url_returns_url_and_state():
    svc = _svc()
    with patch.object(svc, "_make_flow") as mock_flow_cls:
        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth?...", "state123")
        mock_flow_cls.return_value = mock_flow
        url, state = svc.generate_auth_url("My Gmail", "me@gmail.com")
    assert url.startswith("https://")
    assert state == "state123"
    assert "state123" in svc._pending_states

def test_pop_state_valid():
    svc = _svc()
    svc._pending_states["s1"] = {"label": "L", "address": "a@b.com", "ts": time.monotonic()}
    data = svc.pop_state("s1")
    assert data is not None
    assert "s1" not in svc._pending_states

def test_pop_state_expired():
    svc = _svc()
    svc._pending_states["s2"] = {"label": "L", "address": "a@b.com", "ts": time.monotonic() - 700}
    assert svc.pop_state("s2") is None

def test_pop_state_unknown():
    svc = _svc()
    assert svc.pop_state("nonexistent") is None

def test_exchange_code_returns_token_dict():
    svc = _svc()
    with patch.object(svc, "_make_flow") as mock_flow_cls:
        mock_flow = MagicMock()
        mock_creds = MagicMock()
        mock_creds.refresh_token = "rt123"
        mock_creds.token = "at456"
        mock_creds.expiry = None
        mock_creds.scopes = {"https://www.googleapis.com/auth/gmail.readonly"}
        mock_flow.credentials = mock_creds
        mock_flow_cls.return_value = mock_flow
        result = svc.exchange_code("code_abc")
    assert result["refresh_token"] == "rt123"
    assert result["access_token"] == "at456"
```

- **検証**: `pytest tests/test_oauth_gmail_service.py -v` → 全テスト PASSED
- **完了条件**: 5 テストケース全通過
- **commit**: `test(oauth): OAuthGmailService の単体テストを追加`

---

### Task 17: テスト — `tests/test_gmail_api_source.py` 新設 [P]

- **対象**: `tests/test_gmail_api_source.py`（create）
- **手順**: 以下のテストケースを実装

```python
from unittest.mock import MagicMock, patch
from app.adapters.sources.gmail_api import GmailApiSource

def _make_source(account_id="acc1"):
    mock_repo = MagicMock()
    return GmailApiSource(
        refresh_token="rt",
        client_id="cid",
        client_secret="cs",
        account_id=account_id,
        account_repo=mock_repo,
    ), mock_repo

def test_close_is_noop():
    src, _ = _make_source()
    src.close()  # 例外なし

def test_list_recent_maps_to_email_messages():
    src, _ = _make_source()
    mock_service = MagicMock()
    # messages.list
    mock_service.users().messages().list().execute.return_value = {
        "messages": [{"id": "msg1"}]
    }
    # messages.get
    mock_service.users().messages().get().execute.return_value = {
        "id": "msg1",
        "snippet": "テストスニペット",
        "labelIds": ["INBOX", "UNREAD"],
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": "テスト件名"},
                {"name": "From", "value": "sender@example.com"},
                {"name": "To", "value": "me@gmail.com"},
                {"name": "Date", "value": "Fri, 13 Jun 2026 12:00:00 +0000"},
            ],
            "body": {"data": "dGVzdA=="},  # "test" の base64
        },
    }
    with patch.object(src, "_build_service", return_value=mock_service):
        emails = src.list_recent(limit=1)
    assert len(emails) == 1
    assert emails[0].subject == "テスト件名"
    assert emails[0].is_unread is True
    assert emails[0].provider == "gmail"

def test_list_recent_refresh_error_sets_reauth_required():
    import google.auth.exceptions
    src, mock_repo = _make_source()
    with patch.object(src, "_build_service", side_effect=google.auth.exceptions.RefreshError("expired")):
        try:
            src.list_recent()
        except google.auth.exceptions.RefreshError:
            pass
    mock_repo.set_auth_status.assert_called_once_with("acc1", "reauth_required")
```

- **検証**: `pytest tests/test_gmail_api_source.py -v` → 全テスト PASSED
- **完了条件**: 3 テストケース全通過
- **commit**: `test(adapters): GmailApiSource の単体テストを追加`

---

### Task 18: テスト — `tests/test_routes_oauth.py` 新設

- **対象**: `tests/test_routes_oauth.py`（create）
- **依存**: Task 9（routes_oauth），Task 6（AccountRepository），Task 7（OAuthGmailService）
- **手順**: 以下のテストケースを実装（TestClient 使用）

```python
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from app.main import app
from app.api.deps import get_oauth_service, get_account_repo, get_settings

# lifespan を経由した app.state 直接代入は TestClient の with ブロックで上書きされるため，
# FastAPI の dependency_overrides を使ってモックを注入する．


@pytest.fixture(autouse=True)
def cleanup_overrides():
    yield
    app.dependency_overrides.clear()


def _setup_mocks(client_id: str = "cid"):
    mock_oauth = MagicMock()
    mock_repo = MagicMock()
    mock_settings = MagicMock()
    mock_settings.gmail_oauth_client_id = client_id
    mock_settings.frontend_url = "http://localhost:5173"
    app.dependency_overrides[get_oauth_service] = lambda: mock_oauth
    app.dependency_overrides[get_account_repo] = lambda: mock_repo
    app.dependency_overrides[get_settings] = lambda: mock_settings
    return mock_oauth, mock_repo, mock_settings


def test_start_returns_auth_url():
    mock_oauth, _, _ = _setup_mocks()
    mock_oauth.generate_auth_url.return_value = ("https://accounts.google.com/...", "state_abc")
    with TestClient(app) as client:
        resp = client.get("/auth/gmail/start?label=MyGmail&address=me@gmail.com")
    assert resp.status_code == 200
    data = resp.json()
    assert "auth_url" in data
    assert data["state"] == "state_abc"


def test_start_returns_400_when_client_id_missing():
    _setup_mocks(client_id="")
    with TestClient(app) as client:
        resp = client.get("/auth/gmail/start?label=L&address=a@b.com")
    assert resp.status_code == 400


def test_callback_creates_account_and_redirects():
    mock_oauth, mock_repo, _ = _setup_mocks()
    mock_oauth.pop_state.return_value = {"label": "MyGmail", "address": "me@gmail.com"}
    mock_oauth.exchange_code.return_value = {
        "refresh_token": "rt", "access_token": "at",
        "token_expiry": None, "scopes": "https://www.googleapis.com/auth/gmail.readonly",
    }
    mock_oauth.build_credentials.return_value = MagicMock()
    with TestClient(app, follow_redirects=False) as client:
        resp = client.get("/auth/gmail/callback?code=code123&state=state_abc")
    assert resp.status_code == 302
    assert "oauth_success=1" in resp.headers["location"]
    mock_repo.create_oauth.assert_called_once()


def test_callback_returns_400_for_invalid_state():
    mock_oauth, _, _ = _setup_mocks()
    mock_oauth.pop_state.return_value = None
    with TestClient(app) as client:
        resp = client.get("/auth/gmail/callback?code=code&state=invalid")
    assert resp.status_code == 400
```

- **検証**: `pytest tests/test_routes_oauth.py -v` → 全テスト PASSED
- **完了条件**: 4 テストケース全通過
- **commit**: `test(routes): Gmail OAuth エンドポイントの統合テストを追加`

---

## E2E 検証（全 Phase 1 タスク完了後）

1. **DB マイグレーション確認**:
   ```bash
   PYTHONPATH=. alembic upgrade head
   sqlite3 data/ReplyGuard.db ".schema account_configs"
   # → auth_type, refresh_token, auth_status 等の列が存在すること
   ```

2. **バックエンド起動**:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

3. **OAuth 設定の確認**:
   ```bash
   curl http://127.0.0.1:8000/auth/gmail/start?label=test\&address=test@gmail.com
   # → {"auth_url": "https://accounts.google.com/...", "state": "<uuid>"}
   ```
   （`GMAIL_OAUTH_CLIENT_ID` が設定されていなければ 400）

4. **フロントエンド起動**:
   ```bash
   cd frontend && npm run dev
   ```

5. **アカウント追加 E2E**:
   - ブラウザで `http://localhost:5173` を開く
   - アカウントモーダルを開く → Gmail タブに「Google アカウントで接続」ボタンが表示される
   - メールアドレスと表示名を入力 → 「Google アカウントで接続」をクリック
   - ブラウザが `accounts.google.com` の Google ログイン画面に遷移する
   - Google アカウントでログイン・権限許可
   - `http://localhost:5173/?oauth_success=1` にリダイレクトされ，「接続が完了しました」バナーが表示される
   - `GET /accounts` の結果に新しいアカウントが `auth_type: "oauth"`, `auth_status: "ok"` で表示される

6. **メール取得確認**:
   ```bash
   curl -X POST http://127.0.0.1:8000/ingest 2>/dev/null || \
   # API トリガがない場合はスケジューラ起動後 GET /messages で確認
   curl http://127.0.0.1:8000/messages
   # → OAuth アカウントからメールが取得されていること
   ```

7. **既存 IMAP アカウントとの共存確認**:
   - `secrets/gmail.env` に `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` が設定されている環境でバックエンドを起動
   - DB に `auth_type=imap` のアカウントが自動登録されていること（起動ログ確認）
   - メール取得が IMAP・OAuth 両方のアカウントから行われること（ログで確認）

8. **テスト全通過**:
   ```bash
   pytest -q
   # → 全テスト PASSED（IMAP 既存テストが壊れていないこと）
   ```

---

## リスクとロールバック

| リスク | 対策 / ロールバック |
|---|---|
| Google Cloud の「Web アプリ」タイプ Client ID 未作成 | 実装前に前提セットアップを完了させる．Client ID 未設定時 API が 400 を返す設計になっているので IMAP は影響なし |
| Testing モードで refresh_token が 7 日で失効 | `auth_status='reauth_required'` + バナー UX で対処．PoC として許容 |
| SQLite の `batch_alter_table` で既存データが消える | マイグレーション前に `cp data/ReplyGuard.db data/ReplyGuard.db.bak` でバックアップを取る．壊れたら `cp data/ReplyGuard.db.bak data/ReplyGuard.db` で戻す |
| `_pending_states` がサーバ再起動で消える | ユーザーはもう一度「Google で接続」を押せば再取得できるため PoC として許容 |
| `GmailApiSource` の Gmail API レート制限（1日 250 quota unit） | 定期取得は 5 分毎・10 件取得のため通常運用では超えない |

---

## Phase 2（OAuth 確認後の IMAP 削除）— 別タスクとして実施

Phase 1 完了 → ユーザーが実環境で OAuth 動作確認 → **ユーザーが Phase 2 実施を明示承認** → Phase 2 開始．

Phase 2 スコープ（Phase 1 承認時点では実装しない）:
- `app/fetch_gmail_imap.py` / `app/adapters/sources/gmail_imap.py` 削除
- `app/config.py` から `gmail_address` / `gmail_app_password` 削除
- `account_configs.auth_type` 列の削除または 'oauth' 固定化（全アカウントを OAuth 前提に）
- `app/services/ingestion.py` の IMAP 分岐を削除
- `docker/docker-compose.yml` の `gmail-poc-oauth` profile / `127.0.0.1:8080:8080` を整理
- `README.md` から IMAP 関連手順を削除
- IMAP 関連テストを削除
- `secrets/gmail.env.example` から `GMAIL_APP_PASSWORD` を削除

---

## 実装メモ（実装中に追記）

> 計画との乖離・発見事項を実装者が記録する．乖iadau は黙って吸収せず必ずここに書く．
