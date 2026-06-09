"""ポート（抽象境界）層.

ヘキサゴナル構成の port を Protocol で定義する. 各層の実装（adapter）は
ここで定義した契約だけに依存し, 互いの具象を知らない. これにより
スタブ↔実装の差し替えが Protocol 変更なしで済む.

- MessageSource : 受信・正規化層の出力口（Gmail 等 → EmailMessage）
- Analyzer      : LLM 分析層（EmailMessage → AnalysisResult）
- Repository    : 永続化層（MessageRecord の保存・問い合わせ・状態遷移）
- Notifier      : 通知層（重要メールの外部通知）
- errors        : 層をまたいで共有する例外
"""

from app.ports.analyzer import Analyzer
from app.ports.errors import ConflictError, NotFoundError, TransitionError
from app.ports.notifier import Notifier
from app.ports.repository import MessageQuery, Repository
from app.ports.source import MessageSource

__all__ = [
    "Analyzer",
    "ConflictError",
    "MessageQuery",
    "MessageSource",
    "NotFoundError",
    "Notifier",
    "Repository",
    "TransitionError",
]
