"""Curated probe mission events: the schema, its loader and its validator.

``sources/position/probe-events/*.json`` is hand-curated prose and figures —
what each spacecraft did and when. One file per batch, each holding a list of
probes keyed by ``probe_id``; identity beyond that key belongs to the registry
(``probe_id.py``), not here.

The event vocabulary states **what happened**; everything else that varies is
a field, so a consumer never has to read the type to find the subject:

    {"type": "flyby", "date": "1974-02-05T17:01:00Z",
     "target": {"naif": 299, "name": "Venus"}, "purpose": "gravity_assist",
     "stated": {"closest_approach_km": 5768},
     "computed": {"closest_approach_km": 5794.4, "kernel_source": "MARINER10"}}

``stated`` is what the published sources say, ``computed`` what our kernels
say; they share key names where they measure the same thing, so a reader can
show either and label it honestly. ``computed`` is written by
``scripts/compute_probe_events.py`` and is never hand-edited.

Dates are ISO-8601 at whatever precision the record supports — a bare
``1965`` claims a year, not midnight on New Year's Day. ``date_precision``
recovers which was meant; ``approximate`` is a different claim, that the
source itself hedges about the moment.

Spans carry ``end_date``: an ``observation`` campaign, a ``contact_loss``
that was later recovered from, a ``hibernation`` that ended.
"""

import datetime
import functools
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from space_map_data.utils.paths import SOURCES_POSITION_DIR

logger = logging.getLogger(__name__)

EVENTS_DIR = SOURCES_POSITION_DIR / "probe-events"

SCHEMA_VERSION = "v3"

# What happened. A type earns its place by meaning something a field cannot:
# `flyby` covers every close pass (the target says which body, `purpose` says
# whether the pass was for the science or for the orbit change), and `landing`
# covers every arrival at a surface (`outcome` says how it went).
EVENT_TYPES: tuple[str, ...] = (
    "launch",
    "stage_separation",
    "flyby",
    "orbit_insertion",
    "orbit_departure",
    "atmospheric_entry",
    "landing",
    "reentry",
    "sample_collection",
    "sample_return",
    "observation",
    "perihelion",
    "contact_loss",
    "hibernation",
    "anomaly",
    "mission_end",
    "milestone",
)

# Types that are a moment by definition: an `end_date` on one of these is a
# curation error. Everything else may carry one and become a stretch of time.
INSTANT_TYPES = frozenset(
    {
        "launch",
        "stage_separation",
        "flyby",
        "atmospheric_entry",
        "perihelion",
        "mission_end",
    }
)

# Why the craft flew past. Absent on a pass that was merely observed.
FLYBY_PURPOSES = frozenset({"gravity_assist", "science"})

# How an arrival at a surface went. `destroyed_at_landing` covers both the
# uncontrolled crash and the deliberate hard impactor.
LANDING_OUTCOMES = frozenset({"controlled", "destroyed_at_landing"})

# Where the craft ended up, independent of whether it still answers.
STATUS_WHERE = frozenset(
    {
        "planned",  # not yet launched
        "transit",  # under way, has not arrived
        "orbiting",
        "landed",  # on a surface, intact
        "impacted",  # destroyed against a surface
        "reentered",  # destroyed in an atmosphere
        "recovered",  # returned to Earth and retrieved
        "heliocentric",
        "interstellar",
        "unknown",
    }
)

# The five ISO-8601 forms the files use, coarsest first. Anything else is a
# curation error: an offset or a fractional second implies a precision the
# sources for this data do not have.
_DATE_FORMS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("year", re.compile(r"^\d{4}$")),
    ("month", re.compile(r"^\d{4}-\d{2}$")),
    ("day", re.compile(r"^\d{4}-\d{2}-\d{2}$")),
    ("minute", re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z$")),
    ("second", re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")),
)

DatePrecision = Literal["year", "month", "day", "minute", "second"]


def date_precision(value: str) -> DatePrecision | None:
    """How much of ``value`` is a claim. ``None`` if it is not a legal form."""
    for name, pattern in _DATE_FORMS:
        if pattern.match(value):
            return name  # type: ignore[return-value]
    return None


# How long a date of each precision could mean, in days.
_PRECISION_DAYS: dict[str, float] = {
    "year": 366.0,
    "month": 31.0,
    "day": 1.0,
    "minute": 1.0 / 1440.0,
    "second": 1.0 / 86400.0,
}


def event_jd_range(value: str) -> tuple[float, float]:
    """Earliest and latest instant a date could mean. A bare year and a
    timestamp on the same day are not out of order, whichever is listed first."""
    precision = date_precision(value)
    if precision is None:
        raise ValueError(f"not an events-file date: {value!r}")
    start = _jd(value, precision)
    return start, start + _PRECISION_DAYS[precision]


def event_jd(value: str) -> float:
    """Julian date of an event date, at the start of whatever it names."""
    precision = date_precision(value)
    if precision is None:
        raise ValueError(f"not an events-file date: {value!r}")
    return _jd(value, precision)


def _jd(value: str, precision: DatePrecision) -> float:
    """UTC is treated as TDB — the ~37 s offset is below the precision of
    even the second-level records here."""
    if precision == "year":
        dt = datetime.datetime(int(value), 1, 1)
    elif precision == "month":
        year, month = value.split("-")
        dt = datetime.datetime(int(year), int(month), 1)
    else:
        dt = datetime.datetime.fromisoformat(value.rstrip("Z"))
    frac = (dt.hour * 3600 + dt.minute * 60 + dt.second) / 86400.0
    return dt.toordinal() + 1721424.5 + frac


def target_object_ids(naif: int) -> tuple[str, ...]:
    """Candidate object ids for an event-target NAIF (Horizons convention),
    best first. Numbered asteroids are SBDB rows, except the dwarf planets
    the renderer keeps under their NAIF id (Ceres is ``naif-2000001``);
    satellites of asteroids keep the id as written (Dimorphos is
    ``spkid-120065803``). Mirrors ``probes/landing_events._resolve_body``."""
    if naif > 100_000_000:
        return (f"spkid-{naif}",)
    if 2_000_000 < naif < 3_000_000:
        return (f"spkid-{naif + 18_000_000}", f"naif-{naif}")
    if 1_000_000 < naif < 2_000_000:
        return (f"spkid-{naif}",)
    return (f"naif-{naif}",)


@dataclass(frozen=True)
class EventTarget:
    """What the event was directed at: a body by NAIF id, or another craft by
    its registry ``probe_id``. The name is the label the sources use."""

    name: str
    naif: int | None = None
    probe_id: int | None = None


@dataclass(frozen=True)
class EventSite:
    """Where on the target body the craft came down."""

    lat_deg: float
    lon_deg: float
    name: str | None = None


@dataclass(frozen=True)
class ProbeStatus:
    """Where the craft is now, and whether it still answers.

    ``alive`` is ``None`` when nobody knows — a dormant craft nobody has
    called. ``lost`` separates a craft that failed from one that finished and
    was retired; both are silent, and the mission pages say so differently.
    """

    where: str
    alive: bool | None = None
    lost: bool = False


@dataclass(frozen=True)
class ProbeEvent:
    type: str
    date: str
    end_date: str | None = None
    approximate: bool = False
    # The event was attempted and missed (a flyby that flew wide, an insertion
    # that did not take); the row stays so the timeline tells the story.
    failed: bool = False
    target: EventTarget | None = None
    purpose: str | None = None  # flyby
    outcome: str | None = None  # landing
    intentional: bool | None = None  # landing
    site: EventSite | None = None  # landing
    stated: dict[str, Any] = field(default_factory=dict)
    computed: dict[str, Any] = field(default_factory=dict)

    @functools.cached_property
    def precision(self) -> DatePrecision | None:
        return date_precision(self.date)

    @functools.cached_property
    def jd(self) -> float:
        return event_jd(self.date)

    @functools.cached_property
    def end_jd(self) -> float | None:
        return event_jd(self.end_date) if self.end_date else None


@dataclass(frozen=True)
class EventProbe:
    """One spacecraft's curated record. ``probe_id`` keys into the registry,
    which owns every other identifier."""

    probe_id: int
    name: str
    status: ProbeStatus
    events: list[ProbeEvent]
    mission_type: str | None = None
    agency: str | None = None
    parent_mission: str | None = None
    source_urls: list[str] = field(default_factory=list)
    # Manual instruction to the trajectory-propagation detector: "force_on",
    # "force_off", or a from_state seed for a craft with no kernel at all.
    propagation: str | dict[str, Any] | None = None
    batch: str = ""  # source file, for logging


def _target(raw: dict[str, Any] | None) -> EventTarget | None:
    if not raw:
        return None
    return EventTarget(
        name=raw.get("name", ""),
        naif=raw.get("naif"),
        probe_id=raw.get("probe_id"),
    )


def _site(raw: dict[str, Any] | None) -> EventSite | None:
    if not raw:
        return None
    return EventSite(
        lat_deg=float(raw["lat_deg"]),
        lon_deg=float(raw["lon_deg"]),
        name=raw.get("name"),
    )


def _event(raw: dict[str, Any]) -> ProbeEvent:
    return ProbeEvent(
        type=raw["type"],
        date=raw["date"],
        end_date=raw.get("end_date"),
        approximate=bool(raw.get("approximate", False)),
        failed=bool(raw.get("failed", False)),
        target=_target(raw.get("target")),
        purpose=raw.get("purpose"),
        outcome=raw.get("outcome"),
        intentional=raw.get("intentional"),
        site=_site(raw.get("site")),
        stated=raw.get("stated") or {},
        computed=raw.get("computed") or {},
    )


def _probe(raw: dict[str, Any], batch: str) -> EventProbe:
    status = raw.get("status") or {}
    return EventProbe(
        probe_id=int(raw["probe_id"]),
        name=raw.get("name", "?"),
        status=ProbeStatus(
            where=status.get("where", "unknown"),
            alive=status.get("alive"),
            lost=bool(status.get("lost", False)),
        ),
        events=[_event(e) for e in raw.get("events", [])],
        mission_type=raw.get("mission_type"),
        agency=raw.get("agency"),
        parent_mission=raw.get("parent_mission"),
        source_urls=raw.get("source_urls") or [],
        propagation=raw.get("propagation"),
        batch=batch,
    )


def load_event_probes() -> list[EventProbe]:
    """Every curated probe, in file then file order. Malformed files are
    logged and skipped; the pipeline runs without this data. Cached: five
    pipeline stages read the same 13 files."""
    return list(_load_event_probes(EVENTS_DIR))


@functools.lru_cache(maxsize=4)
def _load_event_probes(events_dir: Path) -> tuple[EventProbe, ...]:
    if not events_dir.exists():
        logger.info("No events dir at %s; no curated probe events", events_dir)
        return ()
    out: list[EventProbe] = []
    for path in sorted(events_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except OSError, json.JSONDecodeError:
            logger.exception("events: failed to read %s; skipping", path)
            continue
        batch = data.get("_meta", {}).get("batch", path.stem)
        for raw in data.get("probes", []):
            if raw.get("probe_id") is None:
                # No registry row yet, so nothing downstream can join to it.
                logger.info("events: %s has no probe_id; skipping", raw.get("name"))
                continue
            try:
                out.append(_probe(raw, batch))
            except KeyError, TypeError, ValueError:
                logger.exception(
                    "events: probe %r in %s is malformed; skipping",
                    raw.get("name"),
                    path.name,
                )
    logger.info(
        "events: loaded %d probes, %d events",
        len(out),
        sum(len(p.events) for p in out),
    )
    return tuple(out)


def events_by_probe_id() -> dict[int, EventProbe]:
    """Curated records keyed by registry probe_id, for joining onto exports."""
    return {p.probe_id: p for p in load_event_probes()}
