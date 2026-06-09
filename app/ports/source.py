"""受信・正規化層のポート.

取得元（Gmail IMAP / 将来 Outlook 等）の差を吸収し, 共通スキーマ
EmailMessage の列を返す契約. adapter（app/adapters/sources/*）が実装する.

baseline は list_recent(limit) のみで動く（最新 N 件を再取得し,
Repository.upsert で message_id 冪等にして重複を防ぐ）. 増分同期は
将来 fetch_since で足せる（今は必須にしない）.
"""

from typing import Protocol, runtime_checkable

from app.models import EmailMessage


@runtime_checkable
class MessageSource(Protocol):
    """プロバイダ非依存のメール取得口."""

    def list_recent(self, limit: int = 10) -> list[EmailMessage]:
        """受信トレイの最新メールを新しい順で返す（読み取り専用）."""
        ...

    def close(self) -> None:
        """接続を閉じる（接続を持たない実装では no-op で良い）."""
        ...
