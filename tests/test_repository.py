"""SqlRepository のテスト（SQLite in-memory の実 DB を使う）.

upsert 冪等・state 保持・楽観ロック競合・遷移エラー・問い合わせを検証する.
"""

from datetime import datetime, timezone

import pytest

from app.models import AnalysisResult, MessageRecord, MessageState
from app.ports.errors import ConflictError, NotFoundError, TransitionError
from app.ports.repository import MessageQuery
from app.repositories import db
from app.repositories.sql_repository import SqlRepository

from tests.conftest import make_email, make_record


@pytest.fixture
def repo():
    # 各テストごとに新しい in-memory DB を作る（StaticPool で単一接続共有）.
    db.configure_engine("sqlite:///:memory:")
    db.init_db()
    return SqlRepository()


def test_upsert_inserts_and_is_idempotent(repo):
    records = [make_record("1"), make_record("2")]
    assert repo.upsert_messages(records) == 2
    # 同じ message_id の再 upsert は新規 0 件.
    assert repo.upsert_messages(records) == 0
    assert repo.get("gmail:1") is not None
    assert repo.get("gmail:2") is not None


def test_upsert_empty_returns_zero(repo):
    assert repo.upsert_messages([]) == 0


def test_upsert_preserves_state_on_reingest(repo):
    repo.upsert_messages([make_record("1")])
    # ユーザーが in_progress へ遷移.
    updated = repo.update_state("gmail:1", MessageState.IN_PROGRESS, 0)
    assert updated.state == MessageState.IN_PROGRESS
    assert updated.version == 1
    # 再取得（再 upsert）で state は初期化されない.
    repo.upsert_messages([make_record("1")])
    again = repo.get("gmail:1")
    assert again.state == MessageState.IN_PROGRESS
    assert again.version == 1


def test_upsert_updates_email_and_score(repo):
    repo.upsert_messages([make_record("1")])
    rec = make_record("1", analysis=AnalysisResult(importance=5))
    rec = rec.model_copy(update={"triage_score": 9.5})
    repo.upsert_messages([rec])
    got = repo.get("gmail:1")
    assert got.triage_score == 9.5
    assert got.analysis is not None
    assert got.analysis.importance == 5


def test_get_missing_returns_none(repo):
    assert repo.get("gmail:404") is None


def test_query_filters_by_state(repo):
    repo.upsert_messages([make_record("1"), make_record("2")])
    repo.update_state("gmail:1", MessageState.DONE, 0)
    done = repo.query(MessageQuery(state=MessageState.DONE))
    assert [r.message_id for r in done] == ["gmail:1"]
    unhandled = repo.query(MessageQuery(state=MessageState.UNHANDLED))
    assert [r.message_id for r in unhandled] == ["gmail:2"]


def test_query_unread_only(repo):
    read_email = make_email("1", is_unread=False)
    read_rec = MessageRecord(
        message_id=MessageRecord.make_id("gmail", "1"), email=read_email
    )
    unread_rec = make_record("2")  # is_unread=True
    repo.upsert_messages([read_rec, unread_rec])
    rows = repo.query(MessageQuery(unread_only=True))
    assert [r.message_id for r in rows] == ["gmail:2"]


def test_query_order_by_triage_score_desc(repo):
    r1 = make_record("1").model_copy(update={"triage_score": 1.0})
    r2 = make_record("2").model_copy(update={"triage_score": 9.0})
    r3 = make_record("3").model_copy(update={"triage_score": 5.0})
    repo.upsert_messages([r1, r2, r3])
    rows = repo.query(MessageQuery(order_by="triage_score", descending=True))
    assert [r.message_id for r in rows] == ["gmail:2", "gmail:3", "gmail:1"]


def test_query_limit_offset(repo):
    recs = [
        make_record(str(i)).model_copy(update={"triage_score": float(i)})
        for i in range(1, 6)
    ]
    repo.upsert_messages(recs)
    rows = repo.query(
        MessageQuery(order_by="triage_score", descending=True, limit=2, offset=1)
    )
    # 降順 [5,4,3,2,1] の offset=1, limit=2 → [4,3]
    assert [r.triage_score for r in rows] == [4.0, 3.0]


def test_update_state_success_bumps_version(repo):
    repo.upsert_messages([make_record("1")])
    rec = repo.update_state("gmail:1", MessageState.DONE, 0)
    assert rec.state == MessageState.DONE
    assert rec.version == 1
    assert rec.updated_at is not None
    assert rec.updated_at.tzinfo is not None


def test_update_state_not_found(repo):
    with pytest.raises(NotFoundError):
        repo.update_state("gmail:404", MessageState.DONE, 0)


def test_update_state_conflict_on_wrong_version(repo):
    repo.upsert_messages([make_record("1")])
    with pytest.raises(ConflictError) as ei:
        repo.update_state("gmail:1", MessageState.DONE, 7)
    err = ei.value
    assert err.message_id == "gmail:1"
    assert err.expected == 7
    assert err.actual == 0


def test_update_state_invalid_transition(repo):
    repo.upsert_messages([make_record("1")])
    repo.update_state("gmail:1", MessageState.DONE, 0)  # unhandled→done
    with pytest.raises(TransitionError):
        repo.update_state("gmail:1", MessageState.IN_PROGRESS, 1)  # done→in_progress 不可


def test_update_state_same_state_advances_version(repo):
    repo.upsert_messages([make_record("1")])
    rec = repo.update_state("gmail:1", MessageState.UNHANDLED, 0)  # no-op 遷移
    assert rec.state == MessageState.UNHANDLED
    assert rec.version == 1


def test_created_at_preserved_updated_at_changes(repo):
    repo.upsert_messages([make_record("1")])
    before = repo.get("gmail:1")
    after = repo.update_state("gmail:1", MessageState.DONE, 0)
    assert after.created_at == before.created_at
    assert after.updated_at >= before.updated_at
    assert isinstance(after.created_at, datetime)
    assert after.created_at.tzinfo == timezone.utc
