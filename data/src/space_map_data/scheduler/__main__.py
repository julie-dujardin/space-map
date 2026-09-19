"""Long-running scheduler for space-map data refreshes.

Runs the ``JOBS`` table from ``scheduler.jobs``. On startup, daily jobs whose
slot has already passed today fire immediately; interval jobs always fire once
and then space their runs by the configured interval. Logs go through the
project's logging.toml so docker logs / Grafana see everything.
"""

import logging
import logging.config
import signal
import sys
import time
import tomllib
from datetime import datetime, timezone

from space_map_data.download.common import ProviderResult, download
from space_map_data.scheduler.jobs import JOBS, Job
from space_map_data.scheduler.notify import notify_download_run
from space_map_data.utils.db import session_scope
from space_map_data.utils.paths import DATA_DIR

with open(DATA_DIR / "logging.toml", "rb") as f:
    logging.config.dictConfig(tomllib.load(f))
logger = logging.getLogger("scheduler")


def run_job(job: Job) -> None:
    label = job.label()
    logger.info("Running download for sources=%s", label)
    try:
        with session_scope():
            results = download(sources=list(job.sources))
    except Exception as e:
        logger.exception("Download crashed before completing")
        notify_download_run(
            [ProviderResult(label, ok=False, error=f"{type(e).__name__}: {e}")]
        )
        return
    logger.info("Download finished for sources=%s", label)
    notify_download_run(results)


def _stop(signum: int, _frame: object) -> None:
    logger.info("Received signal %d, exiting", signum)
    sys.exit(0)


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    now = datetime.now(timezone.utc)
    for job in JOBS:
        job.init(now)
        logger.info(
            "Scheduled job sources=%s — %s; first run at %s",
            job.label(),
            job.schedule.describe(),
            job.next_run.isoformat(),
        )

    while True:
        now = datetime.now(timezone.utc)
        next_job = min(JOBS, key=lambda j: j.next_run)
        wait = (next_job.next_run - now).total_seconds()
        if wait > 0:
            logger.info(
                "Next run: sources=%s at %s (in %.0fs)",
                next_job.label(),
                next_job.next_run.isoformat(),
                wait,
            )
            time.sleep(wait)
        run_job(next_job)
        next_job.next_run = next_job.schedule.advance(datetime.now(timezone.utc))


if __name__ == "__main__":
    main()
