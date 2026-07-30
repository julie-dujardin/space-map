"""Earth-sat orbit-class membership + scatter samples.

Walks active SATCAT once to bucket every Earth-orbiter into the zones in
:mod:`.orbit_class`, then picks representative samples for the chart.
Inclination comes from the latest CelesTrak GP snapshot; sats without a
TLE row get a primary zone but no inclination overlays.
"""

import csv
import gzip
import logging
import math
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import orjson
from sqlalchemy import or_
from sqlalchemy.orm import Session

from space_map_data.constants.earth_sats.constellations import (
    CONSTELLATION_SLUG_PREFIX,
)
from space_map_data.constants.earth_sats.launch_vehicles import (
    LAUNCH_VEHICLE_BY_CONSTELLATION,
)
from space_map_data.constants.earth_sats.orbit_class import (
    EarthOrbitClass,
    classify_earth_orbit,
)
from space_map_data.constants.earth_sats.satcat import OrbitCenter, OrbitType
from space_map_data.export.groups.membership import GroupSatcatStats, _accumulate
from space_map_data.export.notable import NotableObject
from space_map_data.export.groups.registry import CLASS_SLUG_PREFIX
from space_map_data.export.position.elements.celestrak_source import iter_day_dirs
from space_map_data.models.object import Object, ObjectType
from space_map_data.models.object.satcat import Satcat

logger = logging.getLogger(__name__)

_EARTH_OBJECT_ID = "naif-399"
_SAT_TYPE_VALUES = [ObjectType.spacecraft.value, ObjectType.debris.value]

SCATTER_TARGET = 1000
SCATTER_FLOOR = 5

# Members baked per zone for the strip + members-tab fallback; the rest
# paginate from Meili.
NOTABLE_MEMBER_COUNT = 20


@dataclass
class EarthOrbitSample:
    """One scatter-plot point; ``classes`` lists every zone the sat hits."""

    slug: str
    name: str
    perigee_km: float
    apogee_km: float
    inclination_deg: float | None
    classes: list[str]


@dataclass
class EarthOrbitClassStats:
    """Per-class roll-up for the orbit-class group bundles.

    Zones hold working payloads and debris alike — they're regions of space, not
    fleets — so ``member_counts``/``membership``/``satcat_stats`` stay combined.
    The payload/debris fields split the same scan for the Satellites and Debris
    category pages, which each own one side of the population.
    """

    member_counts: dict[str, int] = field(default_factory=dict)
    membership: dict[str, list[str]] = field(default_factory=dict)
    orbit_samples: list[EarthOrbitSample] = field(default_factory=list)
    satcat_stats: dict[str, GroupSatcatStats] = field(default_factory=dict)
    # Top sats per zone (sitelink-ranked); the orchestrator merges the two sides
    # back together, plus the zone's member constellations, before writing.
    notable_members: dict[str, list[NotableObject]] = field(default_factory=dict)
    debris_notable_members: dict[str, list[NotableObject]] = field(default_factory=dict)
    # Each constellation's dominant zone, so it lists among that zone's members.
    constellation_zone: dict[str, str] = field(default_factory=dict)
    payload_counts: dict[str, int] = field(default_factory=dict)
    debris_counts: dict[str, int] = field(default_factory=dict)
    payload_satcat_stats: dict[str, GroupSatcatStats] = field(default_factory=dict)
    debris_satcat_stats: dict[str, GroupSatcatStats] = field(default_factory=dict)
    # {bare constellation slug: debris pieces}, counted once per object (not per
    # zone) — the Debris page's "where it came from" chart. Rocket families are
    # included; the bundle maps them to their lv- page.
    debris_source_counts: dict[str, int] = field(default_factory=dict)
    # Typical perigee (km) per zone, for the zone page's third stat card.
    # Lagrange classes are absent: they have no Keplerian shape.
    median_perigees: dict[str, float] = field(default_factory=dict)


def _load_latest_inclinations() -> dict[int, float]:
    """Return NORAD → inclination (deg) from the latest CelesTrak day-dir.

    Reads ``gp-active.csv`` + ``groups/*.csv`` so ASAT-test artefacts
    aren't lost. Older days are skipped — stale TLEs add noise.
    """
    from space_map_data.utils.paths import DOWNLOAD_DIR

    celestrak_dir = DOWNLOAD_DIR / "sources" / "position" / "celestrak"
    days = iter_day_dirs(celestrak_dir)
    if not days:
        logger.warning(
            "No CelesTrak day-dirs under %s; orbit-class overlays will be empty",
            celestrak_dir,
        )
        return {}
    _iso, latest = days[-1]

    out: dict[int, float] = {}
    gp_active = latest / "gp-active.csv"
    if gp_active.exists():
        with open(gp_active, newline="") as f:
            for row in csv.DictReader(f):
                norad = row.get("NORAD_CAT_ID")
                inc = row.get("INCLINATION")
                if not norad or not inc:
                    continue
                try:
                    out[int(norad)] = float(inc)
                except ValueError:
                    continue
    else:
        logger.warning("gp-active.csv missing in %s", latest)

    groups_dir = latest / "groups"
    if groups_dir.exists():
        for g in sorted(groups_dir.glob("*.csv")):
            if g.stat().st_size == 0:
                continue
            with open(g, newline="") as f:
                for row in csv.DictReader(f):
                    norad = row.get("NORAD_CAT_ID")
                    inc = row.get("INCLINATION")
                    if not norad or not inc:
                        continue
                    try:
                        out.setdefault(int(norad), float(inc))
                    except ValueError:
                        continue
    logger.info("Loaded %d inclinations from %s", len(out), latest)
    return out


_LAGRANGE_CLASS_BY_CENTER = {
    OrbitCenter.EARTH_L1: EarthOrbitClass.EL1,
    OrbitCenter.EARTH_L2: EarthOrbitClass.EL2,
}
LAGRANGE_ORBIT_CENTERS = tuple(_LAGRANGE_CLASS_BY_CENTER)


def primary_orbit_class_slug(
    perigee: float | None,
    apogee: float | None,
    orbit_center: OrbitCenter | None,
) -> str | None:
    """The ``class-`` slug of a sat's primary Earth-orbit zone, or None when it
    can't be classified. Lagrange sats bucket by orbit_center; the rest by
    perigee/apogee (the inclination overlays never change the primary)."""
    lagrange = (
        _LAGRANGE_CLASS_BY_CENTER.get(orbit_center)
        if orbit_center is not None
        else None
    )
    if lagrange is not None:
        return f"{CLASS_SLUG_PREFIX}{lagrange.name}"
    if perigee is None or apogee is None:
        return None
    classes = classify_earth_orbit(perigee, apogee, None)
    if not classes:
        return None
    primary = next(c for c in classes if c.primary)
    return f"{CLASS_SLUG_PREFIX}{primary.name}"


def build_earth_orbit_classes(session: Session) -> EarthOrbitClassStats:
    """Bucket active Earth-orbiting SATCAT rows into zones.

    Active = no decay_date, orbit_type=ORBIT. Normal zones need orbit_center
    =EARTH + Earth parent (mirrors the Earth-zone export filter); Sun–Earth
    L1/L2 sats are Sun-parented and admitted by orbit_center instead.
    """
    inclinations = _load_latest_inclinations()

    rows = (
        session.query(
            Object.id,
            Object.name,
            Object.wikidata_qid,
            Object.sitelinks_count,
            Object.image_available,
            Object.object_type,
            Satcat.NORAD_CAT_ID,
            Satcat.OBJECT_NAME,
            Satcat.perigee,
            Satcat.apogee,
            Satcat.decay_date,
            Satcat.orbit_center,
            Satcat.orbit_type,
            Satcat.launch_date,
            Satcat.ops_status,
            Satcat.constellation_slug,
        )
        .join(Object.satcat)
        .filter(
            Object.spkid.is_(None),
            Object.object_type.in_(_SAT_TYPE_VALUES),
            # Lagrange-point sats orbit the Sun (~1.5 M km out), so they're parented
            # to the Sun, not Earth — admit them by orbit_center too.
            or_(
                Object.parent_id == _EARTH_OBJECT_ID,
                Satcat.orbit_center.in_(tuple(_LAGRANGE_CLASS_BY_CENTER)),
            ),
        )
        .all()
    )

    stats = EarthOrbitClassStats()
    skip_counters: Counter[str] = Counter()
    population_per_class: Counter[str] = Counter()
    pool: dict[str, list[tuple[str, str, float, float, float | None, list[str]]]] = {}
    perigee_pool: dict[str, list[float]] = {}
    # Notable-member candidates per zone: (image_available, sitelinks, id, qid, name).
    # Split by payload/debris so each category page draws from its own side.
    notable_pool: dict[str, list[tuple[bool, int, str, str | None, str]]] = {}
    debris_notable_pool: dict[str, list[tuple[bool, int, str, str | None, str]]] = {}
    # Per constellation, its sat count per zone (→ dominant zone). Rocket
    # "constellations" that surface as lv- pages are excluded.
    constellation_zone_counts: dict[str, Counter[str]] = {}

    for (
        obj_id,
        obj_name,
        wikidata_qid,
        sitelinks_count,
        image_available,
        object_type,
        norad,
        sat_name,
        perigee,
        apogee,
        decay_date,
        orbit_center,
        orbit_type,
        launch_date,
        ops_status,
        constellation_slug,
    ) in rows:
        if decay_date:
            skip_counters["decayed"] += 1
            continue
        # Lagrange-point sats are bucketed by orbit_center, not perigee/apogee
        # (they have no Keplerian shape and skip the scatter samples below).
        lagrange = _LAGRANGE_CLASS_BY_CENTER.get(orbit_center)
        inc = inclinations.get(norad)
        if lagrange is not None:
            classes: list[EarthOrbitClass] = [lagrange]
        else:
            if orbit_center != OrbitCenter.EARTH:
                skip_counters["not_earth_centered"] += 1
                continue
            if orbit_type is not None and orbit_type != OrbitType.ORBIT:
                skip_counters["not_in_orbit"] += 1
                continue
            if perigee is None or apogee is None:
                skip_counters["missing_perigee_or_apogee"] += 1
                continue
            classes = classify_earth_orbit(perigee, apogee, inc)
            if not classes:
                skip_counters["unclassified"] += 1
                continue

        class_names = [c.name for c in classes]
        slugs = [f"{CLASS_SLUG_PREFIX}{c}" for c in class_names]
        primary = next(c for c in classes if c.primary)
        primary_slug = f"{CLASS_SLUG_PREFIX}{primary.name}"

        is_debris = object_type == ObjectType.debris
        if is_debris and constellation_slug:
            stats.debris_source_counts[constellation_slug] = (
                stats.debris_source_counts.get(constellation_slug, 0) + 1
            )
        side_counts = stats.debris_counts if is_debris else stats.payload_counts
        side_stats = (
            stats.debris_satcat_stats if is_debris else stats.payload_satcat_stats
        )
        for s in slugs:
            stats.membership.setdefault(s, []).append(obj_id)
            population_per_class[s] += 1
            side_counts[s] = side_counts.get(s, 0) + 1
            if lagrange is None:
                perigee_pool.setdefault(s, []).append(float(perigee))
            # Launch sites are deliberately not accumulated: a zone's top-sites
            # breakdown isn't meaningful, so the bundle ships without it.
            for bucket in (
                stats.satcat_stats.setdefault(s, GroupSatcatStats()),
                side_stats.setdefault(s, GroupSatcatStats()),
            ):
                _accumulate(
                    bucket,
                    launch_date,
                    ops_status,
                    None,
                    None,
                    constellation_slug,
                )

        display_name = sat_name or obj_name or f"NORAD {norad}"
        side_pool = debris_notable_pool if is_debris else notable_pool
        side_pool.setdefault(primary_slug, []).append(
            (
                bool(image_available),
                sitelinks_count or 0,
                obj_id,
                wikidata_qid,
                display_name,
            )
        )
        # Lagrange sats have no Keplerian shape, so they skip the scatter pool.
        if lagrange is None:
            pool.setdefault(primary_slug, []).append(
                (obj_id, display_name, float(perigee), float(apogee), inc, class_names)
            )
        if (
            constellation_slug
            and constellation_slug not in LAUNCH_VEHICLE_BY_CONSTELLATION
        ):
            constellation_zone_counts.setdefault(constellation_slug, Counter())[
                primary_slug
            ] += 1

    for slug, ids in stats.membership.items():
        ids.sort()
        stats.member_counts[slug] = len(ids)

    # Empty classes still get a count=0 entry so each gets a page.
    for cls in EarthOrbitClass:
        slug = f"{CLASS_SLUG_PREFIX}{cls.name}"
        stats.member_counts.setdefault(slug, 0)

    stats.notable_members = _rank_notable(notable_pool)
    stats.debris_notable_members = _rank_notable(debris_notable_pool)

    # Each constellation belongs to its most-populated zone (count, then slug
    # for a stable tiebreak).
    for c_slug, zone_counts in constellation_zone_counts.items():
        best_zone = max(zone_counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
        stats.constellation_zone[f"{CONSTELLATION_SLUG_PREFIX}{c_slug}"] = best_zone

    stats.orbit_samples = _build_samples(pool)
    stats.median_perigees = {
        slug: statistics.median(perigees) for slug, perigees in perigee_pool.items()
    }

    classified = len(rows) - sum(skip_counters.values())
    primary_slugs = [
        f"{CLASS_SLUG_PREFIX}{c.name}" for c in EarthOrbitClass if c.primary
    ]
    logger.info(
        "Earth orbit-class build: %d sats classified into %d zones "
        "(%d payloads, %d debris); skipped %s; samples=%d; notable zones=%d; "
        "constellations mapped=%d",
        classified,
        sum(1 for v in stats.member_counts.values() if v),
        sum(stats.payload_counts.get(s, 0) for s in primary_slugs),
        sum(stats.debris_counts.get(s, 0) for s in primary_slugs),
        dict(skip_counters),
        len(stats.orbit_samples),
        len(stats.notable_members),
        len(stats.constellation_zone),
    )
    return stats


def _rank_notable(
    pool: dict[str, list[tuple[bool, int, str, str | None, str]]],
) -> dict[str, list[NotableObject]]:
    """Top members per zone: most-photogenic, then most-notable. The id tiebreak
    keeps the pick deterministic across runs."""
    out: dict[str, list[NotableObject]] = {}
    for slug, candidates in pool.items():
        candidates.sort(key=lambda c: (not c[0], -c[1], c[2]))
        out[slug] = [
            NotableObject(
                object_id=obj_id,
                wikidata_qid=qid,
                fallback_name=name,
                diameter_km=None,
                first_obs=None,
                sitelinks_count=sitelinks,
            )
            for _img, sitelinks, obj_id, qid, name in candidates[:NOTABLE_MEMBER_COUNT]
        ]
    return out


def _allocate_samples(
    primary_counts: dict[str, int],
    target: int = SCATTER_TARGET,
    floor: int = SCATTER_FLOOR,
) -> dict[str, int]:
    """Sqrt-weighted allocation with a per-class floor."""
    weights = {slug: math.sqrt(n) for slug, n in primary_counts.items() if n > 0}
    total_w = sum(weights.values())
    if total_w == 0:
        return {slug: 0 for slug in primary_counts}
    out: dict[str, int] = {}
    for slug, n in primary_counts.items():
        if n == 0:
            out[slug] = 0
            continue
        raw = round(target * weights[slug] / total_w)
        out[slug] = min(max(raw, floor), n)
    return out


def _build_samples(
    pool: dict[str, list[tuple[str, str, float, float, float | None, list[str]]]],
) -> list[EarthOrbitSample]:
    """Pick samples per primary zone; overlays ride on each dot via classes."""
    primary_counts = {slug: len(entries) for slug, entries in pool.items()}
    allocation = _allocate_samples(primary_counts)
    out: list[EarthOrbitSample] = []
    for slug, n in allocation.items():
        if n == 0:
            continue
        # Sort by id so the slice is deterministic across runs.
        entries = sorted(pool[slug], key=lambda t: t[0])
        step = max(1, len(entries) // n)
        picked = entries[::step][:n]
        for obj_id, name, peri, apo, inc, class_names in picked:
            out.append(
                EarthOrbitSample(
                    slug=slug,
                    name=name,
                    perigee_km=peri,
                    apogee_km=apo,
                    inclination_deg=inc,
                    classes=class_names,
                )
            )
    return out


def write_earth_orbit_samples(out_dir: Path, samples: list[EarthOrbitSample]) -> None:
    """Write groups/__sat_orbit_samples__.json.gz for the scatter chart."""
    payload = {
        "samples": [
            {
                "slug": s.slug,
                "name": s.name,
                "perigee_km": s.perigee_km,
                "apogee_km": s.apogee_km,
                "inclination_deg": s.inclination_deg,
                "classes": s.classes,
            }
            for s in samples
        ],
    }
    path = out_dir / "groups" / "__sat_orbit_samples__.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(orjson.dumps(payload)))
    logger.info(
        "Wrote earth-sat scatter samples: %d points → %s",
        len(samples),
        path.name,
    )
