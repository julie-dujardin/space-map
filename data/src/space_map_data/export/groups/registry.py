"""Group registry: aggregation entities behind /g/<slug>.

Constellations keep bare slugs; operators, launch sites, manufacturers,
countries, orbit classes, and small-body flags are prefixed
(``op-``/``site-``/``mfr-``/``country-``/``class-``/``flag-``) so the same
entity can appear in multiple roles without slug collisions.
"""

from dataclasses import dataclass
from enum import StrEnum

from space_map_data.constants.countries import COUNTRIES, COUNTRY_SLUG_PREFIX
from space_map_data.constants.earth_sats.constellations import CONSTELLATIONS
from space_map_data.constants.earth_sats.launch_sites import (
    LAUNCH_SITE_SLUG_PREFIX,
    LAUNCH_SITES,
)
from space_map_data.constants.earth_sats.manufacturers import (
    MANUFACTURER_SLUG_PREFIX,
    MANUFACTURERS,
)
from space_map_data.constants.earth_sats.operators import (
    OPERATOR_SLUG_PREFIX,
    OPERATORS,
)
from space_map_data.constants.earth_sats.orbit_class import EarthOrbitClass
from space_map_data.constants.small_bodies import ORBIT_CLASS_QIDS
from space_map_data.models.object.sbdb import OrbitClass

CLASS_SLUG_PREFIX = "class-"
SMALL_BODY_FLAG_SLUG_PREFIX = "flag-"


class GroupType(StrEnum):
    CONSTELLATION = "constellation"
    OPERATOR = "operator"
    LAUNCH_SITE = "launch_site"
    MANUFACTURER = "manufacturer"
    COUNTRY = "country"
    ORBIT_CLASS = "orbit_class"
    SMALL_BODY_FLAG = "small_body_flag"
    EARTH_ORBIT_CLASS = "earth_orbit_class"


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


__all__ = [
    "CLASS_SLUG_PREFIX",
    "COUNTRY_SLUG_PREFIX",
    "GROUPS",
    "GROUP_BY_SLUG",
    "Group",
    "GroupCategory",
    "GroupType",
    "LAUNCH_SITE_SLUG_PREFIX",
    "MANUFACTURER_SLUG_PREFIX",
    "OPERATOR_SLUG_PREFIX",
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
    constellations = tuple(
        Group(
            slug=c.slug,
            type=GroupType.CONSTELLATION,
            applies_to=GroupCategory.EARTH_SAT,
            wikidata_qid=c.wikidata_qid,
            fallback_url=c.url,
        )
        for c in CONSTELLATIONS
    )
    operators = tuple(
        Group(
            slug=f"{OPERATOR_SLUG_PREFIX}{o.slug}",
            type=GroupType.OPERATOR,
            applies_to=GroupCategory.EARTH_SAT,
            wikidata_qid=o.wikidata_qid,
            fallback_url=o.url,
        )
        for o in OPERATORS
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
    manufacturers = tuple(
        Group(
            slug=f"{MANUFACTURER_SLUG_PREFIX}{m.slug}",
            type=GroupType.MANUFACTURER,
            applies_to=GroupCategory.EARTH_SAT,
            wikidata_qid=m.wikidata_qid,
        )
        for m in MANUFACTURERS
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
    return (
        constellations
        + operators
        + launch_sites
        + manufacturers
        + countries
        + orbit_classes
        + small_body_flags
        + earth_orbit_classes
    )


GROUPS: tuple[Group, ...] = _build_groups()
GROUP_BY_SLUG: dict[str, Group] = {g.slug: g for g in GROUPS}

assert len(GROUP_BY_SLUG) == len(GROUPS), "Duplicate group slug across types"
