"""Category contents: child-group lists, planet members, and member counts.

Categories (constants/categories.py) are Wikidata-backed browse nodes. Their
members are child groups — asteroid zones, comet families, satellite classes
and the largest constellations — or bodies (Planets, Probes). The child slugs
and counts feed the localized bundle's ``child_groups`` block; planets and
probes ride the existing ``notable_members`` path.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import func
from sqlalchemy.orm import Session

from space_map_data.constants.categories import (
    ASTEROIDS_SLUG,
    COMET_ORBIT_CLASSES,
    COMETS_SLUG,
    PLANETS_SLUG,
    PROBES_SLUG,
    SATELLITES_SLUG,
    SOLAR_SYSTEM_SLUG,
)
from space_map_data.constants.earth_sats.orbit_class import EarthOrbitClass
from space_map_data.export.groups.registry import (
    CLASS_SLUG_PREFIX,
    SMALL_BODY_FLAG_SLUG_PREFIX,
    GROUPS,
    GroupType,
)
from space_map_data.export.notable import NotableObject
from space_map_data.models.object.main import Object, ObjectType, OrbitalSource
from space_map_data.models.object.sbdb import OrbitClass

logger = logging.getLogger(__name__)

# Constellations are long-tailed (~190 specs); the Satellites page shows only
# the largest fleets, ranked by member count.
TOP_CONSTELLATIONS = 12

# Notable members shown on the Solar System root (Sun + top 19 bodies).
NOTABLE_COUNT = 20


@dataclass
class CategoryData:
    children: dict[str, list[str]] = field(
        default_factory=dict
    )  # cat slug -> child slugs
    notable_members: dict[str, list[NotableObject]] = field(default_factory=dict)
    member_counts: dict[str, int] = field(default_factory=dict)
    named_counts: dict[str, int] = field(default_factory=dict)  # cat slug -> named n
    discovery_histograms: dict[str, dict[int, int]] = field(
        default_factory=dict
    )  # cat slug -> {year: count}
    launch_histograms: dict[str, dict[int, int]] = field(default_factory=dict)


def _sum_histograms(
    slugs: list[str], source: dict[str, dict[int, int]]
) -> dict[int, int]:
    """Sum per-slug year histograms over a partition of child slugs."""
    out: dict[int, int] = {}
    for slug in slugs:
        for year, n in source.get(slug, {}).items():
            out[year] = out.get(year, 0) + n
    return out


def _body_member(obj_id: str, qid: str | None, name: str | None) -> NotableObject:
    return NotableObject(
        object_id=obj_id,
        wikidata_qid=qid,
        fallback_name=name or obj_id,
        diameter_km=None,
        first_obs=None,
    )


def _planet_members(session: Session) -> list[NotableObject]:
    """The planets, in heliocentric order (NAIF 199…899)."""
    rows = (
        session.query(Object.id, Object.wikidata_qid, Object.name)
        .filter(Object.object_type == ObjectType.planet)
        .order_by(Object.naif_id)
        .all()
    )
    return [_body_member(obj_id, qid, name) for obj_id, qid, name in rows]


def _star_member(session: Session) -> NotableObject | None:
    """The Sun — pinned first on the Solar System root page."""
    row = (
        session.query(Object.id, Object.wikidata_qid, Object.name)
        .filter(Object.object_type == ObjectType.star)
        .order_by(Object.naif_id)
        .first()
    )
    return _body_member(*row) if row is not None else None


def _solar_system_members(
    session: Session, star: NotableObject | None
) -> list[NotableObject]:
    """Sun first, then the most-linked bodies (same image/sitelinks proxy)."""
    rows = (
        session.query(Object.id, Object.wikidata_qid, Object.name)
        .filter(Object.object_type != ObjectType.barycenter)
        .order_by(
            Object.image_available.desc(), Object.sitelinks_count.desc(), Object.id
        )
        .limit(NOTABLE_COUNT + 1)
        .all()
    )
    members = [_body_member(*r) for r in rows]
    if star is not None:
        members = [star] + [m for m in members if m.object_id != star.object_id]
    return members[:NOTABLE_COUNT]


def _probe_members(session: Session) -> tuple[list[NotableObject], int]:
    """The notable probes (most-linked first) plus the total probe count.

    Probes are SPICE-tracked interplanetary spacecraft (``spice_probe``); Earth
    satellites are also ``spacecraft``-typed but belong to the Satellites tree.
    """
    is_probe = Object.orbital_source == OrbitalSource.spice_probe
    total = session.query(func.count(Object.id)).filter(is_probe).scalar() or 0
    rows = (
        session.query(Object.id, Object.wikidata_qid, Object.name)
        .filter(is_probe)
        .order_by(
            Object.image_available.desc(), Object.sitelinks_count.desc(), Object.id
        )
        .limit(NOTABLE_COUNT)
        .all()
    )
    return [_body_member(*r) for r in rows], total


def build_category_data(
    session: Session,
    member_counts: dict[str, int],
    named_counts: dict[str, int],
    discovery_histograms: dict[str, dict[int, int]],
    launch_histograms: dict[str, dict[int, int]],
) -> CategoryData:
    """Assemble category children + planet members + per-category counts.

    ``member_counts`` is the flattened ``{slug: n}`` for all non-category
    groups; used to drop empty zones and rank constellations.
    ``discovery_histograms`` is keyed by small-body class slug and
    ``launch_histograms`` by earth orbit-class slug; both are summed over the
    classes that partition each category (orbit classes for small bodies, the
    primary shape classes for satellites) to give the category-level chart.
    """

    def nonempty(slug: str) -> bool:
        return member_counts.get(slug, 0) > 0

    asteroid_classes = [
        f"{CLASS_SLUG_PREFIX}{c.name}"
        for c in OrbitClass
        if c not in COMET_ORBIT_CLASSES
    ]
    comet_classes = [
        f"{CLASS_SLUG_PREFIX}{c.name}" for c in OrbitClass if c in COMET_ORBIT_CLASSES
    ]
    flags = [f"{SMALL_BODY_FLAG_SLUG_PREFIX}neo", f"{SMALL_BODY_FLAG_SLUG_PREFIX}pha"]

    asteroids = [s for s in asteroid_classes if nonempty(s)] + [
        s for s in flags if nonempty(s)
    ]
    comets = [s for s in comet_classes if nonempty(s)]

    earth_classes = [
        slug
        for c in EarthOrbitClass
        if nonempty(slug := f"{CLASS_SLUG_PREFIX}{c.name}")
    ]
    constellations = sorted(
        (
            g.slug
            for g in GROUPS
            if g.type is GroupType.CONSTELLATION and nonempty(g.slug)
        ),
        key=lambda s: member_counts.get(s, 0),
        reverse=True,
    )[:TOP_CONSTELLATIONS]
    satellites = earth_classes + constellations

    planet_members = _planet_members(session)
    star = _star_member(session)
    probe_members, probes_total = _probe_members(session)

    children = {
        SOLAR_SYSTEM_SLUG: [
            PLANETS_SLUG,
            ASTEROIDS_SLUG,
            COMETS_SLUG,
            SATELLITES_SLUG,
            PROBES_SLUG,
        ],
        ASTEROIDS_SLUG: asteroids,
        COMETS_SLUG: comets,
        SATELLITES_SLUG: satellites,
    }
    # Object totals, not child counts: orbit classes partition their bodies, so
    # summing is exact; flags are subsets, and satellites sum shape classes only.
    asteroids_total = sum(member_counts.get(s, 0) for s in asteroid_classes)
    asteroids_named = sum(named_counts.get(s, 0) for s in asteroid_classes)
    comets_total = sum(member_counts.get(s, 0) for s in comet_classes)
    satellites_total = sum(
        member_counts.get(f"{CLASS_SLUG_PREFIX}{c.name}", 0)
        for c in EarthOrbitClass
        if c.primary
    )
    member_counts_out = {
        # The root counts every categorized object across the solar system.
        SOLAR_SYSTEM_SLUG: len(planet_members)
        + asteroids_total
        + comets_total
        + satellites_total
        + probes_total,
        ASTEROIDS_SLUG: asteroids_total,
        COMETS_SLUG: comets_total,
        SATELLITES_SLUG: satellites_total,
        PLANETS_SLUG: len(planet_members),
        PROBES_SLUG: probes_total,
    }

    # Discovery/launch charts: sum the histograms over the classes that
    # partition each category (flags are subsets, so they're excluded; sats
    # sum only the primary shape classes — same partition as satellites_total).
    primary_sat_slugs = [
        f"{CLASS_SLUG_PREFIX}{c.name}" for c in EarthOrbitClass if c.primary
    ]
    discovery_out: dict[str, dict[int, int]] = {}
    if asteroid_hist := _sum_histograms(asteroid_classes, discovery_histograms):
        discovery_out[ASTEROIDS_SLUG] = asteroid_hist
    if comet_hist := _sum_histograms(comet_classes, discovery_histograms):
        discovery_out[COMETS_SLUG] = comet_hist
    launch_out: dict[str, dict[int, int]] = {}
    if sat_hist := _sum_histograms(primary_sat_slugs, launch_histograms):
        launch_out[SATELLITES_SLUG] = sat_hist

    notable_members: dict[str, list[NotableObject]] = {}
    if planet_members:
        notable_members[PLANETS_SLUG] = planet_members
    if probe_members:
        notable_members[PROBES_SLUG] = probe_members
    solar_system = _solar_system_members(session, star)
    if solar_system:
        notable_members[SOLAR_SYSTEM_SLUG] = solar_system
    logger.info(
        "Built category data: planets=%d, asteroid zones=%d, comet families=%d, "
        "satellite groups=%d, probes=%d",
        len(planet_members),
        len(asteroids),
        len(comets),
        len(satellites),
        probes_total,
    )
    return CategoryData(
        children=children,
        notable_members=notable_members,
        member_counts=member_counts_out,
        # Only Asteroids has a meaningful named/total gap (~1.7 % named); the
        # Solar System root and other categories are effectively all-named.
        named_counts={ASTEROIDS_SLUG: asteroids_named} if asteroids_named else {},
        discovery_histograms=discovery_out,
        launch_histograms=launch_out,
    )
