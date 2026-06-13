"""実 LLM 分析器（Anthropic / OpenAI / Gemini / Ollama）.

設定で analyzer="anthropic"/"openai"/"gemini"/"ollama" の時だけ使う. SDK 呼び出しの
失敗・タイムアウト・不正出力・スキーマ違反では決して落とさず, StubAnalyzer の結果へ
フォールバックする（RESILIENCE）.

セキュリティ:
- 本文を外部へ送るのは, ここでの正規の LLM API 呼び出しに限る.
- API キー・本文をログに残さない（LLM02）. 失敗時も例外型名のみを記録する.
- LLM 出力は信用せず AnalysisResult（extra="forbid", importance 1-6）で検証し,
  範囲外・欠損・余計なキーは弾く（LLM05）.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.analysis.prompt import SYSTEM_INSTRUCTION, build_user_content
from app.analysis.stub import StubAnalyzer
from app.models import AnalysisResult, EmailMessage
from app.ports.analyzer import Analyzer

logger = logging.getLogger(__name__)

# 構造化出力は短い. 上限を控えめにしてコストを抑える.
_MAX_TOKENS = 1024

# AnalysisResult のうち LLM が出力するフィールドの JSON Schema（共通定義）.
# "analyzer" は呼び出し側で上書きするため含めない.
_RESPONSE_PROPERTIES: dict[str, Any] = {
    "importance": {"type": "integer", "minimum": 1, "maximum": 6},
    "task_weight": {"type": "string", "enum": ["light", "medium", "heavy"]},
    "request_type": {
        "type": "string",
        "enum": [
            "reply_required",
            "task_required",
            "review_required",
            "approval_required",
            "waiting_other",
            "info_only",
        ],
    },
    "is_promotional": {"type": "boolean"},
    "summary": {"type": "string"},
    "suggested_action": {"type": ["string", "null"]},
    "deadline": {"type": ["string", "null"]},
    "reason": {"type": "string"},
}

# OpenAI / Ollama（OpenAI 互換）向け: response_format = json_schema (strict).
_OPENAI_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "email_analysis",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": _RESPONSE_PROPERTIES,
            "required": list(_RESPONSE_PROPERTIES.keys()),
            "additionalProperties": False,
        },
    },
}

# Gemini 向け: response_schema（OpenAPI 風. type は大文字, nullable で表現）.
_GEMINI_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "importance": {"type": "INTEGER"},
        "task_weight": {"type": "STRING", "enum": ["light", "medium", "heavy"]},
        "request_type": {
            "type": "STRING",
            "enum": [
                "reply_required",
                "task_required",
                "review_required",
                "approval_required",
                "waiting_other",
                "info_only",
            ],
        },
        "is_promotional": {"type": "BOOLEAN"},
        "summary": {"type": "STRING"},
        "suggested_action": {"type": "STRING", "nullable": True},
        "deadline": {"type": "STRING", "nullable": True},
        "reason": {"type": "STRING"},
    },
    "required": [
        "importance",
        "task_weight",
        "request_type",
        "is_promotional",
        "summary",
        "reason",
    ],
}


class LLMAnalyzer:
    """Anthropic/OpenAI を用いた `Analyzer` 実装. 失敗時はスタブへフォールバック."""

    def __init__(
        self,
        *,
        provider: str,
        api_key: str,
        model: str,
        timeout_seconds: int,
        max_body_chars: int,
        client: Any | None = None,
        fallback: Analyzer | None = None,
        base_url: str | None = None,
    ) -> None:
        self.provider = provider
        self._api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_body_chars = max_body_chars
        self._base_url = base_url  # OpenAI 互換サーバ（Ollama 等）の base url
        self._client = client  # テストでモック注入 / None なら遅延生成
        self._fallback: Analyzer = fallback or StubAnalyzer()

    def analyze(self, email: EmailMessage) -> AnalysisResult:
        try:
            raw = self._call(email)
            data = self._parse(raw)
            data["analyzer"] = self.provider
            return AnalysisResult(**data)
        except Exception as exc:  # SDK 例外・timeout・JSON/スキーマ不正を一括で吸収
            logger.warning(
                "LLM 分析に失敗（provider=%s）, スタブへフォールバック: %s",
                self.provider,
                type(exc).__name__,
            )
            return self._fallback.analyze(email)

    def _call(self, email: EmailMessage) -> str:
        content = build_user_content(email, self.max_body_chars)
        if self.provider == "anthropic":
            return self._call_anthropic(content)
        if self.provider == "openai":
            return self._call_openai(content)
        if self.provider == "gemini":
            return self._call_gemini(content)
        if self.provider == "ollama":
            return self._call_ollama(content)
        raise ValueError(f"未対応の provider: {self.provider}")

    def _call_anthropic(self, content: str) -> str:
        client = self._client
        if client is None:
            import anthropic  # 遅延 import（未導入なら ImportError → フォールバック）

            client = anthropic.Anthropic(
                api_key=self._api_key, timeout=self.timeout_seconds
            )
        resp = client.messages.create(
            model=self.model,
            max_tokens=_MAX_TOKENS,
            system=SYSTEM_INSTRUCTION,
            messages=[{"role": "user", "content": content}],
        )
        return resp.content[0].text

    def _call_openai(self, content: str) -> str:
        client = self._client
        if client is None:
            import openai  # 遅延 import

            client = openai.OpenAI(api_key=self._api_key, timeout=self.timeout_seconds)
        resp = client.chat.completions.create(
            model=self.model,
            max_tokens=_MAX_TOKENS,
            response_format=_OPENAI_RESPONSE_FORMAT,  # JSON Schema 強制（出力は _parse で再検証）
            messages=[
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {"role": "user", "content": content},
            ],
        )
        return resp.choices[0].message.content

    def _call_ollama(self, content: str) -> str:
        # Ollama の OpenAI 互換エンドポイント（/v1）を openai SDK で叩く.
        # 別PCの自前サーバなので従量課金・レート制限なし. 本文は LAN 外に出ない.
        client = self._client
        if client is None:
            import openai  # 遅延 import

            client = openai.OpenAI(
                api_key=self._api_key or "ollama",
                base_url=self._base_url,
                timeout=self.timeout_seconds,
            )
        resp = client.chat.completions.create(
            model=self.model,
            max_tokens=_MAX_TOKENS,
            response_format=_OPENAI_RESPONSE_FORMAT,  # JSON Schema 強制（出力は _parse で再検証）
            messages=[
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {"role": "user", "content": content},
            ],
        )
        return resp.choices[0].message.content

    def _call_gemini(self, content: str) -> str:
        client = self._client
        if client is None:
            from google import genai  # 遅延 import（未導入なら ImportError → フォールバック）

            # timeout は http_options でミリ秒指定（SDK 仕様）.
            client = genai.Client(
                api_key=self._api_key,
                http_options={"timeout": self.timeout_seconds * 1000},
            )
        # response_mime_type + response_schema で JSON スキーマを強制する. それでも
        # 出力は下の _parse + AnalysisResult で再検証する（LLM05: 信用しない）.
        resp = client.models.generate_content(
            model=self.model,
            contents=content,
            config={
                "system_instruction": SYSTEM_INSTRUCTION,
                "max_output_tokens": _MAX_TOKENS,
                "response_mime_type": "application/json",
                "response_schema": _GEMINI_RESPONSE_SCHEMA,
            },
        )
        return resp.text

    @staticmethod
    def _parse(raw: str) -> dict[str, Any]:
        """応答テキストから JSON オブジェクトを取り出す.

        コードフェンスや前後の説明が混じっても, 最初の { から最後の } までを
        抜き出してパースする（堅牢化）. 取り出せなければ例外でフォールバックさせる.
        """
        if raw is None:
            raise ValueError("空の応答")
        text = raw.strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise ValueError("JSON オブジェクトが見つからない")
        parsed = json.loads(text[start : end + 1])
        if not isinstance(parsed, dict):
            raise ValueError("JSON オブジェクトではない")
        return parsed
