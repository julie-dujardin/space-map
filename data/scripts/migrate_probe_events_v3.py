"""Rewrite the curated probe-events files from schema v2 to v3.

v2 encoded several things in the event *type* that are really fields of the
event (``earth_flyby``, ``gravity_assist``, ``splashdown``), kept the landing
site on the probe instead of the landing, and used one ``metadata`` bag for
both published figures and free-form notes. v3 is described in
``docs/probe-events-schema.md``.

Run with ``--out DIR`` to write elsewhere and diff before committing; the
default rewrites the source files in place.

    uv run python scripts/migrate_probe_events_v3.py --out /tmp/v3
"""

import argparse
import datetime
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from space_map_data.probes.events import EVENTS_DIR  # noqa: E402
from space_map_data.probes.events_validate import validate_files  # noqa: E402
from space_map_data.probes.probe_id import load_registry  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("migrate")

EARTH_NAIF = 399

# v2 type -> v3 type. Types not listed keep their name.
TYPE_MAP = {
    "earth_flyby": "flyby",
    "gravity_assist": "flyby",
    "splashdown": "landing",
    "decay": "reentry",
    "contact_lost": "contact_loss",
    "hibernation_start": "hibernation",
    "interstellar_boundary_crossed": "milestone",
}

# `milestone_type` was a slug of the description. Only these carried a claim
# the type system should make; the rest is prose and stays a milestone.
MILESTONE_TYPE_MAP = {
    "atmospheric_entry": "atmospheric_entry",
    "anomaly_attitude_control_loss": "anomaly",
    "reaction_wheel_failure": "anomaly",
    "safe_mode": "anomaly",
    "parachute_failure": "anomaly",
    "parachute_deployment_anomaly": "anomaly",
}

# Figures whose v2 key said which block they came from rather than what they
# measure.
STATED_RENAMES = {
    "orbit_periapsis_km": "periapsis_km",
    "orbit_apoapsis_km": "apoapsis_km",
    "orbit_inclination_deg": "inclination_deg",
    "orbit_period_minutes": "period_minutes",
    "perigee_altitude_km": "periapsis_km",
    "site": "sample_target_site",
}

# Moved to `target`, or dropped as a duplicate of it.
STATED_DROP = {"target_object", "parent_object", "target_body_name", "milestone_type"}

# Old status -> (where, alive). `None` where means "read it off the events".
STATUS_MAP: dict[str, tuple[str | None, bool | None]] = {
    "landed_active": ("landed", True),
    "landed_inactive": ("landed", False),
    "in_orbit_active": ("orbiting", True),
    "in_orbit_inactive": ("orbiting", False),
    "impacted": ("impacted", False),
    "crashed": ("impacted", False),
    "decayed": ("reentered", False),
    "heliocentric": ("heliocentric", False),
    "interstellar": ("interstellar", True),
    "planned": ("planned", None),
    "in_transit": ("transit", True),
    "unknown": (None, None),
    "active": (None, True),
    "completed": (None, False),
    "lost": (None, False),
    "contact_lost": (None, False),
    "dormant": (None, None),
}

# Craft whose fate the events do not state: a rover lost with the lander that
# carried it, a bus that burned up in the atmosphere it was sampling, a
# capsule destroyed on the way down. Keyed by probe name.
STATUS_OVERRIDES: dict[str, tuple[str, bool | None]] = {
    "Yutu-2": ("landed", None),
    "Pragyan (Chandrayaan-2)": ("impacted", False),
    "Rashid": ("impacted", False),
    "Tenacious": ("impacted", False),
    "Deep Space 2": ("impacted", False),
    "Mars Polar Lander": ("impacted", False),
    "Mars 6": ("impacted", False),
    "Zond 6": ("impacted", False),
    "Deep Impact / EPOXI": ("heliocentric", False),
    "Venera 4": ("reentered", False),
    "Venera 5": ("reentered", False),
    "Venera 6": ("reentered", False),
    "Vega 1 Venus Balloon": ("reentered", False),
    "Vega 2 Venus Balloon": ("reentered", False),
    "Zond 4": ("reentered", False),
    "Hayabusa": ("reentered", False),
    "Mars 96": ("reentered", False),
    "Fobos-Grunt": ("reentered", False),
    "Yinghuo-1": ("reentered", False),
    "Mars Climate Orbiter": ("reentered", False),
    "Double Star TC-1": ("reentered", False),
    "Double Star TC-2": ("orbiting", False),
    "PROBA-3 Coronagraph Spacecraft (CSC)": ("orbiting", True),
    "PROBA-3 Occulter Spacecraft (OSC)": ("orbiting", True),
    "Chandrayaan-3 Propulsion Module": ("orbiting", True),
}

# The body a craft came down on, where neither a landing site nor an earlier
# event names it. Ids are NAIF for bodies, Horizons/SBDB for small bodies.
MOON, VENUS, TITAN, PHOBOS = 301, 299, 606, 401
LANDING_TARGETS: dict[str, tuple[int, str]] = {
    "Apollo 10 LM Snoopy Descent Stage": (MOON, "Moon"),
    "Apollo 11 LM Eagle Ascent Stage": (MOON, "Moon"),
    "Okina (Rstar)": (MOON, "Moon"),
    "LEV-1": (MOON, "Moon"),
    "LEV-2 (SORA-Q)": (MOON, "Moon"),
    "Luna 27": (MOON, "Moon"),
    "Chang'e 8": (MOON, "Moon"),
    "Lunar Orbiter 4": (MOON, "Moon"),
    "Philae": (1000012, "67P/Churyumov-Gerasimenko"),
    "Deep Impact / EPOXI": (1000093, "9P/Tempel 1"),
    "DART": (120065803, "Dimorphos"),
    "MMX (Martian Moons eXploration)": (PHOBOS, "Phobos"),
    "Huygens": (TITAN, "Titan"),
    "Venera 3": (VENUS, "Venus"),
    "Pioneer Venus Orbiter": (VENUS, "Venus"),
    "Pioneer Venus 2 Bus": (VENUS, "Venus"),
    "Magellan": (VENUS, "Venus"),
    "Venus Express": (VENUS, "Venus"),
    "Peregrine Mission One": (EARTH_NAIF, "Earth"),
    "Cluster II Salsa (FM6)": (EARTH_NAIF, "Earth"),
    "Cluster II Samba (FM7)": (EARTH_NAIF, "Earth"),
    "Cluster II Rumba (FM5)": (EARTH_NAIF, "Earth"),
    "Cluster II Tango (FM8)": (EARTH_NAIF, "Earth"),
}

# Uncontrolled destructive reentries the v2 files filed as landings.
TYPE_FIXUPS: dict[tuple[str, str], str] = {
    ("Fobos-Grunt", "2012-01-15T17:46:00Z"): "reentry",
    ("Mars 96", "1996-11-17"): "reentry",
    ("Yinghuo-1", "2012-01-15T17:46:00Z"): "reentry",
}

# One-off curation fixes the migration is the natural place for, keyed by
# (probe, type, v2 date). Huygens' surface transmission is recorded as
# starting eleven seconds before the touchdown it started at.
DATE_FIXUPS: dict[tuple[str, str, str], str] = {
    ("Huygens", "observation", "2005-01-14T11:38:00Z"): "2005-01-14T11:38:11Z",
}


def normalize_date(value: str) -> str:
    """Collapse a v2 date to one of the five legal ISO forms.

    Offsets and fractional seconds claim a precision these sources do not
    have; both are folded to whole UTC seconds.
    """
    text = value.strip()
    if re.match(r"^\d{4}(-\d{2}){0,2}$", text):
        return text
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z?$", text):
        return text.rstrip("Z") + "Z"
    parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def _probe_ids_by_name(files: list[Path]) -> dict[str, int]:
    """Registry names first, then the events files' own names for craft the
    registry has not minted an id for."""
    out: dict[str, int] = {}
    for entry in load_registry():
        if entry.get("name"):
            out[entry["name"]] = int(entry["probe_id"])
    for path in files:
        for probe in json.loads(path.read_text()).get("probes", []):
            if probe.get("probe_id") is not None:
                out[probe["name"]] = int(probe["probe_id"])
    return out


# Suffixes the events files add when naming a craft in passing. The registry
# knows "Hayabusa", the event says "Hayabusa spacecraft bus".
_CRAFT_SUFFIX = re.compile(r"\s+(spacecraft bus|spacecraft|probe)$", re.IGNORECASE)


def _craft_target(name: str, ids_by_name: dict[str, int]) -> dict[str, Any]:
    """A target that is another spacecraft, linked to the registry when the
    name resolves. A name covering several craft ("Milani, Juventas") is left
    unlinked rather than pinned to one of them."""
    bare = _CRAFT_SUFFIX.sub("", name).strip()
    probe_id = ids_by_name.get(name) or ids_by_name.get(bare)
    if probe_id is None:
        # "OSIRIS-REx" is registered as "OSIRIS-REx / OSIRIS-APEX".
        matches = {
            pid
            for known, pid in ids_by_name.items()
            if known.startswith(f"{bare} /") or known == bare
        }
        if len(matches) == 1:
            probe_id = matches.pop()
    target: dict[str, Any] = {"name": bare}
    if probe_id is not None:
        target["probe_id"] = probe_id
    return target


def _site_from_probe(probe: dict[str, Any]) -> dict[str, Any] | None:
    site = probe.get("landing_site")
    if not isinstance(site, dict) or site.get("lat_deg") is None:
        return None
    out: dict[str, Any] = {"lat_deg": site["lat_deg"], "lon_deg": site["lon_deg"]}
    if site.get("site_name"):
        out["name"] = site["site_name"]
    return out


def _site_target(probe: dict[str, Any]) -> dict[str, Any] | None:
    site = probe.get("landing_site")
    if not isinstance(site, dict) or site.get("target_body_naif") is None:
        return None
    return {
        "naif": int(site["target_body_naif"]),
        "name": site.get("target_body_name") or "",
    }


def _infer_where(events: list[dict[str, Any]], today: str) -> str:
    """Where a craft ended up, read off what it last did.

    Planned events are ignored: a craft on its way to an orbit it has not
    entered yet is still in transit.
    """
    where = "heliocentric"
    for ev in events:
        if ev["date"] > today:
            continue
        kind = ev["type"]
        if kind == "landing":
            # A capsule brought down intact on Earth was collected, not landed.
            if (ev.get("target") or {}).get("naif") == EARTH_NAIF:
                where = "recovered" if ev.get("outcome") == "controlled" else "impacted"
            else:
                where = "landed" if ev.get("outcome") == "controlled" else "impacted"
        elif kind == "reentry":
            where = "reentered"
        elif kind == "sample_return":
            where = "recovered"
        elif kind == "orbit_insertion":
            where = "orbiting"
        elif kind in ("orbit_departure", "launch"):
            where = "heliocentric"
    return where


def migrate_event(
    ev: dict[str, Any],
    probe: dict[str, Any],
    ids_by_name: dict[str, int],
    stats: Counter,
    last_target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    kind = ev["type"]
    stated = dict(ev.get("metadata") or {})
    milestone_type = stated.get("milestone_type")

    new_kind = TYPE_MAP.get(kind, kind)
    if kind == "milestone" and milestone_type in MILESTONE_TYPE_MAP:
        new_kind = MILESTONE_TYPE_MAP[milestone_type]
    # A craft that burned up never reached the surface it was aimed at.
    if new_kind == "landing" and ev.get("outcome") == "burnup_above_surface":
        new_kind = "reentry"
    new_kind = TYPE_FIXUPS.get((probe["name"], ev["date"]), new_kind)
    if new_kind != kind:
        stats[f"type {kind} -> {new_kind}"] += 1

    date = DATE_FIXUPS.get((probe["name"], kind, ev["date"]), ev["date"])
    out: dict[str, Any] = {"type": new_kind, "date": normalize_date(date)}
    if ev.get("end_date"):
        out["end_date"] = normalize_date(ev["end_date"])
    if ev.get("approximate"):
        out["approximate"] = True
    out["description"] = ev["description"]

    target = ev.get("flyby_target")
    if target:
        out["target"] = {"naif": target["naif"], "name": target["name"]}
    elif stated.get("target_object"):
        out["target"] = _craft_target(stated["target_object"], ids_by_name)
    elif stated.get("parent_object"):
        out["target"] = _craft_target(stated["parent_object"], ids_by_name)
    elif new_kind in ("landing", "reentry"):
        # The body it came down on: named by the probe's landing site, or —
        # for the comet and asteroid landers, whose site was never recorded —
        # the body the craft was already working at.
        site_target = _site_target(probe)
        if site_target:
            out["target"] = site_target
        elif last_target:
            out["target"] = last_target
            stats["landing target inherited"] += 1
        elif probe["name"] in LANDING_TARGETS:
            naif, name = LANDING_TARGETS[probe["name"]]
            out["target"] = {"naif": naif, "name": name}
            stats["landing target from table"] += 1
    # Both types named their target instead of carrying it.
    if kind in ("splashdown", "earth_flyby"):
        out.setdefault("target", {"naif": EARTH_NAIF, "name": "Earth"})

    # A separation names the other craft; a few records named the craft whose
    # row this is, which says nothing.
    self_named = out.get("target", {}).get("probe_id")
    if self_named is not None and self_named == probe.get("probe_id"):
        out.pop("target")
        stats["self-target dropped"] += 1

    if kind == "gravity_assist":
        out["purpose"] = "gravity_assist"
    if new_kind in ("landing", "reentry"):
        outcome = ev.get("outcome") or ("controlled" if kind == "splashdown" else None)
        if outcome and new_kind == "landing":
            out["outcome"] = outcome
        if ev.get("intentional") is not None and new_kind == "landing":
            out["intentional"] = ev["intentional"]
        site = _site_from_probe(probe)
        if site:
            out["site"] = site

    for key in STATED_DROP:
        stated.pop(key, None)
    for old, new in STATED_RENAMES.items():
        if old in stated:
            stated[new] = stated.pop(old)
    if stated:
        out["stated"] = stated
    if ev.get("computed"):
        out["computed"] = ev["computed"]
    return out


def _fold_spans(events: list[dict[str, Any]], stats: Counter) -> list[dict[str, Any]]:
    """Turn start/end event pairs into one event with an ``end_date``.

    A restoration with nothing open before it (an amateur team reaching a
    craft written off years earlier) is a moment in its own right, and stays
    one as a milestone.
    """
    out: list[dict[str, Any]] = []
    open_by_type: dict[str, dict[str, Any]] = {}
    for ev in events:
        kind = ev["type"]
        if kind in ("contact_loss", "hibernation"):
            open_by_type[kind] = ev
            out.append(ev)
            continue
        if kind in ("contact_restored", "hibernation_end"):
            # A wake-up closes whichever span is open — a lander whose power
            # returns is both back in contact and out of hibernation.
            opener = open_by_type.pop("hibernation", None) or open_by_type.pop(
                "contact_loss", None
            )
            if opener is not None:
                opener["end_date"] = ev["date"]
                stats[f"span closed: {opener['type']}"] += 1
                continue
            ev["type"] = "milestone"
            stats["orphan restoration -> milestone"] += 1
            out.append(ev)
            continue
        out.append(ev)
    return out


def migrate_probe(
    probe: dict[str, Any], ids_by_name: dict[str, int], stats: Counter, today: str
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    last_target: dict[str, Any] | None = None
    for raw in probe["events"]:
        event = migrate_event(raw, probe, ids_by_name, stats, last_target)
        target = event.get("target")
        if target and target.get("naif") is not None:
            last_target = target
        events.append(event)
    events = _fold_spans(events, stats)

    old_status = probe.get("status") or "unknown"
    where, alive = STATUS_MAP.get(old_status, (None, None))
    if where is None:
        where = _infer_where(events, today)
    if probe["name"] in STATUS_OVERRIDES:
        where, alive = STATUS_OVERRIDES[probe["name"]]
    # A craft that failed and one that finished are both silent; only the v2
    # `lost` status said which.
    status: dict[str, Any] = {"where": where, "alive": alive}
    if old_status == "lost":
        status["lost"] = True
    stats[f"status {old_status} -> {where}/{alive}"] += 1

    out: dict[str, Any] = {"probe_id": probe.get("probe_id"), "name": probe["name"]}
    for key in ("parent_mission", "mission_type", "agency"):
        if probe.get(key):
            out[key] = probe[key]
    out["status"] = status
    out["description"] = probe["description"]
    out["source_urls"] = probe.get("source_urls", [])
    out["events"] = events
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="write here instead of in place")
    args = parser.parse_args()

    today = datetime.date.today().isoformat()
    files = sorted(EVENTS_DIR.glob("*.json"))
    ids_by_name = _probe_ids_by_name(files)
    out_dir = args.out or EVENTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    stats: Counter = Counter()
    skipped: list[str] = []
    for path in files:
        data = json.loads(path.read_text())
        if data.get("_meta", {}).get("schema_version") == "v3":
            logger.info("%s is already v3; skipping", path.name)
            continue
        probes = []
        for probe in data.get("probes", []):
            if probe.get("probe_id") is None:
                # Kept, not dropped: the registry has simply not minted an id
                # for this craft yet, and the curation is real either way.
                skipped.append(f"{path.name}/{probe.get('name')}")
            probes.append(migrate_probe(probe, ids_by_name, stats, today))
        data["_meta"]["schema_version"] = "v3"
        data["probes"] = probes
        (out_dir / path.name).write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        )

    for line, count in sorted(stats.items()):
        logger.info("  %-52s %d", line, count)
    if skipped:
        logger.warning("no probe_id (kept, unjoinable): %s", ", ".join(skipped))

    errors, drift = validate_files(sorted(out_dir.glob("*.json")))
    logger.info("validation: %d errors, %d drifting keys", len(errors), len(drift))
    for line in errors[:40]:
        logger.warning("  ERROR %s", line)
    for line in sorted({k.split(": ", 1)[1] for k in drift}):
        logger.info("  drift %s", line)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
