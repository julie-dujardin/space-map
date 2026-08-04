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
    SURFACE_FEATURES_SLUG,
    ASTEROIDS_SLUG,
    COMET_ORBIT_CLASSES,
    COMETS_SLUG,
    DEBRIS_SLUG,
    DWARF_PLANETS_SLUG,
    MOONS_SLUG,
    PLANETS_SLUG,
    PROBES_SLUG,
    RING_SYSTEMS_SLUG,
    SATELLITES_SLUG,
    SOLAR_SYSTEM_SLUG,
)
from space_map_data.constants.rings.catalog import RING_CATALOGS
from space_map_data.constants.earth_sats.constellations import (
    CONSTELLATION_SLUG_PREFIX,
    DEBRIS_CONSTELLATION_SLUGS,
)
from space_map_data.constants.earth_sats.orbit_class import EarthOrbitClass
from space_map_data.export.groups.earth_sat import EarthOrbitClassStats
from space_map_data.export.groups.registry import (
    CLASS_SLUG_PREFIX,
    SMALL_BODY_FLAG_SLUG_PREFIX,
    GROUPS,
    GroupType,
)
from space_map_data.export.groups.membership import GroupSatcatStats
from space_map_data.export.groups.small_body import LargestBody, _notable_members
from space_map_data.export.groups.stats import GroupExtraStats
from space_map_data.export.notable import NotableObject, render_geometry
from space_map_data.export.small_body_color import (
    resolve_moon_color,
    resolve_small_body_color,
)
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
# Same treatment for the Debris page's two child lists (97 launch-vehicle
# families, 15 curated breakup clouds).
TOP_LAUNCH_VEHICLES = 12

# Notable members shown on the Solar System root (Sun + top bodies). Sized so the
# members-tab sphere lineup fills 3 pages of 8.
NOTABLE_COUNT = 20
SOLAR_SYSTEM_NOTABLE_COUNT = 24

# Moons page hero — the most prominent (5 paginated pages of 5 in the frontend
# lineup). Asteroids will reuse this selector.
TOP_MOONS = 25

_PLANET_TYPES = (ObjectType.planet, ObjectType.dwarf_planet)


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
    # A category's headline member, inherited from whichever child group holds
    # it (asteroid/comet classes) or ranked from PCK radii (planets, moons).
    largest_bodies: dict[str, LargestBody] = field(default_factory=dict)
    # Hazardous tally for the Asteroids page, mirroring the orbit-class cards.
    pha_counts: dict[str, int] = field(default_factory=dict)
    # Active/decayed roll-ups for the two Earth categories, in the same shape
    # the membership-backed groups produce.
    satcat_stats: dict[str, GroupSatcatStats] = field(default_factory=dict)
    extra_stats: dict[str, GroupExtraStats] = field(default_factory=dict)
    # cat slug -> bar-chart rows (moons per planet/dwarf, distance-ordered).
    moon_counts: dict[str, list[dict]] = field(default_factory=dict)
    # cat slug -> {bare constellation slug: fleet size}; the Satellites page's
    # top-constellations bar chart and the Debris page's top-sources one (the
    # bundle ranks + caps the list).
    constellation_counts: dict[str, dict[str, int]] = field(default_factory=dict)


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
        # Tints textureless moons in the Moons-page lineup; None (so the frontend
        # tint stands) for planets/dwarfs and unmeasured moons.
        color=resolve_moon_color(naif_id)[0],
    )


def _largest_by_radius(
    session: Session, where, radii: dict[int, dict]
) -> LargestBody | None:
    """Biggest body matching ``where``, by mean PCK radius.

    The small-body categories inherit a measured SBDB diameter from their
    classes; the major bodies have no SBDB row, so their size comes from the
    same PCK radii the renderer uses. Triaxial bodies average their axes.
    """
    best: LargestBody | None = None
    rows = session.query(Object.id, Object.naif_id, Object.name).filter(where).all()
    for obj_id, naif_id, name in rows:
        axes = radii.get(naif_id) if naif_id is not None else None
        if not axes:
            continue
        mean_radius = sum(axes[k] for k in ("a", "b", "c")) / 3
        if best is None or mean_radius * 2 > best.diameter_km:
            best = LargestBody(
                name=name or obj_id,
                diameter_km=mean_radius * 2,
                primary_id=obj_id,
                primary_type="object",
            )
    if best is None:
        logger.info(
            "No PCK radius for any of the %d bodies matching %s; no largest card",
            len(rows),
            where,
        )
    return best


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


@dataclass
class MoonTallies:
    """Moon counts behind the Moons page's chart and the three moon stat cards."""

    total: int = 0
    # Bar-chart rows, ordered by the host's heliocentric distance.
    rows: list[dict] = field(default_factory=list)
    # Hosts that actually have a moon (Mercury/Venus keep a bar, at zero).
    host_count: int = 0
    planet_moons: int = 0
    dwarf_moons: int = 0


def _moon_data(session: Session, planet_elements: dict[int, dict]) -> MoonTallies:
    """Total moon count + per-planet/dwarf tallies for the Moons-page bar chart.

    A moon's host is its parent planet/dwarf; parents that are barycenters
    defer to their planet/dwarf child (mirrors export/objects/moons.py). All
    eight major planets always get a bar (Mercury/Venus included, at zero);
    dwarf planets get one only when they host a moon. Asteroid moons still
    count toward the total but have no chart row. Rows are ordered by
    heliocentric distance (SBDB.a for dwarfs, the Horizons mean-element table
    for the SBDB-less major planets/Pluto). Each row is the bundle wire shape:
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
        au = (
            planet_elements.get(r.naif_id, {}).get("a")
            if r.naif_id is not None
            else None
        )
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
    rows = [row for _, row in ranked] + unranked
    return MoonTallies(
        total=total,
        rows=rows,
        host_count=sum(1 for row in rows if row["n"]),
        planet_moons=sum(host_counts.get(r.id, 0) for r in planet_rows),
        # Dwarf hosts are already filtered to the ones with a moon; asteroid
        # moons (in ``total``, charted nowhere) are excluded by construction.
        dwarf_moons=sum(host_counts.get(r.id, 0) for r in dwarf_rows),
    )


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
        SOLAR_SYSTEM_NOTABLE_COUNT + 1,
        radii,
        gms,
        orientation,
    )
    if star is not None:
        members = [star] + [m for m in members if m.object_id != star.object_id]
    return members[:SOLAR_SYSTEM_NOTABLE_COUNT]


def _ring_system_members(
    session: Session,
    radii: dict[int, dict],
    gms: dict[int, float],
    orientation: dict[int, dict],
) -> list[NotableObject]:
    """Every body the ring catalogue covers, in its curated order.

    Not a query with a ranking: the eight are exactly the bodies
    ``RING_CATALOGS`` holds a table for, and the catalogue already orders them
    the way the page should read — the four giants outward, then the four
    small bodies whose rings are known only from occultations.
    """
    rows = {
        obj_id: (obj_id, naif_id, qid, name)
        for obj_id, naif_id, qid, name in session.query(
            Object.id, Object.naif_id, Object.wikidata_qid, Object.name
        ).filter(Object.id.in_(sorted(RING_CATALOGS)))
    }
    if missing := [body for body in RING_CATALOGS if body not in rows]:
        logger.warning(
            "Ring systems: %d catalogued bodies are not in the object table, "
            "no tile for them: %s",
            len(missing),
            ", ".join(missing),
        )
    return [
        _body_member(*rows[body], radii=radii, gms=gms, orientation=orientation)
        for body in RING_CATALOGS
        if body in rows
    ]


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


def _is_debris_constellation(group_slug: str) -> bool:
    """Whether a ``const-`` group is a breakup cloud rather than a fleet."""
    bare = group_slug.removeprefix(CONSTELLATION_SLUG_PREFIX)
    return bare in DEBRIS_CONSTELLATION_SLUGS


def build_category_data(
    session: Session,
    member_counts: dict[str, int],
    feature_type_counts: dict[str, int],
    named_counts: dict[str, int],
    discovery_histograms: dict[str, dict[int, int]],
    largest_bodies: dict[str, LargestBody],
    earth_orbit: EarthOrbitClassStats,
    radii: dict[int, dict],
    gms: dict[int, float],
    orientation: dict[int, dict],
    entities: WikidataEntityCache,
    planet_elements: dict[int, dict],
) -> CategoryData:
    """Assemble category children + planet members + per-category counts.

    ``member_counts`` is the flattened ``{slug: n}`` for all non-category
    groups; used to drop empty zones and rank constellations.
    ``feature_type_counts`` is ``{ft- slug: feature count}``; it fills the
    Surface Features browse node, whose children are the feature-type pages.
    ``discovery_histograms`` and ``largest_bodies`` are keyed by small-body
    class slug and rolled up over the orbit classes that partition each
    category. ``earth_orbit`` supplies the same roll-up for Earth orbiters,
    already split payload/debris so Satellites and Debris each get their own
    totals and launch chart.
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

    def by_count(slugs) -> list[str]:
        return sorted(slugs, key=lambda s: (-member_counts.get(s, 0), s))

    # Breakup clouds belong to the Debris page, not the Satellites one, so the
    # two constellation lists partition the same group type.
    constellation_slugs = [
        g.slug for g in GROUPS if g.type is GroupType.CONSTELLATION and nonempty(g.slug)
    ]
    constellations = by_count(
        s for s in constellation_slugs if not _is_debris_constellation(s)
    )[:TOP_CONSTELLATIONS]
    debris_clouds = by_count(
        s for s in constellation_slugs if _is_debris_constellation(s)
    )
    launch_vehicles = by_count(
        g.slug
        for g in GROUPS
        if g.type is GroupType.LAUNCH_VEHICLE and nonempty(g.slug)
    )[:TOP_LAUNCH_VEHICLES]
    satellites = earth_classes + constellations
    # Spent stages (lv-) and breakup clouds (const-) are the two ways an object
    # ends up here, so the Debris page lists both.
    debris_children = debris_clouds + launch_vehicles
    # The same fleets feed the Satellites page's top-constellations bar chart
    # (keyed bare for _constellation_refs, which ranks + caps them); the chips
    # are hidden there in favour of it. Debris ranks by where the fragments came
    # from, which the scan counted per object rather than per zone.
    satellite_constellation_counts = {
        slug.removeprefix(CONSTELLATION_SLUG_PREFIX): member_counts.get(slug, 0)
        for slug in constellations
    }

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
    ring_members = _ring_system_members(session, radii, gms, orientation)
    star = _star_member(session, radii, gms, orientation)
    probe_members, probes_total = _probe_members(session, radii, gms, orientation)
    moons = _moon_data(session, planet_elements)
    moons_total, moon_counts = moons.total, moons.rows

    # Most-populated type first: with 57 chips, alphabetical would bury craters.
    feature_types = sorted(
        (slug for slug, n in feature_type_counts.items() if n > 0),
        key=lambda slug: (-feature_type_counts[slug], slug),
    )
    children = {
        # Satellites is reachable under Earth (its real parent), not the root.
        SOLAR_SYSTEM_SLUG: [
            PLANETS_SLUG,
            DWARF_PLANETS_SLUG,
            MOONS_SLUG,
            RING_SYSTEMS_SLUG,
            ASTEROIDS_SLUG,
            COMETS_SLUG,
            PROBES_SLUG,
            SURFACE_FEATURES_SLUG,
        ],
        ASTEROIDS_SLUG: asteroids,
        COMETS_SLUG: comets,
        SATELLITES_SLUG: satellites,
        DEBRIS_SLUG: debris_children,
        SURFACE_FEATURES_SLUG: feature_types,
    }
    # Object totals, not child counts: orbit classes partition their bodies, so
    # summing is exact; flags are subsets, and satellites sum shape classes only.
    asteroids_total = sum(member_counts.get(s, 0) for s in asteroid_classes)
    asteroids_named = sum(named_counts.get(s, 0) for s in asteroid_classes)
    comets_total = sum(member_counts.get(s, 0) for s in comet_classes)
    # Primary shape classes partition the Earth orbiters; the payload/debris
    # split makes each object land in exactly one of the two categories.
    primary_sat_slugs = [
        f"{CLASS_SLUG_PREFIX}{c.name}" for c in EarthOrbitClass if c.primary
    ]
    satellites_total = sum(
        earth_orbit.payload_counts.get(s, 0) for s in primary_sat_slugs
    )
    debris_total = sum(earth_orbit.debris_counts.get(s, 0) for s in primary_sat_slugs)
    member_counts_out = {
        # The root counts every categorized object across the solar system.
        SOLAR_SYSTEM_SLUG: len(planet_members)
        + moons_total
        + asteroids_total
        + comets_total
        + satellites_total
        + debris_total
        + probes_total,
        ASTEROIDS_SLUG: asteroids_total,
        COMETS_SLUG: comets_total,
        SATELLITES_SLUG: satellites_total,
        DEBRIS_SLUG: debris_total,
        PLANETS_SLUG: len(planet_members),
        # Dwarf planets are SBDB-tracked, so they already fall inside
        # asteroids_total (their orbit classes) — counted here for the page's own
        # tally, but not re-added to the root total above.
        DWARF_PLANETS_SLUG: len(dwarf_members),
        MOONS_SLUG: moons_total,
        # The ringed bodies are counted by their own categories too, so this
        # tally stays out of the root total.
        RING_SYSTEMS_SLUG: len(ring_members),
        PROBES_SLUG: probes_total,
        # Features aren't objects, so this tally stays out of the root total.
        SURFACE_FEATURES_SLUG: sum(feature_type_counts.values()),
    }

    # Discovery/launch charts: sum the histograms over the classes that
    # partition each category (flags are subsets, so they're excluded; the two
    # Earth categories sum only the primary shape classes — same partition as
    # their totals above).
    discovery_out: dict[str, dict[int, int]] = {}
    if asteroid_hist := _sum_histograms(asteroid_classes, discovery_histograms):
        discovery_out[ASTEROIDS_SLUG] = asteroid_hist
    if comet_hist := _sum_histograms(comet_classes, discovery_histograms):
        discovery_out[COMETS_SLUG] = comet_hist
    launch_out: dict[str, dict[int, int]] = {}
    for cat_slug, side in (
        (SATELLITES_SLUG, earth_orbit.payload_satcat_stats),
        (DEBRIS_SLUG, earth_orbit.debris_satcat_stats),
    ):
        per_slug = {
            slug: s.launch_histogram for slug, s in side.items() if s.launch_histogram
        }
        if hist := _sum_histograms(primary_sat_slugs, per_slug):
            launch_out[cat_slug] = hist

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
    if ring_members:
        notable_members[RING_SYSTEMS_SLUG] = ring_members
    if asteroid_notable:
        notable_members[ASTEROIDS_SLUG] = asteroid_notable
    if comet_notable:
        notable_members[COMETS_SLUG] = comet_notable
    if probe_members:
        notable_members[PROBES_SLUG] = probe_members
    solar_system = _solar_system_members(session, star, radii, gms, orientation)
    if solar_system:
        notable_members[SOLAR_SYSTEM_SLUG] = solar_system

    # Stat cards. The small-body categories inherit the biggest member of any
    # class that partitions them; the major-body ones rank PCK radii. Flags are
    # excluded — a subset can't hold a body its own class doesn't.
    def _largest_of(class_slugs: list[str]) -> LargestBody | None:
        candidates = [b for s in class_slugs if (b := largest_bodies.get(s))]
        return max(candidates, key=lambda b: b.diameter_km, default=None)

    largest_out: dict[str, LargestBody | None] = {
        ASTEROIDS_SLUG: _largest_of(asteroid_classes),
        COMETS_SLUG: _largest_of(comet_classes),
        PLANETS_SLUG: _largest_by_radius(
            session, Object.object_type == ObjectType.planet, radii
        ),
        DWARF_PLANETS_SLUG: _largest_by_radius(
            session, Object.object_type == ObjectType.dwarf_planet, radii
        ),
        MOONS_SLUG: _largest_by_radius(
            session, Object.object_type == ObjectType.moon, radii
        ),
    }
    # The Asteroids page mirrors its classes' hazardous card, over the whole
    # category; the flag group is the same population, so its total is exact.
    pha_total = member_counts.get(f"{SMALL_BODY_FLAG_SLUG_PREFIX}pha", 0)

    # How much of the fleet still works, over the primary shape classes (they
    # partition the population, so summing double-counts nothing). Debris gets
    # no such card: the handful of fragments SATCAT still calls operational is
    # a data lag, not a fact about the population.
    payloads = earth_orbit.payload_satcat_stats
    satcat_out = {
        SATELLITES_SLUG: GroupSatcatStats(
            active=sum(payloads[s].active for s in primary_sat_slugs if s in payloads)
        )
    }

    extra_stats = {
        PLANETS_SLUG: GroupExtraStats(moon_total=moons.planet_moons),
        DWARF_PLANETS_SLUG: GroupExtraStats(moon_total=moons.dwarf_moons),
        MOONS_SLUG: GroupExtraStats(host_count=moons.host_count),
        # Every breakup and spent stage the fragments trace back to. The chart
        # below ranks them; only the tally says how long the tail is.
        DEBRIS_SLUG: GroupExtraStats(
            child_group_count=len(earth_orbit.debris_source_counts)
        ),
    }
    logger.info(
        "Built category data: planets=%d, dwarf planets=%d, moons=%d (%d notable, "
        "%d planet/dwarf hosts), ring systems=%d, asteroid zones=%d, comet "
        "families=%d, satellite groups=%d (%d payloads), debris groups=%d "
        "(%d pieces from %d sources), probes=%d",
        len(planet_members),
        len(dwarf_members),
        moons_total,
        len(moon_members),
        len(moon_counts),
        len(ring_members),
        len(asteroids),
        len(comets),
        len(satellites),
        satellites_total,
        len(debris_children),
        debris_total,
        len(earth_orbit.debris_source_counts),
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
        largest_bodies={s: b for s, b in largest_out.items() if b},
        pha_counts={ASTEROIDS_SLUG: pha_total} if pha_total else {},
        satcat_stats=satcat_out,
        extra_stats=extra_stats,
        moon_counts={MOONS_SLUG: moon_counts} if moon_counts else {},
        constellation_counts={
            slug: counts
            for slug, counts in (
                (SATELLITES_SLUG, satellite_constellation_counts),
                (DEBRIS_SLUG, earth_orbit.debris_source_counts),
            )
            if counts
        },
    )
