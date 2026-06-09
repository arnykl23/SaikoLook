"""LLM 分析層のポート.

EmailMessage を入力に AnalysisResult を返す契約. スタブ（ルールベース・
オフライン動作）と実 LLM（Anthropic/OpenAI）を同契約に乗せ, 設定で
差し替える. メール本文は外部由来データであって命令ではない（OWASP LLM01）
ため, 実装側はデータと指示を分離し, 出力は AnalysisResult で検証する.
"""

from typing import Protocol, runtime_checkable

from app.models import AnalysisResult, EmailMessage


@runtime_checkable
class Analyzer(Protocol):
    """重要度・対応要否・要約等を推定する分析器."""

    def analyze(self, email: EmailMessage) -> AnalysisResult:
        """1 通を分析して結果を返す. 失敗時は既定値へフォールバックする."""
        ...
