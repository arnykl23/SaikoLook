# Plan: Gmail リモート削除/アーカイブの追随同期（重要度3以下限定）

- 作成日: 2026-06-13
- 深度: Large
- 状態: done（2026-06-13 実装完了・187 tests passed）
- NEEDS CLARIFICATION 残数: 0

## ★ Goal / Why

ユーザーが Gmail 本体でメールを **アーカイブ／削除** した場合に，重要度（`importance`）が **3 以下** のものだけアプリ側へ自動追随させる．現状は一度取り込んだメールが Gmail 側の変化に関わらずアプリ内に残り続ける（取り込みっぱなし）ため，重要度の低い処理済みメールがダッシュボードに溜まる．これを解消し，ユーザーの Gmail 操作とダッシュボードの整合を取る．

操作の方向は **Gmail → アプリの一方向同期**（読み取りのみ）であり，アプリから Gmail への書き込みは一切行わない（`gmail.readonly` を死守）．

## ★ Non-goals（やらないこと）

- **アプリから Gmail を操作する書き込み**（アーカイブ／削除の送信）．読み取り専用スコープを破らない
- **重要度 4 以上の追随**．Gmail で消えてもアプリに残す（対応漏れ防止のため誤って消さない）
- **IMAP（アプリパスワード）版での追随同期**．IMAP では「アーカイブ」と「削除」を区別できない（どちらも INBOX から UID が消えるだけ）ため，ユーザー要件（削除＝物理削除／アーカイブ＝ソフト）を満たせない．本機能は **OAuth（Gmail API）アカウント限定**とし，IMAP アカウントでは同期処理を実行しない（データは一切変更しない＝最も安全側）．理由は Complexity Tracking 参照
- **重要度 4 以上が Gmail で消えたことの警告表示**．今回は残すだけ（将来検討）
- **取り込み窓の外にある古いメールの全件再走査**．History API の差分（カーソル）方式に限定する

## 現状分析（Phase 1 の蒸留結果）

### 関連ファイル

| パス | 役割 | 本計画での扱い |
|---|---|---|
| `app/ports/source.py` | `MessageSource` Protocol（`list_recent`/`close`） | 拡張（削除検知 Protocol 追加） |
| `app/ports/repository.py` | `Repository` Protocol | 拡張（`delete` 追加） |
| `app/repositories/sql_repository.py` | `SqlRepository`（Repository 実装） | `delete` 実装追加 |
| `app/repositories/orm.py` | `MessageRecordORM` / `AccountConfigORM` | `AccountConfigORM` に `last_history_id` 列追加 |
| `app/repositories/account_repository.py` | `AccountRepository`（アカウント設定永続化） | カーソル read/write 追加 |
| `app/adapters/sources/gmail_api.py` | `GmailApiSource`（OAuth・Gmail API v1） | `detect_changes` 実装追加 |
| `app/services/ingestion.py` | `IngestionService.run_once()`（取得→分析→保存→通知） | 同期ステップ追加・`_build_sources` 戻り変更 |
| `app/config.py` | `Settings`（pydantic-settings） | 設定 2 件追加 |
| `migrations/versions/` | Alembic マイグレーション | 列追加マイグレーション新規 |

### 既存の規約・前例（従うべきパターン）

- **重要度**: `AnalysisResult.importance`（`app/models.py:37`，`int`，`Field(ge=1, le=5)`）．DB では `analysis` JSON 列に格納され，専用の非正規化列は持たない．SQL 絞り込みは `func.json_extract(MessageRecordORM.analysis, "$.importance")` で行う前例が `sql_repository.py:28,162` にある
- **メッセージ識別**: PK は `message_id = f"{provider}:{raw_id}"`（`MessageRecord.make_id`，`models.py:73-75`）．Gmail API 版では `raw_id` = Gmail メッセージ ID（`gmail_api.py:112`）
- **ソフト削除の受け皿**: `is_archived`（`MessageRecordORM`，`orm.py:40`）が「メインフィードから隠す可視性フラグ」として既存．`set_archived(message_id, True)` で隠れ，`GET /messages?archived=true` で確認可（`sql_repository.py:180`）
- **OAuth アダプタ**: `GmailApiSource` は `account_id` と `account_repo` を保持し，トークン失効時に `account_repo.set_auth_status(account_id, "reauth_required")` を呼ぶ（`gmail_api.py:55-56`）．`list_recent` は `labelIds=["INBOX"]` で取得（`gmail_api.py:62`）
- **取得パイプライン**: `IngestionService._build_sources()` が `list_for_ingest()` の dict からアカウントごとに source を構築（`ingestion.py:41-92`）．`auth_type=="oauth"` で `GmailApiSource`，それ以外で `GmailImapSource`．`run_once()` は source ごとに `list_recent` → upsert → notify（`ingestion.py:94-170`）
- **Source 拡張の既定路線**: `source.py` の docstring に「baseline は `list_recent` のみで動く．増分同期は将来 `fetch_since` で足せる（今は必須にしない）」とある．削除検知は **optional 拡張**として足すのが既存方針に沿う
- **マイグレーション書式**: `migrations/versions/20260613_0007_add_oauth_columns.py` を雛形にする（`op.batch_alter_table` + `add_column`，`revision`/`down_revision` 連鎖）．現行 head は `0007_add_oauth_columns`
- **物理削除の前例**: `AccountRepository.delete`（`account_repository.py:140-148`）が `session.get → session.delete → commit`，戻り `bool` のパターン．`MessageRecord` には物理削除メソッドが**存在しない**（`Repository` ポート・`SqlRepository`・`StateService` いずれにも無い）

### 制約

- **読み取り専用**: `_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]`（`gmail_api.py:25`）を変更しない．History API（`users.history.list`）・`users.getProfile` は `gmail.readonly` で利用可
- **オフライン完結のテスト**: 既定はオフライン（`pytest -q` は実 Gmail を叩かない）．Gmail API 呼び出しはモックでテストする（`tests/test_gmail_api_source.py` が新規で既存）
- **OAuth 移行が並行進行中**: 本機能は OAuth（Gmail API）完了を前提に有効化する．OAuth 未完了でも IMAP 経路は壊さない（同期はスキップされるだけ）

## 設計（合意済みの決定）

### 決定 1: 同期方向は Gmail → アプリの一方向（書き込みなし）
- 採用: ユーザーが Gmail で行ったアーカイブ／削除を，アプリが読み取りで検知して追随する
- 棄却: アプリが Gmail へアーカイブ操作を書き込む案 — `gmail.modify` が必要になり，「送信・書込み権限は付けない・要求しない」という最優先ポリシー（CLAUDE.md・security.md）に違反する
- 根拠: ユーザー合意（2026-06-13，「操作の方向」質問で『ユーザーが Gmail で操作 → アプリが追随』を選択）

### 決定 2: 重要度 3 以下のみ追随し，アーカイブと削除を区別する
- 採用: `importance <= 3` のメッセージについて，Gmail でのアーカイブ → アプリで `is_archived=True`（ソフト・復元可），Gmail での削除 → アプリで物理削除（DB 行を DELETE）．`importance >= 4` は何もしない（残す）．`analysis` が `None`（重要度不明）も何もしない（安全側）
- 棄却: (a) 重要度に関わらず追随 — 対応漏れ防止の趣旨に反する．(b) 削除もソフト削除で統一 — ユーザーが「削除は完全削除でいい」と明示
- 根拠: ユーザー合意（2026-06-13，「高重要度の扱い」で『アプリに残す（追随しない）』，「消え方」で『アーカイブはアーカイブ行き，削除は完全削除』）

### 決定 3: 検知は Gmail History API（カーソル＝historyId 差分）
- 採用: `GmailApiSource.detect_changes(start_cursor)` を新設し，`users.history.list(startHistoryId=...)` で前回以降の差分を取得．`labelsRemoved` に `INBOX` → アーカイブ，`labelsAdded` に `TRASH` または `messagesDeleted` → 削除と判定．カーソル（`historyId`）は `account_configs.last_history_id` に保存
- 棄却: (a) IMAP UID 集合差分 — アーカイブ/削除を区別できず（決定2を満たせない），UID 集合と UIDVALIDITY の保存が必要で複雑（Complexity Tracking 参照）．(b) 取得窓の全件比較 — 取得窓（既定10件）の外の古いメールを検知できない構造的限界がある
- 根拠: 技術調査（History API は `gmail.readonly` で利用可・差分が軽量・アーカイブと削除を区別できる唯一の手段）

### 決定 4: 検知は optional 拡張 Protocol として足し，対応 source のみ実装
- 採用: `RemovalDetectingSource` Protocol（`detect_changes` を持つ）を `app/ports/source.py` に追加．`IngestionService` は `isinstance(source, RemovalDetectingSource)` で分岐し，持つ source（= `GmailApiSource`）だけ同期する．`GmailImapSource`・`SlackApiSource` は実装せず自然にスキップされる
- 棄却: `MessageSource` 本体に `detect_changes` を必須メソッドとして足す案 — 全 source（IMAP・Slack）に no-op 実装を強制し，「IMAP は非対応」という意図が型に表れない
- 根拠: `source.py` docstring の「baseline は `list_recent` のみ／増分同期は将来拡張」方針に沿う

### データ構造・インタフェース

```python
# app/ports/source.py（追加）
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

@dataclass(frozen=True)
class RemovedMessage:
    """受信トレイから消えたメッセージ1件と，その種別."""
    raw_id: str                          # 取得元の生 ID（make_id 前。Gmail はメッセージ ID）
    kind: Literal["archived", "deleted"] # archived=INBOX から外れた / deleted=削除

@runtime_checkable
class RemovalDetectingSource(Protocol):
    """受信トレイからの削除/アーカイブ差分を検知できる source（optional 拡張）."""

    def detect_changes(
        self, start_cursor: str | None
    ) -> tuple[list[RemovedMessage], str | None]:
        """前回カーソル以降に INBOX から消えたメッセージと，新しいカーソルを返す.

        - start_cursor=None は初回. 差分は空 list で返し, 現在カーソルだけ確立する.
        - 戻りカーソルが None の場合, 呼び出し側は保存をスキップする.
        - 読み取り専用（書き込みは行わない）.
        """
        ...
```

```python
# app/ports/repository.py（Repository Protocol に追加）
def delete(self, message_id: str) -> bool:
    """message_id の行を物理削除する. 削除できたら True, 対象が無ければ False."""
    ...
```

```python
# app/config.py（Settings に追加）
# === リモート削除/アーカイブ追随同期 ===
sync_remote_changes: bool = True            # 機能フラグ（OAuth 完了後に有効化）
auto_archive_importance_threshold: int = 3  # この値以下のみ追随（importance <= 3）
```

```python
# app/repositories/orm.py（AccountConfigORM に追加）
last_history_id: Mapped[str | None] = mapped_column(String, nullable=True)
```

## Complexity Tracking（複雑性の正当化台帳）

| 違反 | 正当化 |
|---|---|
| 新 Protocol `RemovalDetectingSource` の追加 | `MessageSource` 本体に足すと全 source に no-op を強制し「IMAP 非対応」が型に表れない．`source.py` docstring が optional 拡張を既定路線として明記しており，最小の抽象追加 |
| IMAP 版を本機能のスコープ外にする（前合意の「縮退＝アーカイブ」から変更） | 当初は「IMAP でも安全側でアーカイブ縮退」と合意したが，調査で (1) IMAP はアーカイブと削除を区別できず決定2（削除＝物理削除）を満たせない，(2) 縮退にも UID 集合＋UIDVALIDITY の永続化が必要で複雑，(3) OAuth が本命で移行進行中，が判明．スコープ外（同期スキップ＝データ無変更）は前合意より安全側．**ユーザーへ計画提示時に明示し承認を取る** |
| `IngestionService._build_sources` の戻り値を `(source, account_dict)` ペアに変更 | 同期に account_id とカーソルが必要．副次的に OAuth 版で `account_address` が空文字になる既存挙動（`GmailApiSource.address` が `""` を返す）も `acc["address"]` 採用で正される |

## ★ タスク分解

> 各タスクは文脈ゼロの実装者へ単体で渡せる粒度．[P] = 並列可能（ファイル所有が重ならない）．依存関係は各タスク冒頭に明記．

### Task 1: 設定フィールドを追加 [P]
- 依存: なし
- 対象: `app/config.py`（modify）
- 手順:
  1. `Settings` クラスの「=== 通知層 ===」節の直前（`scheduler_enabled` 群の後あたり）に新節を追加:
     ```python
     # === リモート削除/アーカイブ追随同期 ===
     sync_remote_changes: bool = True
     auto_archive_importance_threshold: int = 3
     ```
- 検証: `python -c "from app.config import Settings; s=Settings(); print(s.sync_remote_changes, s.auto_archive_importance_threshold)"` → 期待: `True 3`
- 完了条件: 既定値で起動でき，env（`SYNC_REMOTE_CHANGES`/`AUTO_ARCHIVE_IMPORTANCE_THRESHOLD`）で上書き可能
- commit: `feat: リモート削除追随の設定フラグとしきい値を追加`

### Task 2: 削除検知ポートを追加 [P]
- 依存: なし
- 対象: `app/ports/source.py`（modify）
- 手順:
  1. import を調整: 既存の `from typing import Protocol, runtime_checkable`（`source.py:11`）に `Literal` を足して `from typing import Literal, Protocol, runtime_checkable` にし，新たに `from dataclasses import dataclass` 行を追加する
  2. 「データ構造・インタフェース」節の `RemovedMessage` dataclass と `RemovalDetectingSource` Protocol をファイル末尾に追加（本文そのまま）
- 検証: `python -c "from app.ports.source import RemovedMessage, RemovalDetectingSource; r=RemovedMessage('1','deleted'); print(r.raw_id, r.kind)"` → 期待: `1 deleted`
- 完了条件: import エラーなし．`RemovalDetectingSource` が `runtime_checkable`
- commit: `feat: 受信トレイ削除検知の optional ポート RemovalDetectingSource を追加`

### Task 3: Repository に物理削除を追加 [P]
- 依存: なし
- 対象: `app/ports/repository.py`（modify），`app/repositories/sql_repository.py`（modify），`tests/test_sql_repository.py`（modify or create）
- 手順:
  1. `app/ports/repository.py` の `Repository` Protocol に「データ構造・インタフェース」節の `delete` シグネチャを追加（`list_providers` の後など）
  2. `app/repositories/sql_repository.py` の `SqlRepository` に実装を追加:
     ```python
     def delete(self, message_id: str) -> bool:
         """message_id の行を物理削除する. 削除できたら True, 無ければ False."""
         with self._session_factory() as session:
             orm = session.get(MessageRecordORM, message_id)
             if orm is None:
                 return False
             session.delete(orm)
             session.commit()
         return True
     ```
  3. `tests/test_sql_repository.py`（無ければ作成）に: (a) upsert 後に `delete(id)` で `True` が返り `get(id)` が `None` になる，(b) 存在しない id で `delete` が `False` を返す，の2ケース
- 検証: `pytest tests/test_sql_repository.py -q` → 期待: 追加2ケース含め pass
- 完了条件: `delete` が `Repository` ポートと `SqlRepository` 双方に存在し，テスト緑
- commit: `feat: SqlRepository に物理削除 delete を追加`

### Task 4: account_configs に last_history_id 列を追加 [P]
- 依存: なし
- 対象: `app/repositories/orm.py`（modify），`migrations/versions/20260613_0008_add_last_history_id.py`（create）
- 手順:
  1. `app/repositories/orm.py` の `AccountConfigORM` 末尾（`auth_status` の後）に追加:
     ```python
     last_history_id: Mapped[str | None] = mapped_column(String, nullable=True)
     ```
  2. `migrations/versions/20260613_0008_add_last_history_id.py` を新規作成（`0007` を雛形に）:
     ```python
     """account_configs に Gmail History API カーソル列を追加.

     Revision ID: 0008_add_last_history_id
     Revises: 0007_add_oauth_columns
     Create Date: 2026-06-13
     """
     from alembic import op
     import sqlalchemy as sa

     revision = "0008_add_last_history_id"
     down_revision = "0007_add_oauth_columns"
     branch_labels = None
     depends_on = None


     def upgrade() -> None:
         with op.batch_alter_table("account_configs") as batch_op:
             batch_op.add_column(sa.Column("last_history_id", sa.String(), nullable=True))


     def downgrade() -> None:
         with op.batch_alter_table("account_configs") as batch_op:
             batch_op.drop_column("last_history_id")
     ```
- 検証: `alembic upgrade head && alembic current`（`migrations/env.py:23` が `sqlalchemy.url` を `Settings.database_url` から設定するため CLI でそのまま動く）→ 期待: `current` が `0008_add_last_history_id (head)`．列確認（既定 `data/ReplyGuard.db` 前提）は `python -c "from app.repositories import db; from sqlalchemy import inspect; print('last_history_id' in {c['name'] for c in inspect(db.engine).get_columns('account_configs')})"` → 期待: `True`（起動時 `app/repositories/migrations.py:run_migrations` でも自動適用される．`DATABASE_URL` を差し替えている場合は同じ URL で確認すること）
- 完了条件: マイグレーション適用後 `account_configs.last_history_id` 列が存在し，downgrade で消える
- commit: `feat: account_configs に Gmail History カーソル列 last_history_id を追加`

### Task 5: AccountRepository にカーソル read/write を追加
- 依存: Task 4（列が存在すること）
- 対象: `app/repositories/account_repository.py`（modify），`tests/test_account_repository.py`（modify or create）
- 手順:
  1. `AccountRepository` に追加（`delete` の前後どこでも）:
     ```python
     def get_history_id(self, account_id: str) -> str | None:
         with self._session_factory() as session:
             row = session.get(AccountConfigORM, account_id)
             return row.last_history_id if row is not None else None

     def set_history_id(self, account_id: str, history_id: str) -> None:
         with self._session_factory() as session:
             row = session.get(AccountConfigORM, account_id)
             if row is None:
                 return
             row.last_history_id = history_id
             session.commit()
     ```
- 検証: `pytest tests/test_account_repository.py -q` → 期待: 「create_oauth → set_history_id → get_history_id が一致」「未存在 id で get は None」が pass
- 完了条件: 2 メソッドが動作しテスト緑
- commit: `feat: AccountRepository に History カーソルの読み書きを追加`

### Task 6: GmailApiSource.detect_changes を実装
- 依存: Task 2（`RemovedMessage` を import）
- 対象: `app/adapters/sources/gmail_api.py`（modify），`tests/test_gmail_api_source.py`（modify）
- 手順:
  1. import に `from googleapiclient.errors import HttpError` と `from app.ports.source import RemovedMessage` を追加
  2. `close` の前あたりに実装を追加:
     ```python
     def detect_changes(
         self, start_cursor: str | None
     ) -> tuple[list[RemovedMessage], str | None]:
         """前回 historyId 以降に INBOX から消えたメッセージと新カーソルを返す（読み取り専用）."""
         try:
             service = self._build_service()
         except google.auth.exceptions.RefreshError:
             logger.warning("Gmail OAuth token 失効 (account_id=%s)", self._account_id)
             self._account_repo.set_auth_status(self._account_id, "reauth_required")
             raise

         if start_cursor is None:
             # 初回: 現在の historyId を確立するだけ（差分なし）.
             profile = service.users().getProfile(userId="me").execute()
             hid = str(profile.get("historyId", "")) or None
             return [], hid

         archived_ids: set[str] = set()
         deleted_ids: set[str] = set()
         latest = start_cursor
         page_token = None
         try:
             while True:
                 resp = (
                     service.users().history().list(
                         userId="me",
                         startHistoryId=start_cursor,
                         historyTypes=["labelRemoved", "labelAdded", "messageDeleted"],
                         pageToken=page_token,
                     ).execute()
                 )
                 if resp.get("historyId"):
                     latest = str(resp["historyId"])
                 for h in resp.get("history", []):
                     for d in h.get("messagesDeleted", []):
                         deleted_ids.add(d["message"]["id"])
                     for la in h.get("labelsAdded", []):
                         if "TRASH" in la.get("labelIds", []):
                             deleted_ids.add(la["message"]["id"])
                     for lr in h.get("labelsRemoved", []):
                         if "INBOX" in lr.get("labelIds", []):
                             archived_ids.add(lr["message"]["id"])
                 page_token = resp.get("nextPageToken")
                 if not page_token:
                     break
         except HttpError as e:
             if getattr(e, "resp", None) is not None and e.resp.status == 404:
                 # startHistoryId が古すぎて無効 → 差分を諦め, 現在カーソルへリセット.
                 logger.warning(
                     "history startId 失効 (account_id=%s) — カーソル再確立", self._account_id
                 )
                 profile = service.users().getProfile(userId="me").execute()
                 return [], str(profile.get("historyId", "")) or None
             raise

         # 同一メッセージが両方に該当したら削除を優先.
         archived_ids -= deleted_ids
         removed = [RemovedMessage(gid, "deleted") for gid in sorted(deleted_ids)]
         removed += [RemovedMessage(gid, "archived") for gid in sorted(archived_ids)]
         return removed, latest
     ```
  3. `tests/test_gmail_api_source.py` にテスト追加（`service` をモックする．`_build_service` を monkeypatch するか，`googleapiclient` のモック層を使う）:
     - 初回（`start_cursor=None`）: `getProfile` が `{"historyId": "100"}` → 戻り `([], "100")`
     - 差分: `history.list` が `labelsRemoved INBOX` 1件・`labelsAdded TRASH` 1件・`messagesDeleted` 1件を返す → `deleted` 2件・`archived` 1件，カーソル更新
     - 削除優先: 同一 id が `labelsRemoved INBOX` と `labelsAdded TRASH` 両方 → その id は `deleted` のみ
     - 404（`HttpError` で `resp.status==404`）: `getProfile` で再取得し `([], 新カーソル)`
- 検証: `pytest tests/test_gmail_api_source.py -q` → 期待: 追加4ケース含め pass
- 完了条件: `isinstance(GmailApiSource(...), RemovalDetectingSource)` が `True`．スコープは `gmail.readonly` のまま（変更していない）
- commit: `feat: GmailApiSource に History API ベースの削除/アーカイブ検知を追加`

### Task 7: IngestionService に追随同期ステップを結線
- 依存: Task 1・2・3・5・6 すべて
- 対象: `app/services/ingestion.py`（modify），`tests/test_ingestion.py`（create — 現状存在しない）
- 手順:
  1. import に `from app.ports.source import RemovalDetectingSource` を追加
  2. `_build_sources` の戻り値を **`(source, account_dict)` のペアの list** へ変更:
     - 各 `sources.append(X)` を `sources.append((X, acc))` に変更
     - env フォールバックの append も `sources.append((GmailImapSource(...), {"id": "", "address": addr, "provider": "gmail"}))` のように最小の dict を付ける
  3. `run_once` の取得ループを `for source, acc in sources:` に変更し，`email_source_pairs.append((em, acc.get("address") or source.address))` に変更（OAuth 版で `account_address` が空になるのを防ぐ）
  4. upsert・notify の後に同期ステップを呼ぶ:
     ```python
     if self._settings.sync_remote_changes:
         try:
             self._sync_remote_changes(sources)
         except Exception:
             logger.exception("ingest: リモート削除追随で例外（全体は継続）")
     ```
  5. メソッドを追加:
     ```python
     def _sync_remote_changes(self, source_account_pairs: list) -> None:
         """Gmail でのアーカイブ/削除を重要度3以下に限り追随する（読み取り専用）."""
         threshold = self._settings.auto_archive_importance_threshold
         for source, acc in source_account_pairs:
             if not isinstance(source, RemovalDetectingSource):
                 continue
             account_id = acc.get("id")
             if not account_id:
                 continue
             try:
                 start = self._account_repo.get_history_id(account_id)
                 removed, new_cursor = source.detect_changes(start)
             except google.auth.exceptions.RefreshError:
                 continue  # 失効は detect_changes 側で auth_status を更新済み
             except Exception:
                 logger.exception("削除追随の検知に失敗（継続）")
                 continue
             provider = acc.get("provider", "gmail")
             for r in removed:
                 message_id = MessageRecord.make_id(provider, r.raw_id)
                 try:
                     rec = self._repo.get(message_id)
                     if rec is None or rec.analysis is None:
                         continue
                     if rec.analysis.importance > threshold:
                         continue  # 重要度が高いものは残す
                     if r.kind == "deleted":
                         self._repo.delete(message_id)
                     else:
                         self._repo.set_archived(message_id, True)
                 except Exception:
                     logger.exception("削除追随の適用に失敗 message_id=%s", message_id)
                     continue
             if new_cursor is not None:
                 self._account_repo.set_history_id(account_id, new_cursor)
     ```
  6. `tests/test_ingestion.py`: fake source（`detect_changes` を持ち `RemovalDetectingSource` を満たす）と fake repo/account_repo を使い:
     - importance=2 の `deleted` → `repo.delete` が呼ばれる
     - importance=2 の `archived` → `repo.set_archived(id, True)` が呼ばれる
     - importance=5 の `deleted`/`archived` → 何も呼ばれない（残す）
     - `analysis=None` の対象 → 何も呼ばれない
     - `detect_changes` を持たない source（IMAP/Slack 相当）→ スキップ
     - `sync_remote_changes=False` → `_sync_remote_changes` 自体を呼ばない
     - 同期後に `set_history_id` が新カーソルで呼ばれる
   - fake source のスタブ範囲: `_sync_remote_changes` を単体で叩くテストは `detect_changes` だけ持てば成立する（`RemovalDetectingSource` は `@runtime_checkable` でメソッド名の有無のみ判定）．`run_once` 全体を回すテストにする場合は `list_recent`/`close`/`address` も実装すること
- 検証: `pytest tests/test_ingestion.py -q` → 期待: 既存＋追加ケース pass．さらに `pytest -q` 全体（既存 105 件＋追加）が緑
- 完了条件: `_build_sources` 戻り変更の波及先は `run_once` 内のみ（`grep -rn "_build_sources" app/ tests/` で呼び出し元を確認．現状 `run_once` の1箇所のみ）．同期ステップが機能フラグで on/off できる．`pytest -q` 全体が緑（`_smoke_e2e.py` は E2E 検証の注意2の通り対象外）
- commit: `feat: 取り込み時に Gmail の削除/アーカイブを重要度3以下へ追随同期`

## ★ E2E 検証（全タスク完了後）

### オフライン（CI・実 Gmail 不要）
1. `pytest -q` → 期待: 全件 pass（既存 105 + 追加分）．オフライン回帰はこれに一本化する
2. **注意（既存負債）**: `tests/_smoke_e2e.py:41` の `client.app.state.ingestion._source = FakeSource()` は現行 `IngestionService`（`_source` 属性を持たず `_build_sources` で動的構築）と既に不整合で，本計画着手前から fake 注入が効かず失敗する．**本計画のスコープ外**とし，E2E のオフライン合格基準には含めない（直すなら別タスクで `account_repo` モック注入方式へ修正）．Task 7 の `_build_sources` 戻り変更はこの負債を悪化も改善もさせない

### 実 Gmail（OAuth 完了後・手動）
1. OAuth で Gmail アカウントを追加（アプリ UI のアカウント追加）
2. 一度取り込み（`POST /ingest` またはスケジューラ）→ 初回カーソルが `account_configs.last_history_id` に保存される（DB で確認）
3. Gmail 本体で **重要度3以下** とアプリ上で表示されているメールを 1 通 **アーカイブ**，別の 1 通を **ゴミ箱へ削除**
4. 再度取り込み → 期待:
   - アーカイブしたメールは `GET /messages`（メインフィード）から消え，`GET /messages?archived=true` に現れる
   - 削除したメールは DB から消え，どちらのビューにも現れない
5. Gmail 本体で **重要度4以上** のメールをアーカイブ/削除 → 再取り込み → 期待: アプリには残ったまま（メインフィードに表示）

## リスクとロールバック

- **リスク（誤削除）**: importance 判定を誤った重要メールを物理削除する恐れ → `importance <= 3` 限定＋`analysis=None` スキップで緩和．削除はゴミ箱移動（`TRASH` 追加）or 完全削除のみが対象で，ユーザーの明示操作が起点
- **リスク（カーソル失効）**: `startHistoryId` が古すぎる（通常 1 週間程度で失効）と 404 → その回の差分を取りこぼすがカーソルを現在値へリセットし次回から再開（データ破壊なし）
- **リスク（再分析でしきい値跨ぎ）**: 既存行の `analysis` は upsert で上書きされるため，再分析で importance が 4→3 に下がると追随対象に入る．意図通り（最新の重要度で判断）
- **ロールバック**: 機能は `sync_remote_changes=False`（env）で即時無効化できる．コードは Task 単位の commit で `git revert` 可能．DB 列追加（Task 4）は `alembic downgrade -1` で戻せる

## 実装メモ（実装中に追記）

> 計画との乖離・発見事項を実装者がここに記録する．乖離は黙って吸収せず必ず書く．

- Task 3 の対象を `test_sql_repository.py`（計画書）→ `test_repository.py`（実在ファイル）に修正．既存 SqlRepository テストと統合
- Task 7 `_build_sources` は計画書作成前の OAuth 作業で既に `(source, addr_str)` ペアに変更済みだった．今回 `(source, acc_dict)` ペアに格上げし，取得ループの `account_address` 取得も `acc.get("address")` に追従させた
- 全テスト 187 passed（既存 162 + 追加 25）
