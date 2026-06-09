"""トリアージ採点（未対応検知スコア）.

決定的な純粋関数. メール1通の「放置リスク」を 1 つの float に圧縮する.
ダッシュボードはこのスコア降順で「対応漏れ」を上位に出す.

採点式:
    score = unread_factor * importance * age_factor

- unread_factor: 未読=1.0, 既読=0.3（未読を優先）
- importance   : analysis.importance（1-5）. analysis 無しは既定 2
- age_factor   : 経過日数で単調増加. 1 + min(days, 14)/14 * K
                 （受信直後=1.0, 14 日以上経過=1+K で頭打ち）

すべて 0 以上の float. received_at 不明時は経過 0 日（age_factor=1.0）扱い.
"""

from datetime import datetime, timezone

from app.models import AnalysisResult, EmailMessage

_UNREAD_FACTOR = 1.0
_READ_FACTOR = 0.3
_DEFAULT_IMPORTANCE = 2
_AGE_CAP_DAYS = 14.0
_AGE_GAIN = 1.0  # K: 経過頭打ち時の加算上限


def _age_days(received_at: datetime | None, now: datetime) -> float:
    """received_at→now の経過日数（負値・None は 0 に丸める）."""
    if received_at is None:
        return 0.0
    # tz-naive な received_at は UTC とみなして now と揃える.
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)
    ref = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    elapsed = (ref - received_at).total_seconds() / 86400.0
    return max(elapsed, 0.0)


def compute_triage_score(
    email: EmailMessage, analysis: AnalysisResult | None, now: datetime
) -> float:
    """メール1通のトリアージスコアを返す（決定的・0 以上）."""
    unread_factor = _UNREAD_FACTOR if email.is_unread else _READ_FACTOR
    importance = analysis.importance if analysis is not None else _DEFAULT_IMPORTANCE
    days = _age_days(email.received_at, now)
    age_factor = 1.0 + min(days, _AGE_CAP_DAYS) / _AGE_CAP_DAYS * _AGE_GAIN
    return unread_factor * importance * age_factor
