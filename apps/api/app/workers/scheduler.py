"""APScheduler process with a PostgreSQL job store (persistent job state across restarts).

Schedule (IST): forecasts and public board every 3 h; decisions at 05:15, 11:15, 17:15, 23:15 (after
forecast refreshes) plus on field change; alert dispatch every 5 min; AGMARKNET daily at 19:30 (prices
publish after 18:00, PRD §8.4); model registry sync daily at 03:00.
"""
from __future__ import annotations

import logging
import signal
import sys

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import get_settings
from app.workers.jobs import run_named

log = logging.getLogger("fasalalert.scheduler")
TZ = "Asia/Kolkata"


def build() -> BlockingScheduler:
    s = get_settings()
    sched = BlockingScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=s.database_url, tablename="apscheduler_jobs")},
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 900}, timezone=TZ)
    add = lambda name, trigger: sched.add_job(run_named, trigger, args=[name], id=name, replace_existing=True)
    add("refresh_forecasts", CronTrigger(hour="*/3", minute=5, timezone=TZ))
    add("public_board", CronTrigger(hour="*/3", minute=10, timezone=TZ))
    add("recompute_decisions", CronTrigger(hour="5,11,17,23", minute=15, timezone=TZ))
    add("dispatch_alerts", IntervalTrigger(minutes=5, timezone=TZ))
    add("market_ingest", CronTrigger(hour=19, minute=30, timezone=TZ))
    add("sync_registry", CronTrigger(hour=3, minute=0, timezone=TZ))
    add("train_prices", CronTrigger(day_of_week="sun", hour=2, minute=0, timezone=TZ))  # PRD §9.2: weekly retrain
    return sched


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    s = get_settings()
    s.validate_for_startup()
    if not s.scheduler_enabled:
        log.info("SCHEDULER_ENABLED=false; exiting")
        return
    if len(sys.argv) > 2 and sys.argv[1] == "run":
        print(run_named(sys.argv[2]))  # one-off: python -m app.workers.scheduler run public_board
        return
    sched = build()
    signal.signal(signal.SIGTERM, lambda *_: sched.shutdown(wait=False))
    log.info("scheduler starting with %d jobs", len(sched.get_jobs()))
    sched.start()


if __name__ == "__main__":
    main()
