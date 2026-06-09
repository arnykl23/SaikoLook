"""取得→分析→採点→保存→通知のパイプライン.

IngestionService は AccountRepository からアカウントを取得し, プロバイダごとに
ソースを動的に構築してメールを取得する. 1 通の失敗で全体を落とさず, 個別に
握り込んでログへ残す（観測性）. 本文全文はログ・例外詳細に出さない（LLM02）.
"""

import logging
from datetime import datetime, timezone

from app.adapters.sources.gmail_imap import GmailImapSource
from app.config import Settings
from app.domain.triage import compute_triage_score, compute_urgency_score
from app.models import MessageRecord
from app.ports import Analyzer, Notifier, Repository
from app.repositories.account_repository import AccountRepository

logger = logging.getLogger(__name__)


class IngestionService:
    """取得・分析・採点・保存・通知を 1 サイクルで回すサービス."""

    def __init__(
        self,
        account_repo: AccountRepository,
        analyzer: Analyzer,
        repo: Repository,
        notifier: Notifier,
        settings: Settings,
    ) -> None:
        self._account_repo = account_repo
        self._analyzer = analyzer
        self._repo = repo
        self._notifier = notifier
        self._settings = settings

    def _build_sources(self) -> list:
        """DB アカウントからソースを構築. なければ env 変数のフォールバックを試みる."""
        accounts = self._account_repo.list_for_ingest()
        sources = []
        for acc in accounts:
            if acc["provider"] == "gmail":
                sources.append(
                    GmailImapSource(
                        acc["address"],
                        acc["credential"],
                        max_body_chars=self._settings.llm_max_body_chars,
                    )
                )
            # 将来: Slack, Outlook 等を追加
        if not sources:
            addr = self._settings.gmail_address
            pw = self._settings.gmail_app_password
            if addr and pw:
                sources.append(
                    GmailImapSource(
                        addr, pw, max_body_chars=self._settings.llm_max_body_chars
                    )
                )
        return sources

    def run_once(self) -> dict:
        """1 サイクル実行し件数を返す.

        返り値: ``{"fetched": n, "inserted": m, "notified": k}``.
        個別メールの失敗は握り込み, 全体を止めない.
        """
        now = datetime.now(timezone.utc)

        sources = self._build_sources()
        if not sources:
            logger.info("ingest: アクティブなアカウントなし - スキップ")
            return {"fetched": 0, "inserted": 0, "notified": 0}

        all_emails = []
        for source in sources:
            try:
                all_emails.extend(source.list_recent(self._settings.ingest_limit))
            except Exception:
                logger.exception("ingest: ソースの取得に失敗")

        fetched = len(all_emails)
        records: list[MessageRecord] = []
        is_new_by_id: dict[str, bool] = {}

        for email in all_emails:
            message_id = MessageRecord.make_id(email.provider, email.id)
            try:
                analysis = self._analyzer.analyze(email)
                urgency = compute_urgency_score(analysis, now)
                score = compute_triage_score(analysis, now)
                existing = self._repo.get(message_id)
                record = MessageRecord(
                    message_id=message_id,
                    email=email,
                    analysis=analysis,
                    triage_score=score,
                    urgency_score=urgency,
                )
                records.append(record)
                is_new_by_id[message_id] = existing is None
            except Exception:
                logger.exception("ingest: 分析・採点に失敗 message_id=%s", message_id)
                continue

        inserted = self._repo.upsert_messages(records) if records else 0

        notified = 0
        threshold = self._settings.notify_importance_threshold
        for record in records:
            try:
                is_new = is_new_by_id.get(record.message_id, False)
                importance = record.analysis.importance if record.analysis else 0
                if is_new or importance >= threshold:
                    if self._notifier.notify(record, dedupe_key=record.message_id):
                        notified += 1
            except Exception:
                logger.exception(
                    "ingest: 通知に失敗 message_id=%s", record.message_id
                )
                continue

        logger.info(
            "ingest 完了 fetched=%d inserted=%d notified=%d",
            fetched,
            inserted,
            notified,
        )
        return {"fetched": fetched, "inserted": inserted, "notified": notified}
