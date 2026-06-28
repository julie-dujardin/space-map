"""Solar System minimap: the lineup hero on the Solar System root page.

A schematic of the Sun + planets + dwarf planets on a log heliocentric-distance
axis at true relative diameters, plus the Main-belt and Kuiper-belt bands. It's a
"minimap" users click to jump to a zone, so it stays grounded in real numbers but
not exhaustive — the far scattered bodies (Eris, Sedna) clip off the right edge
into the real map. Belt extents come from the orbit-class scatter samples already
built for the group bundles, so no extra full-catalog scan.
"""

import gzip
import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import orjson
from sqlalchemy.orm import Session

from space_map_data.download.providers.bjj_rings import (
    INNER_RADIUS_KM as SATURN_RING_INNER_KM,
    OUTER_RADIUS_KM as SATURN_RING_OUTER_KM,
)
from space_map_data.export.groups.categories import _wikidata_diameter_km
from space_map_data.export.groups.registry import CLASS_SLUG_PREFIX
from space_map_data.export.groups.small_body import OrbitClassSample
from space_map_data.export.notable import render_size
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.small_body_color import (
    resolve_moon_color,
    resolve_small_body_color,
)
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.models.object.main import Object, ObjectType
from space_map_data.models.object.sbdb import SBDB, CometPrefix, OrbitClass

logger = logging.getLogger(__name__)

# The largest main-belt asteroids, included so the Main-belt band carries a few
# recognizable named dots. Ceres already rides as a dwarf, so it's excluded by
# the dwarf-planet filter. Selected by diameter (not a fixed name list) so the
# count is the only knob.
ASTEROID_COUNT = 3
_MAIN_BELT_CLASSES = (OrbitClass.IMB, OrbitClass.MBA, OrbitClass.OMB)

# Major moons stacked above each planet: big ones only, capped per planet so the
# stacks stay short. Charon-and-friends (dwarf moons) are left out — Pluto sits
# in the crowded dwarf cluster.
MOON_COUNT = 4
MIN_MOON_DIAMETER_KM = 1000.0
# A planet only grows a moons tab past this many moons (mirrors the frontend's
# STRIP_CAPACITY). Below it (Earth, Mars) a moon links to itself, not a tab.
MOON_TAB_THRESHOLD = 5

_SATURN_NAIF = 699

# Belt bands: the dotted regions drawn behind the bodies. Each links to its
# orbit-class group page (Kuiper→TNO is approximate but close enough). The label
# is the displayed text, distinct from the linked group's own name.
_MBA_SLUG = f"{CLASS_SLUG_PREFIX}{OrbitClass.MBA.name}"
_TNO_SLUG = f"{CLASS_SLUG_PREFIX}{OrbitClass.TNO.name}"

# Robust per-belt extent quantiles over each class's sampled semi-major axes.
# Tighter on the high end for TNO so the scattered disk's long tail doesn't
# stretch the Kuiper band past the classical ~30–48 AU.
_BELT_QUANTILES: dict[str, tuple[float, float]] = {
    _MBA_SLUG: (0.02, 0.98),
    _TNO_SLUG: (0.05, 0.70),
}


@dataclass
class MapObject:
    """One body on the minimap."""

    id: str  # Object.id — routing/focus id and localized-name key
    qid: str | None
    name: str  # English fallback; frontend overrides with the localized label
    kind: str  # star | planet | dwarf | asteroid | moon
    a: float  # semi-major axis [AU] — log x position (moons inherit their planet's)
    i: float  # inclination to ecliptic [deg] — vertical offset (0 for moons)
    diameter_km: float
    color: str | None  # resolved tint for small bodies; None lets the frontend tint
    parent: str | None = None  # moons: parent planet Object.id (placement + link)
    # moons: True → link to the parent's moons tab; False → focus the moon itself
    # (parents with too few moons have no tab, e.g. Earth, Mars).
    link_parent: bool = False
    rings: dict | None = None  # ringed planet: {"inner": r, "outer": r} in planet radii
    moon_count: int | None = None  # planets: total moons (shown in the moon tooltip)


@dataclass
class Belt:
    """A dotted distance band behind the bodies, linking to its group page."""

    slug: str  # linked group slug (class-MBA / class-TNO)
    label: str  # displayed band label
    kind: str  # asteroid_belt | kuiper_belt
    inner_au: float
    outer_au: float


@dataclass
class SolarSystemMap:
    objects: list[MapObject]
    belts: list[Belt]


def _diameter_km(
    naif_id: int | None, qid: str | None, radii: dict[int, dict]
) -> float | None:
    """Render diameter from PCK triaxial radii (major bodies) — equator = max(a,b,c)."""
    triaxial, _ = render_size(naif_id, qid, radii, None, None)
    if triaxial is None:
        return None
    return 2 * max(triaxial["a"], triaxial["b"], triaxial["c"])


def _star_and_planets(
    session: Session,
    radii: dict[int, dict],
    planet_elements: dict[int, dict],
    moon_counts: dict[str, int],
) -> list[MapObject]:
    """The Sun (pinned at a=0) and the eight planets, in heliocentric order."""
    out: list[MapObject] = []
    rows = (
        session.query(Object.id, Object.naif_id, Object.wikidata_qid, Object.name)
        .filter(Object.object_type.in_((ObjectType.star, ObjectType.planet)))
        .order_by(Object.naif_id)
        .all()
    )
    for obj_id, naif_id, qid, name in rows:
        diameter = _diameter_km(naif_id, qid, radii)
        if diameter is None:
            logger.warning("Minimap: %s (%s) has no PCK radii; skipping", obj_id, name)
            continue
        if naif_id == 10:
            kind, a, i = "star", 0.0, 0.0
        else:
            elements = planet_elements.get(naif_id)
            if elements is None:
                logger.warning(
                    "Minimap: planet %s (%s) has no Horizons elements; skipping",
                    obj_id,
                    name,
                )
                continue
            kind, a, i = "planet", elements["a"], elements["i"]
        out.append(
            MapObject(
                id=obj_id,
                qid=qid,
                name=name or obj_id,
                kind=kind,
                a=a,
                i=i,
                diameter_km=diameter,
                color=None,
                rings=_saturn_rings(naif_id, radii),
                moon_count=moon_counts.get(obj_id) if kind == "planet" else None,
            )
        )
    return out


def _saturn_rings(naif_id: int | None, radii: dict[int, dict]) -> dict | None:
    """Saturn's ring span as multiples of its equatorial radius, else None."""
    if naif_id != _SATURN_NAIF:
        return None
    pck = radii.get(_SATURN_NAIF)
    if pck is None:
        return None
    eq = max(pck["a"], pck["b"], pck["c"])
    return {
        "inner": round(SATURN_RING_INNER_KM / eq, 3),
        "outer": round(SATURN_RING_OUTER_KM / eq, 3),
    }


def _moons(
    session: Session,
    radii: dict[int, dict],
    planet_elements: dict[int, dict],
    count: int,
    min_diameter: float,
) -> tuple[list[MapObject], dict[str, int]]:
    """The major moons of each planet, plus each planet's total moon count.

    Placement rides the parent's heliocentric x (moons share its ``a``); the
    frontend fans them vertically. Only planet moons ≥ ``min_diameter`` km, top
    ``count`` per planet. ``link_parent`` records whether the parent has enough
    moons for a moons tab; the returned counts (all moons per planet) feed the
    planet dots so the moon tooltip can read "N moons".
    """
    # Moons orbit the planet or its system barycenter; map a barycenter parent to
    # its planet child so a moon of '5' attaches to Jupiter (599).
    bary_to_host = {
        parent_id: host_id
        for parent_id, host_id in session.query(Object.parent_id, Object.id)
        .filter(
            Object.object_type.in_((ObjectType.planet, ObjectType.dwarf_planet)),
            Object.parent_id.isnot(None),
        )
        .all()
    }
    planets = {
        obj_id: naif_id
        for obj_id, naif_id in session.query(Object.id, Object.naif_id).filter(
            Object.object_type == ObjectType.planet
        )
    }
    rows = (
        session.query(
            Object.id,
            Object.naif_id,
            Object.wikidata_qid,
            Object.name,
            Object.parent_id,
        )
        .filter(Object.object_type == ObjectType.moon)
        .all()
    )
    host_total: dict[str, int] = defaultdict(int)
    candidates: dict[
        str, list[tuple[float, str, int | None, str | None, str | None]]
    ] = defaultdict(list)
    for obj_id, naif_id, qid, name, parent_id in rows:
        host = bary_to_host.get(parent_id, parent_id)
        if host not in planets:  # asteroid/dwarf moons aren't stacked
            continue
        host_total[host] += 1
        diameter = _diameter_km(naif_id, qid, radii)
        if diameter is None or diameter < min_diameter:
            continue
        candidates[host].append((diameter, obj_id, naif_id, qid, name))

    out: list[MapObject] = []
    for host, moons in candidates.items():
        a = planet_elements.get(planets[host], {}).get("a", 0.0)
        link_parent = host_total[host] > MOON_TAB_THRESHOLD
        for diameter, obj_id, naif_id, qid, name in sorted(
            moons, key=lambda m: m[0], reverse=True
        )[:count]:
            out.append(
                MapObject(
                    id=obj_id,
                    qid=qid,
                    name=name or obj_id,
                    kind="moon",
                    a=a,
                    i=0.0,
                    diameter_km=diameter,
                    color=resolve_moon_color(naif_id)[0],
                    parent=host,
                    link_parent=link_parent,
                )
            )
    logger.info(
        "Minimap moons: %d across %d planets (≥%.0f km, ≤%d each)",
        len(out),
        len(candidates),
        min_diameter,
        count,
    )
    return out, dict(host_total)


def _dwarf_planets(
    session: Session,
    entities: WikidataEntityCache,
    units: UnitConverter,
    planet_elements: dict[int, dict],
) -> list[MapObject]:
    """Every dwarf planet, sized by its measured Wikidata diameter.

    Distance/inclination come from SBDB; Pluto carries no SBDB row, so it falls
    back to its Horizons mean elements (outer join keeps it in).
    """
    rows = (
        session.query(
            Object.id,
            Object.naif_id,
            Object.wikidata_qid,
            Object.name,
            SBDB.spkid,
            SBDB.a,
            SBDB.i,
            SBDB.spec_B,
            SBDB.spec_T,
            SBDB.albedo,
        )
        .outerjoin(SBDB, SBDB.object_id == Object.id)
        .filter(Object.object_type == ObjectType.dwarf_planet)
        .order_by(Object.naif_id)
        .all()
    )
    out: list[MapObject] = []
    for obj_id, naif_id, qid, name, spkid, a, i, spec_b, spec_t, albedo in rows:
        diameter = _wikidata_diameter_km(qid, entities, units)
        fallback = planet_elements.get(naif_id, {})
        a = a if a is not None else fallback.get("a")
        i = i if i is not None else fallback.get("i")
        if diameter is None or a is None or i is None:
            logger.warning(
                "Minimap: dwarf %s (%s) missing diameter/a/i (%.4g/%.4g/%.4g); skipping",
                obj_id,
                name,
                diameter or float("nan"),
                a or float("nan"),
                i or float("nan"),
            )
            continue
        color = (
            resolve_small_body_color(spkid, spec_b or spec_t, albedo)[0]
            if spkid is not None
            else None
        )
        out.append(
            MapObject(
                id=obj_id,
                qid=qid,
                name=name or obj_id,
                kind="dwarf",
                a=a,
                i=i,
                diameter_km=diameter,
                color=color,
            )
        )
    return out


def _asteroids(session: Session, count: int) -> list[MapObject]:
    """The ``count`` largest main-belt asteroids, sized by their SBDB diameter."""
    rows = (
        session.query(
            Object.id,
            Object.wikidata_qid,
            Object.name,
            SBDB.spkid,
            SBDB.full_name,
            SBDB.pdes,
            SBDB.diameter,
            SBDB.a,
            SBDB.i,
            SBDB.spec_B,
            SBDB.spec_T,
            SBDB.albedo,
        )
        .join(Object, Object.id == SBDB.object_id)
        .filter(SBDB.prefix.is_distinct_from(CometPrefix.D))
        .filter(Object.object_type != ObjectType.dwarf_planet)
        .filter(SBDB.class_.in_(_MAIN_BELT_CLASSES))
        .filter(SBDB.diameter.is_not(None), SBDB.a.is_not(None), SBDB.i.is_not(None))
        .order_by(SBDB.diameter.desc())
        .limit(count)
        .all()
    )
    out: list[MapObject] = []
    for (
        obj_id,
        qid,
        name,
        spkid,
        full_name,
        pdes,
        dia,
        a,
        i,
        spec_b,
        spec_t,
        albedo,
    ) in rows:
        color = (
            resolve_small_body_color(spkid, spec_b or spec_t, albedo)[0]
            if spkid is not None
            else None
        )
        out.append(
            MapObject(
                id=obj_id,
                qid=qid,
                name=name or full_name or pdes or obj_id,
                kind="asteroid",
                a=a,
                i=i,
                diameter_km=dia,
                color=color,
            )
        )
    return out


def _quantile(values: list[float], q: float) -> float:
    """Linear-interpolated quantile of a non-empty sorted-on-the-fly list."""
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    lo = int(pos)
    frac = pos - lo
    if lo + 1 >= len(s):
        return s[-1]
    return s[lo] + frac * (s[lo + 1] - s[lo])


def _belts(orbit_samples: list[OrbitClassSample]) -> list[Belt]:
    """Main-belt + Kuiper bands, extents from the orbit-class scatter samples."""
    by_slug: dict[str, list[float]] = {_MBA_SLUG: [], _TNO_SLUG: []}
    for s in orbit_samples:
        if s.slug in by_slug and s.a is not None:
            by_slug[s.slug].append(s.a)

    specs = [
        (_MBA_SLUG, "Main belt", "asteroid_belt"),
        (_TNO_SLUG, "Kuiper belt", "kuiper_belt"),
    ]
    belts: list[Belt] = []
    for slug, label, kind in specs:
        a_values = by_slug[slug]
        if not a_values:
            logger.warning("Minimap: no %s samples for the %s band", slug, label)
            continue
        lo_q, hi_q = _BELT_QUANTILES[slug]
        inner = _quantile(a_values, lo_q)
        outer = _quantile(a_values, hi_q)
        logger.info(
            "Minimap %s band: %d samples, a∈[%.2f, %.2f], band [%.2f, %.2f] AU "
            "(q%.0f–q%.0f)",
            label,
            len(a_values),
            min(a_values),
            max(a_values),
            inner,
            outer,
            lo_q * 100,
            hi_q * 100,
        )
        belts.append(
            Belt(slug=slug, label=label, kind=kind, inner_au=inner, outer_au=outer)
        )
    return belts


def build_solar_system_map(
    session: Session,
    radii: dict[int, dict],
    entities: WikidataEntityCache,
    units: UnitConverter,
    orbit_samples: list[OrbitClassSample],
    planet_elements: dict[int, dict],
) -> SolarSystemMap:
    """Assemble the minimap: Sun + planets + dwarf planets + the largest
    main-belt asteroids, plus the belt bands."""
    moons, moon_counts = _moons(
        session, radii, planet_elements, MOON_COUNT, MIN_MOON_DIAMETER_KM
    )
    objects = (
        _star_and_planets(session, radii, planet_elements, moon_counts)
        + _dwarf_planets(session, entities, units, planet_elements)
        + _asteroids(session, ASTEROID_COUNT)
        + moons
    )
    belts = _belts(orbit_samples)
    logger.info(
        "Built solar-system minimap: %d objects (a∈[%.3g, %.3g] AU), %d belts",
        len(objects),
        min((o.a for o in objects if o.a > 0), default=0.0),
        max((o.a for o in objects), default=0.0),
        len(belts),
    )
    return SolarSystemMap(objects=objects, belts=belts)


def _object_payload(o: MapObject) -> dict:
    """Wire shape for one map object; moon/ring fields are emitted only when set."""
    entry: dict = {
        "id": o.id,
        "qid": o.qid,
        "name": o.name,
        "kind": o.kind,
        "a": o.a,
        "i": o.i,
        "diameter_km": o.diameter_km,
        "color": o.color,
    }
    if o.parent is not None:
        entry["parent"] = o.parent
        entry["link_parent"] = o.link_parent
    if o.rings is not None:
        entry["rings"] = o.rings
    if o.moon_count is not None:
        entry["moon_count"] = o.moon_count
    return entry


def write_solar_system_map(out_dir: Path, smap: SolarSystemMap) -> None:
    """Write groups/__solar_system_map__.json.gz."""
    payload = {
        "objects": [_object_payload(o) for o in smap.objects],
        "belts": [
            {
                "slug": b.slug,
                "label": b.label,
                "kind": b.kind,
                "inner_au": b.inner_au,
                "outer_au": b.outer_au,
            }
            for b in smap.belts
        ],
    }
    path = out_dir / "groups" / "__solar_system_map__.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(orjson.dumps(payload)))
    logger.info(
        "Wrote solar-system minimap: %d objects, %d belts → %s",
        len(smap.objects),
        len(smap.belts),
        path.name,
    )
