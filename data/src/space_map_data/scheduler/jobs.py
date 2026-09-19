"""The scheduler's job table: which sources refresh together, and when.

Each job pairs a set of sources with a schedule (daily-at-UTC or fixed
interval). Providers carry their own freshness window and skip until it
lapses, so a daily pass over a monthly catalogue costs nothing.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from datetime import time as dtime

from space_map_data.constants.providers import PROVIDERS


@dataclass
class DailyAt:
    """Fire once a day at a fixed UTC time."""

    at: dtime

    def initial_next(self, now: datetime) -> datetime:
        target = now.replace(
            hour=self.at.hour, minute=self.at.minute, second=0, microsecond=0
        )
        # Past today's slot → run immediately on startup.
        return now if target <= now else target

    def advance(self, after: datetime) -> datetime:
        next_target = after.replace(
            hour=self.at.hour, minute=self.at.minute, second=0, microsecond=0
        )
        if next_target <= after:
            next_target += timedelta(days=1)
        return next_target

    def describe(self) -> str:
        return f"daily at {self.at.hour:02d}:{self.at.minute:02d} UTC"

    @property
    def period(self) -> timedelta:
        return timedelta(days=1)


@dataclass
class Every:
    """Fire on startup, then every ``interval``."""

    interval: timedelta

    def initial_next(self, now: datetime) -> datetime:
        return now

    def advance(self, after: datetime) -> datetime:
        return after + self.interval

    def describe(self) -> str:
        return f"every {self.interval}"

    @property
    def period(self) -> timedelta:
        return self.interval


Schedule = DailyAt | Every


@dataclass
class Job:
    name: str
    sources: tuple[str, ...]
    schedule: Schedule
    next_run: datetime = field(init=False)

    def init(self, now: datetime) -> None:
        self.next_run = self.schedule.initial_next(now)

    def label(self) -> str:
        return self.name


# Every source in ALL_SOURCES belongs to exactly one job — a provider that
# nobody schedules silently rots, which is what this table exists to prevent.
# Grouping is by what the data is, and each group runs often enough that its
# slowest member can expire: providers carry their own freshness window and
# skip until it lapses, so a daily pass over a monthly catalogue costs nothing.
JOBS: list[Job] = [
    Job(
        name="celestrak",
        sources=(PROVIDERS.CELESTRAK,),
        schedule=DailyAt(dtime(hour=12, minute=0)),
    ),
    # Space-Track GP fetch — kept off the top/bottom of the hour per their API
    # guidelines (they explicitly reject :00/:30 for hourly element queries).
    Job(
        name="spacetrack",
        sources=(PROVIDERS.SPACETRACK,),
        schedule=DailyAt(dtime(hour=12, minute=17)),
    ),
    # Local syntheses, scheduled behind the element fetch they consume. None of
    # them can skip wholesale; each short-circuits per probe on a stored hash.
    Job(
        name="ephemerides",
        sources=(
            PROVIDERS.SPICE_SPACETRACK_TLE,
            PROVIDERS.SPICE_PROBES_PROPAGATION,
            PROVIDERS.SPICE_DEEPCAT,
            PROVIDERS.SPICE_SMALL_BODY_CHEBYSHEV,
        ),
        schedule=DailyAt(dtime(hour=13, minute=0)),
    ),
    Job(
        name="earth_clouds",
        sources=(PROVIDERS.EARTH_CLOUDS,),
        schedule=Every(timedelta(hours=3)),
    ),
    # Object catalogues. Freshness windows run from a day (GCAT, SBDB) to a
    # month (SsODNet, AsterSat).
    Job(
        name="catalogues",
        sources=(
            PROVIDERS.GCAT,
            PROVIDERS.GCAT_DEEP,
            PROVIDERS.SBDB,
            PROVIDERS.SBDB_MOONS,
            PROVIDERS.ASTERSAT,
            PROVIDERS.JOHNSTON,
            PROVIDERS.SSODNET,
            PROVIDERS.JPL_SATELLITE_DISCOVERY,
        ),
        schedule=DailyAt(dtime(hour=3, minute=0)),
    ),
    # Kernels and reference tables. The slowest window here is GVP at 45 days;
    # the rest are one-shots that re-check cheaply and repair a missing file.
    Job(
        name="references",
        sources=(
            PROVIDERS.SPICE,
            PROVIDERS.SPICE_PROBES,
            PROVIDERS.SPICE_HORIZONS_SYNTH,
            PROVIDERS.IAU_NOMENCLATURE,
            PROVIDERS.GVP,
            PROVIDERS.EARTH_WATER,
            PROVIDERS.TEXTURE_SOURCES,
            PROVIDERS.BJJ_RINGS,
            PROVIDERS.LAUNCH_PERFORMANCE,
            PROVIDERS.PSG_ATMOSPHERE,
            PROVIDERS.MANUAL,
        ),
        schedule=DailyAt(dtime(hour=4, minute=0)),
    ),
    # Ordered: Wikipedia reads the entity files Wikidata writes, and Commons
    # reads both. Wikidata resolves its QIDs against the ingest database, so
    # this job only finds new entities where that database is current.
    Job(
        name="wiki",
        sources=(PROVIDERS.WIKIDATA, PROVIDERS.WIKIPEDIA, PROVIDERS.COMMONS),
        schedule=DailyAt(dtime(hour=5, minute=0)),
    ),
    # Large mirrors that never expire — scheduled for the first fill and for
    # repair after a partial one, not for updates.
    Job(
        name="models",
        sources=(
            PROVIDERS.NASA_3D,
            PROVIDERS.ESA_3D,
            PROVIDERS.BODY_SHAPES,
            PROVIDERS.DAMIT,
        ),
        schedule=Every(timedelta(days=7)),
    ),
]


def revisit_period(source: str) -> timedelta:
    """How long a lapsed source waits, at most, for the scheduler's next pass."""
    for job in JOBS:
        if source in job.sources:
            return job.schedule.period
    raise KeyError(f"{source} is not scheduled")
