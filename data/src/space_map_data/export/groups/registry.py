"""Group registry: aggregation entities behind /g/<slug>.

Constellations keep bare slugs; operators, launch sites, manufacturers, and
countries are prefixed (``op-``/``site-``/``mfr-``/``country-``) so the
same entity can appear in multiple roles without slug collisions.
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


class GroupType(StrEnum):
    CONSTELLATION = "constellation"
    OPERATOR = "operator"
    LAUNCH_SITE = "launch_site"
    MANUFACTURER = "manufacturer"
    COUNTRY = "country"


class GroupCategory(StrEnum):
    """Object category a group filters when set as the active group."""

    EARTH_SAT = "earth_sat"


__all__ = [
    "COUNTRY_SLUG_PREFIX",
    "GROUPS",
    "GROUP_BY_SLUG",
    "Group",
    "GroupCategory",
    "GroupType",
    "LAUNCH_SITE_SLUG_PREFIX",
    "MANUFACTURER_SLUG_PREFIX",
    "OPERATOR_SLUG_PREFIX",
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
    return constellations + operators + launch_sites + manufacturers + countries


GROUPS: tuple[Group, ...] = _build_groups()
GROUP_BY_SLUG: dict[str, Group] = {g.slug: g for g in GROUPS}

assert len(GROUP_BY_SLUG) == len(GROUPS), "Duplicate group slug across types"
