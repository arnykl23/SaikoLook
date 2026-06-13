"""取得→分析→採点→保存→通知のパイプライン.

IngestionService は AccountRepository からアカウントを取得し, プロバイダごとに
ソースを動的に構築してメールを取得する. 1 通の失敗で全体を落とさず, 個別に
握り込んでログへ残す（観測性）. 本文全文はログ・例外詳細に出さない（LLM02）.

分析（LLM）は 1 メールにつき原則 1 回だけ呼ぶ（従量課金の抑制）. ただし再利用する
のは「現行アナライザが出した結果」に限る: レート上限超過などで前回 stub へフォール
バックした結果は確定扱いにせず, 次サイクルで本来のアナライザに昇格させる（取り残し
防止）. 成功後は同一結果を再利用し再課金しない. 期限に依存する triage/urgency
スコアは純粋関数で安価なため, 毎サイクル now で再計算する.
"""

import logging
from datetime import datetime, timezone

import google.auth.exceptions
from app.adapters.sources.github_api import GithubApiSource
from app.adapters.sources.gmail_api import GmailApiSource
from app.adapters.sources.gmail_imap import GmailImapSource
from app.adapters.sources.slack_api import SlackApiSource
from app.config import Settings
from app.domain.triage import compute_triage_score, compute_urgency_score
from app.models import MessageRecord
from app.ports import Analyzer, Notifier, Repository
from app.ports.source import RemovalDetectingSource
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
        # テスト用のソース注入口. セットされていれば DB/env 由来の構築を完全に置き換える
        # （実 Gmail/Slack を叩かずオフライン e2e できるようにするため）.
        self._sources_override: list | None = None

    def _build_sources(self) -> list:
        """DB アカウントからソースを構築. なければ env 変数のフォールバックを試みる.

        戻り値: (source, acc_dict) のペアの list.
        acc_dict は list_for_ingest() の dict（id / provider / address / ... を含む）.
        source.address に頼らず acc["address"] を使うことで OAuth アカウント
        （GmailApiSource.address が "" を返す）でも account_address が正しく記録される.

        テスト用に _sources_override がセットされていれば DB/env 由来の構築を完全に
        置き換える（実 Gmail/Slack を叩かずオフライン e2e するため）. override も
        (source, acc_dict) ペアの list を返すこと.
        """
        if self._sources_override is not None:
            return self._sources_override
        accounts = self._account_repo.list_for_ingest()
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
                        acc,
                    ))
                else:
                    source_pairs.append((
                        GmailImapSource(
                            addr,
                            acc["credential"],
                            max_body_chars=self._settings.llm_max_body_chars,
                        ),
                        acc,
                    ))
            elif acc["provider"] == "slack":
                source_pairs.append((
                    SlackApiSource(
                        acc["credential"],
                        addr,
                        max_body_chars=self._settings.llm_max_body_chars,
                    ),
                    acc,
                ))
            elif acc["provider"] == "github":
                source_pairs.append((
                    GithubApiSource(
                        access_token=acc["access_token"],
                        address=addr,
                        account_id=acc["id"],
                        account_repo=self._account_repo,
                        max_body_chars=self._settings.llm_max_body_chars,
                    ),
                    acc,
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
                    {"id": "", "provider": "gmail", "address": env_addr},
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
        for source, acc in source_pairs:
            account_address = acc.get("address", "") if isinstance(acc, dict) else acc
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

        # 現行アナライザの識別ラベル（LLM は provider, それ以外は name, 既定 "stub"）.
        # このラベルと一致する保存済み結果だけを再利用する. 前回レート上限等で stub に
        # フォールバックした結果は一致しないため, 次サイクルで本来のアナライザに昇格する.
        expected_analyzer = (
            getattr(self._analyzer, "provider", None)
            or getattr(self._analyzer, "name", None)
            or "stub"
        )

        for email, source_address in email_source_pairs:
            message_id = MessageRecord.make_id(email.provider, email.id)
            try:
                existing = self._repo.get(message_id)
                # 分析は原則 1 回（従量課金の抑制）. ただし再利用は現行アナライザの結果に
                # 限り, 前回フォールバックした stub 等は再分析して昇格させる.
                # スコアは now 依存のため毎回ローカルで再計算する（無料）.
                if (
                    existing is not None
                    and existing.analysis is not None
                    and existing.analysis.analyzer == expected_analyzer
                ):
                    analysis = existing.analysis
                else:
                    analysis = self._analyzer.analyze(email)
                urgency = compute_urgency_score(analysis, now)
                score = compute_triage_score(analysis, now)
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

        if self._settings.sync_remote_changes:
            try:
                self._sync_remote_changes(source_pairs)
            except Exception:
                logger.exception("ingest: リモート削除追随で例外（全体は継続）")

        logger.info(
            "ingest 完了 fetched=%d inserted=%d notified=%d",
            fetched,
            inserted,
            notified,
        )
        return {"fetched": fetched, "inserted": inserted, "notified": notified}

    def _sync_remote_changes(self, source_account_pairs: list) -> None:
        """Gmail でのアーカイブ/削除を重要度しきい値以下に限り追随する（読み取り専用）."""
        threshold = self._settings.auto_archive_importance_threshold
        for source, acc in source_account_pairs:
            if not isinstance(source, RemovalDetectingSource):
                continue
            account_id = acc.get("id") if isinstance(acc, dict) else ""
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
            provider = acc.get("provider", "gmail") if isinstance(acc, dict) else "gmail"
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
