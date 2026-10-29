"""Star family (``star-``) group pages.

One page per family of ``constants/stars/families.py``. The extrasolar export
tags the stars, so the counts and the stars that a page lists come from its
served files, as the planets of the sitemap do: a page then tells what the
site serves. A page lists the stars with a Wikipedia article first, then other
stars of the family from the Metadata tiles. Those other stars can change from
one export to the next.
"""

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from functools import partial
from pathlib import Path

import numpy as np
import pyarrow as pa

from space_map_data.constants.stars.families import (
    FAMILIES,
    FAMILY_SLUG_PREFIX,
    PARENTS,
    ROOT_FAMILY,
    SUN_SPECTRAL_TYPE,
)
from space_map_data.export.extrasolar.build import served
from space_map_data.export.extrasolar.families import of_spectral_type
from space_map_data.export.extrasolar.reader import ExportReader
from space_map_data.export.groups.family_pages import (
    FamilyGroups,
    FamilyPages,
    served_metadata,
    sitelink_rank,
)
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

PAGES = FamilyPages(
    FAMILY_SLUG_PREFIX, PARENTS, "published_star_count", "estimated_star_count"
)


def served_families_stamp(extrasolar_dir: Path = EXTRASOLAR_DIR) -> dict | None:
    """The family counts and the Metadata token of the served extrasolar
    export, None with no export served. The pages count the families and list
    stars from the Metadata tiles, so they change with either."""
    metadata = served_metadata(extrasolar_dir)
    if metadata is None:
        return None
    return {
        "families": metadata["families"],
        "metadata": metadata["tables"]["metadata"]["token"],
    }


def build_star_family_groups(
    star_objects: list[StarObject],
    wikidata_entities: WikidataEntityCache,
    extrasolar_dir: Path = EXTRASOLAR_DIR,
    sun: NotableObject | None = None,
) -> FamilyGroups:
    """Counts, child families and listed stars of every star- page.

    With no extrasolar export served, the pages have their text only. The
    Sun is in no catalogue of that export, so `sun` adds it to the families
    of its spectral type.
    """
    out = FamilyGroups()
    sun_families = set(of_spectral_type(SUN_SPECTRAL_TYPE)) if sun else set()
    root = extrasolar_dir / "v1" / "x"
    with served(extrasolar_dir):
        if not (root / "metadata.json").exists():
            logger.warning("Star family pages without stars: no export at %s", root)
            return out
        reader = ExportReader(root)
        listed = reader.metadata["families"]
        out.notable_members = _notable_stars(
            reader,
            [entry["slug"] for entry in listed],
            star_objects,
            wikidata_entities,
            sun,
        )

    PAGES.count(
        out,
        (
            (
                entry["slug"],
                entry["published"] + (entry["slug"] in sun_families),
                entry["estimated"],
            )
            for entry in listed
        ),
    )
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
    sun: NotableObject | None,
) -> dict[str, list[NotableObject]]:
    """The stars that each family but the root lists. A published family
    only: a page lists what catalogues say.

    The stars with a Wikipedia article and the Sun come first, most sitelinks
    first. Other stars of the family fill the rest of the list (`_fill`)."""
    entries = {star.id: star for star in star_objects}
    stars = {id_: star for id_, star in entries.items() if star.qid}
    rows = reader.rows(METADATA.slug, sorted(stars), ["families"])
    if missing := len(stars) - len(rows):
        logger.info("Star family pages: %d stars with an entry are not served", missing)
    tagged = [id_ for id_, row in rows.items() if row["families"]]
    rank = partial(sitelink_rank, wikidata_entities)
    with ThreadPoolExecutor(8) as pool:
        ranks = dict(zip(tagged, pool.map(rank, [stars[id_].qid for id_ in tagged])))
    ranked = [
        (
            sitelinks,
            rows[id_]["families"],
            NotableObject(
                object_id=f"{PREFIX}{id_}",
                wikidata_qid=stars[id_].qid,
                fallback_name=stars[id_].name,
                diameter_km=None,
                first_obs=None,
                extrasolar=True,
                sitelinks_count=sitelinks,
            ),
        )
        for id_, (sitelinks, article) in ranks.items()
        if article
    ]
    if sun is not None:
        found = wikidata_entities.get_entity(sun.wikidata_qid)
        sitelinks = len(found["sitelinks"]) if found else 0
        families = set(of_spectral_type(SUN_SPECTRAL_TYPE))
        mask = sum(1 << bit for bit, family in enumerate(bits) if family in families)
        ranked.append((sitelinks, mask, replace(sun, sitelinks_count=sitelinks)))
    ranked.sort(key=lambda each: (-each[0], each[2].object_id))
    out: dict[str, list[NotableObject]] = defaultdict(list)
    for _, mask, member in ranked:
        for bit, family in enumerate(bits):
            # Every star with a family is in the root, so its list would only
            # be the best-known stars.
            if family == ROOT_FAMILY:
                continue
            members = out[PAGES.slug(family)]
            if mask >> bit & 1 and len(members) < NOTABLE_STARS:
                members.append(member)
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
        bit: {member.object_id for member in out[PAGES.slug(bits[bit])]}
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
                        out[PAGES.slug(bits[bit])].append(
                            NotableObject(
                                object_id=object_id,
                                wikidata_qid=entry.qid if entry else None,
                                fallback_name=name or str(id_),
                                diameter_km=None,
                                first_obs=None,
                                extrasolar=True,
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
