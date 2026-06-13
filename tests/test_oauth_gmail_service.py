"""OAuthGmailService の単体テスト."""
import time
from unittest.mock import MagicMock, patch

from app.services.oauth_gmail import OAuthGmailService


def _svc() -> OAuthGmailService:
    return OAuthGmailService("client_id", "client_secret", "http://localhost:8000/cb")


def test_generate_auth_url_returns_url_and_state() -> None:
    svc = _svc()
    with patch.object(svc, "_make_flow") as mock_make_flow:
        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = (
            "https://accounts.google.com/o/oauth2/auth?...",
            "state123",
        )
        mock_make_flow.return_value = mock_flow
        url, state = svc.generate_auth_url("My Gmail", "me@gmail.com")

    assert url.startswith("https://")
    assert state == "state123"
    assert "state123" in svc._pending_states
    stored = svc._pending_states["state123"]
    assert stored["label"] == "My Gmail"
    assert stored["address"] == "me@gmail.com"


def test_pop_state_valid() -> None:
    svc = _svc()
    svc._pending_states["s1"] = {
        "label": "L",
        "address": "a@b.com",
        "ts": time.monotonic(),
    }
    data = svc.pop_state("s1")
    assert data is not None
    assert data["label"] == "L"
    assert "s1" not in svc._pending_states  # pop 後に消えていること


def test_pop_state_expired() -> None:
    svc = _svc()
    svc._pending_states["s2"] = {
        "label": "L",
        "address": "a@b.com",
        "ts": time.monotonic() - 700,  # TTL=600 を超過
    }
    result = svc.pop_state("s2")
    assert result is None


def test_pop_state_unknown() -> None:
    svc = _svc()
    assert svc.pop_state("nonexistent") is None


def test_exchange_code_returns_token_dict() -> None:
    svc = _svc()
    with patch.object(svc, "_make_flow") as mock_make_flow:
        mock_flow = MagicMock()
        mock_creds = MagicMock()
        mock_creds.refresh_token = "rt123"
        mock_creds.token = "at456"
        mock_creds.expiry = None
        mock_creds.scopes = {"https://www.googleapis.com/auth/gmail.readonly"}
        mock_flow.credentials = mock_creds
        mock_make_flow.return_value = mock_flow

        result = svc.exchange_code("code_abc")

    assert result["refresh_token"] == "rt123"
    assert result["access_token"] == "at456"
    assert "token_expiry" in result
    assert "scopes" in result
