"""Launchlog-derived stats for launch-vehicle (``lv-``) group pages.

The GCAT launchlog has one row per *payload*; a single launch carries many
(a Falcon 9 Starlink flight is ~60 rows sharing one ``launch_tag``). Launch
counts and the per-year histogram therefore dedupe by ``launch_tag`` — the
launch-level fields (vehicle, date, outcome) are identical across a launch's
payloads — while ``payload_count`` keeps the raw row tally.

Outcome comes from GCAT ``Launch_Code``: char 1 is the regime (O orbital, D
deep-space, S suborbital), char 2 the result (S success, F failure).
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from space_map_data.constants.earth_sats.launch_vehicles import (
    LAUNCH_VEHICLE_SLUG_PREFIX,
    match_launch_vehicle_slug,
)
from space_map_data.constants.earth_sats.reusable_vehicles import (
    REUSABLE_VEHICLE_EXTRACTORS,
)
from space_map_data.models.object import LaunchVehicle, Launchlog

logger = logging.getLogger(__name__)

_TOP_VARIANTS = 25
_TOP_REUSABLE = 10
# Spec fields copied from the LaunchVehicle row onto each variant entry.
_VARIANT_SPECS = (
    "launch_mass_t",
    "leo_capacity_kg",
    "gto_capacity_kg",
    "thrust_kn",
    "length_m",
    "diameter_m",
)


@dataclass
class LaunchVehicleStats:
    """Per-vehicle launchlog roll-up consumed by the lv- group bundle."""

    launch_histogram: dict[int, int] = field(default_factory=dict)
    launch_count: int = 0
    payload_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    first_launch_date: str | None = None
    last_launch_date: str | None = None
    # lv_type → distinct-launch count, for the per-variant breakdown.
    variant_launches: dict[str, int] = field(default_factory=dict)
    # Resolved top-variant entries (name, launches, lv.tsv specs); built last.
    variants: list[dict] = field(default_factory=list)
    # vehicle id → {n, first, last, qid}, for the reusable-vehicle breakdown.
    reusable: dict[str, dict] = field(default_factory=dict)
    # Top reusable vehicles (built last) + their sitelink QIDs.
    reusable_vehicles: list[dict] = field(default_factory=list)
    reusable_vehicle_qids: dict[str, str] = field(default_factory=dict)


def build_launch_vehicle_stats(session: Session) -> dict[str, LaunchVehicleStats]:
    """Aggregate launchlog into ``{lv- group slug: LaunchVehicleStats}``.

    Unmatched ``lv_type`` rows (experimental / suborbital one-offs that map to
    no vehicle) are tallied and logged rather than silently dropped.
    """
    specs = {lv.lv_name: lv for lv in session.execute(select(LaunchVehicle)).scalars()}
    by_slug: dict[str, LaunchVehicleStats] = defaultdict(LaunchVehicleStats)
    # launch_tags already counted at launch level; later payloads of the same
    # launch only bump payload_count.
    seen_launch: set[str] = set()
    unmatched_payloads = 0
    unmatched_types: set[str] = set()

    rows = session.execute(
        select(
            Launchlog.lv_type,
            Launchlog.launch_tag,
            Launchlog.launch_date_iso,
            Launchlog.launch_code,
            Launchlog.flight_id,
            Launchlog.name,
        )
    ).all()
    for lv_type, tag, date_iso, code, flight_id, pl_name in rows:
        slug = match_launch_vehicle_slug(lv_type)
        if slug is None:
            unmatched_payloads += 1
            if lv_type:
                unmatched_types.add(lv_type)
            continue
        group_slug = f"{LAUNCH_VEHICLE_SLUG_PREFIX}{slug}"
        stats = by_slug[group_slug]
        stats.payload_count += 1
        if tag is None or tag in seen_launch:
            continue  # already counted this launch's launch-level fields
        seen_launch.add(tag)
        stats.launch_count += 1
        if lv_type:
            stats.variant_launches[lv_type] = stats.variant_launches.get(lv_type, 0) + 1
        extractor = REUSABLE_VEHICLE_EXTRACTORS.get(slug)
        if extractor:
            for rv in extractor(flight_id, pl_name):
                acc = stats.reusable.setdefault(
                    rv.id, {"n": 0, "first": None, "last": None, "qid": rv.qid}
                )
                acc["n"] += 1
                if date_iso:
                    if acc["first"] is None or date_iso < acc["first"]:
                        acc["first"] = date_iso
                    if acc["last"] is None or date_iso > acc["last"]:
                        acc["last"] = date_iso
        if date_iso:
            year = int(date_iso[:4])
            stats.launch_histogram[year] = stats.launch_histogram.get(year, 0) + 1
            if stats.first_launch_date is None or date_iso < stats.first_launch_date:
                stats.first_launch_date = date_iso
            if stats.last_launch_date is None or date_iso > stats.last_launch_date:
                stats.last_launch_date = date_iso
        if code and len(code) >= 2:
            if code[1] == "S":
                stats.success_count += 1
            elif code[1] == "F":
                stats.failure_count += 1

    for stats in by_slug.values():
        stats.variants = _variant_entries(stats.variant_launches, specs)
        stats.reusable_vehicles = _reusable_entries(stats.reusable)
        stats.reusable_vehicle_qids = {
            e["name"]: stats.reusable[e["name"]]["qid"]
            for e in stats.reusable_vehicles
            if stats.reusable[e["name"]]["qid"]
        }

    if unmatched_payloads:
        logger.info(
            "Launch-vehicle stats: %d payload rows across %d lv_type(s) matched no "
            "vehicle (experimental/suborbital one-offs): %s",
            unmatched_payloads,
            len(unmatched_types),
            ", ".join(sorted(unmatched_types)),
        )
    logger.info(
        "Built launch-vehicle stats for %d vehicles (%d launches)",
        len(by_slug),
        sum(s.launch_count for s in by_slug.values()),
    )
    return dict(by_slug)


def _reusable_entries(reusable: dict[str, dict]) -> list[dict]:
    """Top reusable vehicles by flight count, with first/last flight dates."""
    top = sorted(reusable.items(), key=lambda kv: kv[1]["n"], reverse=True)
    out: list[dict] = []
    for name, acc in top[:_TOP_REUSABLE]:
        entry: dict = {"name": name, "n": acc["n"]}
        if acc["first"]:
            entry["first_flight"] = acc["first"]
        if acc["last"]:
            entry["last_flight"] = acc["last"]
        out.append(entry)
    return out


def _variant_entries(
    variant_launches: dict[str, int], specs_by_name: dict[str, LaunchVehicle]
) -> list[dict]:
    """Top variants by launch count, each with its launchlog tally + lv.tsv specs."""
    top = sorted(variant_launches.items(), key=lambda kv: kv[1], reverse=True)
    out: list[dict] = []
    for name, n in top[:_TOP_VARIANTS]:
        entry: dict = {"name": name, "n": n}
        spec = specs_by_name.get(name)
        if spec is not None:
            for f in _VARIANT_SPECS:
                val = getattr(spec, f)
                if val is not None:
                    entry[f] = val
        out.append(entry)
    return out
