"""Schema check for the curated probe-events files.

The files are edited by hand and by agents, so drift is the normal failure
mode: a new type invented for one craft, a figure filed under a fresh key, a
date written to a precision nobody has. Errors are contract breaks a consumer
would trip over; drift is reported separately, because a genuinely new figure
is allowed to appear — it just has to be seen.
"""

import json
import logging
from pathlib import Path
from typing import Any

from space_map_data.probes.events import (
    EVENT_TYPES,
    EVENTS_DIR,
    FLYBY_PURPOSES,
    LANDING_OUTCOMES,
    INSTANT_TYPES,
    SCHEMA_VERSION,
    STATUS_WHERE,
    date_precision,
    event_jd,
    event_jd_range,
)

logger = logging.getLogger(__name__)

PROBE_KEYS = frozenset(
    {
        "probe_id",
        "name",
        "parent_mission",
        "mission_type",
        "agency",
        "status",
        "description",
        "source_urls",
        "propagation",
        "events",
    }
)

EVENT_KEYS = frozenset(
    {
        "type",
        "date",
        "end_date",
        "approximate",
        "failed",
        "description",
        "target",
        "purpose",
        "outcome",
        "intentional",
        "site",
        "stated",
        "computed",
    }
)

# Fields that only mean something on one kind of event.
_ONLY_ON: dict[str, frozenset[str]] = {
    "purpose": frozenset({"flyby"}),
    "outcome": frozenset({"landing"}),
    "intentional": frozenset({"landing"}),
    "site": frozenset({"landing", "reentry"}),
}

# Figures the files are expected to carry. Anything else is drift: kept, but
# listed, so a one-off key is a decision rather than an accident.
CORE_STATED_KEYS = frozenset(
    {
        "launch_vehicle",
        "launch_site",
        "launch_pad",
        "closest_approach_km",
        "closest_approach_altitude_km",
        "relative_velocity_kms",
        "periapsis_km",
        "apoapsis_km",
        "inclination_deg",
        "period_minutes",
        "orbit_number",
        "orbit_type",
        "perihelion_au",
        "perihelion_solar_radii",
        "impact_velocity_kms",
        "velocity_kms",
        "altitude_km",
        "separation_altitude_km",
        "sample_mass_g",
        "sample_target_body",
        "sample_target_site",
        "perihelion_km_from_surface",
        "instrument",
        "images_returned",
        "flyby_number",
        "pass_number",
        "sol",
        "lunar_day",
        "phase",
        "pole",
        "landing_local_time",
        "surface_transmission_minutes",
        "flight_count",
    }
)

COMPUTED_KEYS = frozenset(
    {
        "kernel_source",
        "closest_approach_utc",
        "closest_approach_km",
        "closest_approach_altitude_km",
        "relative_velocity_kms",
        "perihelion_utc",
        "perihelion_au",
        "perihelion_solar_radii",
        "distance_km",
        "altitude_km",
        "lat_deg",
        "lon_deg",
    }
)


def _check_event(ev: dict[str, Any], where: str, errors: list[str], drift: list[str]):
    unknown = set(ev) - EVENT_KEYS
    if unknown:
        errors.append(f"{where}: unknown event keys {sorted(unknown)}")

    kind = ev.get("type")
    if kind not in EVENT_TYPES:
        errors.append(f"{where}: unknown type {kind!r}")

    date = ev.get("date")
    precision = date_precision(date) if isinstance(date, str) else None
    if precision is None:
        errors.append(f"{where}: date {date!r} is not an ISO form the schema allows")
    end = ev.get("end_date")
    if end is not None:
        if date_precision(end) is None:
            errors.append(f"{where}: end_date {end!r} is not a legal ISO form")
        elif kind in INSTANT_TYPES:
            errors.append(f"{where}: end_date on {kind!r}, which is a moment")
        elif (
            isinstance(date, str)
            and precision is not None
            and event_jd(end) < event_jd(date)
        ):
            errors.append(f"{where}: end_date {end} precedes date {date}")

    for key, types in _ONLY_ON.items():
        if key in ev and kind not in types:
            errors.append(f"{where}: {key!r} on {kind!r}")

    if kind == "flyby" and not ev.get("target"):
        errors.append(f"{where}: flyby with no target")
    if (purpose := ev.get("purpose")) and purpose not in FLYBY_PURPOSES:
        errors.append(f"{where}: unknown flyby purpose {purpose!r}")
    if (outcome := ev.get("outcome")) and outcome not in LANDING_OUTCOMES:
        errors.append(f"{where}: unknown landing outcome {outcome!r}")

    target = ev.get("target")
    if target is not None:
        if not target.get("name"):
            errors.append(f"{where}: target with no name")
        if target.get("naif") is not None and target.get("probe_id") is not None:
            errors.append(f"{where}: target is both a body and a craft")
        elif target.get("naif") is None and target.get("probe_id") is None:
            # A craft the registry has no row for: named, but not linkable.
            drift.append(f"{where}: target.unresolved {target.get('name')!r}")
    site = ev.get("site")
    if site is not None and (
        site.get("lat_deg") is None or site.get("lon_deg") is None
    ):
        errors.append(f"{where}: site without coordinates")

    for bag, known in (("stated", CORE_STATED_KEYS), ("computed", COMPUTED_KEYS)):
        values = ev.get(bag) or {}
        if not isinstance(values, dict):
            errors.append(f"{where}: {bag} is not an object")
            continue
        for key in sorted(set(values) - known):
            drift.append(f"{where}: {bag}.{key}")


def _check_probe(probe: dict[str, Any], file: str, errors: list[str], drift: list[str]):
    name = probe.get("name", "?")
    where = f"{file}/{name}"
    unknown = set(probe) - PROBE_KEYS
    if unknown:
        errors.append(f"{where}: unknown probe keys {sorted(unknown)}")
    probe_id = probe.get("probe_id")
    if probe_id is None:
        # A craft the registry has not minted an id for yet; its record is
        # kept but nothing downstream can join to it.
        drift.append(f"{where}: probe_id.unassigned")
    elif not isinstance(probe_id, int):
        errors.append(f"{where}: probe_id is not an int")

    status = probe.get("status")
    if not isinstance(status, dict):
        errors.append(f"{where}: status must be an object")
    else:
        if status.get("where") not in STATUS_WHERE:
            errors.append(f"{where}: unknown status.where {status.get('where')!r}")
        if status.get("alive") not in (True, False, None):
            errors.append(f"{where}: status.alive must be true/false/null")
        if status.get("lost") not in (True, False, None):
            errors.append(f"{where}: status.lost must be true/false")
        unknown_status = set(status) - {"where", "alive", "lost"}
        if unknown_status:
            errors.append(f"{where}: unknown status keys {sorted(unknown_status)}")

    events = probe.get("events")
    if not isinstance(events, list) or not events:
        errors.append(f"{where}: no events")
        return
    last_jd: float | None = None
    for i, ev in enumerate(events):
        _check_event(ev, f"{where}[{i}]", errors, drift)
        try:
            jd, latest = event_jd_range(ev["date"])
        except KeyError, TypeError, ValueError:
            continue
        # Order carries meaning: a landed phase ends at the next departure.
        # Compared against the earliest instant the previous date could mean,
        # so a date-only event may follow a timestamp on the same day.
        if last_jd is not None and latest < last_jd:
            errors.append(f"{where}[{i}]: {ev['date']} is out of order")
        last_jd = jd if last_jd is None else max(last_jd, jd)


def validate_files(paths: list[Path] | None = None) -> tuple[list[str], list[str]]:
    """Check every events file. Returns ``(errors, drift)``."""
    errors: list[str] = []
    drift: list[str] = []
    for path in paths if paths is not None else sorted(EVENTS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path.name}: unreadable ({exc})")
            continue
        version = data.get("_meta", {}).get("schema_version")
        if version != SCHEMA_VERSION:
            errors.append(
                f"{path.name}: schema_version {version!r} != {SCHEMA_VERSION}"
            )
        for probe in data.get("probes", []):
            _check_probe(probe, path.name, errors, drift)
    return errors, drift
