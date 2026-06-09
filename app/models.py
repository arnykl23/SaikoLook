"""層間の契約となる共通スキーマ.

取得元(Gmail/Outlook 等)の差を吸収する EmailMessage を中心に,
LLM 分析結果 AnalysisResult, 永続化単位 MessageRecord を定義する.
全層(取得・分析・状態管理・API・UI)はこれらの型だけを介してやり取りする.

不変条件:
- EmailMessage は破壊変更しない(任意フィールドの追加のみ)。GET /emails の形を保つ。
"""

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EmailMessage(BaseModel):
    """プロバイダ非依存のメール1通(取得・正規化層の出力)。"""

    id: str                       # 取得元の安定識別子(Gmail は IMAP UID)
    provider: str = "gmail"       # "gmail" | "outlook" など
    subject: str = ""
    sender: str = ""              # "Name <addr>"
    to: list[str] = []
    received_at: datetime | None = None
    snippet: str = ""             # 本文先頭のプレビュー
    is_unread: bool = False
    body_text: str | None = None  # LLM 入力用の本文(先頭のみ・任意追加フィールド)


class AnalysisResult(BaseModel):
    """LLM 分析層の出力。extra="forbid" で想定外キーを弾く(LLM05 対策)。"""

    model_config = ConfigDict(extra="forbid")

    importance: int = Field(ge=1, le=5)                       # 重要度 1-5
    needs_reply: bool = False                                 # 対応要否
    task_weight: Literal["light", "medium", "heavy"] = "light"
    category: str = "fyi"                                     # 分類ラベル
    summary: str = ""                                         # 要約
    suggested_action: str | None = None
    deadline: datetime | None = None
    reason: str = ""                                          # 判定理由(説明可能性)
    analyzer: str = "stub"                                    # どの実装が出したか


class MessageState(str, Enum):
    """対応状態の有限状態機械の状態。"""

    UNHANDLED = "unhandled"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    SNOOZED = "snoozed"
    DISMISSED = "dismissed"


class MessageRecord(BaseModel):
    """永続化の単位(メール本体＋分析＋状態)。message_id = f"{provider}:{id}"。"""

    message_id: str
    email: EmailMessage
    analysis: AnalysisResult | None = None
    state: MessageState = MessageState.UNHANDLED
    triage_score: float = 0.0     # 未対応検知スコア(未読×重要度×経過時間)
    version: int = 0              # 楽観ロック用
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @staticmethod
    def make_id(provider: str, raw_id: str) -> str:
        return f"{provider}:{raw_id}"
