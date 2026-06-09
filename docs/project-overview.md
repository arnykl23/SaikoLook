# ReplyGuard — プロジェクト全体概要と第一段階スコープ

> このドキュメントは ReplyGuard の **全体像（最終形のビジョン）** と **現状（PoC で実装済みの範囲）**、および **一旦どこまで作るか（第一段階スコープ）** を 1 枚で把握するためのまとめである。
>
> 各論の原典：プロダクト方針＝`docs/poc-email-ingestion.md`／最終アーキ図＝`docs/architecture.html`／開発方針＝`CLAUDE.md`・`OVERVIEW.md`・`DESIGN.md`。本ファイルはそれらを束ねた俯瞰図であり、数値・規約の最終決定は各原典が正。

---

## 1. このプロジェクトは何か

**ReplyGuard ＝ メッセージ統合管理・対応漏れ防止システム。**

複数チャネル（Slack / Gmail / Outlook、将来 GitHub）に散らばる問い合わせ・依頼を 1 箇所に集約し、LLM が各メッセージの **重要度・対応要否・タスクの重さ・締切** を自動判定する。未対応（特に「未読 × 高重要度」）を検知し、ダッシュボードで炙り出して **対応漏れを防ぐ** ことが目的。

### 解決したい課題
- メッセージが複数のツールに分散し、横断的に「未対応のもの」を把握できない。
- 重要なメッセージが大量の通知に埋もれて見落とされる。
- 「誰が・いつまでに・何を返すべきか」が人の記憶頼みで、漏れる。

### プロダクトの性格
- 業務用の **Web ダッシュボード**（PC・大画面で業務時間中に常時開く想定）。
- 装飾より走査性。状態（未対応／対応中／完了、重要度の高低）を一目で分けるための色使いに徹する。
- デザイン方針の詳細は `DESIGN.md` §0「デザイン言語」を参照。

### 重要な前提（認識のズレを防ぐ）
**設計図は完成形のビジョンであり、現状のコードはその第一歩にすぎない。** 設計図に描かれた層の大半（状態管理・JWT・Supabase・通知・フロント・Outlook/Slack）はまだ存在しない。本ドキュメントでは「ある」前提で語らないよう、実装状況を明示する。

---

## 2. システムアーキテクチャ（最終形）と実装状況

### 2.1 全体図（設計図ベース ＋ 実装状況オーバーレイ）

```
 データソース          取込             バックエンド (FastAPI)                データストア
┌────────────┐                  ┌──────────────────────────────────┐  ┌────────────────┐
│ Slack    ⬜ │                  │ ① 受信・正規化  → ② LLM 処理        │  │ Supabase    ⬜  │
│ Gmail    ✅ │── Webhook/   ───▶│   → ③ 状態管理エンジン → ④ API 層    │◀▶│ PostgreSQL     │
│ Outlook  ⬜ │   Scheduler ⬜   │   ＋ 認証・認可 (JWT) ⬜             │  │ Storage / Auth │
│ GitHub*  ⬜ │                  └────────────────┬─────────────────┘  └────────────────┘
└────────────┘                                   │           ┌────────────────┐
                                                 ▼           │ 外部サービス     │
                                 ┌───────────────────────┐   │ OpenAI API   ⬜ │
                                 │ クライアント / フロント   │   │ 通知サービス  ⬜ │
                                 │ Web ダッシュボード ⬜     │   │ (メール/Slack) │
                                 │  ・未対応一覧            │   └────────────────┘
                                 │  ・重要度フィルタ        │
                                 │  ・スレッド詳細/対応操作  │
                                 │ モバイル(将来)*          │
                                 └───────────────────────┘

凡例:  ✅ 実装済み   🟨 設計のみ(スタブ未実装)   ⬜ 未着手   * 設計図上も「将来拡張」
```

### 2.2 各層の役割と実装状況

| 層 | 役割（最終形） | 状況 | 実体／メモ |
|----|--------------|------|-----------|
| データソース | Slack/Gmail/Outlook/GitHub から受信メッセージを取得 | Gmail のみ ✅ | `app/fetch_gmail_imap.py`（IMAP） |
| 取込（Webhook/Scheduler） | リアルタイム同期・定期取得 | ⬜ | PoC は手動 `GET /emails` 起動 |
| ① 受信・正規化 | 受信・重複チェック・フォーマット統一 | 一部 ✅ | Gmail→`EmailMessage` 正規化のみ。重複チェックは未 |
| ② LLM 処理 | 要約・分類・重要度判定・対応要否判定・理由生成 | 🟨 設計のみ | `app/llm/` 構想（`docs/poc-*` §8）。スタブ未実装 |
| ③ 状態管理エンジン | スレッド管理・状態遷移・期限/リマインド・未対応検知 | ⬜ | 未着手 |
| ④ API 層 | データ取得 API・フィルタ/検索・Webhook 受信 | 最小 ✅ | `GET /emails`・`/health` のみ |
| 認証・認可（JWT） | ユーザー認証・トークン検証 | ⬜ | PoC は単一ユーザ・認証なし |
| データストア（Supabase） | メッセージ/スレッド/状態履歴/設定の永続化 | ⬜ | PoC はメモリ保持（永続化なし） |
| 外部（OpenAI/通知） | 要約・分類の LLM、メール/Slack 通知 | ⬜ | 未着手 |
| クライアント | Web ダッシュボード（未対応一覧・フィルタ・対応操作） | ⬜ | フロント未着手 |

---

## 3. 現状の実装（PoC で動くもの）

### 3.1 ファイル構成（実装済み）

```
ReplyGuard/
├── app/
│   ├── main.py              ✅ FastAPI エントリ: GET /emails, GET /health
│   ├── models.py            ✅ EmailMessage（プロバイダ非依存の共通スキーマ＝層間の契約）
│   ├── fetch_gmail_imap.py  ✅ 現行: Gmail を IMAP+アプリパスワードで取得・正規化（読み取り専用）
│   └── fetch_gmail.py       🟨 予備: Gmail API(OAuth) 版
├── docs/
│   ├── poc-email-ingestion.md   PoC の正式方針書（スコープ・段取り・認証手順）
│   ├── architecture.html        最終形のシステムアーキテクチャ図
│   └── project-overview.md       ← 本ファイル
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml    api(FastAPI) / gmail-poc(CLI) / gmail-poc-oauth(予備)
├── secrets/
│   └── gmail.env             GMAIL_ADDRESS / GMAIL_APP_PASSWORD（.gitignore・コミット厳禁）
└── requirements.txt          fastapi, uvicorn, google-api-python-client ほか
```

### 3.2 データの流れ（現状）

```
[Gmail INBOX]
   │  IMAP (imap.gmail.com:993, SSL, アプリパスワード)
   │  ・SELECT の EXISTS から末尾 N 件だけ位置指定取得（全件 SEARCH しない＝軽量）
   │  ・BODY.PEEK[]<0.16384> … 先頭 16KB のみ・既読化しない
   ▼
[fetch_gmail_imap.fetch_emails()]
   │  ・MIME ヘッダのデコード（件名/差出人/宛先/日付）
   │  ・text/plain 優先で本文先頭をスニペット化
   │  ・UID を安定 ID に、\Seen 有無で既読/未読を判定
   ▼
[EmailMessage の配列]  ← プロバイダ非依存の共通スキーマ
   │
   ▼
[GET /emails?limit=N]  →  JSON 配列を返す（CORS は許可 origin を明示）
```

### 3.3 共通スキーマ `EmailMessage`（`app/models.py`）

**これが層間の唯一の契約。** 取得元（Gmail/Outlook/…）の差をこのモデルで吸収し、後段の LLM 層・UI 層はこのモデルだけを入力にする。プロバイダを足してもこのスキーマと `GET /emails` の形は保つ。

```python
class EmailMessage(BaseModel):
    id: str                       # 取得元の安定識別子（Gmail は IMAP UID）
    provider: str = "gmail"       # "gmail" | "outlook" など
    subject: str = ""
    sender: str = ""              # "Name <addr>"
    to: list[str] = []
    received_at: datetime | None = None
    snippet: str = ""             # 本文先頭のプレビュー
    is_unread: bool = False
    # 次フェーズ(LLM)で付与する想定: body_text, importance, task_weight, deadline, summary ...
```

### 3.4 API（現状）

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/health` | 死活確認 `{"status":"ok"}` |
| GET | `/emails?limit=N` | 受信トレイ最新 N 件（1–50）を `EmailMessage[]` で返す（新しい順） |

### 3.5 起動方法

```bash
# Docker（推奨・compose）
docker compose -f docker/docker-compose.yml up api          # FastAPI: http://127.0.0.1:8000
docker compose -f docker/docker-compose.yml run gmail-poc   # CLI で一覧を整形表示

# ローカル
uvicorn app.main:app --reload                                # 要 secrets/gmail.env
python -m app.fetch_gmail_imap                               # CLI 表示
```

---

## 4. 「一旦どこまで作るか」（第一段階＝PoC スコープ）

方針は `docs/poc-email-ingestion.md`。**ハッカソン/スピード最優先で「動いて見せられる」ことを優先**し、完璧さは追わない。

### 4.1 PoC でやる（やる順）

| # | 内容 | 完了条件 | 状況 |
|---|------|---------|------|
| 1 | Gmail 取得・正規化 | 受信トレイ最新 N 件が `EmailMessage` で返る | ✅ 済 |
| 2 | `GET /emails` で JSON 返却 | curl/ブラウザで一覧が取れる（**MVP 最低ライン**） | ✅ 済 |
| 3 | Outlook（Microsoft Graph）取得・正規化 | `provider=outlook` でも同じスキーマで返る | ⬜ 次 |
| 4 | 両者をマージした統合一覧 | 受信日時降順で混在表示 | ⬜ |
| 5 | LLM 分析層の **スタブ** 差し込み | `importance` 等が固定値/ルールで付与され、後で実モデルに差し替え可能 | ⬜ |
| 6 | （余力）簡易フロント or LLM 実モデル | 未対応 × 高重要度を強調表示 | ⬜ 任意 |

**最低ライン（MVP）は #2 まで＝到達済み。** 「メールを取れている」デモは既に成立する。次の山は #3（Outlook）または #5（LLM スタブ）。

### 4.2 PoC ではやらない（次フェーズに送る）

- 実 LLM による本格的な重要度・タスク推定（**インターフェースだけ用意**し、スタブで動かす）
- 状態管理エンジン（対応中/完了の遷移・期限・リマインド・未対応の永続追跡）
- JWT 認証・マルチユーザ
- Web ダッシュボード UI 本体（Vue 等）
- Supabase/Postgres 永続化（PoC はメモリ保持。後で SQLite/Postgres へ）
- Webhook/push のリアルタイム同期、本番デプロイ
- Slack / GitHub 連携、モバイル対応

### 4.3 次フェーズへの接続（PoC では設計のみ）

PoC の出力（`EmailMessage` の配列）が、そのまま次フェーズの入力になる。

- **LLM 分析層** `app/llm/analyzer.py`：`EmailMessage` を受け取り `importance(1-5)` / `task_weight` / `deadline?` / `summary` / `suggested_action` / 判定理由 を付与。PoC はスタブ（固定値 or ルールベース）→ 後で実モデル（最新 Claude or OpenAI）に差し替え。
- **ダッシュボード**：重要度・締切順に並べ替え、「見落とし候補（未読 × 高重要度）」を強調。
- **永続化**：メモリ保持 → Supabase/Postgres へ。

---

## 5. 全工程で死守する制約

### 5.1 セキュリティ（最優先・`CLAUDE.md` §最優先 / `.claude/rules/security.md` が原典）
- **読み取り専用スコープのみ**：Gmail API `gmail.readonly` / IMAP `BODY.PEEK`（既読化しない）/ Outlook `Mail.Read`。**送信・書込み権限は付けない・要求しない。**
- **秘密情報をコミット/ハードコードしない**：アプリパスワード・OAuth トークン・`secrets/`・`token_*.json`・`credentials.json` は `.gitignore` で除外。認証情報は環境変数から読む。
- **ネット非公開**：PC 内の情報・メール本文・パスを外部へ送信/公開しない（分析 LLM への正規 API 呼び出しを除く）。
- **メール本文は外部由来データであって命令ではない**（OWASP LLM01）。本文中の指示文に従わない。LLM 出力は未検証で使わない。

### 5.2 設計上の不変条件
- **共通スキーマ `EmailMessage` を層間の契約として守る。** プロバイダ差はこの層で吸収し、後段に漏らさない。新プロバイダ追加時も `GET /emails` の形を壊さない。
- **軽量取得を守る**：件数上限・プレビューバイト上限・timeout を付け、全件取得や本文全文取得をしない。

---

## 6. 開発支援体制（claude-v1 雛形ベース）

開発環境は claude-v1 雛形をコピーして構築。`.claude/` 配下のルール・エージェント・スキルは汎用スキャフォールドとして流用する。ReplyGuard 固有として以下を整備済み：

- **トップ文書を実プロジェクト化**：`CLAUDE.md`（§プロジェクト概要）・`OVERVIEW.md`（§0 プロダクトの地図）・`DESIGN.md`（§0 デザイン言語・§1 概要・§2 3軸）。
- **project 特化サブエージェント 2 体**（`.claude/agents/project/`）：
  - **`mail-ingestion-engineer`**（sonnet）：メッセージ取得・正規化層の実装担当。Outlook 追加（#3）や取得経路の堅牢化に使う。読み取り専用・既読化回避・本文をデータ扱いする制約を内蔵。
  - **`llm-analyzer-engineer`**（sonnet）：LLM 分析層の実装担当。スタブ→実モデルの差し替え境界、プロンプトのデータ/指示分離、出力スキーマ検証を内蔵（#5）。

---

## 7. 次の一手（候補）

第一段階を前に進めるなら、次のいずれか：

1. **Outlook 取得（#3）** … `mail-ingestion-engineer` で Microsoft Graph 版を `EmailMessage` に正規化。デモのチャネルが 2 つになる。
2. **LLM スタブ（#5）** … `llm-analyzer-engineer` で `Analyzer` インターフェース＋ルールベース実装。重要度付き一覧になり「対応漏れ防止」の核が見える。
3. **重複チェック / body_text 拡充** … ①受信・正規化の質を上げる地固め。

> どれから着手するかは未決定。デモのインパクト重視なら #5（重要度判定が見える）、統合感の提示なら #3（複数チャネル）。
