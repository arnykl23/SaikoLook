"""Gmail OAuth ルートの統合テスト.

lifespan を経由した app.state 直接代入は TestClient の with ブロックで上書きされるため，
FastAPI の dependency_overrides を使ってモックを注入する．
"""
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.api.deps import get_oauth_service, get_account_repo, get_settings


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
    mock_settings.auth_enabled = False
    app.dependency_overrides[get_oauth_service] = lambda: mock_oauth
    app.dependency_overrides[get_account_repo] = lambda: mock_repo
    app.dependency_overrides[get_settings] = lambda: mock_settings
    return mock_oauth, mock_repo, mock_settings


def test_start_returns_auth_url():
    mock_oauth, _, _ = _setup_mocks()
    mock_oauth.generate_auth_url.return_value = (
        "https://accounts.google.com/o/oauth2/auth?...",
        "state_abc",
    )
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
        "refresh_token": "rt",
        "access_token": "at",
        "token_expiry": None,
        "scopes": "https://www.googleapis.com/auth/gmail.readonly",
    }
    mock_oauth.build_credentials.return_value = MagicMock()
    with TestClient(app, follow_redirects=False) as client:
        resp = client.get("/auth/gmail/callback?code=code123&state=state_abc")
    assert resp.status_code in (302, 307)
    assert "oauth_success=1" in resp.headers["location"]
    mock_repo.create_oauth.assert_called_once()


def test_callback_returns_400_for_invalid_state():
    mock_oauth, _, _ = _setup_mocks()
    mock_oauth.pop_state.return_value = None
    with TestClient(app) as client:
        resp = client.get("/auth/gmail/callback?code=code&state=invalid")
    assert resp.status_code == 400
