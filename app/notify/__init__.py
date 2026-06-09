"""通知層.

重要メール（しきい値以上）/ 新規メールを外部へ通知する. Notifier ポートを
実装する LogNotifier（既定）/ EmailNotifier / SlackNotifier を提供し,
build_notifier(settings) で設定に応じて選ぶ. しきい値判定は呼び出し側
（IngestionService）が担い, 通知層は配送と重複抑止のみを担当する.
"""

from app.notify.email import EmailNotifier
from app.notify.factory import build_notifier
from app.notify.log import LogNotifier
from app.notify.slack import SlackNotifier

__all__ = [
    "EmailNotifier",
    "LogNotifier",
    "SlackNotifier",
    "build_notifier",
]
