"""StateService のテスト（実 DB 上の SqlRepository を介す）."""

import pytest

from app.models import MessageState
from app.ports.errors import ConflictError, NotFoundError, TransitionError
from app.repositories import db
from app.repositories.sql_repository import SqlRepository
from app.services.state_service import StateService

from tests.conftest import make_record


@pytest.fixture
def service():
    db.configure_engine("sqlite:///:memory:")
    db.init_db()
    repo = SqlRepository()
    repo.upsert_messages([make_record("1")])
    return StateService(repo), repo


def test_transition_success(service):
    svc, _ = service
    rec = svc.transition("gmail:1", MessageState.IN_PROGRESS, 0)
    assert rec.state == MessageState.IN_PROGRESS
    assert rec.version == 1


def test_transition_chain(service):
    svc, _ = service
    svc.transition("gmail:1", MessageState.IN_PROGRESS, 0)
    rec = svc.transition("gmail:1", MessageState.DONE, 1)
    assert rec.state == MessageState.DONE
    assert rec.version == 2


def test_transition_not_found(service):
    svc, _ = service
    with pytest.raises(NotFoundError):
        svc.transition("gmail:404", MessageState.DONE, 0)


def test_transition_invalid_raises(service):
    svc, _ = service
    svc.transition("gmail:1", MessageState.DONE, 0)
    with pytest.raises(TransitionError):
        svc.transition("gmail:1", MessageState.IN_PROGRESS, 1)  # done→in_progress 不可


def test_transition_conflict_propagates(service):
    svc, _ = service
    with pytest.raises(ConflictError):
        svc.transition("gmail:1", MessageState.DONE, 99)
