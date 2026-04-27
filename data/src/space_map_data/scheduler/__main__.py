"""Long-running scheduler for space-map data refreshes.

Runs daily at DAILY_AT_UTC. On startup, runs immediately only if today's
scheduled time has already passed (otherwise it'll be picked up by the loop).
Logs go through the project's logging.toml so docker logs / Grafana see
everything.
"""

import logging
import logging.config
import signal
import sys
import time
import tomllib
from datetime import datetime, timedelta, timezone
from datetime import time as dtime

from space_map_data.download.common import ProviderResult, download
from space_map_data.scheduler.notify import notify_download_run
from space_map_data.utils.db import session_scope
from space_map_data.utils.paths import DATA_DIR

DAILY_AT_UTC = dtime(hour=12, minute=0, tzinfo=timezone.utc)
SOURCES: tuple[str, ...] = ("celestrak",)

with open(DATA_DIR / "logging.toml", "rb") as f:
    logging.config.dictConfig(tomllib.load(f))
logger = logging.getLogger("scheduler")


def seconds_until_next_run(now: datetime) -> float:
    today = now.replace(
        hour=DAILY_AT_UTC.hour, minute=DAILY_AT_UTC.minute, second=0, microsecond=0
    )
    target = today if today > now else today + timedelta(days=1)
    return (target - now).total_seconds()


def run_download() -> None:
    logger.info("Running download for sources=%s", ",".join(SOURCES))
    try:
        with session_scope():
            results = download(sources=list(SOURCES))
    except Exception as e:
        logger.exception("Download crashed before completing")
        notify_download_run(
            [ProviderResult("scheduler", ok=False, error=f"{type(e).__name__}: {e}")]
        )
        return
    logger.info("Download finished")
    notify_download_run(results)


def _stop(signum: int, _frame: object) -> None:
    logger.info("Received signal %d, exiting", signum)
    sys.exit(0)


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    logger.info(
        "Scheduler started; sources=%s; daily run at %02d:%02d UTC",
        ",".join(SOURCES),
        DAILY_AT_UTC.hour,
        DAILY_AT_UTC.minute,
    )

    now = datetime.now(timezone.utc)
    today_target = now.replace(
        hour=DAILY_AT_UTC.hour, minute=DAILY_AT_UTC.minute, second=0, microsecond=0
    )
    if now >= today_target:
        logger.info("Past today's scheduled time; running now")
        run_download()
    else:
        logger.info("Today's scheduled run is upcoming; skipping startup run")

    while True:
        now = datetime.now(timezone.utc)
        wait = seconds_until_next_run(now)
        next_run = now + timedelta(seconds=wait)
        logger.info("Next run at %s (in %.0fs)", next_run.isoformat(), wait)
        time.sleep(wait)
        run_download()


if __name__ == "__main__":
    main()
