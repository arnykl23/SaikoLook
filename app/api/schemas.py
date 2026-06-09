"""API 層の入出力スキーマ.

ドメインモデル（app/models.py）と分けて, リクエスト境界の検証専用スキーマを
置く. レスポンスは原則ドメインモデル（EmailMessage / MessageRecord）を
response_model に使い, 二重定義しない. ここに置くのは入力用と補助の出力用のみ.
"""

from pydantic import BaseModel, Field

from app.models import MessageState


class StateUpdateRequest(BaseModel):
    """POST /messages/{id}/state の本文（楽観ロック付き状態遷移）."""

    state: MessageState
    version: int = Field(ge=0)


class LoginRequest(BaseModel):
    """POST /auth/login の本文."""

    username: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=1024)


class TokenResponse(BaseModel):
    """JWT 発行レスポンス."""

    access_token: str
    token_type: str = "bearer"


class IngestResult(BaseModel):
    """POST /ingest のレスポンス（run_once の件数）."""

    fetched: int
    inserted: int
    notified: int
