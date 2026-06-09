"""LLM 分析層. EmailMessage を入力に AnalysisResult を返す.

公開契約（他層はこの名前で import する）:
- StubAnalyzer:  ルールベースのオフライン分析器（PoC 既定）
- LLMAnalyzer:   Anthropic/OpenAI 実装（差し替え用・失敗時はスタブへフォールバック）
- build_analyzer(settings): 設定から Analyzer を選ぶファクトリ
"""

from app.analysis.factory import build_analyzer
from app.analysis.llm import LLMAnalyzer
from app.analysis.stub import StubAnalyzer

__all__ = ["StubAnalyzer", "LLMAnalyzer", "build_analyzer"]
