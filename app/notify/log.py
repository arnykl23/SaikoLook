"""ログ通知（既定）と通知基底.

BaseNotifier が重複抑止（dedupe）を共通化し, 各実装は _deliver のみ書く.
dedupe_key を一定期間（プロセス生存中）保持し, 同一メールの二重通知を防ぐ.
LogNotifier は要点のみを標準ログへ出す — 本文全文・スニペットは出さない（LLM02）.
"""

import logging

from app.models import MessageRecord

logger = logging.getLogger(__name__)


class BaseNotifier:
    """重複抑止を共通化する通知基底.

    notify() が dedupe を判定し, 未送なら _deliver() を呼ぶ. 重複・配送失敗を
    呼び出し側へ True/False で返す. dedupe はプロセス内メモリ set で行う.
    """

    def __init__(self) -> None:
        self._sent: set[str] = set()

    def notify(self, record: MessageRecord, dedupe_key: str) -> bool:
        if dedupe_key in self._sent:
            return False
        self._deliver(record)
        self._sent.add(dedupe_key)
        return True

    def _deliver(self, record: MessageRecord) -> None:  # pragma: no cover
        raise NotImplementedError


class LogNotifier(BaseNotifier):
    """標準ログへ要点だけ出す既定通知（オフライン・外部送信なし）."""

    def _deliver(self, record: MessageRecord) -> None:
        importance = record.analysis.importance if record.analysis else None
        logger.info(
            "通知: message_id=%s importance=%s state=%s triage=%.1f from=%s",
            record.message_id,
            importance,
            record.state.value,
            record.triage_score,
            record.email.sender,
        )
