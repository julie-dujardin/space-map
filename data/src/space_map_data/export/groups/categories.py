"""Category contents: child-group lists, planet members, and member counts.

Categories (constants/categories.py) are Wikidata-backed browse nodes. Their
members are child groups — asteroid zones, comet families, satellite classes
and the largest constellations — or bodies (Planets, Moons, Probes). The child
slugs and counts feed the localized bundle's ``child_groups`` block; the planet
lineup, the top moons and the notable probes ride the ``notable_members`` path.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import func
from sqlalchemy.orm import Session

from space_map_data.constants.categories import (
    ASTEROIDS_SLUG,
    COMET_ORBIT_CLASSES,
    COMETS_SLUG,
    DWARF_PLANETS_SLUG,
    MOONS_SLUG,
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
from space_map_data.export.groups.small_body import _notable_members
from space_map_data.export.notable import NotableObject, render_geometry
from space_map_data.export.small_body_color import resolve_small_body_color
from space_map_data.export.objects.wikidata_claims import (
    diameter_km_from_claims,
    radius_km_from_claims,
)
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.ingest.providers.objects.sbdb import G_KM3_PER_KG_S2
from space_map_data.models.object.main import Object, ObjectType, OrbitalSource
from space_map_data.models.object.sbdb import SBDB, OrbitClass

logger = logging.getLogger(__name__)

# Constellations are long-tailed (~190 specs); the Satellites page shows only
# the largest fleets, ranked by member count.
TOP_CONSTELLATIONS = 12

# Notable members shown on the Solar System root (Sun + top 19 bodies).
NOTABLE_COUNT = 20

# Moons page hero — the most prominent (5 paginated pages of 5 in the frontend
# lineup). Asteroids will reuse this selector.
TOP_MOONS = 25

_PLANET_TYPES = (ObjectType.planet, ObjectType.dwarf_planet)

# Semi-major axis (AU) for the major planets + Pluto, which carry no SBDB row;
# orders the moons-per-planet chart by heliocentric distance. Dwarf planets are
# SBDB-tracked and use their measured SBDB.a instead.
_PLANET_AU: dict[int, float] = {
    199: 0.387,  # Mercury
    299: 0.723,  # Venus
    399: 1.000,  # Earth
    499: 1.524,  # Mars
    599: 5.203,  # Jupiter
    699: 9.537,  # Saturn
    799: 19.191,  # Uranus
    899: 30.07,  # Neptune
    999: 39.48,  # Pluto
}


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
    # cat slug -> bar-chart rows (moons per planet/dwarf, distance-ordered).
    moon_counts: dict[str, list[dict]] = field(default_factory=dict)


def _sum_histograms(
    slugs: list[str], source: dict[str, dict[int, int]]
) -> dict[int, int]:
    """Sum per-slug year histograms over a partition of child slugs."""
    out: dict[int, int] = {}
    for slug in slugs:
        for year, n in source.get(slug, {}).items():
            out[year] = out.get(year, 0) + n
    return out


def _mass_kg_from_gm(gm_km3_s2: float | None) -> float | None:
    """Body mass from its PCK gravitational parameter: M = GM / G.

    The planet-level GM (e.g. BODY599_GM, not the system barycenter) gives the
    planet's own mass. Mirrors SBDB's GM→mass conversion.
    """
    if gm_km3_s2 is None:
        return None
    return gm_km3_s2 / G_KM3_PER_KG_S2


def _body_member(
    obj_id: str,
    naif_id: int | None,
    qid: str | None,
    name: str | None,
    radii: dict[int, dict],
    gms: dict[int, float],
    orientation: dict[int, dict],
) -> NotableObject:
    """Denormalize a body, attaching its PCK mass + shared lineup render geometry."""
    geo = render_geometry(naif_id, qid, radii, orientation=orientation)
    return NotableObject(
        object_id=obj_id,
        wikidata_qid=qid,
        fallback_name=name or obj_id,
        diameter_km=None,
        first_obs=None,
        mass_kg=_mass_kg_from_gm(gms.get(naif_id) if naif_id is not None else None),
        radii=geo.radii,
        radius_km=geo.radius_km,
        pole=geo.pole,
    )


def _ranked_members(
    session: Session,
    where,
    limit: int,
    radii: dict[int, dict],
    gms: dict[int, float],
    orientation: dict[int, dict],
) -> list[NotableObject]:
    """Top ``limit`` bodies for a hero strip: image-bearing first, then most
    Wikidata-linked (sitelinks as a prominence proxy), id as a stable tiebreak.

    The shared prominence-ranked selector behind every notable strip that isn't
    a fixed lineup: Moons now, Asteroids next; the Probes page and Solar System
    root layer their own filter/pin on top. ``where`` is one SQLAlchemy clause.
    """
    rows = (
        session.query(Object.id, Object.naif_id, Object.wikidata_qid, Object.name)
        .filter(where)
        .order_by(
            Object.image_available.desc(), Object.sitelinks_count.desc(), Object.id
        )
        .limit(limit)
        .all()
    )
    return [
        _body_member(*row, radii=radii, gms=gms, orientation=orientation)
        for row in rows
    ]


def _planet_members(
    session: Session,
    radii: dict[int, dict],
    gms: dict[int, float],
    orientation: dict[int, dict],
) -> list[NotableObject]:
    """The planets, in heliocentric order (NAIF 199…899)."""
    rows = (
        session.query(Object.id, Object.naif_id, Object.wikidata_qid, Object.name)
        .filter(Object.object_type == ObjectType.planet)
        .order_by(Object.naif_id)
        .all()
    )
    return [
        _body_member(*row, radii=radii, gms=gms, orientation=orientation)
        for row in rows
    ]


def _wikidata_diameter_km(
    qid: str | None, entities: WikidataEntityCache, units: UnitConverter
) -> float | None:
    """A dwarf planet's diameter (km) from Wikidata — P2120 radius or P2386."""
    if qid is None:
        return None
    entity = entities.get_entity(qid)
    if entity is None:
        return None
    claims = entity["claims"]
    radius = radius_km_from_claims(claims, units, qid)
    if radius is not None:
        return 2 * radius
    return diameter_km_from_claims(claims, units, qid)


def _dwarf_planet_members(
    session: Session,
    radii: dict[int, dict],
    gms: dict[int, float],
    orientation: dict[int, dict],
    entities: WikidataEntityCache,
    units: UnitConverter,
) -> list[NotableObject]:
    """The dwarf planets, most-prominent first (image then sitelinks).

    Unlike the eight major planets these carry no static heliocentric order, so
    they rank by prominence like the moons strip. Their lineup size comes from
    each body's measured Wikidata diameter (none are in the PCK that feeds the
    major planets/moons).
    """
    rows = (
        session.query(
            Object.id,
            Object.naif_id,
            Object.wikidata_qid,
            Object.name,
            SBDB.spkid,
            SBDB.spec_B,
            SBDB.spec_T,
            SBDB.albedo,
        )
        # Outer join: Pluto carries no SBDB row, but still belongs in the lineup.
        .outerjoin(SBDB, SBDB.object_id == Object.id)
        .filter(Object.object_type == ObjectType.dwarf_planet)
        .order_by(
            Object.image_available.desc(), Object.sitelinks_count.desc(), Object.id
        )
        .all()
    )
    members: list[NotableObject] = []
    for obj_id, naif_id, qid, name, spkid, spec_b, spec_t, albedo in rows:
        member = _body_member(
            obj_id, naif_id, qid, name, radii=radii, gms=gms, orientation=orientation
        )
        member.diameter_km = _wikidata_diameter_km(member.wikidata_qid, entities, units)
        if member.diameter_km is None:
            logger.warning(
                "Dwarf planet %s (%s) has no Wikidata diameter; it won't size in "
                "the lineup",
                member.object_id,
                member.wikidata_qid,
            )
        # The TNO dwarfs (Eris, Makemake, …) are textureless, so the lineup tints
        # them by their measured colour like any other small body.
        if spkid is not None:
            member.albedo = albedo
            member.spec = spec_b or spec_t
            member.color = resolve_small_body_color(spkid, spec_b or spec_t, albedo)[0]
        members.append(member)
    return members


def _moon_data(session: Session) -> tuple[int, list[dict]]:
    """Total moon count + per-planet/dwarf tallies for the Moons-page bar chart.

    A moon's host is its parent planet/dwarf; parents that are barycenters
    defer to their planet/dwarf child (mirrors export/objects/moons.py). All
    eight major planets always get a bar (Mercury/Venus included, at zero);
    dwarf planets get one only when they host a moon. Asteroid moons still
    count toward the total but have no chart row. Rows are ordered by
    heliocentric distance (SBDB.a for dwarfs, a static table for the major
    planets/Pluto). Each row is the bundle wire shape:
    ``{name, primary_type, primary_id, n}``.
    """
    total = (
        session.query(func.count(Object.id))
        .filter(Object.object_type == ObjectType.moon)
        .scalar()
        or 0
    )

    parent_counts = (
        session.query(Object.parent_id, func.count(Object.id))
        .filter(Object.object_type == ObjectType.moon, Object.parent_id.isnot(None))
        .group_by(Object.parent_id)
        .all()
    )
    # Barycenter parent -> its planet/dwarf child (the body the user focuses).
    bary_to_host = {
        parent_id: host_id
        for parent_id, host_id in session.query(Object.parent_id, Object.id)
        .filter(Object.object_type.in_(_PLANET_TYPES), Object.parent_id.isnot(None))
        .all()
    }
    host_counts: dict[str, int] = {}
    for parent_id, n in parent_counts:
        host_id = bary_to_host.get(parent_id, parent_id)
        host_counts[host_id] = host_counts.get(host_id, 0) + n

    # All major planets always appear (Mercury/Venus included, at zero);
    # dwarf planets appear only when they host a moon — otherwise every
    # moonless trans-Neptunian dwarf would clutter the chart.
    planet_rows = (
        session.query(Object.id, Object.naif_id, Object.name)
        .filter(Object.object_type == ObjectType.planet)
        .all()
    )
    dwarf_rows = (
        session.query(Object.id, Object.naif_id, Object.name)
        .filter(
            Object.id.in_(host_counts),
            Object.object_type == ObjectType.dwarf_planet,
        )
        .all()
    )
    host_rows = [*planet_rows, *dwarf_rows]
    kept = {r.id for r in host_rows}
    dropped = sum(c for host, c in host_counts.items() if host not in kept)
    if dropped:
        logger.info(
            "Moons chart: %d moon(s) of non-planet hosts (e.g. asteroid moons) "
            "counted in the total but excluded from the per-planet bars",
            dropped,
        )

    sbdb_a = {
        object_id: a
        for object_id, a in session.query(SBDB.object_id, SBDB.a)
        .filter(SBDB.object_id.in_(kept), SBDB.a.isnot(None))
        .all()
    }

    ranked: list[tuple[float, dict]] = []
    unranked: list[dict] = []
    for r in host_rows:
        row = {
            "name": r.name or r.id,
            "primary_type": "object",
            "primary_id": r.id,
            "n": host_counts.get(r.id, 0),
        }
        au = _PLANET_AU.get(r.naif_id) if r.naif_id is not None else None
        if au is None:
            au = sbdb_a.get(r.id)
        if au is None:
            logger.warning(
                "Moons chart: no heliocentric distance for host %s (%s); "
                "appending it after the distance-ordered rows",
                r.id,
                r.name,
            )
            unranked.append(row)
        else:
            ranked.append((au, row))
    ranked.sort(key=lambda t: t[0])
    return total, [row for _, row in ranked] + unranked


def _star_member(
    session: Session,
    radii: dict[int, dict],
    gms: dict[int, float],
    orientation: dict[int, dict],
) -> NotableObject | None:
    """The Sun — pinned first on the Solar System root page."""
    row = (
        session.query(Object.id, Object.naif_id, Object.wikidata_qid, Object.name)
        .filter(Object.object_type == ObjectType.star)
        .order_by(Object.naif_id)
        .first()
    )
    return (
        _body_member(*row, radii=radii, gms=gms, orientation=orientation)
        if row is not None
        else None
    )


def _solar_system_members(
    session: Session,
    star: NotableObject | None,
    radii: dict[int, dict],
    gms: dict[int, float],
    orientation: dict[int, dict],
) -> list[NotableObject]:
    """Sun first, then the most-linked bodies (same image/sitelinks proxy)."""
    # +1 so pinning the Sun first can't drop the last ranked body.
    members = _ranked_members(
        session,
        Object.object_type != ObjectType.barycenter,
        NOTABLE_COUNT + 1,
        radii,
        gms,
        orientation,
    )
    if star is not None:
        members = [star] + [m for m in members if m.object_id != star.object_id]
    return members[:NOTABLE_COUNT]


def _probe_members(
    session: Session,
    radii: dict[int, dict],
    gms: dict[int, float],
    orientation: dict[int, dict],
) -> tuple[list[NotableObject], int]:
    """The notable probes (most-linked first) plus the total probe count.

    Probes are SPICE-tracked interplanetary spacecraft (``spice_probe``); Earth
    satellites are also ``spacecraft``-typed but belong to the Satellites tree.
    """
    is_probe = Object.orbital_source == OrbitalSource.spice_probe
    total = session.query(func.count(Object.id)).filter(is_probe).scalar() or 0
    return (
        _ranked_members(session, is_probe, NOTABLE_COUNT, radii, gms, orientation),
        total,
    )


def build_category_data(
    session: Session,
    member_counts: dict[str, int],
    named_counts: dict[str, int],
    discovery_histograms: dict[str, dict[int, int]],
    launch_histograms: dict[str, dict[int, int]],
    radii: dict[int, dict],
    gms: dict[int, float],
    orientation: dict[int, dict],
    entities: WikidataEntityCache,
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

    units = UnitConverter(entities)
    planet_members = _planet_members(session, radii, gms, orientation)
    dwarf_members = _dwarf_planet_members(
        session, radii, gms, orientation, entities, units
    )
    moon_members = _ranked_members(
        session,
        Object.object_type == ObjectType.moon,
        TOP_MOONS,
        radii,
        gms,
        orientation,
    )
    star = _star_member(session, radii, gms, orientation)
    probe_members, probes_total = _probe_members(session, radii, gms, orientation)
    moons_total, moon_counts = _moon_data(session)

    children = {
        # Satellites is reachable under Earth (its real parent), not the root.
        SOLAR_SYSTEM_SLUG: [
            PLANETS_SLUG,
            DWARF_PLANETS_SLUG,
            MOONS_SLUG,
            ASTEROIDS_SLUG,
            COMETS_SLUG,
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
        + moons_total
        + asteroids_total
        + comets_total
        + satellites_total
        + probes_total,
        ASTEROIDS_SLUG: asteroids_total,
        COMETS_SLUG: comets_total,
        SATELLITES_SLUG: satellites_total,
        PLANETS_SLUG: len(planet_members),
        # Dwarf planets are SBDB-tracked, so they already fall inside
        # asteroids_total (their orbit classes) — counted here for the page's own
        # tally, but not re-added to the root total above.
        DWARF_PLANETS_SLUG: len(dwarf_members),
        MOONS_SLUG: moons_total,
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

    # Category lineup heroes: the most prominent asteroids / comets across all
    # their orbit classes. Dwarf planets are excluded from Asteroids (they keep
    # their own page and still rank inside their orbit-class zone, e.g. Ceres in
    # the Main Belt); comets have no dwarfs to exclude.
    asteroid_notable = _notable_members(
        session,
        SBDB.class_.not_in(COMET_ORBIT_CLASSES),
        Object.object_type.is_distinct_from(ObjectType.dwarf_planet),
        radii=radii,
        units=units,
        wikidata_entities=entities,
    )
    comet_notable = _notable_members(
        session,
        SBDB.class_.in_(COMET_ORBIT_CLASSES),
        radii=radii,
        units=units,
        wikidata_entities=entities,
    )

    notable_members: dict[str, list[NotableObject]] = {}
    if planet_members:
        notable_members[PLANETS_SLUG] = planet_members
    if dwarf_members:
        notable_members[DWARF_PLANETS_SLUG] = dwarf_members
    if moon_members:
        notable_members[MOONS_SLUG] = moon_members
    if asteroid_notable:
        notable_members[ASTEROIDS_SLUG] = asteroid_notable
    if comet_notable:
        notable_members[COMETS_SLUG] = comet_notable
    if probe_members:
        notable_members[PROBES_SLUG] = probe_members
    solar_system = _solar_system_members(session, star, radii, gms, orientation)
    if solar_system:
        notable_members[SOLAR_SYSTEM_SLUG] = solar_system
    logger.info(
        "Built category data: planets=%d, dwarf planets=%d, moons=%d (%d notable, "
        "%d planet/dwarf hosts), asteroid zones=%d, comet families=%d, satellite "
        "groups=%d, probes=%d",
        len(planet_members),
        len(dwarf_members),
        moons_total,
        len(moon_members),
        len(moon_counts),
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
        moon_counts={MOONS_SLUG: moon_counts} if moon_counts else {},
    )
