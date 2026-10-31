"""Group export: per-group bundles + membership index for /g/<slug> pages."""

import logging
from dataclasses import dataclass, field, replace
from pathlib import Path

import orjson
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, joinedload

from space_map_data.constants.categories import (
    COMETS_SLUG,
    DEBRIS_SLUG,
    PLANETS_SLUG,
    PROBES_SLUG,
    SATELLITES_SLUG,
    SOLAR_SYSTEM_SLUG,
    STARS_SLUG,
)
from space_map_data.constants.earth_sats.constellations import (
    CONSTELLATION_BY_SLUG,
    CONSTELLATION_SLUG_PREFIX,
    ConstellationSpec,
)
from space_map_data.export.extrasolar.skycultures import sky_constellation_names
from space_map_data.export.groups.bundles import write_group_bundles
from space_map_data.export.groups.categories import (
    build_category_data,
    star_member,
)
from space_map_data.export.groups.earth_sat import (
    NOTABLE_MEMBER_COUNT,
    EarthOrbitClassStats,
    build_earth_orbit_classes,
    write_earth_orbit_samples,
)
from space_map_data.export.groups.feature_type import build_feature_type_groups
from space_map_data.export.groups.launch_site import build_launch_site_stats
from space_map_data.export.groups.launch_vehicle import build_launch_vehicle_stats
from space_map_data.export.groups.membership import (
    build_earth_groups_data,
    write_earth_membership,
)
from space_map_data.export.groups.moon_discovery import (
    build_moon_discovery,
    write_moon_discovery,
)
from space_map_data.export.groups.planet_family import (
    SolarPlanets,
    build_planet_family_groups,
    write_planet_plot,
)
from space_map_data.export.groups.planetary_systems_map import (
    build_planetary_systems_map,
    write_planetary_systems_map,
)
from space_map_data.export.groups.probe_targets import (
    LAGRANGE_ZONE_SLUGS,
    build_group_probes,
)
from space_map_data.export.groups.registry import (
    ORGANIZATION_BUS_CHILDREN,
    Group,
    GroupCategory,
    GroupType,
)
from space_map_data.export.groups.sky_pages import build_sky_pages
from space_map_data.export.groups.small_body import (
    _exported_sbdb_filter,
    build_small_body_group_stats,
    write_orbit_samples,
)
from space_map_data.export.groups.solar_system_map import (
    build_solar_system_map,
    write_solar_system_map,
)
from space_map_data.export.groups.star_family import (
    build_star_family_groups,
    write_star_plot,
)
from space_map_data.export.groups.stats import GroupExtraStats
from space_map_data.export.names import Names, ObjectNames, entity_names
from space_map_data.export.notable import (
    NotableObject,
    craft_model_slugs,
    j2000_poles,
    shape_model_slugs,
    textured_object_ids,
)
from space_map_data.export.objects.fragments import build_comet_families
from space_map_data.export.objects.missions import build_probe_missions
from space_map_data.export.objects.stars import (
    PlanetObject,
    StarObject,
    available_extrasolar_objects,
)
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.solar_planets import solar_planet_records
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.models.object.main import Object
from space_map_data.models.object.sbdb import SBDB
from space_map_data.utils.paths import EXPORT_DIR

logger = logging.getLogger(__name__)


@dataclass
class SplitCometGroups:
    """Dynamic group pages for parentless split-comet families."""

    groups: list[Group] = field(default_factory=list)
    member_counts: dict[str, int] = field(default_factory=dict)
    notable_members: dict[str, list[NotableObject]] = field(default_factory=dict)
    member_ids: dict[str, list[str]] = field(default_factory=dict)
    # The names of each page, as the fragments name their comet.
    names: dict[str, Names] = field(default_factory=dict)
    extra_stats: dict[str, GroupExtraStats] = field(default_factory=dict)


@dataclass
class MissionGroups:
    """Dynamic group pages for probe missions (primary + sibling craft)."""

    groups: list[Group] = field(default_factory=list)
    member_counts: dict[str, int] = field(default_factory=dict)
    notable_members: dict[str, list[NotableObject]] = field(default_factory=dict)
    primary_ids: dict[str, str] = field(default_factory=dict)
    # The names of each page, as its probes name their mission.
    names: dict[str, Names] = field(default_factory=dict)
    extra_stats: dict[str, GroupExtraStats] = field(default_factory=dict)


def _mission_groups(names: ObjectNames) -> MissionGroups:
    """One group page per probe mission, built from the probe registry.

    The mission's Wikidata QID (set on the primary as ``primary_qid``) drives
    the sidebar; members list the primary first, then its sibling craft. The
    ``primary_ids`` map gives each page a focus redirect to its primary probe.
    """
    out = MissionGroups()
    for mission in build_probe_missions(names):
        members = [mission.primary, *mission.members]
        out.groups.append(
            Group(
                slug=mission.slug,
                type=GroupType.MISSION,
                applies_to=GroupCategory.PROBE,
                wikidata_qid=mission.mission_qid,
            )
        )
        out.member_counts[mission.slug] = len(members)
        out.notable_members[mission.slug] = members
        out.primary_ids[mission.slug] = mission.primary_object_id
        out.names[mission.slug] = mission.names
        out.extra_stats[mission.slug] = GroupExtraStats(
            launch_year=mission.launch_year, mission_status=mission.status
        )
    logger.info("Mission group pages: %d", len(out.groups))
    return out


def _constellation_fallback_name(spec: ConstellationSpec) -> str:
    """Display name for a constellation with no Wikidata label (mirrors the
    group-bundle fallback): its TLE name prefix, else the prettified slug."""
    if isinstance(spec.prefix, str) and (p := spec.prefix.strip(" -_")):
        return p
    return spec.slug.replace("-", " ").title()


def _earth_zone_notable_members(
    earth_orbit_stats: EarthOrbitClassStats,
    wikidata_entities: WikidataEntityCache,
) -> dict[str, list[NotableObject]]:
    """Per-zone notable members: top sats merged with the constellations that
    call the zone home, re-ranked by Wikidata prominence so a prominent
    constellation (Starlink) rides alongside individual sats.

    A libration zone is left as it arrives. Its members are probes, which
    carry no sitelink count, so the ranking below would tie them all at zero
    and fall through to the id — replacing "latest arrival first" with the
    order the probe ids happen to sort in.
    """
    zone_constellations: dict[str, list[str]] = {}
    for const_slug, zone_slug in earth_orbit_stats.constellation_zone.items():
        zone_constellations.setdefault(zone_slug, []).append(const_slug)

    # A zone holds both sides of the population, so its strip draws from both
    # pools; the shared sitelinks sort below picks the top of the union.
    per_zone: dict[str, list[NotableObject]] = {}
    for pool in (
        earth_orbit_stats.notable_members,
        earth_orbit_stats.debris_notable_members,
    ):
        for zone_slug, members in pool.items():
            per_zone.setdefault(zone_slug, []).extend(members)

    out: dict[str, list[NotableObject]] = {}
    for zone_slug, sats in per_zone.items():
        if zone_slug in LAGRANGE_ZONE_SLUGS:
            out[zone_slug] = list(sats[:NOTABLE_MEMBER_COUNT])
            continue
        members = list(sats)
        for const_slug in zone_constellations.get(zone_slug, ()):
            spec = CONSTELLATION_BY_SLUG.get(
                const_slug.removeprefix(CONSTELLATION_SLUG_PREFIX)
            )
            if spec is None:
                continue
            wd = wikidata_entities.get_referenced(spec.wikidata_qid)
            members.append(
                NotableObject(
                    object_id="",
                    wikidata_qid=spec.wikidata_qid,
                    names=entity_names(wd, _constellation_fallback_name(spec)),
                    diameter_km=None,
                    first_obs=None,
                    group_slug=const_slug,
                    sitelinks_count=len(wd["sitelinks"]) if wd else 0,
                )
            )
        members.sort(
            key=lambda m: (-(m.sitelinks_count or 0), m.group_slug or m.object_id)
        )
        out[zone_slug] = members[:NOTABLE_MEMBER_COUNT]
    return out


def _earth_category_notable(
    per_zone: dict[str, list[NotableObject]],
) -> list[NotableObject]:
    """Top individual objects across every earth orbit-class zone, for the
    Satellites and Debris category strips. Constellations have their own
    breakdown there, so only real objects count; one spanning zones is deduped
    on its best signal."""
    best: dict[str, NotableObject] = {}
    for members in per_zone.values():
        for member in members:
            if not member.object_id:
                continue
            prev = best.get(member.object_id)
            if prev is None or (member.sitelinks_count or 0) > (
                prev.sitelinks_count or 0
            ):
                best[member.object_id] = member
    return sorted(
        best.values(), key=lambda m: (-(m.sitelinks_count or 0), m.object_id)
    )[:NOTABLE_MEMBER_COUNT]


def _split_comet_orbits(
    session: Session, member_ids: dict[str, list[str]]
) -> dict[str, GroupExtraStats]:
    """Discovery year + perihelion per family, from its fragments' SBDB rows.

    Fragments share the parent's orbit, so the smallest perihelion among them
    stands for the family. The discovery year is the earliest observation of
    any piece — the parent comet's own discovery, in practice.
    """
    all_ids = [oid for ids in member_ids.values() for oid in ids]
    rows = {
        object_id: (first_obs, q)
        for object_id, first_obs, q in session.query(
            SBDB.object_id, SBDB.first_obs, SBDB.q
        ).filter(SBDB.object_id.in_(all_ids))
    }
    out: dict[str, GroupExtraStats] = {}
    for slug, ids in member_ids.items():
        years: list[int] = []
        perihelia: list[float] = []
        for object_id in ids:
            first_obs, q = rows.get(object_id, (None, None))
            if first_obs:
                try:
                    years.append(int(first_obs[:4]))
                except ValueError:
                    logger.info(
                        "%s: unparseable first_obs %r, excluded from the "
                        "discovery year",
                        slug,
                        first_obs,
                    )
            if q is not None:
                perihelia.append(q)
        out[slug] = GroupExtraStats(
            discovery_year=min(years) if years else None,
            perihelion_au=min(perihelia) if perihelia else None,
        )
    return out


def _split_comet_groups(session: Session, names: ObjectNames) -> SplitCometGroups:
    """One group page per parentless split-comet family (no intact body).

    Families with an intact parent get their fragment list on that body's
    object page instead. Members are restricted to exported fragments, so a
    family whose pieces are all unexported (Shoemaker-Levy 9 — all D-prefix)
    yields no page.
    """
    families = build_comet_families(session, names)
    exported = {
        object_id
        for (object_id,) in session.query(SBDB.object_id)
        .join(Object, Object.id == SBDB.object_id)
        .filter(*_exported_sbdb_filter())
        .all()
    }
    out = SplitCometGroups()
    skipped: list[str] = []
    member_ids: dict[str, list[str]] = {}
    for family in families.values():
        if family.parent_object_id is not None:
            continue
        members = [f for f in family.fragments if f.object_id in exported]
        if not members:
            skipped.append(family.parent_pdes)
            continue
        slug = family.page_id
        out.groups.append(
            Group(
                slug=slug,
                type=GroupType.SPLIT_COMET,
                applies_to=GroupCategory.SMALL_BODY,
                wikidata_qid=family.parent_qid,
            )
        )
        out.member_counts[slug] = len(members)
        out.notable_members[slug] = members
        out.names[slug] = family.names
        member_ids[slug] = [f.object_id for f in members]
    out.member_ids = member_ids
    out.extra_stats = _split_comet_orbits(session, member_ids)
    enriched = sum(1 for g in out.groups if g.wikidata_qid)
    logger.info(
        "Split-comet group pages: %d parentless families (%d with a Wikidata QID),"
        " %d skipped (no exported fragments): %s",
        len(out.groups),
        enriched,
        len(skipped),
        ", ".join(skipped) if skipped else "[]",
    )
    return out


def _gallery_subjects(session: Session, names: ObjectNames) -> dict[str, Names]:
    """Name every object that has a picture — the pool member shelves draw from.

    Naming the whole pool up front costs one query; the alternative is looking
    up each shelf's subject as it is built, once per collection it appears in.
    """
    rows = (
        session.query(Object)
        .options(joinedload(Object.satcat))
        .filter(Object.image_available.is_(True))
        .all()
    )
    return {obj.id: names.of(obj) for obj in rows}


def run_groups_tier(
    engine: Engine,
    out_dir: Path,
    wikidata_entities: WikidataEntityCache,
    radii: dict[int, dict],
    gms: dict[int, float],
    displacement_metadata: dict[str, dict] | None = None,
    model_metadata: dict[str, dict] | None = None,
    star_objects: list[StarObject] | None = None,
    planet_objects: list[PlanetObject] | None = None,
) -> dict[str, int]:
    """Build + write the groups tier; returns bucket counts for metadata.json.

    ``radii``/``gms`` (SPICE PCK) give the category planet + moon members their
    mass + triaxial radii for the planets/moons-page charts. ``model_metadata``
    arrives raw because the two meshes it yields are read differently: a body's
    shape model keys off the bundle, a spacecraft's off ``Object.model_name``.
    ``star_objects`` and ``planet_objects`` are the entries of the served stars
    and planets, which the lists name as their pages do.
    """
    from space_map_data.export.systems import (
        load_nut_prec,
        load_nut_prec_angles,
        load_nut_prec_phase_degrees,
        load_orientation,
        load_planet_elements,
        load_ring_metadata,
    )
    from space_map_data.utils.paths import DOWNLOAD_DIR

    units = UnitConverter(wikidata_entities)
    # Poles for the lineup hero's true tilt — loaded here rather than widening
    # the orchestrator→tier interface for a tier-internal render detail.
    poles = j2000_poles(
        load_orientation(DOWNLOAD_DIR),
        load_nut_prec(DOWNLOAD_DIR),
        load_nut_prec_angles(DOWNLOAD_DIR),
        load_nut_prec_phase_degrees(DOWNLOAD_DIR),
    )
    # Horizons mean elements for the SBDB-less planets (minimap + moons chart).
    planet_elements = load_planet_elements(DOWNLOAD_DIR)
    model_slugs = shape_model_slugs(model_metadata or {})
    with Session(engine) as session:
        names = ObjectNames(
            wikidata_entities, session, star_objects or (), planet_objects or ()
        )
        craft_models = craft_model_slugs(session, model_metadata or {})
        gallery_subjects = _gallery_subjects(session, names)
        build = build_earth_groups_data(session)
        small_body_stats = build_small_body_group_stats(
            session, names, radii, units, poles
        )
        earth_orbit_stats = build_earth_orbit_classes(session, names)
        feature_types = build_feature_type_groups(session, names)
        sun = star_member(session, names, radii, gms, poles)
        build.membership[GroupType.EARTH_ORBIT_CLASS] = earth_orbit_stats.membership
        build.stats[GroupType.EARTH_ORBIT_CLASS] = earth_orbit_stats.satcat_stats

        extra_member_counts = dict(small_body_stats.member_counts)
        extra_member_counts.update(earth_orbit_stats.member_counts)
        # Counts the category builder needs to rank constellations + drop empty
        # zones: membership-backed groups plus the small-body/earth extras.
        all_counts = {
            slug: len(ids)
            for mem in build.membership.values()
            for slug, ids in mem.items()
        }
        all_counts.update(extra_member_counts)
        category_data = build_category_data(
            session,
            names,
            all_counts,
            feature_types.member_counts,
            small_body_stats.named_counts,
            small_body_stats.discovery_histograms,
            small_body_stats.largest_bodies,
            earth_orbit_stats,
            radii,
            gms,
            poles,
            wikidata_entities,
            planet_elements,
        )
        split_comets = _split_comet_groups(session, names)
        launch_vehicle_stats = build_launch_vehicle_stats(session)
        launch_site_stats = build_launch_site_stats(session)
        textured_ids = textured_object_ids(session)
        moon_discovery = build_moon_discovery(session)
        solar_system_map = build_solar_system_map(
            session,
            names,
            radii,
            wikidata_entities,
            units,
            small_body_stats.orbit_samples,
            planet_elements,
        )
        planetary_systems_map = build_planetary_systems_map(
            session,
            radii,
            poles,
            load_ring_metadata(out_dir),
            units,
            wikidata_entities,
        )
    missions = _mission_groups(names)
    star_families = build_star_family_groups(star_objects or [], names, sun=sun)
    planet_families = build_planet_family_groups(
        names,
        SolarPlanets(
            category_data.notable_members.get(PLANETS_SLUG, []),
            solar_planet_records(radii, gms, planet_elements),
        ),
    )
    planets_page = planet_families.planets
    sky_pages = build_sky_pages(star_objects or [], names)

    # Each constellation lists the buses its members fly, most-used first; the
    # chip count is the within-constellation tally, not the bus's global total.
    constellation_bus_children = {
        c_slug: sorted(counts, key=lambda s: (-counts[s], s))
        for c_slug, counts in build.constellation_bus_counts.items()
    }

    extra_member_counts.update(category_data.member_counts)
    extra_member_counts.update(split_comets.member_counts)
    extra_member_counts.update(missions.member_counts)
    extra_member_counts.update(feature_types.member_counts)
    extra_member_counts.update(star_families.member_counts)
    extra_member_counts.update(planet_families.member_counts)
    extra_member_counts.update(sky_pages.member_counts)
    extra_named_counts = dict(small_body_stats.named_counts)
    extra_named_counts.update(category_data.named_counts)
    extra_notable_members = dict(small_body_stats.notable_members)
    extra_notable_members.update(category_data.notable_members)
    extra_notable_members.update(split_comets.notable_members)
    extra_notable_members.update(missions.notable_members)
    extra_notable_members.update(feature_types.notable_members)
    extra_notable_members.update(star_families.notable_members)
    extra_notable_members.update(planet_families.notable_members)
    extra_notable_members.update(sky_pages.notable_members)
    extra_notable_members.update(
        _earth_zone_notable_members(earth_orbit_stats, wikidata_entities)
    )
    for cat_slug, pool in (
        (SATELLITES_SLUG, earth_orbit_stats.notable_members),
        (DEBRIS_SLUG, earth_orbit_stats.debris_notable_members),
    ):
        if notable := _earth_category_notable(pool):
            extra_notable_members[cat_slug] = notable
    # Constellation → its dominant zone, so the group index can list each
    # constellation among its zone's members.
    constellation_orbit_classes = {
        const_slug: [zone_slug]
        for const_slug, zone_slug in earth_orbit_stats.constellation_zone.items()
    }
    # Category discovery charts ride the same per-slug path as small-body
    # classes; satellite launch charts need their own override since categories
    # carry no GroupSatcatStats.
    extra_histograms = dict(small_body_stats.discovery_histograms)
    extra_histograms.update(category_data.discovery_histograms)
    extra_largest_bodies = dict(small_body_stats.largest_bodies)
    extra_largest_bodies.update(category_data.largest_bodies)
    extra_pha_counts = dict(small_body_stats.pha_counts)
    extra_pha_counts.update(category_data.pha_counts)
    # Categories carry no membership, so their active/decayed roll-up joins the
    # per-type stats map the writer flattens.
    build.stats[GroupType.CATEGORY] = category_data.satcat_stats

    extra_stats: dict[str, GroupExtraStats] = {
        **category_data.extra_stats,
        **split_comets.extra_stats,
        **missions.extra_stats,
        **star_families.extra_stats,
        **planet_families.extra_stats,
        **sky_pages.extra_stats,
    }
    # The Planets page lists every planet. It also lists its Solar System
    # planets on their own, and the Solar System page's tile counts only those.
    extra_member_lists: dict[str, dict[str, list[NotableObject]]] = {}
    solar_planet_counts: dict[str, dict[str, int]] = {}
    if planets_page is not None:
        extra_member_counts[PLANETS_SLUG] = planets_page.member_count
        extra_notable_members[PLANETS_SLUG] = planets_page.notable_members
        extra_stats[PLANETS_SLUG] = replace(
            extra_stats.get(PLANETS_SLUG, GroupExtraStats()),
            **planets_page.stats.to_dict(),
        )
        extra_member_lists[PLANETS_SLUG] = {"solar_members": planets_page.solar_members}
        solar_planet_counts[SOLAR_SYSTEM_SLUG] = {
            PLANETS_SLUG: len(planets_page.solar_members)
        }
    for slug, median in earth_orbit_stats.median_perigees.items():
        extra_stats.setdefault(slug, GroupExtraStats()).median_perigee_km = median
    for slug, moid in small_body_stats.median_moids.items():
        extra_stats.setdefault(slug, GroupExtraStats()).median_moid_au = moid
    # The Comets and Probes pages are lists of child groups; their own tally is
    # the one number the chips below don't add up to.
    extra_stats.setdefault(COMETS_SLUG, GroupExtraStats()).child_group_count = len(
        split_comets.groups
    )
    extra_stats.setdefault(PROBES_SLUG, GroupExtraStats()).child_group_count = len(
        missions.groups
    )
    # Same source as the page's launch chart, so the card's year is the year
    # the first bar sits on.
    if probe_launches := category_data.launch_histograms.get(PROBES_SLUG):
        extra_stats[PROBES_SLUG].launch_year = min(probe_launches)

    group_probes = build_group_probes(
        session,
        names,
        {
            object_id: slug
            for slug, ids in split_comets.member_ids.items()
            for object_id in ids
        },
    )
    # The target labels ride the same body_names map the per-body charts fill.
    extra_chart_names = {
        slug: dict(chart_names)
        for slug, chart_names in category_data.chart_names.items()
    }
    for slug, target_names in group_probes.names.items():
        extra_chart_names.setdefault(slug, {}).update(target_names)
    if planets_page is not None:
        extra_chart_names.setdefault(PLANETS_SLUG, {}).update(planets_page.card_names)
    extra_chart_names.setdefault(STARS_SLUG, {}).update(star_families.card_names)

    write_earth_membership(out_dir, build.membership)
    write_orbit_samples(out_dir, small_body_stats.orbit_samples)
    write_earth_orbit_samples(out_dir, earth_orbit_stats.orbit_samples)
    write_solar_system_map(out_dir, solar_system_map)
    write_planetary_systems_map(out_dir, planetary_systems_map)
    write_moon_discovery(out_dir, moon_discovery)
    if planets_page is not None:
        write_planet_plot(out_dir, planets_page.plot)
    if star_families.plot is not None:
        write_star_plot(out_dir, star_families.plot)

    return write_group_bundles(
        out_dir,
        wikidata_entities,
        build.membership,
        build.stats,
        extra_member_counts=extra_member_counts,
        extra_histograms=extra_histograms,
        extra_launch_histograms=category_data.launch_histograms,
        extra_largest_bodies=extra_largest_bodies,
        extra_pha_counts=extra_pha_counts,
        extra_stats=extra_stats,
        gallery_subjects=gallery_subjects,
        extra_named_counts=extra_named_counts,
        extra_notable_members=extra_notable_members,
        extra_member_lists=extra_member_lists,
        extra_probes=group_probes.probes,
        extra_chart_rows=category_data.chart_rows,
        extra_chart_names=extra_chart_names,
        extra_primary_ids=missions.primary_ids,
        child_slugs_by_group={
            **category_data.children,
            **ORGANIZATION_BUS_CHILDREN,
            **constellation_bus_children,
            **star_families.children,
            **planet_families.children,
            **sky_pages.children,
        },
        child_counts_by_group={
            **build.constellation_bus_counts,
            **solar_planet_counts,
        },
        extra_groups=(*split_comets.groups, *missions.groups),
        extra_group_names={
            **split_comets.names,
            **missions.names,
            **sky_constellation_names(wikidata_entities, sky_pages.page_labels),
            **sky_pages.names,
        },
        launch_vehicle_stats=launch_vehicle_stats,
        launch_site_stats=launch_site_stats,
        feature_type_stats=feature_types.stats,
        constellation_orbit_classes=constellation_orbit_classes,
        extra_constellation_counts=category_data.constellation_counts,
        displacement_metadata=displacement_metadata,
        model_slugs=model_slugs,
        craft_models=craft_models,
        textured_ids=textured_ids,
    )


def update_metadata_group_bundles(out_dir: Path, group_bundles: dict[str, int]) -> None:
    """Patch only ``group_bundles`` in metadata.json (for additive runs)."""
    path = out_dir / "metadata.json"
    metadata = orjson.loads(path.read_bytes()) if path.exists() else {}
    metadata["group_bundles"] = group_bundles
    path.write_bytes(orjson.dumps(metadata, option=orjson.OPT_INDENT_2))


def export_groups_only(engine: Engine) -> None:
    """Additive run: write groups + membership + patch metadata.json only."""
    from space_map_data.export.localization import write_group_messages
    from space_map_data.export.sitemap import available_planet_pages
    from space_map_data.export.systems import (
        load_displacement_metadata,
        load_gms,
        load_model_metadata,
        load_radii,
    )
    from space_map_data.utils.paths import DOWNLOAD_DIR

    out_dir = EXPORT_DIR / "v1"
    if not out_dir.exists():
        raise SystemExit(f"Export dir {out_dir} missing — run a full export first.")
    wikidata_entities = WikidataEntityCache()
    radii = load_radii(DOWNLOAD_DIR)
    gms = load_gms(DOWNLOAD_DIR)
    displacement_metadata = load_displacement_metadata(out_dir)
    star_objects, planet_objects = available_extrasolar_objects()
    group_bundles = run_groups_tier(
        engine,
        out_dir,
        wikidata_entities,
        radii,
        gms,
        displacement_metadata,
        load_model_metadata(out_dir),
        star_objects,
        available_planet_pages().served(planet_objects),
    )
    update_metadata_group_bundles(out_dir, group_bundles)
    write_group_messages(wikidata_entities)
    logger.info("Groups-only export complete (%d bundles)", group_bundles["global"])
