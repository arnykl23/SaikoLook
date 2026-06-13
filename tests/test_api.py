"""API エンドポイントのテスト（TestClient + in-memory SQLite）.

依存性注入を差し替えて lifespan を起動せずにテストする.
- get_repo / get_state_service → in-memory SqlRepository
- require_auth → 無条件素通り（auth_enabled の設定不要）
"""

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_repo, get_state_service, require_auth
from app.main import app
from app.models import MessageState
from app.repositories import db
from app.repositories.sql_repository import SqlRepository
from app.services.state_service import StateService

from tests.conftest import make_record


@pytest.fixture
def api_client():
    db.configure_engine("sqlite:///:memory:")
    db.init_db()
    repo = SqlRepository()
    svc = StateService(repo)

    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_state_service] = lambda: svc
    app.dependency_overrides[require_auth] = lambda: None

    repo.upsert_messages([make_record("1"), make_record("2")])

    yield TestClient(app), repo

    app.dependency_overrides.clear()


# --- GET /messages -----------------------------------------------------------

def test_list_messages_default_excludes_archived(api_client):
    client, repo = api_client
    repo.set_archived("gmail:1", True)
    resp = client.get("/messages")
    assert resp.status_code == 200
    ids = [m["message_id"] for m in resp.json()]
    assert "gmail:1" not in ids
    assert "gmail:2" in ids


def test_list_messages_archived_param_returns_only_archived(api_client):
    client, repo = api_client
    repo.set_archived("gmail:1", True)
    resp = client.get("/messages", params={"archived": "true"})
    assert resp.status_code == 200
    ids = [m["message_id"] for m in resp.json()]
    assert "gmail:1" in ids
    assert "gmail:2" not in ids


def test_list_messages_default_includes_all_non_archived(api_client):
    client, _ = api_client
    resp = client.get("/messages")
    assert resp.status_code == 200
    ids = [m["message_id"] for m in resp.json()]
    assert "gmail:1" in ids
    assert "gmail:2" in ids


# --- POST /messages/{id}/archive ---------------------------------------------

def test_archive_endpoint_sets_is_archived(api_client):
    client, repo = api_client
    resp = client.post("/messages/gmail:1/archive")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_archived"] is True
    assert data["message_id"] == "gmail:1"
    assert repo.get("gmail:1").is_archived is True


def test_archive_endpoint_not_found(api_client):
    client, _ = api_client
    resp = client.post("/messages/gmail:999/archive")
    assert resp.status_code == 404


# --- POST /messages/{id}/unarchive -------------------------------------------

def test_unarchive_endpoint_restores_record(api_client):
    client, repo = api_client
    repo.set_archived("gmail:1", True)
    resp = client.post("/messages/gmail:1/unarchive")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_archived"] is False
    assert data["state"] == MessageState.UNHANDLED.value


def test_unarchive_increments_version(api_client):
    client, repo = api_client
    before = repo.get("gmail:1")
    client.post("/messages/gmail:1/unarchive")
    after = repo.get("gmail:1")
    assert after.version == before.version + 1


def test_unarchive_endpoint_not_found(api_client):
    client, _ = api_client
    resp = client.post("/messages/gmail:999/unarchive")
    assert resp.status_code == 404


# --- 自動アーカイブ（done/dismissed 遷移後にフィードから消えること）-----------

def test_done_via_state_endpoint_auto_archives(api_client):
    client, repo = api_client
    resp = client.post(
        "/messages/gmail:1/state",
        json={"state": "done", "version": 0},
    )
    assert resp.status_code == 200
    assert resp.json()["is_archived"] is True
    # メインフィードに出ないこと.
    feed = client.get("/messages").json()
    assert all(m["message_id"] != "gmail:1" for m in feed)
    # アーカイブビューに出ること.
    archive = client.get("/messages", params={"archived": "true"}).json()
    assert any(m["message_id"] == "gmail:1" for m in archive)


# --- GET /providers -------------------------------------------------------

def test_list_providers_endpoint(api_client):
    client, _ = api_client
    resp = client.get("/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert "gmail" in data


# --- GET /messages?providers= --------------------------------------------

def test_list_messages_filter_by_provider(api_client):
    client, _ = api_client
    resp = client.get("/messages", params={"providers": "gmail"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) > 0
    assert all(m["email"]["provider"] == "gmail" for m in data)


def test_list_messages_filter_by_unknown_provider_returns_empty(api_client):
    client, _ = api_client
    resp = client.get("/messages", params={"providers": "slack"})
    assert resp.status_code == 200
    assert resp.json() == []


# --- GET /messages?importance_min= ---------------------------------------

def test_list_messages_filter_by_importance_min(api_client):
    from app.models import AnalysisResult
    from tests.conftest import make_record as _make_record
    client, repo = api_client
    # importance=5 のレコードを追加.
    r_high = _make_record("high", analysis=AnalysisResult(importance=5))
    r_low = _make_record("low", analysis=AnalysisResult(importance=2))
    repo.upsert_messages([r_high, r_low])
    resp = client.get("/messages", params={"importance_min": 4})
    assert resp.status_code == 200
    ids = [m["message_id"] for m in resp.json()]
    assert "gmail:high" in ids
    assert "gmail:low" not in ids


def test_list_messages_importance_min_validation(api_client):
    client, _ = api_client
    resp = client.get("/messages", params={"importance_min": 0})
    assert resp.status_code == 422
    resp = client.get("/messages", params={"importance_min": 6})
    assert resp.status_code == 200  # 6 は有効な最大値
    resp = client.get("/messages", params={"importance_min": 7})
    assert resp.status_code == 422


# --- GET /messages?order_by=received_at / importance ---------------------

def test_list_messages_order_by_received_at(api_client):
    client, _ = api_client
    resp = client.get("/messages", params={"order_by": "received_at", "descending": "false"})
    assert resp.status_code == 200


def test_list_messages_order_by_importance(api_client):
    from app.models import AnalysisResult
    from tests.conftest import make_record as _make_record
    client, repo = api_client
    r = _make_record("imp", analysis=AnalysisResult(importance=4))
    repo.upsert_messages([r])
    resp = client.get("/messages", params={"order_by": "importance", "descending": "true"})
    assert resp.status_code == 200
