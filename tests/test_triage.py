"""トリアージ採点（推奨度＝重要度×緊急度）と緊急度採点のテスト（決定的・純関数）."""

from datetime import datetime, timedelta, timezone

from app.domain.triage import compute_triage_score, compute_urgency_score
from app.models import AnalysisResult

NOW = datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc)


def _analysis(importance: int, deadline: datetime | None = None) -> AnalysisResult:
    return AnalysisResult(importance=importance, deadline=deadline)


# --- compute_triage_score ---

def test_triage_non_negative_float():
    score = compute_triage_score(None, NOW)
    assert isinstance(score, float)
    assert score >= 0.0


def test_triage_no_analysis_uses_default_importance():
    # analysis なし → importance=2, urgency=0 → score = 2 * 1.0 = 2.0
    assert compute_triage_score(None, NOW) == 2.0


def test_triage_importance_scales_score():
    low = compute_triage_score(_analysis(1), NOW)
    high = compute_triage_score(_analysis(5), NOW)
    assert high > low


def test_triage_urgency_boosts_score():
    a_no_dl = _analysis(3)
    a_overdue = _analysis(3, deadline=NOW - timedelta(days=1))
    assert compute_triage_score(a_overdue, NOW) > compute_triage_score(a_no_dl, NOW)


def test_triage_overdue_deadline_formula():
    # importance=2, urgency=5.0 → 2 * (1+5) = 12.0
    a = _analysis(2, deadline=NOW - timedelta(days=1))
    assert compute_triage_score(a, NOW) == 2.0 * 6.0


def test_triage_no_deadline_formula():
    # importance=4, urgency=0 → 4 * 1.0 = 4.0
    a = _analysis(4)
    assert compute_triage_score(a, NOW) == 4.0


def test_triage_deterministic():
    a = _analysis(3, deadline=NOW + timedelta(days=7))
    assert compute_triage_score(a, NOW) == compute_triage_score(a, NOW)


# --- compute_urgency_score ---

def _analysis_with_deadline(deadline: datetime | None) -> AnalysisResult:
    return AnalysisResult(importance=3, deadline=deadline)


def test_urgency_no_analysis_returns_zero():
    assert compute_urgency_score(None, NOW) == 0.0


def test_urgency_no_deadline_returns_zero():
    assert compute_urgency_score(_analysis_with_deadline(None), NOW) == 0.0


def test_urgency_overdue_returns_max():
    past = NOW - timedelta(days=1)
    assert compute_urgency_score(_analysis_with_deadline(past), NOW) == 5.0


def test_urgency_beyond_window_returns_floor():
    far_future = NOW + timedelta(days=31)
    assert compute_urgency_score(_analysis_with_deadline(far_future), NOW) == 0.5


def test_urgency_at_window_boundary_returns_floor():
    at_window = NOW + timedelta(days=30)
    assert compute_urgency_score(_analysis_with_deadline(at_window), NOW) == 0.5


def test_urgency_today_deadline_near_max():
    today = NOW + timedelta(hours=1)
    score = compute_urgency_score(_analysis_with_deadline(today), NOW)
    assert 4.4 < score <= 4.5


def test_urgency_decreases_as_deadline_recedes():
    s1 = compute_urgency_score(_analysis_with_deadline(NOW + timedelta(days=1)), NOW)
    s2 = compute_urgency_score(_analysis_with_deadline(NOW + timedelta(days=7)), NOW)
    s3 = compute_urgency_score(_analysis_with_deadline(NOW + timedelta(days=14)), NOW)
    assert s1 > s2 > s3


def test_urgency_overdue_beats_imminent():
    overdue = NOW - timedelta(days=1)
    imminent = NOW + timedelta(hours=1)
    assert compute_urgency_score(_analysis_with_deadline(overdue), NOW) > \
           compute_urgency_score(_analysis_with_deadline(imminent), NOW)
