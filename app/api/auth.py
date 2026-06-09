"""JWT 認証（PyJWT・HS256）.

auth_enabled=True のときのみ有効. auth/login が単一デモユーザーを検証して
token を発行し, 保護ルートは Authorization: Bearer を要求する. 検証は
依存（api/deps.require_auth）が行う. 秘密（jwt_secret/パスワード）は settings
経由のみで, ログ・レスポンス・例外詳細に出さない.
"""

import hmac
from datetime import datetime, timedelta, timezone

import jwt

from app.config import Settings


def authenticate(settings: Settings, username: str, password: str) -> bool:
    """デモ用の単一ユーザー資格情報を定数時間比較で検証する."""
    user_ok = hmac.compare_digest(username, settings.auth_username)
    pass_ok = hmac.compare_digest(password, settings.auth_password)
    return user_ok and pass_ok


def create_access_token(settings: Settings, subject: str) -> str:
    """subject を sub に持つ JWT を発行する."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(settings: Settings, token: str) -> dict:
    """JWT を検証してペイロードを返す. 失敗時は jwt の例外を送出する."""
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )
