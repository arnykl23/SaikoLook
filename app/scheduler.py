"""取り込みスケジューラ（APScheduler BackgroundScheduler）.

scheduler_enabled が真のとき, ingest_interval_seconds ごとに
IngestionService.run_once を回す. lifespan の起動で start, 終了で shutdown
する. ジョブ内の例外はアプリを落とさずログに残す.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import Settings
from app.services.ingestion import IngestionService

logger = logging.getLogger(__name__)


def _safe_run(ingestion: IngestionService) -> None:
    try:
        ingestion.run_once()
    except Exception:
        logger.exception("scheduler: run_once が失敗")


def start_scheduler(
    ingestion: IngestionService, settings: Settings
) -> BackgroundScheduler:
    """周期取り込みジョブを登録して開始する."""
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _safe_run,
        trigger="interval",
        seconds=settings.ingest_interval_seconds,
        args=[ingestion],
        id="ingest",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info("scheduler 開始 interval=%ds", settings.ingest_interval_seconds)
    return scheduler
