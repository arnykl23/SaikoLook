"""FSM 遷移規則のテスト（決定的・純関数）."""

import pytest

from app.domain.fsm import assert_transition, can_transition
from app.models import MessageState
from app.ports.errors import TransitionError

S = MessageState

# (current, target) -> 許可されるか
_VALID = {
    (S.UNHANDLED, S.IN_PROGRESS),
    (S.UNHANDLED, S.DONE),
    (S.UNHANDLED, S.SNOOZED),
    (S.UNHANDLED, S.DISMISSED),
    (S.IN_PROGRESS, S.DONE),
    (S.IN_PROGRESS, S.SNOOZED),
    (S.IN_PROGRESS, S.DISMISSED),
    (S.IN_PROGRESS, S.UNHANDLED),
    (S.SNOOZED, S.UNHANDLED),
    (S.SNOOZED, S.IN_PROGRESS),
    (S.SNOOZED, S.DONE),
    (S.SNOOZED, S.DISMISSED),
    (S.DONE, S.UNHANDLED),
    (S.DISMISSED, S.UNHANDLED),
}


@pytest.mark.parametrize("current,target", sorted(_VALID, key=lambda p: (p[0].value, p[1].value)))
def test_valid_transitions_allowed(current, target):
    assert can_transition(current, target) is True


def test_same_state_is_noop_allowed():
    for s in MessageState:
        assert can_transition(s, s) is True


@pytest.mark.parametrize("current", list(MessageState))
@pytest.mark.parametrize("target", list(MessageState))
def test_matrix_matches_spec(current, target):
    expected = current == target or (current, target) in _VALID
    assert can_transition(current, target) is expected


def test_invalid_transitions_rejected():
    # done からは unhandled のみ許可. in_progress へは不可.
    assert can_transition(S.DONE, S.IN_PROGRESS) is False
    assert can_transition(S.DISMISSED, S.DONE) is False
    assert can_transition(S.DONE, S.DISMISSED) is False


def test_assert_transition_raises_on_invalid():
    with pytest.raises(TransitionError) as ei:
        assert_transition("gmail:1", S.DONE, S.IN_PROGRESS)
    err = ei.value
    assert err.message_id == "gmail:1"
    assert err.current == "done"
    assert err.requested == "in_progress"


def test_assert_transition_passes_on_valid():
    assert_transition("gmail:1", S.UNHANDLED, S.DONE)  # 例外が出なければ OK
    assert_transition("gmail:1", S.DONE, S.DONE)  # 同状態
