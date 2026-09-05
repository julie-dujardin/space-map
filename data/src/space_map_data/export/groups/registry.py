"""Group registry: aggregation entities behind /g/<slug>.

Every group type's ``/g/`` slug carries a prefix
(``const-``/``org-``/``site-``/``country-``/``class-``/``flag-``/``cat-``/
``bus-``/``comet-family-``/``ft-``) so the same entity can appear in multiple roles
without slug collisions and a slug's type is recognizable on sight.
"""

from dataclasses import dataclass
from enum import StrEnum

from space_map_data.constants.categories import CATEGORIES
from space_map_data.constants.countries import COUNTRIES, COUNTRY_SLUG_PREFIX
from space_map_data.constants.earth_sats.constellations import (
    CONSTELLATION_SLUG_PREFIX,
    CONSTELLATIONS,
    STATION_CONSTELLATION_SLUGS,
)
from space_map_data.constants.earth_sats.launch_vehicles import (
    LAUNCH_VEHICLE_BY_CONSTELLATION,
    LAUNCH_VEHICLE_SLUG_PREFIX,
    LAUNCH_VEHICLES,
)
from space_map_data.constants.earth_sats.launch_sites import (
    LAUNCH_SITE_SLUG_PREFIX,
    LAUNCH_SITES,
)
from space_map_data.constants.earth_sats.organizations import (
    ORGANIZATION_SLUG_PREFIX,
    ORGANIZATIONS,
)
from space_map_data.constants.earth_sats.orbit_class import EarthOrbitClass
from space_map_data.constants.earth_sats.satellite_models import (
    BUS_SLUG_PREFIX,
    SATELLITE_BUSES,
)
from space_map_data.constants.nomenclature.feature_types import (
    FEATURE_TYPE_SLUGS,
    FEATURE_TYPES,
)
from space_map_data.constants.small_bodies import ORBIT_CLASS_QIDS
from space_map_data.models.object.sbdb import OrbitClass

CLASS_SLUG_PREFIX = "class-"
SMALL_BODY_FLAG_SLUG_PREFIX = "flag-"


class GroupType(StrEnum):
    CONSTELLATION = "constellation"
    ORGANIZATION = "organization"
    LAUNCH_SITE = "launch_site"
    BUS = "bus"
    COUNTRY = "country"
    ORBIT_CLASS = "orbit_class"
    SMALL_BODY_FLAG = "small_body_flag"
    EARTH_ORBIT_CLASS = "earth_orbit_class"
    CATEGORY = "category"
    # ROCKET constellations (spent stages in orbit) merged with GCAT launchlog
    # history.
    LAUNCH_VEHICLE = "launch_vehicle"
    # Synthetic per-family page for a parentless split comet (no intact body in
    # the catalog, e.g. Shoemaker-Levy 9). Built dynamically from the DB, not in
    # _build_groups; carries its fragments as notable members.
    SPLIT_COMET = "split_comet"
    # Synthetic per-mission page (primary probe + sibling craft), built from the
    # probe registry; carries a `primary` redirect that focuses the primary probe.
    MISSION = "mission"
    # One page per IAU feature-type code (crater, mons, vallis, ...); members are
    # surface features across every body, not objects.
    FEATURE_TYPE = "feature_type"


# Orthogonal to orbit class (an object can be both NEO and MBA). Membership is
# resolved render-time from the per-point `flags` byte on elements tiles.
SMALL_BODY_FLAGS: tuple[tuple[str, str], ...] = (
    ("neo", "Q265392"),
    ("pha", "Q2014814"),
)


class GroupCategory(StrEnum):
    """Object category a group filters when set as the active group."""

    EARTH_SAT = "earth_sat"
    SMALL_BODY = "small_body"
    PROBE = "probe"  # mission pages; focus redirects to the primary probe
    CATEGORY = "category"  # browse-tree node; no scene filter
    SURFACE_FEATURE = "surface_feature"  # members are features, not objects


__all__ = [
    "BUS_SLUG_PREFIX",
    "CLASS_SLUG_PREFIX",
    "COUNTRY_SLUG_PREFIX",
    "GROUPS",
    "GROUP_BY_SLUG",
    "Group",
    "GroupCategory",
    "GroupType",
    "LAUNCH_SITE_SLUG_PREFIX",
    "LAUNCH_VEHICLE_SLUG_PREFIX",
    "ORGANIZATION_BUS_CHILDREN",
    "ORGANIZATION_SLUG_PREFIX",
    "SMALL_BODY_FLAG_SLUG_PREFIX",
    "SMALL_BODY_FLAGS",
]


@dataclass(frozen=True)
class Group:
    slug: str
    type: GroupType
    applies_to: GroupCategory
    wikidata_qid: str | None = None
    fallback_url: str | None = None  # External site when no Wikidata


def _build_groups() -> tuple[Group, ...]:
    # ROCKET constellations are surfaced as lv- launch-vehicle pages instead;
    # exclude them here so they don't also emit a const- page. Station
    # constellations only classify: a station and what docked to it is no fleet.
    constellations = tuple(
        Group(
            slug=f"{CONSTELLATION_SLUG_PREFIX}{c.slug}",
            type=GroupType.CONSTELLATION,
            applies_to=GroupCategory.EARTH_SAT,
            wikidata_qid=c.wikidata_qid,
            fallback_url=c.url,
        )
        for c in CONSTELLATIONS
        if c.slug not in LAUNCH_VEHICLE_BY_CONSTELLATION
        and c.slug not in STATION_CONSTELLATION_SLUGS
    )
    launch_vehicles = tuple(
        Group(
            slug=f"{LAUNCH_VEHICLE_SLUG_PREFIX}{lv.slug}",
            type=GroupType.LAUNCH_VEHICLE,
            applies_to=GroupCategory.EARTH_SAT,
            wikidata_qid=lv.qid,
        )
        for lv in LAUNCH_VEHICLES
    )
    organizations = tuple(
        Group(
            slug=f"{ORGANIZATION_SLUG_PREFIX}{o.slug}",
            type=GroupType.ORGANIZATION,
            applies_to=GroupCategory.EARTH_SAT,
            wikidata_qid=o.wikidata_qid,
            fallback_url=o.fallback_url,
        )
        for o in ORGANIZATIONS
    )
    launch_sites = tuple(
        Group(
            slug=f"{LAUNCH_SITE_SLUG_PREFIX}{s.slug}",
            type=GroupType.LAUNCH_SITE,
            applies_to=GroupCategory.EARTH_SAT,
            wikidata_qid=s.wikidata_qid,
        )
        for s in LAUNCH_SITES
    )
    buses = tuple(
        Group(
            slug=f"{BUS_SLUG_PREFIX}{b.slug}",
            type=GroupType.BUS,
            applies_to=GroupCategory.EARTH_SAT,
            wikidata_qid=b.wikidata_qid,
        )
        for b in SATELLITE_BUSES
    )
    countries = tuple(
        Group(
            slug=f"{COUNTRY_SLUG_PREFIX}{c.slug}",
            type=GroupType.COUNTRY,
            applies_to=GroupCategory.EARTH_SAT,
            wikidata_qid=c.wikidata_qid,
        )
        for c in COUNTRIES
    )
    orbit_classes = tuple(
        Group(
            slug=f"{CLASS_SLUG_PREFIX}{cls.name}",
            type=GroupType.ORBIT_CLASS,
            applies_to=GroupCategory.SMALL_BODY,
            wikidata_qid=ORBIT_CLASS_QIDS.get(cls),
        )
        for cls in OrbitClass
    )
    small_body_flags = tuple(
        Group(
            slug=f"{SMALL_BODY_FLAG_SLUG_PREFIX}{name}",
            type=GroupType.SMALL_BODY_FLAG,
            applies_to=GroupCategory.SMALL_BODY,
            wikidata_qid=qid,
        )
        for name, qid in SMALL_BODY_FLAGS
    )
    # All earth-sat zones (primary + overlay) share the ``class-`` prefix;
    # names don't collide with small-body OrbitClass values (LEO/MEO/... vs
    # MBA/NEO/...) and applies_to disambiguates per category.
    earth_orbit_classes = tuple(
        Group(
            slug=f"{CLASS_SLUG_PREFIX}{cls.name}",
            type=GroupType.EARTH_ORBIT_CLASS,
            applies_to=GroupCategory.EARTH_SAT,
            wikidata_qid=cls.qid,
        )
        for cls in EarthOrbitClass
    )
    categories = tuple(
        Group(
            slug=c.slug,
            type=GroupType.CATEGORY,
            applies_to=GroupCategory.CATEGORY,
            wikidata_qid=c.wikidata_qid,
        )
        for c in CATEGORIES
    )
    feature_types = tuple(
        Group(
            slug=FEATURE_TYPE_SLUGS[code],
            type=GroupType.FEATURE_TYPE,
            applies_to=GroupCategory.SURFACE_FEATURE,
            wikidata_qid=ft.qid,
        )
        for code, ft in FEATURE_TYPES.items()
    )
    return (
        constellations
        + launch_vehicles
        + organizations
        + launch_sites
        + buses
        + countries
        + orbit_classes
        + small_body_flags
        + earth_orbit_classes
        + categories
        + feature_types
    )


GROUPS: tuple[Group, ...] = _build_groups()
GROUP_BY_SLUG: dict[str, Group] = {g.slug: g for g in GROUPS}

assert len(GROUP_BY_SLUG) == len(GROUPS), "Duplicate group slug across types"


def _build_organization_bus_children() -> dict[str, list[str]]:
    """Organization group slug -> its bus group slugs, for the bus chip list.

    A bus's manufacturer slug is its organization slug, so buses hang off the
    merged org page (the org carries the ``manufacturer`` role).
    """
    children: dict[str, list[str]] = {}
    for b in SATELLITE_BUSES:
        org_slug = f"{ORGANIZATION_SLUG_PREFIX}{b.manufacturer.slug}"
        children.setdefault(org_slug, []).append(f"{BUS_SLUG_PREFIX}{b.slug}")
    return children


ORGANIZATION_BUS_CHILDREN: dict[str, list[str]] = _build_organization_bus_children()
