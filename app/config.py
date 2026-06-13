"""アプリ設定（単一ソース）.

secrets/gmail.env と secrets/app.env から環境変数を読み, 型付き Settings に
束ねる. 秘密情報はここに「読み込む」だけでハードコードしない. baseline は
全フィールドが既定値で動く（SQLite・スタブ分析・ログ通知・認証無効）ため,
追加アカウント無しで end-to-end 起動できる. 各 upgrade は app.env で任意に有効化.

env のキーはフィールド名の大文字化（例: gmail_address → GMAIL_ADDRESS）.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # 後の file が前を上書き（app.env が gmail.env を上書き）. 欠損ファイルは無視.
        env_file=("secrets/gmail.env", "secrets/github.env", "secrets/app.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # === Gmail（取得・正規化層）===
    gmail_address: str = ""
    gmail_app_password: str = ""
    # OAuth フロー設定（アプリパスワード方式の代替）
    gmail_oauth_client_id:     str = ""
    gmail_oauth_client_secret: str = ""
    gmail_oauth_redirect_uri:  str = "http://127.0.0.1:8000/auth/gmail/callback"
    frontend_url:              str = "http://localhost:5173"

    # === GitHub（取得・正規化層 / OAuth App）===
    # OAuth App（classic）の web flow. notifications scope のみ要求（読み取り専用は運用規律で担保）.
    github_oauth_client_id:     str = ""
    github_oauth_client_secret: str = ""
    github_oauth_redirect_uri:  str = "http://127.0.0.1:8000/auth/github/callback"

    # === DB（永続化層）===
    # 既定はローカル SQLite（追加アカウント不要）. Supabase/Postgres に上げる時は
    # app.env で DATABASE_URL=postgresql+psycopg2://... を設定する.
    database_url: str = "sqlite:///./data/replyguard.db"

    # === 認証（API 層）===
    # デモ簡便のため既定無効. 有効化時は JWT_SECRET を必ず設定する.
    auth_enabled: bool = False
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720
    # 単一ユーザーのデモ用ログイン情報（auth_enabled 時のみ使用）
    auth_username: str = "admin"
    auth_password: str = ""

    # === CORS（API 層）===
    allowed_origins: str = (
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:5173,http://127.0.0.1:5173"
    )

    # === 取得スケジューラ（結線）===
    scheduler_enabled: bool = True
    ingest_on_startup: bool = True
    ingest_interval_seconds: int = 300
    ingest_limit: int = 10

    # === LLM 分析層 ===
    # "stub"（既定・オフライン）| "anthropic" | "openai" | "gemini"
    analyzer: str = "stub"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    # 空ならプロバイダ別の既定モデルを factory が解決する（例 gemini→gemini-2.5-flash-lite）.
    llm_model: str = ""
    llm_timeout_seconds: int = 30
    # 本文をLLMへ渡す際の最大文字数（コスト/漏洩面の上限）
    llm_max_body_chars: int = 4000

    # === リモート削除/アーカイブ追随同期 ===
    sync_remote_changes: bool = True
    auto_archive_importance_threshold: int = 3

    # === 通知層 ===
    # "log"（既定・オフライン）| "email" | "slack"
    notifier: str = "log"
    notify_importance_threshold: int = 4
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    notify_email_from: str = ""
    notify_email_to: str = ""
    slack_webhook_url: str = ""

    @property
    def origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """プロセス内シングルトン. テストでは get_settings.cache_clear() で差し替える."""
    return Settings()
