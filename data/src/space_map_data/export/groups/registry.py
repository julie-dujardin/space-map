"""Group registry: unified view of aggregation entities behind /g/<slug>.

A Group is a user-facing collection of objects (constellation, operator,
launch site, ...). ``applies_to`` is the object category the group can
filter — determines which membership file the frontend consults.

Group slugs share a single global namespace. Constellations keep bare slugs
("starlink") for backwards compatibility; operators and launch sites are
namespaced (``op-spacex``, ``site-baikonur``) so the constant tables can
reuse natural identifiers without colliding.
"""

from dataclasses import dataclass
from enum import StrEnum

from space_map_data.constants.earth_sats.constellations import CONSTELLATIONS
from space_map_data.constants.earth_sats.launch_sites import (
    LAUNCH_SITE_SLUG_PREFIX,
    LAUNCH_SITES,
)
from space_map_data.constants.earth_sats.operators import (
    OPERATOR_SLUG_PREFIX,
    OPERATORS,
)


class GroupType(StrEnum):
    CONSTELLATION = "constellation"
    OPERATOR = "operator"
    LAUNCH_SITE = "launch_site"


class GroupCategory(StrEnum):
    """Object category a group filters when set as the active group."""

    EARTH_SAT = "earth_sat"


__all__ = [
    "GROUPS",
    "GROUP_BY_SLUG",
    "Group",
    "GroupCategory",
    "GroupType",
    "LAUNCH_SITE_SLUG_PREFIX",
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
    return constellations + operators + launch_sites


GROUPS: tuple[Group, ...] = _build_groups()
GROUP_BY_SLUG: dict[str, Group] = {g.slug: g for g in GROUPS}

assert len(GROUP_BY_SLUG) == len(GROUPS), "Duplicate group slug across types"
