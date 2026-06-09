"""通知器のファクトリ.

settings.notifier の値で実装を選ぶ. 必要な設定が欠けていれば LogNotifier に
フォールバックする（オフラインでも常に動く）. 司令塔の lifespan から呼ぶ.
"""

import logging

from app.config import Settings
from app.notify.email import EmailNotifier
from app.notify.log import LogNotifier
from app.notify.slack import SlackNotifier
from app.ports import Notifier

logger = logging.getLogger(__name__)


def build_notifier(settings: Settings) -> Notifier:
    kind = (settings.notifier or "log").lower()

    if kind == "email":
        if settings.smtp_host and settings.notify_email_to:
            return EmailNotifier(settings)
        logger.warning("notifier=email だが SMTP 設定不足. LogNotifier にフォールバック")
        return LogNotifier()

    if kind == "slack":
        if settings.slack_webhook_url:
            return SlackNotifier(settings)
        logger.warning("notifier=slack だが webhook 未設定. LogNotifier にフォールバック")
        return LogNotifier()

    return LogNotifier()
