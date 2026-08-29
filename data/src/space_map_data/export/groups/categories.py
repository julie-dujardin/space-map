"""Category contents: child-group lists, planet members, and member counts.

Categories (constants/categories.py) are Wikidata-backed browse nodes. Members
are child groups (asteroid zones, comet families, satellite classes, largest
constellations) or bodies (Planets, Moons, Probes) — the former feed
``child_groups``, the latter ride ``notable_members``.
"""

import datetime
import logging
from dataclasses import dataclass, field, replace

from sqlalchemy import func
from sqlalchemy.orm import Session

from space_map_data.constants.categories import (
    SURFACE_FEATURES_SLUG,
    ASTEROIDS_SLUG,
    ATMOSPHERES_SLUG,
    COMET_ORBIT_CLASSES,
    COMETS_SLUG,
    DEBRIS_SLUG,
    DWARF_PLANETS_SLUG,
    MOONS_SLUG,
    OCEANS_SLUG,
    PLANETARY_SYSTEMS_SLUG,
    PLANETS_SLUG,
    PROBES_SLUG,
    RING_SYSTEMS_SLUG,
    SATELLITES_SLUG,
    SOLAR_SYSTEM_SLUG,
    STRUCTURE_ACTIVITY_SLUG,
    VOLCANISM_SLUG,
    TECTONICS_SLUG,
    MAGNETIC_FIELDS_SLUG,
    TIDAL_HEATING_SLUG,
    RADIATION_SLUG,
)
from space_map_data.constants.atmosphere.facts import ATMOSPHERE_FACTS
from space_map_data.constants.atmosphere.structure import (
    ATMOSPHERE_STRUCTURE,
    CAPPED_ROLES,
)
from space_map_data.constants.activity.magnetism import MAGNETIC_FIELDS
from space_map_data.constants.activity.tidal import TIDAL_HEATING
from space_map_data.constants.activity.volcanism import GEOLOGIC_ACTIVITY
from space_map_data.constants.interior.bodies import INTERIOR_FACTS
from space_map_data.constants.radiation.environments import RADIATION_ENVIRONMENTS
from space_map_data.constants.rings.catalog import RING_CATALOGS, catalog_span_km
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
from space_map_data.export.objects.missions import probe_launch_year
from space_map_data.export.objects.activity import collection_row
from space_map_data.export.objects.atmosphere import limb_profile, pressure_block
from space_map_data.export.objects.interior import cutaway_layers, ocean_block
from space_map_data.export.objects import radiation
from space_map_data.export.objects.rings import ring_catalog_sources, ring_mass_block
from space_map_data.export.objects.temperature import heliocentric_distance_au
from space_map_data.export.small_body_color import (
    resolve_moon_color,
    resolve_small_body_color,
)
from space_map_data.export.objects.wikidata_claims import (
    diameter_km_from_claims,
    discovery_year_from_claims,
    radius_km_from_claims,
)
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.ingest.providers.objects.sbdb import G_KM3_PER_KG_S2
from space_map_data.models.object.main import Object, ObjectType, OrbitalSource
from space_map_data.models.object.sbdb import SBDB, OrbitClass
from space_map_data.models.object.sbdb_moon import SBDBMoon
from space_map_data.probes.probe_id import load_registry

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


def _merge_histograms(*histograms: dict[int, int]) -> dict[int, int]:
    """Add year histograms that come from different member sets."""
    out: dict[int, int] = {}
    for histogram in histograms:
        for year, n in histogram.items():
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

    Major bodies have no SBDB row, so size comes from the same PCK radii the
    renderer uses; triaxial bodies average their axes.
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
    """Top ``limit`` bodies for a hero strip: image-bearing first, then sitelinks
    (prominence proxy), id as tiebreak. Shared by every notable strip except
    fixed lineups; the Probes page and Solar System root layer their own
    filter/pin on top.
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


def _planetary_system_members(
    session: Session,
    radii: dict[int, dict],
    gms: dict[int, float],
    orientation: dict[int, dict],
) -> list[NotableObject]:
    """One member per barycenter with a moon, in heliocentric order. Each
    routes to the barycenter page but carries its primary's QID and images:
    the barycenter has neither a photograph nor a label anyone would search
    for, and the frontend titles the member "<primary> system" off the label.
    """
    barycenters = {
        bary_id: naif_id
        for bary_id, naif_id in session.query(Object.id, Object.naif_id).filter(
            Object.object_type == ObjectType.barycenter
        )
    }
    with_moons = {
        parent_id
        for (parent_id,) in session.query(Object.parent_id)
        .filter(
            Object.object_type == ObjectType.moon, Object.parent_id.in_(barycenters)
        )
        .distinct()
    }
    hosts = (
        session.query(
            Object.parent_id,
            Object.id,
            Object.naif_id,
            Object.wikidata_qid,
            Object.name,
        )
        .filter(Object.object_type.in_(_PLANET_TYPES), Object.parent_id.in_(with_moons))
        .all()
    )
    members = []
    for bary_id, host_id, naif_id, qid, name in hosts:
        host = _body_member(
            host_id, naif_id, qid, name, radii=radii, gms=gms, orientation=orientation
        )
        members.append(replace(host, object_id=bary_id, image_of=host_id))
    members.sort(key=lambda m: barycenters[m.object_id] or 0)
    return members


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
    """The dwarf planets, most-prominent first (image then sitelinks) — unlike
    the eight majors they have no static heliocentric order. Lineup size comes
    from each body's Wikidata diameter; none are in the PCK that sizes
    planets/moons.
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


def _wikidata_discovery_histogram(
    members: list[NotableObject], entities: WikidataEntityCache
) -> dict[int, int]:
    """Discoveries per year over a body list, from each member's Wikidata P575.

    For bodies the JPL satellite table doesn't cover and whose SBDB arc starts
    on a precovery plate — the dwarf planets — Wikidata is the only date that
    means "discovered".
    """
    histogram: dict[int, int] = {}
    for member in members:
        entity = (
            entities.get_entity(member.wikidata_qid) if member.wikidata_qid else None
        )
        year = (
            discovery_year_from_claims(entity["claims"], entities)
            if entity is not None
            else None
        )
        if year is None:
            logger.warning(
                "No discovery date for %s (%s); it won't count in the timeline",
                member.object_id,
                member.wikidata_qid,
            )
            continue
        histogram[year] = histogram.get(year, 0) + 1
    return histogram


def moon_discovery_rows(session: Session) -> list[tuple[str, int]]:
    """Every dated moon as ``(host id, discovery year)``.

    The JPL satellite-discovery table covers the moons with an IAU name; SBDB's
    satellite records carry the provisional ones, and the two agree wherever
    they overlap. The host is the moon's parent, which for a planetary moon is
    its system barycenter — see `groups/moon_discovery.py`, which splits these
    rows per system.
    """
    rows = (
        session.query(Object.parent_id, Object.discovery_year, SBDBMoon.year)
        .outerjoin(SBDBMoon, SBDBMoon.object_id == Object.id)
        .filter(Object.object_type == ObjectType.moon)
        .all()
    )
    dated: list[tuple[str, int]] = []
    undated = 0
    for parent_id, jpl_year, sbdb_year in rows:
        year = jpl_year if jpl_year is not None else sbdb_year
        if year is None:
            undated += 1
            continue
        dated.append((parent_id, year))
    if undated:
        logger.info("%d moons carry no discovery year", undated)
    return dated


def _moon_discovery_histogram(session: Session) -> dict[int, int]:
    """Moons per year of discovery, across every host."""
    histogram: dict[int, int] = {}
    for _, year in moon_discovery_rows(session):
        histogram[year] = histogram.get(year, 0) + 1
    return histogram


def _ring_discovery_histogram(members: list[NotableObject]) -> dict[int, int]:
    """Ring systems per year of discovery, over the bodies the page tiles.

    Scoped to `members` like the stat row: a catalogued body with no object row
    gets no tile, so it should not sit in the chart either.
    """
    shown = {member.object_id for member in members}
    histogram: dict[int, int] = {}
    for body, catalog in RING_CATALOGS.items():
        if body not in shown or catalog.discovery_year is None:
            continue
        year = catalog.discovery_year
        histogram[year] = histogram.get(year, 0) + 1
    return histogram


def _probe_launch_histogram(session: Session) -> dict[int, int]:
    """Probes per launch year, over the craft the page counts.

    The registry runs wider than the export (craft we carry no kernel for), so
    it is filtered to the SPICE-tracked objects. Missions still on the pad are
    dropped: the chart records what has flown, and its cumulative line would
    otherwise count craft that have not launched.
    """
    probe_ids = {
        obj_id
        for (obj_id,) in session.query(Object.id).filter(
            Object.orbital_source == OrbitalSource.spice_probe
        )
    }
    this_year = datetime.date.today().year
    histogram: dict[int, int] = {}
    planned = 0
    for entry in load_registry():
        if f"probe-{entry['probe_id']}" not in probe_ids:
            continue
        year = probe_launch_year(entry.get("inception_mjd"))
        if year is None:
            continue
        if year > this_year:
            planned += 1
            continue
        histogram[year] = histogram.get(year, 0) + 1
    if planned:
        logger.info("%d probes are not launched yet; left out of the timeline", planned)
    return histogram


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

    Barycenter parents defer to their planet/dwarf child. All eight major
    planets always get a bar (even at zero); dwarf planets only when they host
    a moon. Asteroid moons count toward the total but get no row. Rows order by
    heliocentric distance (SBDB.a for dwarfs, Horizons elements for the
    SBDB-less majors).
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
    """Every body the ring catalogue covers, in its curated order (giants
    outward, then occultation-only bodies) — not ranked, the catalogue already
    reads right. Each member carries its ring mass separately; ``_body_member``
    attaches the planet's mass, not the rings'.
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
        replace(
            _body_member(*rows[body], radii=radii, gms=gms, orientation=orientation),
            ring_mass=ring_mass_block(body),
        )
        for body in RING_CATALOGS
        if body in rows
    ]


def _ring_system_stats(members: list[NotableObject]) -> GroupExtraStats:
    """The Ring Systems page's stat row: catalogue depth, span and discovery
    year, none of it restated by the tiles/chart below. Names come from the
    members rather than Wikidata, like ``largest_body`` — the card links to a
    body, not a piece of prose.
    """
    names = {member.object_id: member.fallback_name for member in members}
    widest: dict | None = None
    for body, catalog in RING_CATALOGS.items():
        span = catalog_span_km(catalog)
        if span is None or body not in names:
            continue
        if widest is None or span > widest["span_km"]:
            widest = {
                "primary_type": "object",
                "primary_id": body,
                "name": names[body],
                "span_km": span,
            }
    years = [
        catalog.discovery_year
        for catalog in RING_CATALOGS.values()
        if catalog.discovery_year is not None
    ]
    return GroupExtraStats(
        discovery_year=min(years) if years else None,
        ring_feature_count=sum(len(c.features) for c in RING_CATALOGS.values()),
        widest_rings=widest,
        # Scoped to the systems the page actually lists, like `widest_rings`.
        ring_sources=ring_catalog_sources(m.object_id for m in members) or None,
    )


def _property_members(
    session: Session,
    body_ids: list[str],
    attach,
    page: str,
    radii: dict[int, dict],
    gms: dict[int, float],
    orientation: dict[int, dict],
) -> list[NotableObject]:
    """Members of a Structure & Activity page: exactly the bodies the constants
    hold the property for, already in page order — not a query. A body the
    constants know but the object table doesn't is logged and dropped.
    """
    rows = {
        obj_id: (obj_id, naif_id, qid, name)
        for obj_id, naif_id, qid, name in session.query(
            Object.id, Object.naif_id, Object.wikidata_qid, Object.name
        ).filter(Object.id.in_(sorted(body_ids)))
    }
    if missing := [body for body in body_ids if body not in rows]:
        logger.warning(
            "%s: %d bodies are not in the object table, no tile for them: %s",
            page,
            len(missing),
            ", ".join(missing),
        )
    return [
        attach(
            _body_member(*rows[body], radii=radii, gms=gms, orientation=orientation),
            body,
        )
        for body in body_ids
        if body in rows
    ]


def _atmosphere_members(
    session: Session,
    radii: dict[int, dict],
    gms: dict[int, float],
    orientation: dict[int, dict],
) -> list[NotableObject]:
    """Every body with a measured envelope, thickest first.

    A published pressure is what makes a body a member. The four without —
    Ceres, Enceladus, Dione, Rhea — are exospheres nobody has put a number on,
    and would print "Unknown" on the figure the page ranks by.
    """
    measured = {
        body: facts.pressure
        for body, facts in ATMOSPHERE_FACTS.items()
        if facts.pressure is not None
    }
    logger.info(
        "Atmospheres: %d of %d bodies carry a pressure; dropped %s",
        len(measured),
        len(ATMOSPHERE_FACTS),
        ", ".join(sorted(set(ATMOSPHERE_FACTS) - set(measured))) or "none",
    )

    ordered = sorted(measured, key=lambda body: (-measured[body].pascals, body))

    def attach(member: NotableObject, body: str) -> NotableObject:
        return replace(
            member,
            atmosphere_pressure=pressure_block(measured[body]),
            limb=limb_profile(body),
        )

    return _property_members(
        session, ordered, attach, "Atmospheres", radii, gms, orientation
    )


def _ocean_members(
    session: Session,
    radii: dict[int, dict],
    gms: dict[int, float],
    orientation: dict[int, dict],
) -> list[NotableObject]:
    """Every body with an ocean, largest first.

    Ranked by volume, not depth or share of the body — the one measure the
    nine can be compared on, and the one that puts Earth's ocean fifth.
    """
    oceans = {
        body: block
        for body in INTERIOR_FACTS
        if (block := ocean_block(body)) is not None
    }
    ordered = sorted(oceans, key=lambda body: -oceans[body]["volume_km3"])

    def attach(member: NotableObject, body: str) -> NotableObject:
        return replace(member, ocean=oceans[body], cutaway=cutaway_layers(body))

    return _property_members(
        session, ordered, attach, "Oceans", radii, gms, orientation
    )


def _atmosphere_stats(members: list[NotableObject]) -> GroupExtraStats:
    """The Atmospheres page's stat row: type count and tallest height, neither
    restating the pressure chart below. Height uses cross-section layers, not
    the exosphere — that would make Earth's the tallest atmosphere at
    10,000 km, a gas too thin to draw.
    """
    names = {member.object_id: member.fallback_name for member in members}
    tallest: dict | None = None
    for body, structure in ATMOSPHERE_STRUCTURE.items():
        if body not in names:
            continue
        tops = [
            layer.top_km
            for layer in structure.layers
            if layer.top_km is not None and layer.role not in CAPPED_ROLES
        ]
        if not tops:
            continue
        if tallest is None or max(tops) > tallest["km"]:
            tallest = {
                "primary_type": "object",
                "primary_id": body,
                "name": names[body],
                "km": max(tops),
            }
    return GroupExtraStats(
        atmosphere_type_count=len(
            {ATMOSPHERE_FACTS[body].atmosphere_type for body in names}
        ),
        tallest_atmosphere=tallest,
    )


def _ocean_stats(members: list[NotableObject]) -> GroupExtraStats:
    """The Oceans page's stat row: total volume and deepest ocean. The total is
    the point — the nine oceans hold forty times Earth's alone — and a
    log-axis chart can't show a sum; depth isn't what it ranks by either.
    """
    deepest: dict | None = None
    total = 0.0
    for member in members:
        if member.ocean is None:
            continue
        total += member.ocean["volume_km3"]
        if deepest is None or member.ocean["thickness_km"] > deepest["thickness_km"]:
            deepest = {
                "primary_type": "object",
                "primary_id": member.object_id,
                "name": member.fallback_name,
                "thickness_km": member.ocean["thickness_km"],
            }
    return GroupExtraStats(
        ocean_volume_km3=total or None,
        deepest_ocean=deepest,
    )


def _activity_members(
    session: Session,
    table: dict,
    rank,
    page: str,
    radii: dict[int, dict],
    gms: dict[int, float],
    orientation: dict[int, dict],
) -> list[NotableObject]:
    """Members of one of the three heat pages, ordered by what its chart plots.
    All three read one `collection_row` — a body is usually on more than one —
    and the cutaway rides along everywhere, since these pages describe what
    happens inside the body.
    """

    def attach(member: NotableObject, body: str) -> NotableObject:
        return replace(
            member, activity=collection_row(body), cutaway=cutaway_layers(body)
        )

    return _property_members(
        session, sorted(table, key=rank), attach, page, radii, gms, orientation
    )


def _measured_first(value: float | None, body: str) -> tuple[int, float, str]:
    """Sort key: bodies with a figure first and largest, then the rest.

    A leading flag rather than a sentinel — these quantities span ten decades,
    so no number reliably sorts under all of them.
    """
    return (1, 0.0, body) if value is None else (0, -value, body)


RUNGS = {"active": 0, "probable": 1, "suspected": 2, "dormant": 3, "extinct": 4}


def _volcanism_members(session, radii, gms, orientation) -> list[NotableObject]:
    """Every body with a geologic record, most recently active first. Ordered
    by status, not a number: only a few of the fifteen have a heat output or
    vent count, so what separates them is whether anyone caught them at it.
    """
    rungs = RUNGS
    return _activity_members(
        session,
        GEOLOGIC_ACTIVITY,
        lambda body: (rungs.get(GEOLOGIC_ACTIVITY[body].volcanism.status, 9), body),
        "Volcanism",
        radii,
        gms,
        orientation,
    )


def _tectonics_members(session, radii, gms, orientation) -> list[NotableObject]:
    """Every body whose crust anyone has read a tectonic history off (ten of
    volcanism's fifteen lack one). Ordered by the same status ladder, then
    style, so the ice shells sit together — read across styles more than down
    them.
    """
    tectonic = {
        body: facts.tectonics
        for body, facts in GEOLOGIC_ACTIVITY.items()
        if facts.tectonics is not None
    }
    logger.info(
        "Tectonics: %d of %d bodies carry a style; without one: %s",
        len(tectonic),
        len(GEOLOGIC_ACTIVITY),
        ", ".join(sorted(set(GEOLOGIC_ACTIVITY) - set(tectonic))) or "none",
    )
    return _activity_members(
        session,
        tectonic,
        lambda body: (
            RUNGS.get(tectonic[body].status, 9),
            tectonic[body].style,
            body,
        ),
        "Tectonics",
        radii,
        gms,
        orientation,
    )


def _magnetic_members(session, radii, gms, orientation) -> list[NotableObject]:
    """Every body anyone has measured a field on, strongest first. Surface
    field, not dipole moment — the figure a reader can picture standing on the
    body; moment stays in the row for comparison. Having one is also what
    makes a body a member: Venus (only an upper bound) and the Jupiter-induced
    fields on Io/Europa/Callisto are excluded so the page doesn't lead with
    "None detected". Titan stays; its 0.78 nT bound prints as "< 0.78 nT" with
    no bar.
    """
    measured = {
        body: field
        for body, field in MAGNETIC_FIELDS.items()
        if field.surface_field_t is not None
    }
    logger.info(
        "Magnetic fields: %d of %d bodies carry a surface field; dropped %s",
        len(measured),
        len(MAGNETIC_FIELDS),
        ", ".join(sorted(set(MAGNETIC_FIELDS) - set(measured))) or "none",
    )

    def rank(body: str) -> tuple[int, float, str]:
        field = measured[body].surface_field_t
        return _measured_first(field.value if field else None, body)

    return _activity_members(
        session, measured, rank, "Magnetic fields", radii, gms, orientation
    )


def _tidal_members(session, radii, gms, orientation) -> list[NotableObject]:
    """Every body a tide is raised on, hardest-worked first.

    Only three of the eleven have a wattage; the rest order by the role the
    tide plays in their heat budget and carry no bar.
    """
    roles = {"dominant": 0, "significant": 1, "minor": 2, "negligible": 3, "past": 4}

    def rank(body: str) -> tuple[int, float, str]:
        power = TIDAL_HEATING[body].power_w
        if power is not None:
            return (0, -power.value, body)
        return (1, float(roles.get(TIDAL_HEATING[body].role, 9)), body)

    return _activity_members(
        session, TIDAL_HEATING, rank, "Tidal heating", radii, gms, orientation
    )


def radiation_places(session: Session) -> dict[str, radiation.Place]:
    """Where each member of the Radiation page sits, which is what its dose
    depends on.

    Only the parent is looked up, and the semi-major axis is passed as absent:
    every member is a planet or a major moon, so its parent is a barycentre
    with a tabulated distance and the axis would never be consulted. A member
    orbiting the Sun directly would fall through that and get no figure, which
    is why the caller logs the ones that come back placeless.
    """
    parents = {
        body: parent_id
        for body, parent_id in session.query(Object.id, Object.parent_id).filter(
            Object.id.in_(sorted(RADIATION_ENVIRONMENTS))
        )
    }
    return {
        body: radiation.Place(
            parent_id=parents.get(body),
            distance_au=heliocentric_distance_au(None, parents.get(body)),
        )
        for body in RADIATION_ENVIRONMENTS
    }


def _radiation_members(
    session: Session,
    places: dict[str, radiation.Place],
    radii: dict[int, dict],
    gms: dict[int, float],
    orientation: dict[int, dict],
) -> list[NotableObject]:
    """Every place anyone has put a dose on, harshest first.

    A figure is what makes a body a member, the rule the pressure and field
    pages follow. Seven of the fourteen environments on record have one; the
    other seven are known well enough to be classified and not well enough to
    be quoted, and a row reading only "worst in the solar system" beside six
    numbers is a caption, not a member.

    Ranked across both mechanisms even though the charts split them, so the row
    order is one list a reader can read down. The two belt moons take the top
    by five orders of magnitude, which is the honest opening.
    """
    rows = {
        body: row
        for body in RADIATION_ENVIRONMENTS
        if (row := radiation.collection_row(body, places[body])) is not None
    }
    logger.info(
        "Radiation: %d of %d characterised places carry a dose; without one: %s",
        len(rows),
        len(RADIATION_ENVIRONMENTS),
        ", ".join(sorted(set(RADIATION_ENVIRONMENTS) - set(rows))) or "none",
    )
    if placeless := [body for body in rows if places[body].distance_au is None]:
        logger.warning(
            "Radiation: %d members have no heliocentric distance, so no modelled "
            "dose: %s",
            len(placeless),
            ", ".join(sorted(placeless)),
        )

    def rank(body: str) -> tuple[int, float, str]:
        return _measured_first(_row_dose(rows[body]), body)

    def attach(member: NotableObject, body: str) -> NotableObject:
        return replace(member, radiation=rows[body], cutaway=cutaway_layers(body))

    return _property_members(
        session, sorted(rows, key=rank), attach, "Radiation", radii, gms, orientation
    )


def _row_dose(row: dict) -> float | None:
    """The one figure a row plots: published where there is one, modelled where
    there is not — the rule the body's own panel follows."""
    published = row.get("surface_dose")
    if published is not None:
        return published["sv_per_day"]["value"]
    modelled = row.get("modelled_surface_dose")
    return modelled["sv_per_day"] if modelled is not None else None


def _radiation_stats(
    members: list[NotableObject], places: dict[str, radiation.Place]
) -> GroupExtraStats:
    """What the two charts cannot say.

    The quietest surface is on one of them and draws nothing — Venus is nine
    decades under the Moon, so its bar is zero pixels wide and the card is the
    only place its figure reads. The other is the fact about the set: how much
    of it anyone has actually measured, which is three of seven.
    """
    measured: list[str] = []
    quietest: dict | None = None
    for member in members:
        row = member.radiation or {}
        published = row.get("surface_dose")
        if published is not None and not published["sv_per_day"].get("modelled"):
            measured.append(member.fallback_name)
        dose = _row_dose(row)
        if dose is not None and (quietest is None or dose < quietest["sv_per_day"]):
            quietest = {
                "primary_type": "object",
                "primary_id": member.object_id,
                "name": member.fallback_name,
                "sv_per_day": dose,
            }
    return GroupExtraStats(
        radiation_measured=sorted(measured) or None,
        quietest_surface=quietest,
        # Scoped to the members: a bibliography backs what the page shows, and
        # the seven places that lost their row took their citations with them.
        radiation_sources=radiation.collection_sources(
            {member.object_id: places[member.object_id] for member in members}
        )
        or None,
    )


def _volcanism_stats(members: list[NotableObject]) -> GroupExtraStats:
    """Erupting now, the hottest, and every vent anyone has mapped — none
    restating the status-rung chart below. The erupting card names its members
    in the tooltip; the count is small enough a reader will want to know
    which.
    """
    erupting = [
        member.fallback_name
        for member in members
        if (member.activity or {}).get("volcanism", {}).get("status") == "active"
    ]
    hottest: dict | None = None
    centres = 0
    for member in members:
        volcanism = (member.activity or {}).get("volcanism", {})
        centres += int(volcanism.get("known_centres") or 0)
        power = volcanism.get("endogenic_power_w")
        if power is not None and (hottest is None or power > hottest["watts"]):
            hottest = {
                "primary_type": "object",
                "primary_id": member.object_id,
                "name": member.fallback_name,
                "watts": power,
            }
    return GroupExtraStats(
        erupting_now=sorted(erupting) or None,
        hottest_body=hottest,
        known_centres=centres or None,
    )


def _tectonics_stats(members: list[NotableObject]) -> GroupExtraStats:
    """How many kinds of crust there are, and how many are still moving.

    Neither restates the per-style tally chart. Style count is the page's
    finding — five ways a crust can behave across ten bodies.
    """
    styles = set()
    moving = 0
    for member in members:
        tectonics = (member.activity or {}).get("tectonics", {})
        if tectonics.get("style"):
            styles.add(tectonics["style"])
        if tectonics.get("status") == "active":
            moving += 1
    return GroupExtraStats(
        tectonic_style_count=len(styles) or None,
        tectonic_active_count=moving or None,
    )


def _magnetic_stats(members: list[NotableObject]) -> GroupExtraStats:
    """How many generate a field now, and the two extremes of the ones that do.

    The tilt card is the page's best fact: Uranus's dipole is 59° off its
    rotation axis.
    """
    dynamos = 0
    strongest: dict | None = None
    tilted: dict | None = None
    for member in members:
        magnetism = (member.activity or {}).get("magnetism", {})
        if magnetism.get("kind") == "dynamo":
            dynamos += 1
        ref = {
            "primary_type": "object",
            "primary_id": member.object_id,
            "name": member.fallback_name,
        }
        field = magnetism.get("surface_field_t")
        # A non-detection's bound is not a measurement, and the strongest-field
        # card is the one place that distinction would be invisible.
        if (
            field is not None
            and not magnetism.get("surface_field_t_upper_limit")
            and (strongest is None or field > strongest["tesla"])
        ):
            strongest = ref | {"tesla": field}
        tilt = magnetism.get("dipole_tilt_deg")
        if tilt is not None and (tilted is None or tilt > tilted["degrees"]):
            tilted = ref | {"degrees": tilt}
    return GroupExtraStats(
        dynamo_count=dynamos or None,
        strongest_field=strongest,
        most_tilted_field=tilted,
    )


def _tidal_stats(members: list[NotableObject]) -> GroupExtraStats:
    """The hardest-worked tide, and how many bodies the tide is the whole story
    for. Two cards: nothing else here is a fact about the set."""
    strongest: dict | None = None
    dominant = 0
    for member in members:
        tidal = (member.activity or {}).get("tidal", {})
        if tidal.get("role") == "dominant":
            dominant += 1
        power = tidal.get("power_w")
        if power is not None and (strongest is None or power > strongest["watts"]):
            strongest = {
                "primary_type": "object",
                "primary_id": member.object_id,
                "name": member.fallback_name,
                "watts": power,
            }
    return GroupExtraStats(hottest_body=strongest, tide_dominant_count=dominant or None)


def _probe_members(
    session: Session,
    radii: dict[int, dict],
    gms: dict[int, float],
    orientation: dict[int, dict],
) -> tuple[list[NotableObject], int]:
    """The notable probes (most-linked first) plus the total probe count.

    Probes are SPICE-tracked (``spice_probe``); Earth satellites are also
    ``spacecraft``-typed but belong to the Satellites tree.
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

    ``member_counts`` drops empty zones and ranks constellations;
    ``feature_type_counts`` fills Surface Features. ``discovery_histograms``/
    ``largest_bodies`` roll up over each category's orbit classes;
    ``earth_orbit`` gives the same roll-up for Earth orbiters, already split
    payload/debris.
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
    # Same fleets feed the Satellites page's top-constellations bar chart
    # (keyed bare, so the bundle can rank + cap them); chips are hidden there.
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
    atmosphere_members = _atmosphere_members(session, radii, gms, orientation)
    ocean_members = _ocean_members(session, radii, gms, orientation)
    volcanism_members = _volcanism_members(session, radii, gms, orientation)
    tectonics_members = _tectonics_members(session, radii, gms, orientation)
    magnetic_members = _magnetic_members(session, radii, gms, orientation)
    tidal_members = _tidal_members(session, radii, gms, orientation)
    radiation_where = radiation_places(session)
    radiation_members = _radiation_members(
        session, radiation_where, radii, gms, orientation
    )
    star = _star_member(session, radii, gms, orientation)
    system_members = _planetary_system_members(session, radii, gms, orientation)
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
        # Systems and probes lead: what the map is made of, then what we sent
        # into it; the kinds of body follow.
        SOLAR_SYSTEM_SLUG: [
            PLANETARY_SYSTEMS_SLUG,
            PROBES_SLUG,
            PLANETS_SLUG,
            DWARF_PLANETS_SLUG,
            MOONS_SLUG,
            RING_SYSTEMS_SLUG,
            ASTEROIDS_SLUG,
            COMETS_SLUG,
            SURFACE_FEATURES_SLUG,
            STRUCTURE_ACTIVITY_SLUG,
        ],
        ASTEROIDS_SLUG: asteroids,
        COMETS_SLUG: comets,
        SATELLITES_SLUG: satellites,
        DEBRIS_SLUG: debris_children,
        SURFACE_FEATURES_SLUG: feature_types,
        # Ring Systems is a page of the same kind and deliberately not a child:
        # a ring is a swarm in orbit, closer to a moon than to a layer of the
        # body it goes round.
        # Read outward and then by mechanism: the two envelopes, the crust and
        # what moves it, the tide that supplies the heat, then the field and the
        # particles it steers. Tidal heating sits with volcanism and tectonics
        # because it is where their heat comes from, not with the field.
        STRUCTURE_ACTIVITY_SLUG: [
            ATMOSPHERES_SLUG,
            OCEANS_SLUG,
            VOLCANISM_SLUG,
            TECTONICS_SLUG,
            TIDAL_HEATING_SLUG,
            MAGNETIC_FIELDS_SLUG,
            RADIATION_SLUG,
        ],
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
        # A system is its bodies, all counted elsewhere, so it stays out of the
        # root total too.
        PLANETARY_SYSTEMS_SLUG: len(system_members),
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
        # Property pages count bodies their own categories already count, so
        # these stay out of the root total too — which itself unions rather
        # than sums, since an ocean world always has an envelope too.
        ATMOSPHERES_SLUG: len(atmosphere_members),
        OCEANS_SLUG: len(ocean_members),
        VOLCANISM_SLUG: len(volcanism_members),
        TECTONICS_SLUG: len(tectonics_members),
        MAGNETIC_FIELDS_SLUG: len(magnetic_members),
        TIDAL_HEATING_SLUG: len(tidal_members),
        RADIATION_SLUG: len(radiation_members),
        STRUCTURE_ACTIVITY_SLUG: len(
            {
                member.object_id
                for page in (
                    atmosphere_members,
                    ocean_members,
                    volcanism_members,
                    tectonics_members,
                    magnetic_members,
                    tidal_members,
                    radiation_members,
                )
                for member in page
            }
        ),
    }

    # Discovery/launch charts sum histograms over the classes that partition
    # each category — flags excluded as subsets, Earth categories over the
    # primary shape classes only, same as the totals above.
    discovery_out: dict[str, dict[int, int]] = {}
    if asteroid_hist := _sum_histograms(asteroid_classes, discovery_histograms):
        discovery_out[ASTEROIDS_SLUG] = asteroid_hist
    if comet_hist := _sum_histograms(comet_classes, discovery_histograms):
        discovery_out[COMETS_SLUG] = comet_hist
    # The body categories with a discovery record of their own: each counts its
    # members one by one, none being partitioned into orbit classes.
    if dwarf_hist := _wikidata_discovery_histogram(dwarf_members, entities):
        discovery_out[DWARF_PLANETS_SLUG] = dwarf_hist
    moon_hist = _moon_discovery_histogram(session)
    if moon_hist:
        discovery_out[MOONS_SLUG] = moon_hist
    if ring_hist := _ring_discovery_histogram(ring_members):
        discovery_out[RING_SYSTEMS_SLUG] = ring_hist
    # The root page's own curve: every body we have a discovery date for. The
    # dwarf planets are not added on top — nine of the ten already count inside
    # their orbit class, and one more body would not move a 1.5 M-strong total.
    if solar_hist := _merge_histograms(
        _sum_histograms(asteroid_classes + comet_classes, discovery_histograms),
        moon_hist,
    ):
        discovery_out[SOLAR_SYSTEM_SLUG] = solar_hist
    launch_out: dict[str, dict[int, int]] = {}
    if probe_hist := _probe_launch_histogram(session):
        launch_out[PROBES_SLUG] = probe_hist
    for cat_slug, side in (
        (SATELLITES_SLUG, earth_orbit.payload_satcat_stats),
        (DEBRIS_SLUG, earth_orbit.debris_satcat_stats),
    ):
        per_slug = {
            slug: s.launch_histogram for slug, s in side.items() if s.launch_histogram
        }
        if hist := _sum_histograms(primary_sat_slugs, per_slug):
            launch_out[cat_slug] = hist

    # Category lineup heroes: most prominent asteroids/comets across all orbit
    # classes. Dwarf planets excluded from Asteroids — they keep their own
    # page but still rank inside their orbit-class zone (e.g. Ceres in Main Belt).
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
    if atmosphere_members:
        notable_members[ATMOSPHERES_SLUG] = atmosphere_members
    if ocean_members:
        notable_members[OCEANS_SLUG] = ocean_members
    if volcanism_members:
        notable_members[VOLCANISM_SLUG] = volcanism_members
    if tectonics_members:
        notable_members[TECTONICS_SLUG] = tectonics_members
    if magnetic_members:
        notable_members[MAGNETIC_FIELDS_SLUG] = magnetic_members
    if tidal_members:
        notable_members[TIDAL_HEATING_SLUG] = tidal_members
    if radiation_members:
        notable_members[RADIATION_SLUG] = radiation_members
    if asteroid_notable:
        notable_members[ASTEROIDS_SLUG] = asteroid_notable
    if comet_notable:
        notable_members[COMETS_SLUG] = comet_notable
    if probe_members:
        notable_members[PROBES_SLUG] = probe_members
    solar_system = _solar_system_members(session, star, radii, gms, orientation)
    if solar_system:
        notable_members[SOLAR_SYSTEM_SLUG] = solar_system
    if system_members:
        notable_members[PLANETARY_SYSTEMS_SLUG] = system_members

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
    # partition the population). No such card for Debris: the fragments SATCAT
    # still calls operational are a data lag, not a fact worth showing.
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
    if ring_members:
        extra_stats[RING_SYSTEMS_SLUG] = _ring_system_stats(ring_members)
    if atmosphere_members:
        extra_stats[ATMOSPHERES_SLUG] = _atmosphere_stats(atmosphere_members)
    if ocean_members:
        extra_stats[OCEANS_SLUG] = _ocean_stats(ocean_members)
    if volcanism_members:
        extra_stats[VOLCANISM_SLUG] = _volcanism_stats(volcanism_members)
    if tectonics_members:
        extra_stats[TECTONICS_SLUG] = _tectonics_stats(tectonics_members)
    if magnetic_members:
        extra_stats[MAGNETIC_FIELDS_SLUG] = _magnetic_stats(magnetic_members)
    if tidal_members:
        extra_stats[TIDAL_HEATING_SLUG] = _tidal_stats(tidal_members)
    if radiation_members:
        extra_stats[RADIATION_SLUG] = _radiation_stats(
            radiation_members, radiation_where
        )
    logger.info(
        "Built category data: planets=%d, dwarf planets=%d, moons=%d (%d notable, "
        "%d planet/dwarf hosts), ring systems=%d, atmospheres=%d, oceans=%d, "
        "volcanism=%d, tectonics=%d, magnetic=%d, tidal=%d, radiation=%d, "
        "asteroid zones=%d, comet "
        "families=%d, satellite groups=%d (%d payloads), debris groups=%d "
        "(%d pieces from %d sources), probes=%d",
        len(planet_members),
        len(dwarf_members),
        moons_total,
        len(moon_members),
        len(moon_counts),
        len(ring_members),
        len(atmosphere_members),
        len(ocean_members),
        len(volcanism_members),
        len(tectonics_members),
        len(magnetic_members),
        len(tidal_members),
        len(radiation_members),
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
