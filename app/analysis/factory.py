"""設定から Analyzer を組み立てる. 既定はオフライン StubAnalyzer.

実 LLM を指定しても, 対応 API キーが無い・SDK が未導入なら StubAnalyzer に
フォールバックして起動を止めない（警告ログのみ・秘密情報は出さない）.
"""

from __future__ import annotations

import importlib.util
import logging

from app.analysis.llm import LLMAnalyzer
from app.analysis.stub import StubAnalyzer
from app.config import Settings
from app.ports.analyzer import Analyzer

logger = logging.getLogger(__name__)

_SDK_PACKAGE = {"anthropic": "anthropic", "openai": "openai"}


def build_analyzer(settings: Settings) -> Analyzer:
    choice = (settings.analyzer or "stub").lower()

    if choice == "stub":
        return StubAnalyzer()

    if choice in _SDK_PACKAGE:
        api_key = (
            settings.anthropic_api_key
            if choice == "anthropic"
            else settings.openai_api_key
        )
        if not api_key:
            logger.warning(
                "analyzer=%s だが API キー未設定のため StubAnalyzer にフォールバック",
                choice,
            )
            return StubAnalyzer()
        if importlib.util.find_spec(_SDK_PACKAGE[choice]) is None:
            logger.warning(
                "analyzer=%s だが SDK 未導入のため StubAnalyzer にフォールバック",
                choice,
            )
            return StubAnalyzer()
        return LLMAnalyzer(
            provider=choice,
            api_key=api_key,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_body_chars=settings.llm_max_body_chars,
        )

    logger.warning("未知の analyzer=%s のため StubAnalyzer にフォールバック", choice)
    return StubAnalyzer()
