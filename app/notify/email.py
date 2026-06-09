"""SMTP メール通知.

settings の smtp_* / notify_email_* を使い, 重要メールの「要点」を SMTP で
送る. 本文全文は載せない（LLM02）. 資格情報は settings 経由のみで, ログ・
例外詳細に出さない. 配送失敗は例外として呼び出し側（IngestionService）が握る.
"""

import logging
import smtplib
from email.message import EmailMessage as MimeMessage

from app.config import Settings
from app.models import MessageRecord
from app.notify.log import BaseNotifier

logger = logging.getLogger(__name__)


class EmailNotifier(BaseNotifier):
    """SMTP でメール通知する."""

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

    def _deliver(self, record: MessageRecord) -> None:
        s = self._settings
        importance = record.analysis.importance if record.analysis else "-"
        summary = record.analysis.summary if record.analysis else ""

        mime = MimeMessage()
        mime["Subject"] = f"[ReplyGuard] 重要メール (importance={importance})"
        mime["From"] = s.notify_email_from or s.smtp_user
        mime["To"] = s.notify_email_to
        mime.set_content(
            f"件名: {record.email.subject}\n"
            f"差出人: {record.email.sender}\n"
            f"重要度: {importance}\n"
            f"要約: {summary}\n"
            f"message_id: {record.message_id}\n"
        )

        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as server:
            server.starttls()
            if s.smtp_user:
                server.login(s.smtp_user, s.smtp_password)
            server.send_message(mime)

        logger.info("メール通知を送信 message_id=%s", record.message_id)
