"""Star family (``star-``) group pages.

One page per family of ``constants/stars/families.py``. The extrasolar export
tags the stars, so the counts and the stars that a page lists come from its
served files, as the planets of the sitemap do: a page then tells what the
site serves.
"""

import json
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from space_map_data.constants.providers import LANGUAGES
from space_map_data.constants.stars.families import (
    FAMILIES,
    FAMILY_SLUG_PREFIX,
    PARENTS,
    ROOT_FAMILY,
)
from space_map_data.export.extrasolar.build import served
from space_map_data.export.extrasolar.reader import ExportReader
from space_map_data.export.groups.stats import GroupExtraStats
from space_map_data.export.notable import NotableObject
from space_map_data.export.objects.stars import PREFIX, StarObject
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.extrasolar.tables import METADATA
from space_map_data.utils.paths import EXTRASOLAR_DIR

logger = logging.getLogger(__name__)

# As many stars as the other collections list.
NOTABLE_STARS = 20


def family_slug(family: str) -> str:
    return f"{FAMILY_SLUG_PREFIX}{family}"


def parent_slugs(slug: str) -> list[str]:
    """The pages of the families that contain the family of ``slug``."""
    family = slug.removeprefix(FAMILY_SLUG_PREFIX)
    return [family_slug(parent) for parent in PARENTS.get(family, ())]


def served_families_stamp(extrasolar_dir: Path = EXTRASOLAR_DIR) -> list | None:
    """The family counts of the served extrasolar export, None with no export
    served. A change of the rules or of the registry that moves a star moves
    a count, so the pages change with them."""
    path = extrasolar_dir / "v1" / "x" / "metadata.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())["families"]


@dataclass
class StarFamilyGroups:
    """Everything the group tier needs for the star- pages."""

    member_counts: dict[str, int] = field(default_factory=dict)
    extra_stats: dict[str, GroupExtraStats] = field(default_factory=dict)
    notable_members: dict[str, list[NotableObject]] = field(default_factory=dict)
    # The child families of each page that have stars, most stars first.
    children: dict[str, list[str]] = field(default_factory=dict)


def build_star_family_groups(
    star_objects: list[StarObject],
    wikidata_entities: WikidataEntityCache,
    extrasolar_dir: Path = EXTRASOLAR_DIR,
) -> StarFamilyGroups:
    """Counts, child families and listed stars of every star- page.

    With no extrasolar export served, the pages have their text only.
    """
    out = StarFamilyGroups()
    root = extrasolar_dir / "v1" / "x"
    with served(extrasolar_dir):
        if not (root / "metadata.json").exists():
            logger.warning("Star family pages without stars: no export at %s", root)
            return out
        reader = ExportReader(root)
        listed = reader.metadata["families"]
        out.notable_members = _notable_stars(
            reader, [entry["slug"] for entry in listed], star_objects, wikidata_entities
        )

    for entry in listed:
        slug = family_slug(entry["slug"])
        out.member_counts[slug] = entry["published"] + entry["estimated"]
        out.extra_stats[slug] = GroupExtraStats(
            published_star_count=entry["published"],
            estimated_star_count=entry["estimated"],
        )
    children: dict[str, list[str]] = defaultdict(list)
    for family, parents in PARENTS.items():
        if out.member_counts.get(family_slug(family)):
            for parent in parents:
                children[family_slug(parent)].append(family_slug(family))
    out.children = {
        slug: sorted(kids, key=lambda kid: (-out.member_counts[kid], kid))
        for slug, kids in children.items()
    }
    logger.info(
        "Star family pages: %d families, %d with stars, %d with listed stars",
        len(FAMILIES),
        sum(1 for n in out.member_counts.values() if n),
        len(out.notable_members),
    )
    return out


def _notable_stars(
    reader: ExportReader,
    bits: list[str],
    star_objects: list[StarObject],
    wikidata_entities: WikidataEntityCache,
) -> dict[str, list[NotableObject]]:
    """The stars with a Wikipedia article that each family but the root has,
    most sitelinks first. A published family only: a page lists what
    catalogues say."""
    stars = {star.id: star for star in star_objects if star.qid}
    rows = reader.rows(METADATA.slug, sorted(stars), ["families"])
    if missing := len(stars) - len(rows):
        logger.info("Star family pages: %d stars with an entry are not served", missing)
    tagged = [id_ for id_, row in rows.items() if row["families"]]

    def rank(id_: int) -> tuple[int, bool]:
        """Sitelinks, and whether one is an article in a language of the site."""
        found = wikidata_entities.get_star_entity(stars[id_].qid)
        if found is None or found.entity is None:
            return 0, False
        return found.sitelinks, not set(found.entity["sitelinks"]).isdisjoint(LANGUAGES)

    with ThreadPoolExecutor(8) as pool:
        ranks = dict(zip(tagged, pool.map(rank, tagged)))
    ranked = sorted(
        ((sitelinks, id_) for id_, (sitelinks, article) in ranks.items() if article),
        key=lambda pair: (-pair[0], pair[1]),
    )
    out: dict[str, list[NotableObject]] = defaultdict(list)
    for sitelinks, id_ in ranked:
        mask = rows[id_]["families"]
        star = stars[id_]
        for bit, family in enumerate(bits):
            # Every star with a family is in the root, so its list would only
            # be the best-known stars.
            if family == ROOT_FAMILY:
                continue
            members = out[family_slug(family)]
            if mask >> bit & 1 and len(members) < NOTABLE_STARS:
                members.append(
                    NotableObject(
                        object_id=f"{PREFIX}{id_}",
                        wikidata_qid=star.qid,
                        fallback_name=star.name,
                        diameter_km=None,
                        first_obs=None,
                        star=True,
                        sitelinks_count=sitelinks,
                    )
                )
    return {slug: members for slug, members in out.items() if members}
