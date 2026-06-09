"""対応状態の有限状態機械（FSM）.

MessageState 間の許可された遷移を定義する純粋関数. 実装側（repository/
state_service）はここを唯一の真実として遷移可否を判断し, 不正なら
TransitionError を送出する. design-spec の遷移規則に準拠する.

許可される遷移:
- unhandled  → in_progress | done | snoozed | dismissed
- in_progress→ done | snoozed | dismissed | unhandled
- snoozed    → unhandled | in_progress | done | dismissed
- done       → unhandled                （誤操作の戻し）
- dismissed  → unhandled                （誤操作の戻し）

同状態への遷移（current == target）は no-op として許可する.
実装メモ: 同状態遷移も update_state では正規の UPDATE として扱い version を
進める（楽観ロックの一貫性を保ち, 「最新版で操作した」ことを記録するため）.
"""

from app.models import MessageState
from app.ports.errors import TransitionError

# 各状態から遷移可能な集合（同状態は下の can_transition で別途許可）.
_ALLOWED: dict[MessageState, frozenset[MessageState]] = {
    MessageState.UNHANDLED: frozenset(
        {
            MessageState.IN_PROGRESS,
            MessageState.DONE,
            MessageState.SNOOZED,
            MessageState.DISMISSED,
        }
    ),
    MessageState.IN_PROGRESS: frozenset(
        {
            MessageState.DONE,
            MessageState.SNOOZED,
            MessageState.DISMISSED,
            MessageState.UNHANDLED,
        }
    ),
    MessageState.SNOOZED: frozenset(
        {
            MessageState.UNHANDLED,
            MessageState.IN_PROGRESS,
            MessageState.DONE,
            MessageState.DISMISSED,
        }
    ),
    MessageState.DONE: frozenset({MessageState.UNHANDLED}),
    MessageState.DISMISSED: frozenset({MessageState.UNHANDLED}),
}


def can_transition(current: MessageState, target: MessageState) -> bool:
    """current → target が許可されるなら True. 同状態は no-op として許可する."""
    if current == target:
        return True
    return target in _ALLOWED.get(current, frozenset())


def assert_transition(
    message_id: str, current: MessageState, target: MessageState
) -> None:
    """不正な遷移なら TransitionError を送出する（許可なら何もしない）."""
    if not can_transition(current, target):
        raise TransitionError(message_id, current.value, target.value)
