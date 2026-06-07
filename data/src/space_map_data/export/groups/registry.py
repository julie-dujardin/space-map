"""Group registry: unified view of aggregation entities behind /g/<slug>.

A Group is a user-facing collection of objects (constellation, operator,
asteroid class, ...). `applies_to` is the object category the group can
filter — determines which membership file the frontend consults. Phase 1
covers only constellations applied to earth sats.
"""

from dataclasses import dataclass
from enum import StrEnum

from space_map_data.constants.earth_sats.constellations import CONSTELLATIONS


class GroupType(StrEnum):
    CONSTELLATION = "constellation"


class GroupCategory(StrEnum):
    """Object category a group filters when set as the active group."""

    EARTH_SAT = "earth_sat"


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
    return constellations


GROUPS: tuple[Group, ...] = _build_groups()
GROUP_BY_SLUG: dict[str, Group] = {g.slug: g for g in GROUPS}
