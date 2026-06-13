# 分析層（`app/analysis/`）— `AnalysisResult` スキーマ仕様

取得層が返した `EmailMessage` を受け取り、`AnalysisResult` を返す層。実装は
`StubAnalyzer`（ルールベース・オフライン）と `LLMAnalyzer`（Anthropic /
OpenAI / Gemini / Ollama）の2系統で、どちらも `app/ports/analyzer.py` の
`Analyzer` プロトコルに従う。

## `AnalysisResult`（`app/models.py`）

```python
class AnalysisResult(BaseModel):
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
```

| フィールド | 型 | 既定値 | 意味 |
|---|---|---|---|
| `importance` | `int` (1-6) | — | 重要度。6 が最重要。`domain/triage.py` の `triage_score` 計算に使う |
| `task_weight` | `"light" \| "medium" \| "heavy"` | `"light"` | 対応にかかる手間の見積もり |
| `request_type` | `RequestType`（6値、下記） | `"info_only"` | 対応区分（ファクト） |
| `is_promotional` | `bool` | `False` | 宣伝・広告・メルマガ等の自動配信か |
| `summary` | `str` | `""` | 日本語の短い要約（1〜2文） |
| `suggested_action` | `str \| None` | `None` | 推奨アクション。無ければ `null` |
| `deadline` | `datetime \| None` | `None` | 締切（読み取れなければ `null`）。`urgency_score` 計算に使う |
| `reason` | `str` | `""` | 判定理由（説明可能性） |
| `analyzer` | `str` | `"stub"` | どの実装が出したか（`stub` / `anthropic` / `openai` / `gemini` / `ollama`） |

`extra="forbid"` のため、ここに無いキーを含む応答は検証エラーとなり
`StubAnalyzer` へフォールバックする（LLM05: LLM 出力を信用しない）。

### `RequestType`（対応区分）

| 値 | 意味 |
|---|---|
| `reply_required` | 返信が必要 |
| `task_required` | 返信以外の作業・タスクが必要 |
| `review_required` | 内容の確認・レビューが必要 |
| `approval_required` | 承認・決裁が必要 |
| `waiting_other` | 他者対応待ち・自分のアクションは不要 |
| `info_only` | 情報共有のみ・対応不要 |

### 設計上のメモ（重複フィールドを置いていない理由）

- 「要返信か」は `request_type == "reply_required"` で判定する（`needs_reply` 相当のフィールドは持たない）。
- 「締切があるか」は `deadline is not None` で判定する（`has_deadline` 相当のフィールドは持たない）。
- 「自分宛か」は概ね `request_type` で表現される（`is_direct` 相当のフィールドは持たない）。
- `status`（対応中/完了等）は `domain/fsm.py` の `MessageState` が単一の真実source。`AnalysisResult` には持たせない。
- `urgency` / `confidence` / `owner` は YAGNI として採用しない。緊急度は `domain/triage.py` の `urgency_score`（`deadline` 由来）で算出する。

## プロンプト（`prompt.py`）

`SYSTEM_INSTRUCTION` で出力 JSON スキーマを明示し、メール本文・件名・差出人は
`<email_data>` デリミタ内の「データ」として与え、その中の指示に従わないことを
明記する（OWASP LLM01 対策）。本文は `max_body_chars` で切り詰める。

## ネイティブ構造化出力（`llm.py`）

プロバイダ側のスキーマ強制機能で `AnalysisResult` 相当の JSON 出力を補助する。
ただし最終的な検証は常に `AnalysisResult(**data)` で行う（LLM05: プロバイダの
スキーマ強制を信用しても、Pydantic 検証は省略しない）。

| プロバイダ | 方式 | 定義 |
|---|---|---|
| OpenAI / Ollama | `response_format: {"type": "json_schema", "json_schema": {"strict": true, ...}}`（JSON Schema, `additionalProperties: false`, 全フィールド `required`） | `_OPENAI_RESPONSE_FORMAT`（`_RESPONSE_PROPERTIES` を共有） |
| Gemini | `response_schema`（OpenAPI 風. 型は大文字 `OBJECT`/`STRING`/`INTEGER`/`BOOLEAN`、任意項目は `nullable: true`） | `_GEMINI_RESPONSE_SCHEMA` |
| Anthropic | ネイティブスキーマ強制なし。プロンプト指示 + `AnalysisResult` 検証のみ | — |

`_RESPONSE_PROPERTIES` が共通の JSON Schema プロパティ定義（OpenAI/Ollama 向け）。
スキーマを変更する場合は `_RESPONSE_PROPERTIES` と `_GEMINI_RESPONSE_SCHEMA` の
両方、および `SYSTEM_INSTRUCTION` のスキーマ説明を合わせて更新する。

## フォールバック・分析ポリシー

- SDK 呼び出し失敗・タイムアウト・JSON パース失敗・スキーマ不正・余計なキーは
  すべて例外として捕捉し、`StubAnalyzer` の結果へフォールバックする
  （例外メッセージにはクラス名のみ記録し、本文・APIキーは出さない＝LLM02）。
- 分析は1メールにつき原則1回（`IngestionService` が管理）。前回 stub
  フォールバックした結果のみ次サイクルで再分析し昇格させる。

## スキーマ変更時の注意

`analysis` カラムは JSON blob（`sa.JSON`）のため列定義の Alembic マイグレーション
は不要だが、`extra="forbid"` のフィールドを削除・リネームする場合は既存レコードの
JSON から旧キーを取り除くデータマイグレーションが必要（例:
`migrations/versions/20260614_0009_drop_analysis_category.py`,
`20260614_0010_drop_analysis_redundant_flags.py`）。
