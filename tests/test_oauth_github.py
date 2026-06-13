"""OAuthGithubService の単体テスト.

実 GitHub API は叩かない.
httpx.post / httpx.get を unittest.mock.patch でモックして検証する.
"""
import time
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from app.services.oauth_github import OAuthGithubService


def _svc() -> OAuthGithubService:
    return OAuthGithubService(
        client_id="test_client_id",
        client_secret="test_client_secret",
        redirect_uri="http://localhost:8000/auth/github/callback",
    )


# ===== generate_auth_url =====

def test_generate_auth_url_contains_scope_and_state() -> None:
    """返却 URL に scope=notifications と state= が含まれること."""
    svc = _svc()
    url, state = svc.generate_auth_url("MyLabel")

    parsed = urlparse(url)
    qs = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert "github.com" in parsed.netloc
    assert qs.get("scope") == ["notifications"]
    assert qs.get("state") == [state]


def test_generate_auth_url_contains_client_id_and_redirect_uri() -> None:
    """返却 URL に client_id と redirect_uri が含まれること."""
    svc = _svc()
    url, state = svc.generate_auth_url("MyLabel")

    parsed = urlparse(url)
    qs = parse_qs(parsed.query)

    assert qs.get("client_id") == ["test_client_id"]
    assert qs.get("redirect_uri") == ["http://localhost:8000/auth/github/callback"]


def test_generate_auth_url_registers_state_in_pending() -> None:
    """生成された state が _pending_states に登録されること."""
    svc = _svc()
    url, state = svc.generate_auth_url("MyLabel")

    assert state in svc._pending_states
    stored = svc._pending_states[state]
    assert stored["label"] == "MyLabel"
    assert "ts" in stored


def test_generate_auth_url_returns_unique_states() -> None:
    """2回呼ぶと異なる state が生成されること（CSRF 対策の一意性）."""
    svc = _svc()
    _, s1 = svc.generate_auth_url("L1")
    _, s2 = svc.generate_auth_url("L2")
    assert s1 != s2


# ===== pop_state =====

def test_pop_state_returns_entry_once() -> None:
    """pop_state は1回目は entry を返し，2回目は None を返すこと."""
    svc = _svc()
    svc._pending_states["s1"] = {"label": "L", "ts": time.monotonic()}

    first = svc.pop_state("s1")
    second = svc.pop_state("s1")

    assert first is not None
    assert first["label"] == "L"
    assert second is None


def test_pop_state_removes_from_pending() -> None:
    """pop 後に _pending_states から削除されること."""
    svc = _svc()
    svc._pending_states["s2"] = {"label": "L", "ts": time.monotonic()}
    svc.pop_state("s2")

    assert "s2" not in svc._pending_states


def test_pop_state_expired_returns_none() -> None:
    """TTL（600秒）を超過した state は None を返すこと."""
    svc = _svc()
    svc._pending_states["s3"] = {
        "label": "L",
        "ts": time.monotonic() - 700,  # 600s TTL 超過
    }
    result = svc.pop_state("s3")
    assert result is None


def test_pop_state_unknown_returns_none() -> None:
    """存在しない state は None を返すこと."""
    svc = _svc()
    assert svc.pop_state("nonexistent") is None


# ===== exchange_code =====

def test_exchange_code_returns_access_token() -> None:
    """access_token を含む dict を返すこと."""
    svc = _svc()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": "gho_testtoken123",
        "scope": "notifications",
        "token_type": "bearer",
    }

    with patch("httpx.post", return_value=mock_resp) as mock_post:
        result = svc.exchange_code("code_abc")

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    # POST 先 URL の確認
    assert "github.com/login/oauth/access_token" in call_kwargs.args[0]
    # リクエスト data に code が含まれること
    assert call_kwargs.kwargs["data"]["code"] == "code_abc"
    # Accept ヘッダが application/json であること
    assert call_kwargs.kwargs["headers"]["Accept"] == "application/json"

    assert result["access_token"] == "gho_testtoken123"
    assert result["scopes"] == "notifications"


def test_exchange_code_raises_on_missing_access_token() -> None:
    """access_token が欠落したレスポンスで RuntimeError を送出すること."""
    svc = _svc()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "error": "bad_verification_code",
        "error_description": "The code passed is incorrect or expired.",
    }

    with patch("httpx.post", return_value=mock_resp):
        with pytest.raises(RuntimeError):
            svc.exchange_code("invalid_code")


def test_exchange_code_error_message_does_not_leak_secret() -> None:
    """RuntimeError のメッセージに client_secret が含まれないこと（秘密情報非漏洩）."""
    svc = _svc()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"error": "bad_code"}

    with patch("httpx.post", return_value=mock_resp):
        with pytest.raises(RuntimeError) as exc_info:
            svc.exchange_code("bad_code")

    assert "test_client_secret" not in str(exc_info.value)


# ===== fetch_user_login =====

def test_fetch_user_login_returns_login() -> None:
    """GET /user の login フィールドを返すこと."""
    svc = _svc()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "login": "octocat",
        "id": 1,
        "name": "The Octocat",
    }

    with patch("httpx.get", return_value=mock_resp) as mock_get:
        login = svc.fetch_user_login("gho_testtoken123")

    mock_get.assert_called_once()
    call_kwargs = mock_get.call_args
    # エンドポイント確認
    assert "api.github.com/user" in call_kwargs.args[0]
    # Authorization ヘッダに Bearer トークンが含まれること
    assert "Bearer gho_testtoken123" in call_kwargs.kwargs["headers"]["Authorization"]
    # Accept ヘッダ確認
    assert "application/vnd.github" in call_kwargs.kwargs["headers"]["Accept"]

    assert login == "octocat"
