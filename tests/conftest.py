"""pytest 共有フィクスチャ.

各層のテストが使う最小の素材を提供する. 実 API（Gmail/LLM/SMTP/Slack）は
テストで叩かない — source/analyzer/notifier はフェイク or モックを使う.
"""

from datetime import datetime, timezone

import pytest

from app.models import AnalysisResult, EmailMessage, MessageRecord


def make_email(
    raw_id: str = "1",
    *,
    provider: str = "gmail",
    subject: str = "テスト件名",
    sender: str = "Alice <alice@example.com>",
    is_unread: bool = True,
    body_text: str | None = "本文サンプル",
    received_at: datetime | None = None,
) -> EmailMessage:
    """テスト用 EmailMessage を生成する."""
    return EmailMessage(
        id=raw_id,
        provider=provider,
        subject=subject,
        sender=sender,
        to=["me@example.com"],
        received_at=received_at or datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc),
        snippet=(body_text or "")[:120],
        is_unread=is_unread,
        body_text=body_text,
    )


def make_record(
    raw_id: str = "1",
    *,
    analysis: AnalysisResult | None = None,
) -> MessageRecord:
    """テスト用 MessageRecord を生成する."""
    email = make_email(raw_id)
    return MessageRecord(
        message_id=MessageRecord.make_id(email.provider, email.id),
        email=email,
        analysis=analysis,
    )


@pytest.fixture
def sample_email() -> EmailMessage:
    return make_email()


@pytest.fixture
def sample_record() -> MessageRecord:
    return make_record()
