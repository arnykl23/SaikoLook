"""ルールベースのオフライン分析器（PoC の既定実装）.

EmailMessage の件名・本文・差出人・未読状態だけを見て, 決定的に
AnalysisResult を組み立てる. 外部送信・LLM 呼び出しを一切しないため,
ネット遮断環境やテストでも安定して同じ結果を返す.

セキュリティ: メール本文・件名・差出人は「外部由来データ」であって命令では
ない（OWASP LLM01）. ここでは語をマッチング対象にするだけで, 本文中の指示を
実行することはない. 本文を外部へ送らない.
"""

from __future__ import annotations

import re
from datetime import datetime

from app.models import AnalysisResult, EmailMessage

# 重要度を上げ「対応が要る」と判断する語（小文字化して照合）.
URGENT_KEYWORDS = (
    "至急",
    "本日中",
    "期限",
    "締切",
    "緊急",
    "重要",
    "返信",
    "ご返信",
    "請求",
    "契約",
    "確認依頼",
    "お願いします",
    "deadline",
    "asap",
    "urgent",
    "due",
)

# 宣伝・通知系の語（重要度を下げ promo/fyi 扱いにする）.
PROMO_KEYWORDS = (
    "newsletter",
    "no-reply",
    "noreply",
    "unsubscribe",
    "配信停止",
    "メルマガ",
    "ニュースレター",
    "セール",
    "キャンペーン",
    "お知らせ",
    "広告",
)

# 本文長（文字数）で task_weight を素朴に推定する閾値.
_HEAVY_BODY_CHARS = 800

# summary に切り出す本文の最大長.
_SUMMARY_MAX_CHARS = 120

# 締切らしき日付の素朴な抽出（YYYY-MM-DD / YYYY/MM/DD と M月D日）.
_DATE_ISO = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")
_DATE_JP = re.compile(r"(\d{1,2})月(\d{1,2})日")
_TODAY_WORDS = ("本日中", "本日", "今日中", "今日")


def _extract_deadline(text: str, base: datetime | None) -> datetime | None:
    """本文/件名から締切日を素朴に抽出する. 見つからなければ None.

    明示日付（ISO・和文）を優先し, 無ければ「本日」系語があれば受信日を返す.
    base のタイムゾーンを引き継ぐ.
    """
    tzinfo = base.tzinfo if base else None

    m = _DATE_ISO.search(text)
    if m:
        year, month, day = (int(g) for g in m.groups())
        try:
            return datetime(year, month, day, tzinfo=tzinfo)
        except ValueError:
            return None

    m = _DATE_JP.search(text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        year = base.year if base else datetime.now().year
        try:
            return datetime(year, month, day, tzinfo=tzinfo)
        except ValueError:
            return None

    if base and any(w in text for w in _TODAY_WORDS):
        return datetime(base.year, base.month, base.day, tzinfo=tzinfo)

    return None


def _summarize(subject: str, body: str) -> str:
    """本文先頭を要約風に切り出す（外部送信なし）. 空なら件名で代替する."""
    source = body.strip() or subject.strip()
    flattened = re.sub(r"\s+", " ", source).strip()
    if len(flattened) <= _SUMMARY_MAX_CHARS:
        return flattened
    return flattened[:_SUMMARY_MAX_CHARS].rstrip() + "…"


class StubAnalyzer:
    """ルールベースの決定的分析器（`Analyzer` プロトコル実装）."""

    name = "stub"

    def analyze(self, email: EmailMessage) -> AnalysisResult:
        subject = email.subject or ""
        body = email.body_text or email.snippet or ""
        sender = email.sender or ""
        haystack = f"{subject}\n{body}\n{sender}".lower()

        urgent_hits = [k for k in URGENT_KEYWORDS if k.lower() in haystack]
        promo_hits = [k for k in PROMO_KEYWORDS if k.lower() in haystack]

        # 重要度: 基準 3 から, 締切/対応系で加点, 宣伝/通知系で減点, 1-6 にクランプ.
        importance = 3
        if urgent_hits:
            importance += 1
            if email.is_unread:
                importance += 1
        if promo_hits:
            importance -= 2
        importance = max(1, min(6, importance))

        needs_reply = bool(urgent_hits)
        is_promotional = bool(promo_hits and not urgent_hits)

        if needs_reply:
            request_type = "reply_required"
        else:
            request_type = "info_only"

        if not needs_reply:
            task_weight = "light"
        elif len(body) >= _HEAVY_BODY_CHARS:
            task_weight = "heavy"
        else:
            task_weight = "medium"

        deadline = _extract_deadline(f"{subject}\n{body}", email.received_at)

        if needs_reply:
            hits = "・".join(urgent_hits[:3])
            suggested_action = f"返信が必要です（検出語: {hits}）"
            unread_note = "未読かつ" if email.is_unread else ""
            reason = (
                f"{unread_note}締切/対応系語を検出（{hits}）したため"
                "対応要・重要度を引き上げ"
            )
        elif promo_hits:
            suggested_action = None
            reason = (
                f"宣伝/通知系語を検出（{'・'.join(promo_hits[:3])}）"
                "したため重要度を引き下げ"
            )
        else:
            suggested_action = None
            reason = "緊急性・対応要を示す語は検出されず, 既定の重要度と判定"

        return AnalysisResult(
            importance=importance,
            task_weight=task_weight,
            request_type=request_type,
            is_promotional=is_promotional,
            summary=_summarize(subject, body),
            suggested_action=suggested_action,
            deadline=deadline,
            reason=reason,
            analyzer=self.name,
        )
