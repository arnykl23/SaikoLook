"""Slack Incoming Webhook 通知.

settings.slack_webhook_url へ要点を POST する. webhook URL は秘匿情報のため
ログ・例外詳細に出さない（LLM02）. 本文全文は載せない. 配送失敗は例外として
呼び出し側（IngestionService）が握る.
"""

import logging

import httpx

from app.config import Settings
from app.models import MessageRecord
from app.notify.log import BaseNotifier

logger = logging.getLogger(__name__)


class SlackNotifier(BaseNotifier):
    """Slack Webhook で通知する."""

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

    def _deliver(self, record: MessageRecord) -> None:
        importance = record.analysis.importance if record.analysis else "-"
        summary = record.analysis.summary if record.analysis else ""
        text = (
            f":mailbox: *SaikoLook 重要メール* (importance={importance})\n"
            f"*件名*: {record.email.subject}\n"
            f"*差出人*: {record.email.sender}\n"
            f"*要約*: {summary}"
        )
        resp = httpx.post(
            self._settings.slack_webhook_url,
            json={"text": text},
            timeout=10.0,
        )
        resp.raise_for_status()
        logger.info("Slack 通知を送信 message_id=%s", record.message_id)
