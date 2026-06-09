"""LLMAnalyzer のパース・検証・フォールバック経路を検証する.

実 API は叩かず, SDK クライアントをモック注入する. 整形 JSON はパース成功,
不正 JSON・範囲外・余計なキー・API 例外は StubAnalyzer へフォールバックする
ことを確認する.
"""

from types import SimpleNamespace

import pytest

from app.analysis.llm import LLMAnalyzer
from tests.conftest import make_email

VALID_JSON = """{
  "importance": 5,
  "needs_reply": true,
  "task_weight": "heavy",
  "category": "action_required",
  "summary": "契約書の返信依頼",
  "suggested_action": "本日中に返信する",
  "deadline": "2026-06-15T00:00:00+00:00",
  "reason": "締切が明示され対応が必要"
}"""


class FakeAnthropicClient:
    """client.messages.create(...) -> resp.content[0].text を模倣する."""

    def __init__(self, text: str):
        self._text = text
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        return SimpleNamespace(content=[SimpleNamespace(text=self._text)])


class FakeOpenAIClient:
    """client.chat.completions.create(...) -> resp.choices[0].message.content を模倣する."""

    def __init__(self, text: str):
        self._text = text
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        message = SimpleNamespace(content=self._text)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _make_anthropic(text: str) -> LLMAnalyzer:
    return LLMAnalyzer(
        provider="anthropic",
        api_key="dummy",
        model="claude-sonnet-4-6",
        timeout_seconds=30,
        max_body_chars=4000,
        client=FakeAnthropicClient(text),
    )


def _make_openai(text: str) -> LLMAnalyzer:
    return LLMAnalyzer(
        provider="openai",
        api_key="dummy",
        model="gpt-4o",
        timeout_seconds=30,
        max_body_chars=4000,
        client=FakeOpenAIClient(text),
    )


def test_anthropic_valid_json_parsed():
    result = _make_anthropic(VALID_JSON).analyze(make_email())
    assert result.importance == 5
    assert result.needs_reply is True
    assert result.task_weight == "heavy"
    assert result.analyzer == "anthropic"
    assert result.deadline is not None


def test_openai_valid_json_parsed():
    result = _make_openai(VALID_JSON).analyze(make_email())
    assert result.importance == 5
    assert result.analyzer == "openai"


def test_json_wrapped_in_code_fence_is_parsed():
    fenced = f"```json\n{VALID_JSON}\n```"
    result = _make_anthropic(fenced).analyze(make_email())
    assert result.importance == 5
    assert result.analyzer == "anthropic"


def test_invalid_json_falls_back_to_stub():
    result = _make_anthropic("これは JSON ではありません").analyze(make_email())
    assert result.analyzer == "stub"  # フォールバック


def test_out_of_range_importance_falls_back():
    bad = VALID_JSON.replace('"importance": 5', '"importance": 99')
    result = _make_anthropic(bad).analyze(make_email())
    assert result.analyzer == "stub"


def test_extra_key_falls_back():
    bad = VALID_JSON.replace(
        '"reason": "締切が明示され対応が必要"',
        '"reason": "x", "exec": "rm -rf /"',
    )
    result = _make_anthropic(bad).analyze(make_email())
    assert result.analyzer == "stub"


def test_client_exception_falls_back():
    class BoomClient:
        def __init__(self):
            self.messages = SimpleNamespace(create=self._boom)

        def _boom(self, **kwargs):
            raise RuntimeError("timeout")

    analyzer = LLMAnalyzer(
        provider="anthropic",
        api_key="dummy",
        model="claude-sonnet-4-6",
        timeout_seconds=30,
        max_body_chars=4000,
        client=BoomClient(),
    )
    result = analyzer.analyze(make_email())
    assert result.analyzer == "stub"


def test_unsupported_provider_falls_back():
    analyzer = LLMAnalyzer(
        provider="unknown",
        api_key="dummy",
        model="x",
        timeout_seconds=30,
        max_body_chars=4000,
        client=FakeAnthropicClient(VALID_JSON),
    )
    result = analyzer.analyze(make_email())
    assert result.analyzer == "stub"


@pytest.mark.parametrize("factory", [_make_anthropic, _make_openai])
def test_body_is_truncated_to_max_chars(factory):
    """max_body_chars を超える本文でもクラッシュせず動く（切り詰めの経路を踏む）."""
    analyzer = factory(VALID_JSON)
    analyzer.max_body_chars = 50
    result = analyzer.analyze(make_email(body_text="あ" * 5000))
    assert result.importance == 5
