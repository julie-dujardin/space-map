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
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import orjson
from sqlalchemy.orm import Session

from space_map_data.constants.earth_sats.orbit_class import (
    EarthOrbitClass,
    classify_earth_orbit,
)
from space_map_data.constants.earth_sats.satcat import OrbitCenter, OrbitType
from space_map_data.export.groups.membership import GroupSatcatStats, _accumulate
from space_map_data.export.groups.registry import CLASS_SLUG_PREFIX
from space_map_data.export.position.elements.celestrak_source import iter_day_dirs
from space_map_data.models.object import Object, ObjectType
from space_map_data.models.object.satcat import Satcat

logger = logging.getLogger(__name__)

_EARTH_OBJECT_ID = "naif-399"
_SAT_TYPE_VALUES = [ObjectType.spacecraft.value, ObjectType.debris.value]

SCATTER_TARGET = 1000
SCATTER_FLOOR = 5


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
    """Per-class roll-up for the orbit-class group bundles."""

    member_counts: dict[str, int] = field(default_factory=dict)
    membership: dict[str, list[str]] = field(default_factory=dict)
    orbit_samples: list[EarthOrbitSample] = field(default_factory=list)
    satcat_stats: dict[str, GroupSatcatStats] = field(default_factory=dict)


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


def build_earth_orbit_classes(session: Session) -> EarthOrbitClassStats:
    """Bucket active Earth-orbiting SATCAT rows into zones.

    Active = no decay_date, orbit_center=EARTH, orbit_type=ORBIT, parent
    = Earth — mirrors the Earth-zone export filter.
    """
    inclinations = _load_latest_inclinations()

    rows = (
        session.query(
            Object.id,
            Object.name,
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
            Object.parent_id == _EARTH_OBJECT_ID,
        )
        .all()
    )

    stats = EarthOrbitClassStats()
    skip_counters: Counter[str] = Counter()
    population_per_class: Counter[str] = Counter()
    pool: dict[str, list[tuple[str, str, float, float, float | None, list[str]]]] = {}

    for (
        obj_id,
        obj_name,
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
        if orbit_center != OrbitCenter.EARTH:
            skip_counters["not_earth_centered"] += 1
            continue
        if orbit_type is not None and orbit_type != OrbitType.ORBIT:
            skip_counters["not_in_orbit"] += 1
            continue
        if perigee is None or apogee is None:
            skip_counters["missing_perigee_or_apogee"] += 1
            continue

        inc = inclinations.get(norad)
        classes = classify_earth_orbit(perigee, apogee, inc)
        if not classes:
            skip_counters["unclassified"] += 1
            continue

        class_names = [c.name for c in classes]
        slugs = [f"{CLASS_SLUG_PREFIX}{c}" for c in class_names]
        primary = next(c for c in classes if c.primary)
        primary_slug = f"{CLASS_SLUG_PREFIX}{primary.name}"

        for s in slugs:
            stats.membership.setdefault(s, []).append(obj_id)
            population_per_class[s] += 1
            satcat_stats = stats.satcat_stats.setdefault(s, GroupSatcatStats())
            # Launch sites are deliberately not accumulated: a zone's top-sites
            # breakdown isn't meaningful, so the bundle ships without it.
            _accumulate(
                satcat_stats,
                launch_date,
                ops_status,
                None,
                None,
                constellation_slug,
            )

        display_name = sat_name or obj_name or f"NORAD {norad}"
        pool.setdefault(primary_slug, []).append(
            (obj_id, display_name, float(perigee), float(apogee), inc, class_names)
        )

    for slug, ids in stats.membership.items():
        ids.sort()
        stats.member_counts[slug] = len(ids)

    # Empty classes still get a count=0 entry so each gets a page.
    for cls in EarthOrbitClass:
        slug = f"{CLASS_SLUG_PREFIX}{cls.name}"
        stats.member_counts.setdefault(slug, 0)

    stats.orbit_samples = _build_samples(pool)

    classified = len(rows) - sum(skip_counters.values())
    logger.info(
        "Earth orbit-class build: %d sats classified into %d zones; "
        "skipped %s; samples=%d",
        classified,
        sum(1 for v in stats.member_counts.values() if v),
        dict(skip_counters),
        len(stats.orbit_samples),
    )
    return stats


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
