"""層をまたいで共有するドメイン例外.

API 層がこれらを捕捉して HTTP ステータスへ写像する（例: ConflictError→409）.
実装側（repository/service）はこれらを送出するだけで, HTTP を知らない.
"""


class DomainError(Exception):
    """ReplyGuard ドメイン例外の基底."""


class NotFoundError(DomainError):
    """対象の MessageRecord が存在しない（→ 404）."""


class ConflictError(DomainError):
    """楽観ロックの version 不一致（→ 409）.

    expected/actual を持ち, クライアントに再取得を促す.
    """

    def __init__(self, message_id: str, expected: int, actual: int) -> None:
        self.message_id = message_id
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"version 競合: message_id={message_id} "
            f"expected={expected} actual={actual}"
        )


class TransitionError(DomainError):
    """FSM 上で許可されない状態遷移（→ 409/422）."""

    def __init__(self, message_id: str, current: str, requested: str) -> None:
        self.message_id = message_id
        self.current = current
        self.requested = requested
        super().__init__(
            f"不正な状態遷移: message_id={message_id} "
            f"{current} -> {requested}"
        )
