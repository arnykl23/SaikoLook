"""永続化層のポート.

MessageRecord（メール本体＋分析＋状態）の保存・問い合わせ・状態遷移を
担う契約. 実装（app/repositories/*）は SQLAlchemy 等で具象化する.
状態遷移は楽観ロック（version）で守り, 競合時は ConflictError を送出する.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from app.models import MessageRecord, MessageState


@dataclass(frozen=True)
class MessageQuery:
    """一覧取得の問い合わせ条件（API のクエリパラメータと対応）."""

    state: MessageState | None = None       # 状態で絞り込み（None=全件）
    unread_only: bool = False
    archived: bool = False                  # False=メインフィード, True=アーカイブビュー
    limit: int = 100
    offset: int = 0
    order_by: str = "triage_score"          # "triage_score" | "received_at" | "importance"
    descending: bool = True
    providers: list[str] = field(default_factory=list)       # 空なら全プロバイダ
    account_addresses: list[str] = field(default_factory=list)  # 空なら全アカウント
    importance_min: int | None = None
    received_after: datetime | None = None
    received_before: datetime | None = None


@runtime_checkable
class Repository(Protocol):
    """MessageRecord の永続化口."""

    def upsert_messages(self, records: list[MessageRecord]) -> int:
        """message_id をキーに冪等 upsert する. 新規挿入件数を返す.

        既存レコードの state はユーザー操作を尊重して保持する
        （取得のたびに状態を初期化しない）.
        """
        ...

    def get(self, message_id: str) -> MessageRecord | None:
        """1 件取得. 無ければ None."""
        ...

    def query(self, q: MessageQuery) -> list[MessageRecord]:
        """条件に合う一覧を返す."""
        ...

    def update_state(
        self, message_id: str, new_state: MessageState, expected_version: int
    ) -> MessageRecord:
        """状態遷移（楽観ロック）. 更新後のレコードを返す.

        - 対象が無ければ NotFoundError
        - expected_version が現在と不一致なら ConflictError
        - FSM 上不正な遷移なら TransitionError
        """
        ...

    def set_archived(self, message_id: str, archived: bool) -> MessageRecord:
        """is_archived を更新する. 更新後のレコードを返す.

        - 対象が無ければ NotFoundError
        """
        ...

    def unarchive(self, message_id: str) -> MessageRecord:
        """アーカイブを解除し状態を unhandled に戻す（原子更新）.

        is_archived=False, state=unhandled, version+=1 を1回の UPDATE で行う.
        - 対象が無ければ NotFoundError
        """
        ...

    def list_providers(self) -> list[str]:
        """DB に存在する distinct な provider 一覧をアルファベット順で返す."""
        ...

    def delete_by_account_address(self, account_address: str) -> int:
        """指定アカウントアドレスのメッセージを全件削除して件数を返す."""
        ...

    def delete_orphan_messages(self, valid_addresses: list[str]) -> int:
        """有効アドレス一覧にないメッセージを全件削除して件数を返す."""
        ...
