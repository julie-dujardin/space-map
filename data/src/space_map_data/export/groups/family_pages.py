"""What the star family and the planet family group pages share.

The extrasolar export tags the stars and the planets with families. Each
family has a page, and the pages of one tree count and list their members
from the served export.
"""

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.groups.stats import GroupExtraStats
from space_map_data.export.notable import NotableObject
from space_map_data.export.wikidata import WikidataEntityCache


@dataclass
class FamilyGroups:
    """Everything the group tier needs for the pages of one family tree."""

    member_counts: dict[str, int] = field(default_factory=dict)
    extra_stats: dict[str, GroupExtraStats] = field(default_factory=dict)
    notable_members: dict[str, list[NotableObject]] = field(default_factory=dict)
    # The child families of each page that have members, most members first.
    children: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class FamilyPages:
    """The pages of one family tree. `published` and `estimated` are the
    GroupExtraStats fields of the two member counts of a page. `root` is the
    page above the families without a parent, None when the tree has its
    root family in `parents`."""

    prefix: str
    parents: Mapping[str, tuple[str, ...]]
    published: str
    estimated: str
    root: str | None = None

    def slug(self, family: str) -> str:
        return f"{self.prefix}{family}"

    def parent_slugs(self, slug: str) -> list[str]:
        """The pages of the families that contain the family of ``slug``,
        else the root page."""
        family = slug.removeprefix(self.prefix)
        if family in self.parents:
            return [self.slug(parent) for parent in self.parents[family]]
        return [self.root] if self.root else []

    def count(self, out: FamilyGroups, counts: Iterable[tuple[str, int, int]]) -> None:
        """Set the member counts, the stats and the child families of `out`
        from the family, published count and estimated count of each page."""
        children: dict[str, list[str]] = defaultdict(list)
        for family, published, estimated in counts:
            slug = self.slug(family)
            out.member_counts[slug] = published + estimated
            out.extra_stats[slug] = replace(
                GroupExtraStats(),
                **{self.published: published, self.estimated: estimated},
            )
            if published + estimated:
                for parent in self.parent_slugs(slug):
                    children[parent].append(slug)
        out.children = {
            slug: sorted(kids, key=lambda kid: (-out.member_counts[kid], kid))
            for slug, kids in children.items()
        }


def served_metadata(extrasolar_dir: Path) -> dict | None:
    """The metadata.json of the served extrasolar export, None with no
    export served."""
    path = extrasolar_dir / "v1" / "x" / "metadata.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def sitelink_rank(
    wikidata_entities: WikidataEntityCache, qid: str | None
) -> tuple[int, bool]:
    """The sitelinks of `qid`, and whether one is an article in a language
    of the site."""
    found = wikidata_entities.get_star_entity(qid)
    if found is None or found.entity is None:
        return 0, False
    return found.sitelinks, not set(found.entity["sitelinks"]).isdisjoint(LANGUAGES)


def object_sitelink_rank(
    wikidata_entities: WikidataEntityCache, qid: str | None
) -> tuple[int, bool]:
    """`sitelink_rank` of the item of a Solar System object."""
    found = wikidata_entities.get_entity(qid)
    if found is None:
        return 0, False
    return len(found["sitelinks"]), not set(found["sitelinks"]).isdisjoint(LANGUAGES)
