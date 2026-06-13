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

# 各プロバイダの SDK 判定用モジュール名・APIキー属性名・既定モデル.
_SDK_MODULE = {
    "anthropic": "anthropic",
    "openai": "openai",
    "gemini": "google.genai",
}
_API_KEY_ATTR = {
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
    "gemini": "gemini_api_key",
}
_DEFAULT_MODEL = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.5-flash-lite",  # 最安ティア（コスト重視）
}


def build_analyzer(settings: Settings) -> Analyzer:
    choice = (settings.analyzer or "stub").lower()

    if choice == "stub":
        return StubAnalyzer()

    if choice in _SDK_MODULE:
        api_key = getattr(settings, _API_KEY_ATTR[choice], "")
        if not api_key:
            logger.warning(
                "analyzer=%s だが API キー未設定のため StubAnalyzer にフォールバック",
                choice,
            )
            return StubAnalyzer()
        if importlib.util.find_spec(_SDK_MODULE[choice]) is None:
            logger.warning(
                "analyzer=%s だが SDK 未導入のため StubAnalyzer にフォールバック",
                choice,
            )
            return StubAnalyzer()
        # llm_model 未指定ならプロバイダ別の既定を使う（誤プロバイダのモデル名混入を防ぐ）.
        model = settings.llm_model or _DEFAULT_MODEL[choice]
        return LLMAnalyzer(
            provider=choice,
            api_key=api_key,
            model=model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_body_chars=settings.llm_max_body_chars,
        )

    logger.warning("未知の analyzer=%s のため StubAnalyzer にフォールバック", choice)
    return StubAnalyzer()
