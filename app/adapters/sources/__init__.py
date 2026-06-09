"""メッセージ取得アダプタの組み立て.

settings から取得元（現状は Gmail IMAP）を生成して MessageSource を返す.
将来 Outlook 等を足す時はここで provider を分岐する.
"""

from app.adapters.sources.gmail_imap import GmailImapSource
from app.config import Settings
from app.ports.source import MessageSource

__all__ = ["GmailImapSource", "build_source"]


def build_source(settings: Settings) -> MessageSource:
    """settings の認証情報から MessageSource を生成する.

    現状は Gmail IMAP のみ. 認証情報の有無はここでは検査しない
    （未設定なら list_recent 呼び出し時に RuntimeError）.
    """
    return GmailImapSource(
        settings.gmail_address,
        settings.gmail_app_password,
        max_body_chars=settings.llm_max_body_chars,
    )
