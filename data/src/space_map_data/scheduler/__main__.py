"""Long-running scheduler for space-map data refreshes.

Runs the download once at startup (cheap no-op if today is already done thanks
to per-provider metadata.json) and then daily at DAILY_AT_UTC. Logs go through
the project's logging.toml so docker logs / Grafana see everything.
"""

import logging
import logging.config
import signal
import sys
import time
import tomllib
from datetime import datetime, timedelta, timezone
from datetime import time as dtime

from space_map_data.download.common import download
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
            download(sources=list(SOURCES))
        logger.info("Download finished")
    except Exception:
        logger.exception("Download failed")


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
    run_download()

    while True:
        now = datetime.now(timezone.utc)
        wait = seconds_until_next_run(now)
        next_run = now + timedelta(seconds=wait)
        logger.info("Next run at %s (in %.0fs)", next_run.isoformat(), wait)
        time.sleep(wait)
        run_download()


if __name__ == "__main__":
    main()
