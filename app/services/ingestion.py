"""取得→分析→採点→保存→通知のパイプライン.

IngestionService は AccountRepository からアカウントを取得し, プロバイダごとに
ソースを動的に構築してメールを取得する. 1 通の失敗で全体を落とさず, 個別に
握り込んでログへ残す（観測性）. 本文全文はログ・例外詳細に出さない（LLM02）.
"""

import logging
from datetime import datetime, timezone

import google.auth.exceptions
from app.adapters.sources.gmail_api import GmailApiSource
from app.adapters.sources.gmail_imap import GmailImapSource
from app.adapters.sources.slack_api import SlackApiSource
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
        # (source, account_address) ペアで返す．
        # source.address に頼らず acc["address"] を使うことで OAuth アカウント（address="" を返す）でも
        # account_address が正しく message_records に記録される．
        source_pairs: list[tuple] = []
        for acc in accounts:
            # auth_status が ok 以外（reauth_required / revoked）ならスキップ
            if acc.get("auth_status", "ok") not in ("ok", ""):
                logger.warning(
                    "アカウントスキップ (auth_status=%s, address=%s)",
                    acc.get("auth_status"), acc.get("address"),
                )
                continue
            addr = acc["address"]
            if acc["provider"] == "gmail":
                auth_type = acc.get("auth_type", "imap")
                if auth_type == "oauth":
                    source_pairs.append((
                        GmailApiSource(
                            refresh_token=acc["refresh_token"],
                            client_id=self._settings.gmail_oauth_client_id,
                            client_secret=self._settings.gmail_oauth_client_secret,
                            account_id=acc["id"],
                            account_repo=self._account_repo,
                            max_body_chars=self._settings.llm_max_body_chars,
                        ),
                        addr,
                    ))
                else:
                    source_pairs.append((
                        GmailImapSource(
                            addr,
                            acc["credential"],
                            max_body_chars=self._settings.llm_max_body_chars,
                        ),
                        addr,
                    ))
            elif acc["provider"] == "slack":
                source_pairs.append((
                    SlackApiSource(
                        acc["credential"],
                        addr,
                        max_body_chars=self._settings.llm_max_body_chars,
                    ),
                    addr,
                ))
            # 将来: Outlook 等を追加
        if not source_pairs:
            env_addr = self._settings.gmail_address
            pw = self._settings.gmail_app_password
            if env_addr and pw:
                source_pairs.append((
                    GmailImapSource(
                        env_addr, pw, max_body_chars=self._settings.llm_max_body_chars
                    ),
                    env_addr,
                ))
        return source_pairs

    def run_once(self) -> dict:
        """1 サイクル実行し件数を返す.

        返り値: ``{"fetched": n, "inserted": m, "notified": k}``.
        個別メールの失敗は握り込み, 全体を止めない.
        """
        now = datetime.now(timezone.utc)

        # 削除済みアカウントのメッセージを自動クリーンアップ
        valid_addresses = [acc["address"] for acc in self._account_repo.list_for_ingest()]
        cleaned = self._repo.delete_orphan_messages(valid_addresses)
        if cleaned:
            logger.info("ingest: 孤立メッセージ %d 件を自動削除", cleaned)

        source_pairs = self._build_sources()
        if not source_pairs:
            logger.info("ingest: アクティブなアカウントなし - スキップ")
            return {"fetched": 0, "inserted": 0, "notified": 0}

        # (email, account_address) のペアで収集する.
        email_source_pairs: list[tuple] = []
        for source, account_address in source_pairs:
            try:
                emails = source.list_recent(limit=self._settings.ingest_limit)
            except google.auth.exceptions.RefreshError:
                logger.warning("OAuth token 失効のためアカウントをスキップ（UI でリフレッシュ要）")
                continue
            except Exception:
                logger.exception("取得失敗（継続）")
                continue
            for em in emails:
                email_source_pairs.append((em, account_address))

        fetched = len(email_source_pairs)
        records: list[MessageRecord] = []
        is_new_by_id: dict[str, bool] = {}

        for email, source_address in email_source_pairs:
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
                    account_address=source_address,
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
