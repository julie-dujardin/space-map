"""CLI entry point for: space-map-tracking

A long-running poller rather than a download provider: the DSN feed keeps no
history and has to be sampled minute-by-minute to catch short passes, and the
scheduler notifies on every run that did work, which at this cadence would be
several hundred pushes a day.

Each task carries its own interval, so the minute-resolution DSN feed and the
monthly ESTRACK figures share one process without either dictating the other's
cadence. Publishing is one more task rather than a job of its own: it reads the
stores this process owns, and writing the file is local.
"""

import argparse
import logging
import logging.config
import signal
import sys
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

import httpx

from space_map_data.tracking import publish
from space_map_data.tracking.dsn.feed import (
    FeedError,
    SpacecraftInfo,
    fetch_config,
    fetch_feed,
)
from space_map_data.tracking.dsn.store import ActivityStore
from space_map_data.tracking.dsnbot import repo as dsnbot
from space_map_data.tracking.dsnbot.store import BotStore
from space_map_data.tracking.estrack import api as estrack
from space_map_data.tracking.estrack.store import EstrackStore
from space_map_data.utils.paths import CONFIG_FILE, DATA_DIR

logger = logging.getLogger("tracking")

DSN_POLL = timedelta(minutes=1)
DSN_CONFIG_REFRESH = timedelta(hours=1)
# The live flags have read false for every mission since we started watching,
# so this is a standing check for them coming back, not a data source. Five
# minutes is frequent enough to notice within a pass and gentle on a backend
# that publishes nothing else in real time.
ESTRACK_LIVE_POLL = timedelta(minutes=5)
# Monthly aggregates; four times a day is enough to watch the current month
# fill in and to catch the rollover that drops the oldest month upstream.
ESTRACK_STATS_POLL = timedelta(hours=6)
# The bot's repository is cumulative and 8 MB, and it holds history rather
# than news — we watch the same feed ourselves, a minute at a time.
BOT_REFRESH = timedelta(hours=24)
# The published file only changes when a probe is heard from, which is far
# rarer than a poll; rebuilding it is a local write, so this is cheap.
PUBLISH = timedelta(minutes=5)
# Consecutive failures back off to this, so an upstream outage costs a request
# every few minutes instead of every minute.
MAX_BACKOFF = timedelta(minutes=10)


def _stop(signum: int, _frame: object) -> None:
    logger.info("Received signal %d, exiting", signum)
    sys.exit(0)


@dataclass
class Task:
    """One periodic job, with its own failure backoff."""

    name: str
    interval: timedelta
    run: Callable[[], None]
    next_run: float = 0.0
    failures: int = 0
    # Set once a task has failed enough to be worth saying out loud only when
    # it recovers, rather than on every retry.
    complained: bool = field(default=False)

    def due(self, now: float) -> bool:
        return now >= self.next_run

    def execute(self, now: float) -> None:
        try:
            self.run()
        except Exception as e:
            self.failures += 1
            delay = min(
                self.interval.total_seconds() * 2**self.failures,
                MAX_BACKOFF.total_seconds(),
            )
            self.next_run = now + delay
            # A FeedError is the upstream misbehaving and says so in one line;
            # anything else is ours and deserves the traceback.
            if isinstance(e, (FeedError, estrack.EstrackError, dsnbot.BotError)):
                logger.warning(
                    "%s failed (%d in a row): %s", self.name, self.failures, e
                )
            else:
                logger.exception("%s crashed (%d in a row)", self.name, self.failures)
            self.complained = True
            return
        if self.complained:
            logger.info("%s recovered after %d failure(s)", self.name, self.failures)
            self.complained = False
        self.failures = 0
        self.next_run = now + self.interval.total_seconds()


class Poller:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.dsn_store = ActivityStore()
        self.estrack_store = EstrackStore()
        self.bot_store = BotStore()
        self.dsn_config: dict[str, SpacecraftInfo] = {}
        self.estrack_names: dict[str, str] = {}

    def publish(self) -> None:
        publish.write(publish.build(self.dsn_store, self.estrack_store, self.bot_store))

    def bot_refresh(self) -> None:
        posts = dsnbot.parse_posts(dsnbot.fetch_repo(self.client))
        new = self.bot_store.record(posts, self.dsn_config)
        logger.info(
            "DSN bot: %d post(s), %d code(s)%s",
            len(posts),
            len(self.bot_store.codes),
            f", new: {', '.join(new)}" if new else "",
        )

    def dsn_poll(self) -> None:
        snapshot = fetch_feed(self.client)
        new = self.dsn_store.record(snapshot, self.dsn_config)
        logger.info(
            "DSN: %d dish(es), %d spacecraft tracked%s",
            len(snapshot.dishes),
            len(snapshot.active_targets()),
            f", new: {', '.join(new)}" if new else "",
        )

    def dsn_config_refresh(self) -> None:
        raw, self.dsn_config = fetch_config(self.client)
        self.dsn_store.store_config(raw)
        logger.info("DSN spacecraft map: %d code(s)", len(self.dsn_config))

    def estrack_live_poll(self) -> None:
        missions, stations = estrack.fetch_live(self.client)
        live = self.estrack_store.record_live(missions, stations)
        if live:
            logger.info("ESTRACK live: %s", ", ".join(live))

    def estrack_stats_refresh(self) -> None:
        missions, stations = estrack.fetch_reference(self.client)
        self.estrack_names = self.estrack_store.store_reference(missions, stations)
        months = estrack.fetch_months(self.client)
        new: list[str] = []
        for month in months:
            stats = estrack.fetch_month(self.client, month)
            new += self.estrack_store.record_month(stats, self.estrack_names)
        active = {
            code: state.last_active_month
            for code, state in self.estrack_store.missions.items()
            if state.last_active_month
        }
        logger.info(
            "ESTRACK: %d month(s) %s, %d/%d mission(s) with volume%s",
            len(months),
            "/".join(months),
            len(active),
            len(self.estrack_store.missions),
            f", new: {', '.join(new)}" if new else "",
        )


def run(once: bool, dsn_interval: timedelta) -> None:
    with open(CONFIG_FILE, "rb") as f:
        user_agent = tomllib.load(f)["download"]["user_agent"]

    with httpx.Client(
        headers={"User-Agent": user_agent}, timeout=30.0, follow_redirects=True
    ) as client:
        poller = Poller(client)
        tasks = [
            # Ordered so the DSN map and the ESTRACK reference data are in hand
            # before the first poll that needs them to name anything.
            Task("dsn-config", DSN_CONFIG_REFRESH, poller.dsn_config_refresh),
            Task("estrack-stats", ESTRACK_STATS_POLL, poller.estrack_stats_refresh),
            Task("dsn-bot", BOT_REFRESH, poller.bot_refresh),
            Task("dsn-poll", dsn_interval, poller.dsn_poll),
            Task("estrack-live", ESTRACK_LIVE_POLL, poller.estrack_live_poll),
            Task("publish", PUBLISH, poller.publish),
        ]
        while True:
            now = time.monotonic()
            for task in tasks:
                if task.due(now):
                    task.execute(time.monotonic())
            if once:
                return
            time.sleep(min(max(t.next_run - time.monotonic(), 0) for t in tasks))


def cli():
    parser = argparse.ArgumentParser(
        description="Track spacecraft activity across the DSN and ESTRACK"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    poll = commands.add_parser("run", help="Poll both networks until stopped")
    poll.add_argument(
        "--dsn-interval",
        type=float,
        default=DSN_POLL.total_seconds(),
        metavar="SECONDS",
        help=f"Seconds between DSN polls (default: {DSN_POLL.total_seconds():.0f})",
    )
    poll.add_argument(
        "--once",
        action="store_true",
        help="Run every task once and exit (for checking output)",
    )

    commands.add_parser("publish", help="Rebuild the published activity file and exit")

    args = parser.parse_args()

    with open(DATA_DIR / "logging.toml", "rb") as f:
        logging.config.dictConfig(tomllib.load(f))

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    if args.command == "publish":
        publish.write(publish.build(ActivityStore(), EstrackStore(), BotStore()))
    else:
        run(args.once, timedelta(seconds=args.dsn_interval))


if __name__ == "__main__":
    cli()
