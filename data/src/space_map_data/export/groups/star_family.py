"""Star family (``star-``) group pages.

One page per family of ``constants/stars/families.py``. The extrasolar export
tags the stars, so the counts and the stars that a page lists come from its
served files, as the planets of the sitemap do: a page then tells what the
site serves. A page lists the stars with a Wikipedia article first, then other
stars of the family from the Metadata tiles. Those other stars can change from
one export to the next.
"""

import json
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyarrow as pa

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
# The fill reads at most this share of the Metadata rows, so the tier stays
# quick. A rare family can then list fewer stars than it has.
FILL_ROW_SHARE = 0.5
# Tiles read at a time, between two checks of the lists.
FILL_BATCH = 64


def family_slug(family: str) -> str:
    return f"{FAMILY_SLUG_PREFIX}{family}"


def parent_slugs(slug: str) -> list[str]:
    """The pages of the families that contain the family of ``slug``."""
    family = slug.removeprefix(FAMILY_SLUG_PREFIX)
    return [family_slug(parent) for parent in PARENTS.get(family, ())]


def served_families_stamp(extrasolar_dir: Path = EXTRASOLAR_DIR) -> dict | None:
    """The family counts and the Metadata token of the served extrasolar
    export, None with no export served. The pages count the families and list
    stars from the Metadata tiles, so they change with either."""
    path = extrasolar_dir / "v1" / "x" / "metadata.json"
    if not path.exists():
        return None
    metadata = json.loads(path.read_text())
    return {
        "families": metadata["families"],
        "metadata": metadata["tables"]["metadata"]["token"],
    }


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
    """The stars that each family but the root lists. A published family
    only: a page lists what catalogues say.

    The stars with a Wikipedia article come first, most sitelinks first.
    Other stars of the family fill the rest of the list (`_fill`)."""
    entries = {star.id: star for star in star_objects}
    stars = {id_: star for id_, star in entries.items() if star.qid}
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
    _fill(reader, bits, out, entries)
    return {slug: members for slug, members in out.items() if members}


def _fill(
    reader: ExportReader,
    bits: list[str],
    out: dict[str, list[NotableObject]],
    entries: dict[int, StarObject],
) -> None:
    """Fill each list but the root's up to NOTABLE_STARS with other stars of
    the family, from the Metadata tiles in order of level, shallowest first.

    A shallow tile covers more sky for its rows, so it holds more catalogued
    stars per row read. The fill reads at most FILL_ROW_SHARE of the rows, so
    a rare family can stay short. A star takes the name of its Metadata row,
    as its own page does.
    """
    published = {
        entry["slug"]: entry["published"] for entry in reader.metadata["families"]
    }
    wanted = {
        bit: min(NOTABLE_STARS, published[family])
        for bit, family in enumerate(bits)
        if family != ROOT_FAMILY
    }
    listed = {
        bit: {member.object_id for member in out[family_slug(bits[bit])]}
        for bit in wanted
    }
    open_bits = {bit for bit, n in wanted.items() if len(listed[bit]) < n}
    split = reader.split(METADATA.slug)
    order = np.lexsort((split.pixel, split.level)).tolist()
    budget = reader.metadata["tables"][METADATA.slug]["rows"] * FILL_ROW_SHARE

    def read(leaf: int) -> tuple[int, list[tuple[int, int, str | None]]]:
        """The rows of a tile, and the ID, families and name of each row
        with a published family."""
        tile = reader.leaf(METADATA.slug, leaf)
        ids = tile.numpy("id")
        if ids.size == 0:
            return 0, []
        families = tile.numpy("families")
        at = np.flatnonzero(families != 0)
        names = tile.column("name").take(pa.array(at)).to_pylist()
        return ids.size, list(zip(ids[at].tolist(), families[at].tolist(), names))

    read_rows = read_tiles = added = 0
    with ThreadPoolExecutor(8) as pool:
        for start in range(0, len(order), FILL_BATCH):
            if not open_bits or read_rows >= budget:
                break
            batch = order[start : start + FILL_BATCH]
            for size, found in pool.map(read, batch):
                read_rows += size
                for id_, mask, name in found:
                    for bit in [bit for bit in open_bits if mask >> bit & 1]:
                        object_id = f"{PREFIX}{id_}"
                        if object_id in listed[bit]:
                            continue
                        entry = entries.get(id_)
                        out[family_slug(bits[bit])].append(
                            NotableObject(
                                object_id=object_id,
                                wikidata_qid=entry.qid if entry else None,
                                fallback_name=name or str(id_),
                                diameter_km=None,
                                first_obs=None,
                                star=True,
                            )
                        )
                        listed[bit].add(object_id)
                        added += 1
                        if len(listed[bit]) == wanted[bit]:
                            open_bits.discard(bit)
            read_tiles += len(batch)
    logger.info(
        "Star family pages: %d stars filled in from %d of %d Metadata tiles"
        " (%d rows); short: %s",
        added,
        read_tiles,
        len(order),
        read_rows,
        ", ".join(
            f"{bits[bit]} {len(listed[bit])}/{n}"
            for bit, n in sorted(wanted.items())
            if len(listed[bit]) < n
        )
        or "none",
    )
