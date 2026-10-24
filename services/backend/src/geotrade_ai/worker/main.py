"""`backend worker`: APScheduler process running every Phase 1 job (P1-BE-19)."""

import logging
import signal
from datetime import UTC, datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from prometheus_client import start_http_server

from geotrade_ai.core.config import get_settings
from geotrade_ai.core.db import get_sessionmaker
from geotrade_ai.market_calendar import is_market_open, is_trading_day
from geotrade_ai.normalize import IST
from geotrade_ai.worker import alerts, jobs, pipeline, prices
from geotrade_ai.worker.http import Fetcher
from geotrade_ai.worker.ingest import poll_due_sources

log = logging.getLogger(__name__)


def main() -> None:
    s = get_settings()
    factory = get_sessionmaker()
    fetcher = Fetcher()
    start_http_server(s.worker_metrics_port)

    def poll_feeds() -> None:
        with factory() as session:
            poll_due_sources(session, fetcher)

    def pipeline_tick() -> None:
        pipeline.run_all(factory)
        with factory() as session:
            pipeline.update_backlog_gauge(session)

    def sync_intraday() -> None:
        if s.enable_prices and is_market_open(datetime.now(UTC)):
            with factory() as session:
                prices.sync(session, "5m", "1d", [prices.YFinanceProvider()])
                prices.sync(session, "1d", "5d")

    def sync_eod() -> None:
        if s.enable_prices and is_trading_day(datetime.now(IST).date()):
            with factory() as session:
                prices.sync(session, "1d", "5d")

    def alert_sweep() -> None:
        with factory() as session:
            alerts.sweep(session)

    def rescore() -> None:
        with factory() as session:
            jobs.rescore_fallbacks(session)

    sched = BlockingScheduler(
        timezone=IST, job_defaults={"max_instances": 1, "coalesce": True, "misfire_grace_time": 30}
    )
    sched.add_job(
        poll_feeds, "interval", seconds=max(s.feed_poll_seconds // 4, 10), jitter=3, id="poll_feeds"
    )
    sched.add_job(pipeline_tick, "interval", seconds=s.pipeline_tick_seconds, id="pipeline_tick")
    sched.add_job(
        sync_intraday, "cron", day_of_week="mon-fri", hour="9-15", minute="*/5", jitter=20, id="sync_intraday"
    )
    sched.add_job(sync_eod, "cron", day_of_week="mon-fri", hour=16, minute=0, jitter=60, id="sync_prices_eod")
    sched.add_job(rescore, "cron", hour=2, minute=0, id="rescore_fallbacks")
    sched.add_job(alert_sweep, "interval", seconds=60, jitter=5, id="alert_sweep")
    if s.enable_prices:  # fill candles on start so charts are not empty
        sched.add_job(sync_eod, id="sync_prices_startup")

    def stop(*_: object) -> None:
        log.info("worker stopping")
        sched.shutdown(wait=False)

    signal.signal(signal.SIGTERM, stop)
    log.info("worker started", extra={"extra": {"jobs": [j.id for j in sched.get_jobs()]}})
    try:
        sched.start()
    finally:
        fetcher.close()
