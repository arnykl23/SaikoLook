"""状態遷移ユースケース（StateService）.

Repository ポートに対する状態遷移の調停役. FSM 規則で遷移可否を検証してから
楽観ロック付きの update_state を呼ぶ. API 層はこのサービス経由で状態を変える.

- 対象が無ければ NotFoundError
- FSM 上不正な遷移なら TransitionError
- version 競合なら ConflictError
（いずれも repo から伝播・もしくは本サービスが送出する.）
"""

from app.domain.fsm import assert_transition
from app.models import MessageRecord, MessageState
from app.ports.errors import NotFoundError
from app.ports.repository import Repository


_AUTO_ARCHIVE_STATES = frozenset({MessageState.DONE, MessageState.DISMISSED})


class StateService:
    def __init__(self, repo: Repository) -> None:
        self._repo = repo

    def transition(
        self, message_id: str, target: MessageState, expected_version: int
    ) -> MessageRecord:
        """message_id を target へ遷移する（楽観ロック）. 更新後レコードを返す.

        done / dismissed への遷移では自動的に is_archived=True にする.
        """
        current = self._repo.get(message_id)
        if current is None:
            raise NotFoundError(f"message_id={message_id} は存在しません")
        # 早期に分かりやすい TransitionError を出す（repo 側でも再検証する）.
        assert_transition(message_id, current.state, target)
        record = self._repo.update_state(message_id, target, expected_version)
        if target in _AUTO_ARCHIVE_STATES:
            record = self._repo.set_archived(message_id, True)
        return record
