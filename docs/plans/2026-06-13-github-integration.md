# Plan: GitHub をメッセージソースとして追加（OAuth App・Notifications API・読み取り専用）

- 作成日: 2026-06-13
- 深度: Large
- 状態: approved (2026-06-13 ユーザー承認 — 「オッケー、それで行こう」「オッケー、それで行こう、」)
- NEEDS CLARIFICATION 残数: 0

## ★ Goal / Why

GitHub を ReplyGuard の新プロバイダとして追加し，PR/Issue のレビュー依頼・メンション・コメント・アサインなどの「対応すべき通知」をダッシュボードへ集約する．Gmail / Slack と同じく，取得 → 正規化（`EmailMessage`）→ LLM 分析 → 状態管理 → 表示の既存パイプラインに載せる．認証は将来のマルチユーザー SaaS 化（AWS デプロイ・複数人が各自の GitHub を接続）を見据え，**OAuth App（classic・web flow）** で実装する．

## ★ Non-goals（やらないこと）

- **期限機能**（Milestone `due_on` / GitHub Projects のカスタム日付フィールド）— ユーザー指示により当面実装しない．`EmailMessage`/`AnalysisResult` の `deadline` は GitHub では常に `None` のまま
- **GitHub への書込み**（通知の既読化 mark-as-read 等）— 一切呼ばない．後述の通り `notifications` scope には書込み権限が技術的に含まれるが，「呼ばない運用規律」で読み取り専用を担保する
- **削除/既読追随同期**（`RemovalDetectingSource` の実装）— Gmail のような既読同期は GitHub では当面なし
- **GitHub App / installation token** — Notifications API が GitHub App / fine-grained token で非対応のため不採用（classic PAT・OAuth App の token のみ対応）
- **`subscribed` / `ci_activity` / `state_change` / `security_alert` / `approval_requested` の取り込み** — ノイズが多いため除外．取り込むのは `review_requested` / `mention` / `comment` / `assign` / `author` / `team_mention` の6種のみ
- **条件付きリクエスト（If-Modified-Since / ETag）の永続化** — レート最適化は将来課題．PoC では `all=false`（未読のみ）＋`ingest_limit` 上限でレートを吸収する（DB マイグレーション不要を維持するため）
- **OAuth フローの汎用化（provider パラメータ化）** — Gmail ルートを複製する（理由は Complexity Tracking 参照）

## 現状分析（Phase 1 の蒸留結果）

### 関連ファイル（複製元・修正対象）

| ファイル | 役割 | 本計画での扱い |
|---|---|---|
| `app/services/oauth_gmail.py` | Gmail OAuth フローサービス（`generate_auth_url`/`pop_state`/`exchange_code`/`build_credentials`） | **複製元**（GitHub 版を新規作成） |
| `app/api/routes_oauth.py` | `/auth/gmail/{start,callback,reauth}` の3エンドポイント | **複製元**（GitHub 版を新規作成） |
| `app/adapters/sources/slack_api.py` | httpx 直叩きの MessageSource 実装（`verify_credentials`/`_request`/`list_recent`/`close`） | **複製元**（GitHub 版の雛形） |
| `app/adapters/sources/gmail_api.py` | OAuth token 失効時に `set_auth_status("reauth_required")` を呼ぶ前例 | 失効検知パターンの参照元 |
| `app/services/ingestion.py` | `_build_sources()` の provider 分岐（gmail/slack） | 修正（github 分岐追加） |
| `app/api/deps.py` | DI（`get_oauth_service` 等） | 修正（`get_github_oauth_service` 追加） |
| `app/main.py` | lifespan で `app.state.oauth_service` 構築・`include_router` | 修正（github サービス構築・ルータ登録） |
| `app/config.py` | Settings（`gmail_oauth_*` フィールド・行29-32） | 修正（`github_oauth_*` 追加） |
| `app/models.py` | `_SUPPORTED_PROVIDERS = {"gmail", "slack"}`（行78） | 修正（`"github"` 追加） |
| `app/repositories/account_repository.py` | `create_oauth(provider, label, address, refresh_token, ...)`（行87-115）/ `get_by_id`/`set_auth_status` | 流用（変更なし） |
| `app/repositories/orm.py` | `AccountConfigORM`（`auth_type`/`refresh_token`/`access_token`/`token_expiry`/`scopes`/`auth_status` 列） | 流用（マイグレーション不要） |
| `frontend/src/api.ts` | `startGmailOAuth`/`reauthGmailAccount`（行152付近） | 修正（GitHub 版関数追加） |
| `frontend/src/components/AccountsModal.vue` | プロバイダ選択 UI（行188-208）・credential ラベル computed（行74-86）・OAuth ボタン（行256-265） | 修正（GitHub ボタン・分岐追加） |
| `frontend/src/App.vue` | `oauth_success` 検出（行198-199）・reauth ハンドラ（行166-167） | 修正（GitHub reauth 分岐追加） |
| `tests/test_slack_source.py` | httpx mock パターンのテスト前例 | テストの雛形 |

### 既存の規約・前例

- **共通スキーマ `EmailMessage`（`app/models.py:18-29`）は破壊変更禁止**（任意フィールドの追加のみ可）．GitHub 通知もこのスキーマへ正規化する．種別は `subject` にプレフィックス埋め込みで表現し，スキーマは変更しない
- **MessageSource Protocol（`app/ports/source.py:18-27`）**: `list_recent(limit) -> list[EmailMessage]` と `close() -> None` の2メソッド．`RemovalDetectingSource` は実装しない
- **`verify_credentials` 静的メソッド**は Protocol 外だが Slack が実装する慣例（`routes_accounts.py` が呼ぶ）．GitHub は OAuth フロー経由のため，接続検証は OAuth callback 内の `GET /user` で兼ねる
- **OAuth token 保存**は `AccountRepository.create_oauth()` を呼ぶ（`routes_oauth.py:73-81` の前例）
- **`auth_status`（ok / reauth_required）機構**はプロバイダ非依存．token 失効時に `set_auth_status(account_id, "reauth_required")` を呼べば既存の再認可 UI が反応する
- **秘密情報は `secrets/*.env`**（gitignore 済み）から Settings が読む．`env_file=("secrets/gmail.env", "secrets/app.env")`

### 制約（GitHub API の技術的事実・調査で確定）

- **Notifications API（`GET /notifications`）は classic PAT または OAuth App の user-to-server token でのみ動作**．GitHub App / fine-grained token は非対応（出典: docs.github.com/en/rest/activity/notifications "only support authentication using a personal access token (classic)"）
- **OAuth App の `notifications` scope で `GET /notifications` を叩ける**．`repo` scope は不要（private リポジトリの通知も `notifications` だけで取得可）
- **`notifications` scope には書込み（既読化・購読変更・watch）が含まれる**．read だけに絞る scope は存在しない → 運用規律で担保（Non-goals 参照）
- **OAuth App の access token（`gho_` プレフィックス）は無期限・refresh token なし**（GitHub App 専用機能の expiration オプトインは OAuth App には無い）．1年間未使用で自動失効
- **OAuth web flow**: `GET https://github.com/login/oauth/authorize` → `code` → `POST https://github.com/login/oauth/access_token`．PKCE は不要（client_secret 方式）．`state` で CSRF 対策（必須）
- **通知本体には送信者も本文も含まれない**: 各通知に対し `subject.url`（PR/Issue 本体）と `subject.latest_comment_url`（最新コメント）の追加 GET が必要
- **レート制限**: 認証済み 5000 req/h．`all=false`＋`ingest_limit=10` なら1サイクル最大 `1 + 10×2 = 21` req，5分間隔で約 252 req/h（余裕内）

## 設計（合意済みの決定）

### 決定 1: 認証方式 = OAuth App（classic・web flow）
- 採用: OAuth App，`notifications` scope のみ，access token を DB 保存（`refresh_token` は空文字）
- 棄却: classic PAT（他ユーザーに PAT 発行を強いるのは SaaS 化で非現実的）／ GitHub App（Notifications API 非対応）
- 根拠: 2026-06-13 ユーザー「awsとかででもとして複数人に繋いでもらう予定」→ マルチユーザー OAuth が必須．技術調査で GitHub App が Notifications 非対応と確定

### 決定 2: 取得 API = Notifications API + 本文追加取得
- 採用: `GET /notifications?all=false` → `reason` で6種フィルタ → 各件 `subject.url` と `subject.latest_comment_url` を追加 GET して送信者・本文を補完
- 棄却: Search API（`review-requested:@me`）単独（既読/未読管理ができず，他 reason を一網打尽にできない）
- 根拠: 2026-06-13 ユーザー「本文も取得（推奨）」を選択．LLM 分析の精度を優先

### 決定 3: 種別表現 = subject プレフィックス埋め込み（スキーマ非変更）
- 採用: `subject = f"[{ラベル}] {PR/Issue タイトル}"`（例 `[review依頼] Fix login bug`）．`EmailMessage` は変更しない
- 棄却: `EmailMessage` に `message_type` フィールド追加（後段の全層・API レスポンス形・フロントに波及する．YAGNI）
- 根拠: 2026-06-13 ユーザー合意（種別は当面 subject 埋め込み）．将来 `message_type` 追加を候補として記録

### 決定 4: OAuth サービス／ルートは httpx 直叩きで複製（汎用化しない）
- 採用: `oauth_github.py`・`routes_github_oauth.py` を Gmail 版から複製．OAuth サービスは httpx で実装（新規依存なし）
- 棄却: requests_oauthlib 導入（依存追加不要）／ provider パラメータ化の汎用ルート（Gmail/GitHub/Outlook が揃う前の早すぎる共通化）
- 根拠: 2026-06-13 ユーザー合意．Complexity Tracking 参照

### reason → 種別ラベル対応表

| reason | subject プレフィックス |
|---|---|
| `review_requested` | `[review依頼]` |
| `mention` | `[メンション]` |
| `comment` | `[コメント]` |
| `assign` | `[アサイン]` |
| `author` | `[自分のPR/Issue]` |
| `team_mention` | `[チームメンション]` |
| 上記以外 | 取り込まない（スキップ） |

### データ構造・インタフェース

**`app/config.py`（Settings に追加）**
```python
# === GitHub（取得・正規化層 / OAuth App）===
github_oauth_client_id:     str = ""
github_oauth_client_secret: str = ""
github_oauth_redirect_uri:  str = "http://127.0.0.1:8000/auth/github/callback"
```

**`app/services/oauth_github.py`（新規・httpx 実装）**
```python
class OAuthGithubService:
    _STATE_TTL = 600  # 秒
    _AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
    _TOKEN_URL = "https://github.com/login/oauth/access_token"
    _USER_URL = "https://api.github.com/user"
    SCOPES = "notifications"  # space 区切り。read だけに絞る scope は存在しない

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str) -> None: ...
    # state を secrets.token_urlsafe(32) で生成、{label, ts} を in-memory 保持（PKCE 不要なので flow は保持しない）
    def generate_auth_url(self, label: str) -> tuple[str, str]: ...  # (auth_url, state)
    def pop_state(self, state: str) -> dict | None: ...              # TTL 検証して取り出し
    def exchange_code(self, code: str) -> dict: ...                  # {access_token, scopes} を返す（POST、Accept: application/json）
    def fetch_user_login(self, access_token: str) -> str: ...        # GET /user の login を address に使う
```

**`app/adapters/sources/github_api.py`（新規・httpx 実装）**
```python
_API_BASE = "https://api.github.com"
_INTERESTED_REASONS = {"review_requested", "mention", "comment", "assign", "author", "team_mention"}
_REASON_LABEL = { ... }  # 上の対応表

class GithubApiSource:
    def __init__(self, access_token: str, address: str, account_id: str,
                 account_repo, *, max_body_chars: int = 4000, timeout: int = 10) -> None: ...
    @property
    def address(self) -> str: ...
    def list_recent(self, limit: int = 10) -> list[EmailMessage]: ...
    # 1. GET /notifications?all=false&per_page=limit （Authorization: Bearer）
    #    - 401 → account_repo.set_auth_status(account_id, "reauth_required") して raise
    # 2. reason ∉ _INTERESTED_REASONS の通知はスキップ
    # 3. 各通知: subject.url を GET（本体）→ user.login（送信者）・html_url
    #            subject.latest_comment_url を GET（あれば）→ body（本文）
    #            本体/コメント取得失敗は握って snippet=title・body_text=None で継続
    # 4. EmailMessage へ正規化（下記マッピング）
    def close(self) -> None: ...  # no-op
    @staticmethod
    def verify_credentials(access_token: str, *, timeout: int = 10) -> None: ...  # GET /user、失敗で RuntimeError
```

**GitHub 通知 → `EmailMessage` マッピング**

| EmailMessage | 値 |
|---|---|
| `id` | `notification["id"]`（thread id） |
| `provider` | `"github"`（固定） |
| `subject` | `f"[{_REASON_LABEL[reason]}] {notification['subject']['title']}"` |
| `sender` | 本体 `user.login`（取得失敗時は `notification['repository']['full_name']`） |
| `to` | `[notification["repository"]["full_name"]]` |
| `received_at` | `notification["updated_at"]`（ISO8601 → datetime） |
| `snippet` | 本文（無ければ title）先頭120文字・空白畳み |
| `is_unread` | `notification["unread"]` |
| `body_text` | コメント/本体 body の先頭 `max_body_chars`（無ければ None） |

`MessageRecord.make_id("github", notification_id)` → `"github:<id>"` で自然に機能する．

## Complexity Tracking（複雑性の正当化台帳）

| 違反 | 正当化 |
|---|---|
| OAuth サービス/ルートを汎用化せず Gmail から複製（重複コード） | Gmail は google-auth-oauthlib（PKCE）・GitHub は httpx（client_secret）と実装が根本的に異なり，共通化すると分岐だらけの抽象になる．Outlook を含む3プロバイダが揃った段階でリファクタする方が安全（早すぎる共通化の回避）．2026-06-13 ユーザー合意済み |

その他の新規抽象レイヤ・ラッパーの追加: なし．DB マイグレーション: なし（既存 OAuth カラム転用）．

## ★ タスク分解

> 各タスクは文脈ゼロの実装者へ単体で渡せる粒度．[P] = 並列可能（ファイル所有が重ならないことを確認済み）．依存関係は各タスク冒頭に明記．

### Task 1: 設定・プロバイダ登録の土台 [P]
- 依存: なし
- 対象: `app/config.py`（modify），`app/models.py`（modify），`secrets/github.env.example`（create）
- 手順:
  1. `app/config.py` の `frontend_url`（行32）の直後に「GitHub」セクションを追加（上記データ構造の3フィールド）
  2. `app/models.py:78` の `_SUPPORTED_PROVIDERS = {"gmail", "slack"}` を `{"gmail", "slack", "github"}` に変更
  3. `secrets/github.env.example` を新規作成（中身: `GITHUB_OAUTH_CLIENT_ID=`／`GITHUB_OAUTH_CLIENT_SECRET=` の2行＋コメント．**実値は書かない**）
  4. `app/config.py` の `env_file` タプルに `"secrets/github.env"` を追加（`("secrets/gmail.env", "secrets/github.env", "secrets/app.env")` の順．app.env が最後で上書き優先を維持）
- 検証: `python -c "from app.config import Settings; s=Settings(); print(s.github_oauth_client_id, s.github_oauth_redirect_uri)"` → 期待: 空文字と `http://127.0.0.1:8000/auth/github/callback` が出力．`pytest -q` → 期待: 全 pass（実行前の baseline 件数から減らない＝回帰なし）
- 完了条件: Settings が `github_oauth_*` 3フィールドを持ち，`AccountConfigCreate(provider="github", ...)` がバリデーションエラーにならない．`git status` で `secrets/github.env`（実値ファイル）が追跡対象に現れない（`.gitignore` の `secrets/*.env` でカバー済みを確認）
- commit: `feat: GitHub プロバイダの設定フィールドと secrets 雛形を追加`

### Task 2: OAuthGithubService（OAuth フローのコア） [P]
- 依存: Task 1（`github_oauth_*` 設定）
- 対象: `app/services/oauth_github.py`（create），`tests/test_oauth_github.py`（create）
- 手順:
  1. `app/services/oauth_github.py` を上記シグネチャで作成．`generate_auth_url` は `secrets.token_urlsafe(32)` で state 生成し `{"label": label, "ts": time.monotonic()}` を `_pending_states` に保持．認可 URL は `_AUTHORIZE_URL?client_id=&redirect_uri=&scope=notifications&state=`
  2. `exchange_code` は `httpx.post(_TOKEN_URL, data={client_id, client_secret, code, redirect_uri}, headers={"Accept": "application/json"})` → JSON の `access_token`/`scope` を返す．`access_token` 欠落時は `RuntimeError`
  3. `fetch_user_login` は `httpx.get(_USER_URL, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})` → `login`
  4. `pop_state` は Gmail 版（`oauth_gmail.py:48-55`）と同じ TTL ロジック
  5. テスト: `httpx.post`/`httpx.get` を `unittest.mock.patch` でモック．(a) `generate_auth_url` が URL に `scope=notifications`/`state=` を含む，(b) `pop_state` が一度きり取り出し・期限切れ None，(c) `exchange_code` が access_token を返す・欠落で RuntimeError，(d) `fetch_user_login` が login を返す
- 検証: `pytest tests/test_oauth_github.py -q` → 期待: 全テスト pass（実 GitHub に接続しない）
- 完了条件: 4メソッドが揃い，テストが緑
- commit: `feat: GitHub OAuth フローサービス（OAuthGithubService）を追加`

### Task 3: OAuth エンドポイントと DI/ルータ配線
- 依存: Task 2（`OAuthGithubService`）
- 対象: `app/api/routes_github_oauth.py`（create），`app/api/deps.py`（modify），`app/main.py`（modify）
- 手順:
  1. `routes_github_oauth.py` を `routes_oauth.py` から複製して作成．prefix `/auth/github`．差分:
     - `start_oauth`: `address` クエリは取らない（GitHub は認可後に `GET /user` で判明するため）．`label` のみ受ける．`github_oauth_client_id` 未設定なら 400
     - `oauth_callback`: `pop_state` → `exchange_code(code)` → `fetch_user_login(access_token)` で address 確定 → `repo.create_oauth(provider="github", label=..., address=login, refresh_token="", access_token=token, token_expiry=None, scopes=scopes)` → `RedirectResponse(f"{frontend_url}/?oauth_success=1")`．交換失敗は `?oauth_error=exchange_failed`
     - `reauth_account`: Gmail 版と同形（`label` で `generate_auth_url`）
  2. `deps.py` に `get_github_oauth_service(request) -> OAuthGithubService: return request.app.state.github_oauth_service` を追加（import も）
  3. `app/main.py` の lifespan で `app.state.github_oauth_service = OAuthGithubService(settings.github_oauth_client_id, settings.github_oauth_client_secret, settings.github_oauth_redirect_uri)` を構築し，`app.include_router(routes_github_oauth.router)` を追加（Gmail の `oauth_service`/`include_router` 箇所に倣う）
- 検証: `pytest -q` で回帰なし．`python -c "from app.main import app; from fastapi.testclient import TestClient;\nwith TestClient(app) as c:\n    r=c.get('/auth/github/start?label=test'); print(r.status_code)"` → 期待: `github_oauth_client_id` 未設定環境では `400`（client_id 設定時は `auth_url` を含む 200）．**`with TestClient(app) as c:` で lifespan を起動すること**（`app.state.github_oauth_service` は lifespan 内で構築されるため，`with` 無しだと `AttributeError`=500 になる）
- 完了条件: 3エンドポイントが登録され，未設定時に 400 を返す
- commit: `feat: GitHub OAuth エンドポイント（/auth/github）を追加し配線`

### Task 4: GithubApiSource（取得・正規化） [P]
- 依存: Task 1（`provider="github"`）
- 対象: `app/adapters/sources/github_api.py`（create），`tests/test_github_source.py`（create）
- 手順:
  1. `github_api.py` を上記シグネチャで作成．`slack_api.py` の `_request`/`verify_credentials`/`close` パターンを踏襲しつつ，ヘッダは `Authorization: Bearer <token>`・`Accept: application/vnd.github+json`
  2. `list_recent`: `GET /notifications?all=false&per_page={limit}`．レスポンス `401` は `account_repo.set_auth_status(account_id, "reauth_required")` を呼んで `RuntimeError` を raise
  3. `reason ∉ _INTERESTED_REASONS` をスキップ．残った通知ごとに `subject.url`（本体）と `subject.latest_comment_url`（あれば）を GET．本体/コメント取得失敗は握って継続（snippet=title・body_text=None）
  4. 上記マッピング表どおり `EmailMessage` を構築．`received_at` は `datetime.fromisoformat(updated_at.replace("Z", "+00:00"))` でパース（Python 3.10 は `Z` 直接非対応のため置換が必須）．**結果が tz-aware（UTC）になることをテストで確認**（他プロバイダの `received_at` は tz-aware で揃っており，naive になると比較で不整合を生む）
  5. `verify_credentials` は `GET /user` 成功で OK・失敗で `RuntimeError`
  6. テスト（`test_slack_source.py` 構造踏襲・`httpx.get` を patch）: (a) MessageSource Protocol 適合，(b) 6種 reason の正規化（subject プレフィックス確認），(c) 対象外 reason 除外，(d) 本文・送信者の追加取得，(e) snippet/body_text 切り詰め，(f) 401 で `set_auth_status` 呼び出し＋raise，(g) 本体取得失敗時のフォールバック，(h) `verify_credentials` 成功/失敗，(i) `close` no-op
- 検証: `pytest tests/test_github_source.py -q` → 期待: 全テスト pass（実 GitHub に接続しない）
- 完了条件: `isinstance` ベースで MessageSource として振る舞い，6 reason を正規化できる
- commit: `feat: GitHub Notifications 取得アダプタ（GithubApiSource）を追加`

### Task 5: IngestionService への結線
- 依存: Task 4（`GithubApiSource`），Task 1（provider 登録）
- 対象: `app/services/ingestion.py`（modify），`app/repositories/account_repository.py`（modify），`tests/test_ingestion.py`（modify）
- 手順:
  1. `ingestion.py` 冒頭の import に `from app.adapters.sources.github_api import GithubApiSource` を追加
  2. `_build_sources()` の `elif acc["provider"] == "slack":` ブロック（行84-92）の直後に github 分岐を追加:
     ```python
     elif acc["provider"] == "github":
         source_pairs.append((
             GithubApiSource(
                 access_token=acc["access_token"],
                 address=addr,
                 account_id=acc["id"],
                 account_repo=self._account_repo,
                 max_body_chars=self._settings.llm_max_body_chars,
             ),
             acc,
         ))
     ```
  3. `list_for_ingest()`（`account_repository.py:46-62`）は現状 `access_token` を返さない（id/provider/address/credential/auth_type/refresh_token/auth_status のみ）．**`"access_token": r.access_token` キーの追加が必須**（Task 5 が `account_repository.py` を所有・修正する）．このキーが無いと `_build_sources()` の github 分岐が `KeyError: 'access_token'` で落ち，**Gmail/Slack を含む全取り込みループを巻き込む回帰になる**ため，GitHub 分岐の追加と同一タスクで必ず行う
  4. テスト: `tests/test_ingestion.py` に「provider=github のアカウントから `GithubApiSource` が構築される」ケースを追加（`_build_sources` の戻り値型を検証）
- 検証: `pytest tests/test_ingestion.py -q` → 期待: 既存テスト＋新規が緑．`pytest -q` で全体回帰なし（Slack/Gmail の取り込みが落ちないこと）
- 完了条件: (a) `list_for_ingest()` の戻り dict に `access_token` キーが含まれる，(b) github プロバイダのアカウントが取り込みループに乗る，(c) 既存 Slack/Gmail 取り込みが回帰しない（`KeyError` を出さない）
- commit: `feat: 取り込みパイプラインに GitHub ソースを結線`

### Task 6: フロントエンド（GitHub OAuth 接続 UI） [P]
- 依存: Task 3（`/auth/github` エンドポイント．ただしコード上はフロント単独で書ける）
- 対象: `frontend/src/api.ts`（modify），`frontend/src/components/AccountsModal.vue`（modify），`frontend/src/App.vue`（modify）
- 手順:
  1. `api.ts`: `startGmailOAuth`（行152付近）に倣い `startGithubOAuth(label: string)` を追加（`GET /auth/github/start?label=` → `auth_url`）．`reauthGithubAccount(accountId)` も追加（`POST /auth/github/{id}/reauth`）
  2. `AccountsModal.vue`: provider 選択行（行188-208）に GitHub ボタンを追加（Outlook の disabled を参考に，github はアクティブ）．`selectedProvider === 'github'` のとき「GitHub で接続」ボタン（Gmail の OAuth ボタン行256-265 に倣う）を出し，押下で `startGithubOAuth(label)` → `window.location.href = auth_url`．**GitHub は Gmail 同様 address/credential 入力不要（OAuth ボタンのみ）のため，現状 `!== 'gmail'` で分岐している計4箇所を `'gmail'` と `'github'` の両方を除外する形に変更する**: (a) `onSubmit` の credential 必須チェック（行119 `selectedProvider !== 'gmail' && !form.credential.trim()`），(b) フォームの `@submit.prevent`（行213），(c) address 入力欄の `v-if`（行226），(d) credential 入力欄の `v-if`（行238）．credential ラベル computed（行74-86）にも github ケースを追加（実際には非表示なので最小で可）
  3. `App.vue`: reauth ハンドラ `onReauth(accountId)`（行164-171）を修正．現状は accountId のみで provider を判定できないため，**`accountsList.value.find(a => a.id === accountId)?.provider` で provider を引き，`github` なら `reauthGithubAccount(accountId)`，それ以外は既存の `reauthGmailAccount` を呼ぶ**分岐にする（`AccountConfig` に `provider` フィールドは存在）．`reauthGithubAccount` の import 追加も忘れない．`oauth_success` 処理（行198-199）は provider 非依存なので変更不要
- 検証: `cd frontend && npm run typecheck` → 期待: 型エラーなし．`npm run build` → 期待: ビルド成功
- 完了条件: アカウント追加モーダルに GitHub が現れ，押下で GitHub 認可画面へ遷移する（実接続は E2E で確認）
- commit: `feat: GitHub OAuth 接続 UI をアカウント設定に追加`

### Task 7: インフラ・セットアップ手順 [P]
- 依存: Task 1（`secrets/github.env`）
- 対象: `docker/docker-compose.yml`（modify），`README.md`（modify）
- 手順:
  1. `docker-compose.yml` の `env_file` は**オブジェクト形式**（`- path: ../secrets/gmail.env` / `required: true`）．`api` サービスの `env_file` リストに `- path: ../secrets/github.env` / `required: false` を追加（`secrets/github.env` 未作成でも起動できるよう `required: false`）．同じ env_file ブロックを持つ他サービス（`gmail-poc` 等）があれば同様に追加．frontend サービスは `VITE_API_BASE` 等のみ使い github.env を読まないため対象外
  2. `README.md` に「GitHub 連携（OAuth App）」節を追加: (a) GitHub の Settings → Developer settings → OAuth Apps で新規 App 作成，(b) Authorization callback URL を `http://127.0.0.1:8000/auth/github/callback`（本番は AWS のドメイン）に設定，(c) Client ID / Client secret を `secrets/github.env` に記入，(d) 要求 scope は `notifications` のみ（書込み権限は付けない）
- 検証: `docker compose -f docker/docker-compose.yml config` → 期待: パースエラーなし，`github.env` が env_file に反映．`README.md` に GitHub 節が存在
- 完了条件: docker から github.env が読まれ，セットアップ手順が文書化されている
- commit: `docs: GitHub OAuth App のセットアップ手順と compose 設定を追加`

### 並列実行プラン（ファイル所有マップ）

- **第1波**: Task 1（config/models/secrets）を単独で先行（全体の前提）
- **第2波 [P]**: Task 2（oauth_github.py）∥ Task 4（github_api.py）∥ Task 7（compose/README）— ファイル所有が完全に分離
- **第3波**: Task 3（routes/deps/main — hotspot の deps.py・main.py を単独所有）
- **第4波**: Task 5（ingestion.py ＋ account_repository.py）∥ Task 6（frontend — 別ディレクトリ）
- hotspot 注意: `deps.py`・`main.py` は Task 3 のみが触る（直列）．`account_repository.py` は Task 5 のみが触る（`access_token` キー追加は必須）

## ★ E2E 検証（全タスク完了後）

実 GitHub アカウントと OAuth App が必要（PoC 手動確認）:

1. GitHub で OAuth App を作成し callback URL を設定，Client ID/secret を `secrets/github.env` に記入
2. API 起動（`uvicorn app.main:app --reload --port 8000`）＋フロント起動（`cd frontend && npm run dev`）
3. ダッシュボードのアカウント設定モーダルを開き「GitHub」を選択 →「GitHub で接続」→ GitHub 認可画面で承認 → `?oauth_success=1` で戻りバナー表示
4. アカウント一覧に GitHub アカウント（address = GitHub login）が現れることを確認
5. 自分宛てにレビュー依頼/メンションがある状態で取り込みを実行（`POST /ingest` またはスケジューラ待ち）→ ダッシュボードに `[review依頼] ...` 等のカードが現れ，本文・送信者・受信日時が表示されることを確認
6. token を GitHub 側で revoke → 次回取り込みで該当アカウントが `reauth_required` になり，UI に再認可導線が出ることを確認
7. **読み取り専用の確認**: 取り込み後も GitHub 側で通知が「未読」のまま（既読化されていない）ことを確認

## リスクとロールバック

- **リスク1（scope の書込み混在）**: `notifications` scope は既読化等の書込みを技術的に許す．コードで write API を呼ばない規律が破られると未読が消える副作用．→ 対策: `github_api.py` は GET のみ（POST/PATCH/PUT/DELETE を書かない）．コードレビューで確認
- **リスク2（レート制限）**: 本文追加取得で 1通知=2追加コール．未読が大量だと 5000 req/h に近づく．→ 対策: `all=false`＋`ingest_limit` で上限．将来 If-Modified-Since 永続化で最適化
- **リスク3（token 無期限の保管）**: access token を平文で DB 保存（Gmail OAuth と同じ PoC 方針）．→ 本番は要暗号化（`account_repository.py` 冒頭コメントの既知事項．本計画のスコープ外）
- **リスク4（個人情報）**: PR/Issue 本文・コメントを取得・保存する．`data/*.db` は gitignore 済み・ログに本文を出さない既存規律を踏襲
- **ロールバック**: タスク=コミット単位で revert 可能．プロバイダ追加は加算的（既存 Gmail/Slack に影響しない）．最悪 `_SUPPORTED_PROVIDERS` から `"github"` を外し github 分岐を無効化すれば既存機能は無傷

## 実装メモ（実装中に追記）

> 計画との乖離・発見事項を実装者がここに記録する．乖離は黙って吸収せず必ず書く．

- （未記入）
