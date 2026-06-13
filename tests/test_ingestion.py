"""IngestionService のテスト.

- analyze-once（分析は原則1回・従量課金抑制）とフォールバック再分析
  （レート上限等で stub に落ちた結果を次サイクルで本来のアナライザへ昇格）を
  実 SqlRepository（in-memory）で検証する.
- _sync_remote_changes（リモート削除/アーカイブ追随）を MagicMock で検証する.

実 Gmail / LLM は叩かない（fake source・fake/mock repo・fake analyzer）.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.models import AnalysisResult, EmailMessage
from app.ports.source import RemovedMessage
from app.repositories import db
from app.repositories.sql_repository import SqlRepository
from app.services.ingestion import IngestionService
from tests.conftest import make_email, make_record


# ===========================================================================
# analyze-once / フォールバック再分析（実 SqlRepository を使用）
# ===========================================================================

ACCOUNT_ADDRESS = "me@example.com"


class CountingAnalyzer:
    """analyze 呼び出し回数を数えるフェイク analyzer（自分の name を analyzer に刻む）."""

    name = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def analyze(self, email: EmailMessage) -> AnalysisResult:
        self.calls += 1
        return AnalysisResult(
            importance=4,
            needs_reply=True,
            task_weight="medium",
            category="action_required",
            summary="要約",
            reason="テスト",
            analyzer=self.name,
        )


class FlakyGeminiAnalyzer:
    """provider=gemini を名乗るが, 1 回目だけ stub へフォールバックした体を返す.

    レート上限超過 → stub フォールバック → 次サイクルで昇格, の挙動を模す.
    """

    provider = "gemini"

    def __init__(self) -> None:
        self.calls = 0

    def analyze(self, email: EmailMessage) -> AnalysisResult:
        self.calls += 1
        label = "stub" if self.calls == 1 else "gemini"  # 初回のみ失敗→stub
        return AnalysisResult(
            importance=3, summary="x", reason="y", analyzer=label
        )


class FakeSource:
    """固定のメール群を返す読み取り専用フェイクソース."""

    def __init__(self, emails: list[EmailMessage], address: str = ACCOUNT_ADDRESS):
        self._emails = emails
        self.address = address

    def list_recent(self, limit: int = 10) -> list[EmailMessage]:
        return self._emails[:limit]

    def close(self) -> None:
        return None


class FakeAccountRepo:
    """run_once の孤立メッセージ掃除で使う list_for_ingest を満たす最小 fake."""

    def __init__(self, addresses: list[str]):
        self._addresses = list(addresses)

    def list_for_ingest(self) -> list[dict]:
        return [
            {"id": "", "provider": "gmail", "address": a, "auth_status": "ok"}
            for a in self._addresses
        ]


class NullNotifier:
    def notify(self, record, dedupe_key: str) -> bool:
        return False


def _make_ingest_service(
    source: FakeSource, analyzer, *, address: str = ACCOUNT_ADDRESS
) -> IngestionService:
    settings = SimpleNamespace(
        ingest_limit=10,
        notify_importance_threshold=4,
        llm_max_body_chars=4000,
        sync_remote_changes=False,
    )
    service = IngestionService(
        account_repo=FakeAccountRepo([address]),
        analyzer=analyzer,
        repo=SqlRepository(),
        notifier=NullNotifier(),
        settings=settings,
    )
    # 実ソース構築（IMAP/OAuth 接続）を避け, (source, acc) ペアに差し替える.
    acc = {"id": "", "provider": "gmail", "address": address}
    service._sources_override = [(source, acc)]
    return service


@pytest.fixture(autouse=True)
def _inmemory_db():
    db.configure_engine("sqlite:///:memory:")
    db.init_db()


def test_analyze_is_called_once_across_reingest():
    emails = [make_email("1"), make_email("2")]
    analyzer = CountingAnalyzer()
    service = _make_ingest_service(FakeSource(emails), analyzer)

    first = service.run_once()
    assert first["fetched"] == 2
    assert first["inserted"] == 2
    assert analyzer.calls == 2  # 新着 2 件を分析

    # 同じメールを再取得しても analyze は呼ばれない（保存済み結果を再利用）.
    second = service.run_once()
    assert second["fetched"] == 2
    assert second["inserted"] == 0
    assert analyzer.calls == 2  # ★増えない


def test_new_email_in_second_cycle_is_analyzed_only_once():
    analyzer = CountingAnalyzer()
    source = FakeSource([make_email("1")])
    service = _make_ingest_service(source, analyzer)

    service.run_once()
    assert analyzer.calls == 1

    # 2 通目が増えたサイクル: 既存 1 は再利用, 新着 1 のみ分析.
    source._emails = [make_email("1"), make_email("2")]
    service.run_once()
    assert analyzer.calls == 2


def test_reused_analysis_is_persisted():
    analyzer = CountingAnalyzer()
    service = _make_ingest_service(FakeSource([make_email("1")]), analyzer)
    service.run_once()
    service.run_once()

    record = service._repo.get("gmail:1")
    assert record is not None
    assert record.analysis is not None
    assert record.analysis.importance == 4


def test_fallback_stub_is_reanalyzed_until_provider_succeeds():
    """前回 stub へ落ちた結果は確定扱いにせず, 次サイクルで gemini へ昇格する."""
    analyzer = FlakyGeminiAnalyzer()
    service = _make_ingest_service(FakeSource([make_email("1")]), analyzer)

    # 1 サイクル目: gemini が失敗し stub へフォールバック.
    service.run_once()
    assert analyzer.calls == 1
    assert service._repo.get("gmail:1").analysis.analyzer == "stub"

    # 2 サイクル目: stub != gemini なので再分析 → 今度は成功して gemini に昇格.
    service.run_once()
    assert analyzer.calls == 2
    assert service._repo.get("gmail:1").analysis.analyzer == "gemini"

    # 3 サイクル目: gemini == gemini なので再利用（再課金しない）.
    service.run_once()
    assert analyzer.calls == 2


# ===========================================================================
# _sync_remote_changes（リモート削除/アーカイブ追随・MagicMock を使用）
# ===========================================================================

class FakeDetectingSource:
    """RemovalDetectingSource を満たす最小 fake."""

    def __init__(self, removed: list[RemovedMessage], new_cursor: str | None = "cur2"):
        self._removed = removed
        self._new_cursor = new_cursor

    def detect_changes(
        self, start_cursor: str | None
    ) -> tuple[list[RemovedMessage], str | None]:
        return self._removed, self._new_cursor

    # list_recent / close / address は _sync_remote_changes では不要
    # （run_once 全体を回す場合は追加が必要）


class FakeNonDetectingSource:
    """RemovalDetectingSource を持たない source（IMAP/Slack 相当）."""

    def list_recent(self, limit: int = 10):
        return []

    def close(self) -> None:
        pass

    @property
    def address(self) -> str:
        return "test@example.com"


def _make_service(
    *,
    sync: bool = True,
    threshold: int = 3,
    sources_with_accs: list | None = None,
) -> tuple[IngestionService, MagicMock, MagicMock]:
    """テスト用 IngestionService を生成. repo と account_repo の MagicMock を返す."""
    mock_repo = MagicMock()
    mock_account_repo = MagicMock()
    mock_analyzer = MagicMock()
    mock_notifier = MagicMock()
    mock_settings = MagicMock()
    mock_settings.sync_remote_changes = sync
    mock_settings.auto_archive_importance_threshold = threshold
    mock_settings.ingest_limit = 10
    mock_settings.notify_importance_threshold = 4

    svc = IngestionService(
        account_repo=mock_account_repo,
        analyzer=mock_analyzer,
        repo=mock_repo,
        notifier=mock_notifier,
        settings=mock_settings,
    )

    # _build_sources をモンキーパッチして sources_with_accs を返す
    if sources_with_accs is not None:
        svc._build_sources = lambda: sources_with_accs

    return svc, mock_repo, mock_account_repo


def test_sync_deletes_low_importance_deleted_message() -> None:
    """importance=2 の deleted → repo.delete が呼ばれる."""
    removed = [RemovedMessage("msg1", "deleted")]
    src = FakeDetectingSource(removed, new_cursor="cur2")
    acc = {"id": "acc1", "provider": "gmail"}

    svc, mock_repo, mock_account_repo = _make_service()
    mock_account_repo.get_history_id.return_value = "cur1"

    rec = make_record("msg1", analysis=AnalysisResult(importance=2))
    mock_repo.get.return_value = rec

    svc._sync_remote_changes([(src, acc)])

    mock_repo.delete.assert_called_once_with("gmail:msg1")
    mock_repo.set_archived.assert_not_called()
    mock_account_repo.set_history_id.assert_called_once_with("acc1", "cur2")


def test_sync_archives_low_importance_archived_message() -> None:
    """importance=2 の archived → repo.set_archived(id, True) が呼ばれる."""
    removed = [RemovedMessage("msg2", "archived")]
    src = FakeDetectingSource(removed, new_cursor="cur2")
    acc = {"id": "acc1", "provider": "gmail"}

    svc, mock_repo, mock_account_repo = _make_service()
    mock_account_repo.get_history_id.return_value = "cur1"

    rec = make_record("msg2", analysis=AnalysisResult(importance=3))
    mock_repo.get.return_value = rec

    svc._sync_remote_changes([(src, acc)])

    mock_repo.set_archived.assert_called_once_with("gmail:msg2", True)
    mock_repo.delete.assert_not_called()


def test_sync_skips_high_importance_deleted() -> None:
    """importance=5 の deleted → 何もしない（残す）."""
    removed = [RemovedMessage("msg3", "deleted")]
    src = FakeDetectingSource(removed)
    acc = {"id": "acc1", "provider": "gmail"}

    svc, mock_repo, mock_account_repo = _make_service()
    mock_account_repo.get_history_id.return_value = "cur1"

    rec = make_record("msg3", analysis=AnalysisResult(importance=5))
    mock_repo.get.return_value = rec

    svc._sync_remote_changes([(src, acc)])

    mock_repo.delete.assert_not_called()
    mock_repo.set_archived.assert_not_called()


def test_sync_skips_high_importance_archived() -> None:
    """importance=4 の archived → 何もしない."""
    removed = [RemovedMessage("msg4", "archived")]
    src = FakeDetectingSource(removed)
    acc = {"id": "acc1", "provider": "gmail"}

    svc, mock_repo, mock_account_repo = _make_service()
    mock_account_repo.get_history_id.return_value = "cur1"

    rec = make_record("msg4", analysis=AnalysisResult(importance=4))
    mock_repo.get.return_value = rec

    svc._sync_remote_changes([(src, acc)])

    mock_repo.delete.assert_not_called()
    mock_repo.set_archived.assert_not_called()


def test_sync_skips_message_with_no_analysis() -> None:
    """analysis=None の場合 → 何もしない（安全側）."""
    removed = [RemovedMessage("msg5", "deleted")]
    src = FakeDetectingSource(removed)
    acc = {"id": "acc1", "provider": "gmail"}

    svc, mock_repo, mock_account_repo = _make_service()
    mock_account_repo.get_history_id.return_value = "cur1"

    rec = make_record("msg5", analysis=None)
    mock_repo.get.return_value = rec

    svc._sync_remote_changes([(src, acc)])

    mock_repo.delete.assert_not_called()
    mock_repo.set_archived.assert_not_called()


def test_sync_skips_message_not_in_db() -> None:
    """DB にない message_id（get=None）は何もしない."""
    removed = [RemovedMessage("msg_gone", "deleted")]
    src = FakeDetectingSource(removed)
    acc = {"id": "acc1", "provider": "gmail"}

    svc, mock_repo, mock_account_repo = _make_service()
    mock_account_repo.get_history_id.return_value = "cur1"
    mock_repo.get.return_value = None

    svc._sync_remote_changes([(src, acc)])

    mock_repo.delete.assert_not_called()
    mock_repo.set_archived.assert_not_called()


def test_sync_skips_non_detecting_source() -> None:
    """RemovalDetectingSource を持たない source（IMAP/Slack）はスキップ."""
    src = FakeNonDetectingSource()
    acc = {"id": "acc1", "provider": "gmail"}

    svc, mock_repo, mock_account_repo = _make_service()

    svc._sync_remote_changes([(src, acc)])

    mock_repo.delete.assert_not_called()
    mock_repo.set_archived.assert_not_called()
    mock_account_repo.get_history_id.assert_not_called()


def test_sync_skips_when_flag_disabled() -> None:
    """sync_remote_changes=False のとき _sync_remote_changes は呼ばれない（run_once 経由）."""
    removed = [RemovedMessage("msg_x", "deleted")]
    src = FakeDetectingSource(removed)
    acc = {"id": "acc1", "provider": "gmail", "address": "x@example.com",
           "credential": "", "auth_type": "oauth", "refresh_token": "rt",
           "auth_status": "ok"}

    svc, mock_repo, mock_account_repo = _make_service(sync=False, sources_with_accs=[(src, acc)])
    mock_account_repo.get_history_id.return_value = "cur1"
    mock_repo.get.return_value = None

    # _sync_remote_changes をモニター
    call_count = []
    original = svc._sync_remote_changes
    def counting_sync(pairs):
        call_count.append(1)
        return original(pairs)
    svc._sync_remote_changes = counting_sync

    svc.run_once()

    assert len(call_count) == 0, "_sync_remote_changes should not be called when flag is off"


def test_sync_saves_new_cursor() -> None:
    """detect_changes が返した new_cursor が set_history_id に渡される."""
    removed = []
    src = FakeDetectingSource(removed, new_cursor="cursor_new")
    acc = {"id": "acc2", "provider": "gmail"}

    svc, mock_repo, mock_account_repo = _make_service()
    mock_account_repo.get_history_id.return_value = "cursor_old"

    svc._sync_remote_changes([(src, acc)])

    mock_account_repo.set_history_id.assert_called_once_with("acc2", "cursor_new")


def test_sync_does_not_save_none_cursor() -> None:
    """detect_changes が None カーソルを返したら set_history_id は呼ばれない."""
    removed = []
    src = FakeDetectingSource(removed, new_cursor=None)
    acc = {"id": "acc2", "provider": "gmail"}

    svc, mock_repo, mock_account_repo = _make_service()
    mock_account_repo.get_history_id.return_value = None

    svc._sync_remote_changes([(src, acc)])

    mock_account_repo.set_history_id.assert_not_called()
