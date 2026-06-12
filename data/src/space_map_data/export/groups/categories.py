"""Category contents: child-group lists, planet members, and member counts.

Categories (constants/categories.py) are Wikidata-backed browse nodes. Their
members are child groups — asteroid zones, comet families, satellite classes
and the largest constellations — or, for Planets, the planet bodies. The child
slugs and counts feed the localized bundle's ``child_groups`` block; planets
ride the existing ``notable_members`` path.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from space_map_data.constants.categories import (
    ASTEROIDS_SLUG,
    COMET_ORBIT_CLASSES,
    COMETS_SLUG,
    PLANETS_SLUG,
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
from space_map_data.models.object.main import Object, ObjectType
from space_map_data.models.object.sbdb import OrbitClass

logger = logging.getLogger(__name__)

# Constellations are long-tailed (~190 specs); the Satellites page shows only
# the largest fleets, ranked by member count.
TOP_CONSTELLATIONS = 12


@dataclass
class CategoryData:
    children: dict[str, list[str]] = field(
        default_factory=dict
    )  # cat slug -> child slugs
    notable_members: dict[str, list[NotableObject]] = field(default_factory=dict)
    member_counts: dict[str, int] = field(default_factory=dict)


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
    """The Sun — the one body that anchors the Solar System root page."""
    row = (
        session.query(Object.id, Object.wikidata_qid, Object.name)
        .filter(Object.object_type == ObjectType.star)
        .order_by(Object.naif_id)
        .first()
    )
    return _body_member(*row) if row is not None else None


def build_category_data(
    session: Session, member_counts: dict[str, int]
) -> CategoryData:
    """Assemble category children + planet members + per-category counts.

    ``member_counts`` is the flattened ``{slug: n}`` for all non-category
    groups; used to drop empty zones and rank constellations.
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

    children = {
        SOLAR_SYSTEM_SLUG: [PLANETS_SLUG, ASTEROIDS_SLUG, COMETS_SLUG, SATELLITES_SLUG],
        ASTEROIDS_SLUG: asteroids,
        COMETS_SLUG: comets,
        SATELLITES_SLUG: satellites,
    }
    # Object totals, not child counts: orbit classes partition their bodies, so
    # summing is exact; flags are subsets, and satellites sum shape classes only.
    asteroids_total = sum(member_counts.get(s, 0) for s in asteroid_classes)
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
        + satellites_total,
        ASTEROIDS_SLUG: asteroids_total,
        COMETS_SLUG: comets_total,
        SATELLITES_SLUG: satellites_total,
        PLANETS_SLUG: len(planet_members),
    }

    notable_members: dict[str, list[NotableObject]] = {}
    if planet_members:
        notable_members[PLANETS_SLUG] = planet_members
    if star is not None:
        notable_members[SOLAR_SYSTEM_SLUG] = [star]
    logger.info(
        "Built category data: planets=%d, asteroid zones=%d, comet families=%d, "
        "satellite groups=%d",
        len(planet_members),
        len(asteroids),
        len(comets),
        len(satellites),
    )
    return CategoryData(
        children=children,
        notable_members=notable_members,
        member_counts=member_counts_out,
    )
