"""推奨スコア（重要度＋期限緊急度の複合）と緊急度スコア（期限近接）.

決定的な純粋関数.

triage_score（推奨度）採点式:
    score = importance * (1 + urgency_score)

- deadline なし (urgency=0.0): importance × 1.0 → 1〜6
- 期限超過     (urgency=5.0): importance × 6.0 → 6〜36
- 0〜30日以内            : urgency が 4.5→0.5 に減衰するため線形補間

urgency_score（緊急度）採点式:
    deadline なし → 0.0
    期限超過      → 5.0
    0〜30日以内   → 4.5→0.5 に線形減衰
    30日超        → 0.5（将来の期限として記録のみ）

すべて 0 以上の float. deadline 不明時は urgency=0 扱い.
"""

from datetime import datetime, timezone

from app.models import AnalysisResult

_DEFAULT_IMPORTANCE = 2
_URGENCY_WINDOW_DAYS = 30.0  # この期間内に期限が迫ると urgency が上がる


def compute_triage_score(analysis: AnalysisResult | None, now: datetime) -> float:
    """推奨スコア = 重要度 × (1 + 緊急度スコア)（決定的・0 以上）."""
    importance = analysis.importance if analysis is not None else _DEFAULT_IMPORTANCE
    urgency = compute_urgency_score(analysis, now)
    return importance * (1.0 + urgency)


def compute_urgency_score(analysis: AnalysisResult | None, now: datetime) -> float:
    """期限ベースの緊急度スコアを返す（0.0〜5.0）.

    deadline なし → 0.0（緊急判定不可）
    期限超過      → 5.0
    0〜30日以内   → 4.5→0.5 に線形減衰
    30日超        → 0.5（将来の予定として記録のみ）
    """
    if analysis is None or analysis.deadline is None:
        return 0.0
    deadline = analysis.deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    ref = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    days_remaining = (deadline - ref).total_seconds() / 86400.0
    if days_remaining < 0.0:
        return 5.0
    if days_remaining >= _URGENCY_WINDOW_DAYS:
        return 0.5
    return 0.5 + 4.0 * (1.0 - days_remaining / _URGENCY_WINDOW_DAYS)
