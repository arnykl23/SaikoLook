"""StubAnalyzer の決定的な振る舞いを検証する.

ルール（締切系語で重要度↑・宣伝系語で重要度↓・決定性・締切抽出・型/範囲）が
効くことを複数ケースで固める. 外部 API は一切叩かない.
"""

from datetime import datetime, timezone

from app.analysis.stub import StubAnalyzer
from app.models import AnalysisResult
from tests.conftest import make_email


def _analyze(**kwargs) -> AnalysisResult:
    return StubAnalyzer().analyze(make_email(**kwargs))


def test_urgent_unread_raises_importance_and_request_type():
    result = _analyze(
        subject="【至急】契約書のご返信をお願いします",
        body_text="本日中にご返信ください。",
        is_unread=True,
    )
    assert result.importance >= 4
    assert result.request_type == "reply_required"
    assert result.task_weight in ("medium", "heavy")
    assert result.analyzer == "stub"


def test_urgent_read_is_slightly_lower_than_unread():
    read = _analyze(subject="至急 返信ください", body_text="x", is_unread=False)
    unread = _analyze(subject="至急 返信ください", body_text="x", is_unread=True)
    assert unread.importance > read.importance
    assert read.request_type == "reply_required"


def test_promo_keywords_lower_importance():
    result = _analyze(
        subject="週末セールのお知らせ",
        sender="No-Reply <noreply@shop.example.com>",
        body_text="newsletter: 配信停止はこちら",
        is_unread=True,
    )
    assert result.importance <= 2
    assert result.request_type == "info_only"
    assert result.is_promotional is True
    assert result.suggested_action is None


def test_neutral_mail_is_default_importance():
    result = _analyze(
        subject="ランチのお誘い",
        body_text="来週どこか空いてますか",
        is_unread=True,
    )
    assert result.importance == 3
    assert result.request_type == "info_only"
    assert result.is_promotional is False
    assert result.task_weight == "light"


def test_deadline_extracted_from_iso_date():
    result = _analyze(
        subject="期限は 2026-06-15 です",
        body_text="ご対応ください",
    )
    assert result.deadline is not None
    assert (result.deadline.year, result.deadline.month, result.deadline.day) == (
        2026,
        6,
        15,
    )


def test_deadline_extracted_from_japanese_date():
    received = datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc)
    result = StubAnalyzer().analyze(
        make_email(subject="6月20日が締切です", received_at=received)
    )
    assert result.deadline is not None
    assert (result.deadline.month, result.deadline.day) == (6, 20)


def test_no_deadline_when_absent():
    result = _analyze(subject="ご報告", body_text="特に締切はありません")
    assert result.deadline is None


def test_heavy_task_weight_for_long_urgent_body():
    long_body = "返信が必要です。" + "詳細な背景説明。" * 200
    result = _analyze(subject="至急ご対応を", body_text=long_body, is_unread=True)
    assert result.request_type == "reply_required"
    assert result.task_weight == "heavy"


def test_summary_is_truncated_and_flattened():
    body = "一行目\n二行目\n" + "あ" * 300
    result = _analyze(subject="件名", body_text=body)
    assert "\n" not in result.summary
    assert len(result.summary) <= 121  # 120 + 省略記号


def test_deterministic_same_input_same_output():
    email = make_email(subject="至急 返信", body_text="本日中に", is_unread=True)
    a = StubAnalyzer().analyze(email)
    b = StubAnalyzer().analyze(email)
    assert a.model_dump() == b.model_dump()


def test_importance_always_in_range():
    for subject in ("至急 至急 緊急 重要 締切 返信", "セール お知らせ 広告", "通常"):
        result = _analyze(subject=subject)
        assert 1 <= result.importance <= 6
