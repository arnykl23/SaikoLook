"""通知層のポート.

重要メール（しきい値以上）を外部へ通知する契約. LogNotifier（既定・
オフライン）/ Email(SMTP) / Slack(webhook) を同契約に乗せ, 設定で選ぶ.
dedupe_key で同一メールの重複通知を防ぐ.
"""

from typing import Protocol, runtime_checkable

from app.models import MessageRecord


@runtime_checkable
class Notifier(Protocol):
    """重要メールの通知口."""

    def notify(self, record: MessageRecord, dedupe_key: str) -> bool:
        """通知を送る. 実際に送ったら True, 重複抑止/しきい値未満なら False."""
        ...
