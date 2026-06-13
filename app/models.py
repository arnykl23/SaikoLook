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

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    is_spam: bool = False          # 取得元プロバイダが迷惑メールに分類していたか(任意追加フィールド)


# 対応区分（LLM が抽出するファクト）.
# reply_required   : 返信が必要
# task_required    : 返信以外の作業・タスクが必要
# review_required  : 内容の確認・レビューが必要
# approval_required: 承認・決裁が必要
# waiting_other    : 他者対応待ち・自分のアクションは不要
# info_only        : 情報共有のみ・対応不要
RequestType = Literal[
    "reply_required",
    "task_required",
    "review_required",
    "approval_required",
    "waiting_other",
    "info_only",
]


class AnalysisResult(BaseModel):
    """LLM 分析層の出力。extra="forbid" で想定外キーを弾く(LLM05 対策)。"""

    model_config = ConfigDict(extra="forbid")

    importance: int = Field(ge=1, le=6)                       # 重要度 1-6
    task_weight: Literal["light", "medium", "heavy"] = "light"
    request_type: RequestType = "info_only"                   # 対応区分
    is_promotional: bool = False                              # 宣伝・広告・メルマガ等か
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
    urgency_score: float = 0.0    # 期限緊急度スコア(deadline 近接度)
    account_address: str = ""     # 受信アカウントのメールアドレス
    is_archived: bool = False     # メインフィードから隠す可視性フラグ（状態とは独立）
    version: int = 0              # 楽観ロック用
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @staticmethod
    def make_id(provider: str, raw_id: str) -> str:
        return f"{provider}:{raw_id}"


_SUPPORTED_PROVIDERS = {"gmail", "slack"}


class AccountConfig(BaseModel):
    """アカウント設定（レスポンス用: 認証情報を含まない）."""

    id: str
    provider: str
    label: str
    address: str = ""
    created_at: datetime | None = None


class AccountConfigCreate(BaseModel):
    """アカウント追加リクエスト. credential はレスポンスには返さない."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    label: str
    address: str
    credential: str  # アプリパスワード等（保存後は API から取得不可）

    @field_validator("provider")
    @classmethod
    def _validate_provider(cls, v: str) -> str:
        if v not in _SUPPORTED_PROVIDERS:
            raise ValueError(f"未対応のプロバイダ: {v}（対応: {_SUPPORTED_PROVIDERS}）")
        return v

    @field_validator("address")
    @classmethod
    def _strip_address(cls, v: str) -> str:
        return v.strip()

    @field_validator("credential")
    @classmethod
    def _normalize_credential(cls, v: str) -> str:
        # Google のアプリパスワードは「xxxx xxxx xxxx xxxx」形式で表示されるため
        # コピペでスペースが混入しやすい. 全スペースを除去して正規化する.
        return v.replace(" ", "").strip()
