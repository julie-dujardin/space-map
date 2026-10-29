"""Star family (``star-``) group pages.

One page per family of ``constants/stars/families.py``. The extrasolar export
tags the stars, so the counts and the stars that a page lists come from its
served files, as the planets of the sitemap do: a page then tells what the
site serves. A page lists the stars with a Wikipedia article first, then the
brightest other stars of the family, which the extrasolar export picks.
"""

import json
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from functools import partial
from pathlib import Path

from space_map_data.constants.stars.families import (
    FAMILIES,
    FAMILY_SLUG_PREFIX,
    PARENTS,
    ROOT_FAMILY,
    SUN_SPECTRAL_TYPE,
)
from space_map_data.export.extrasolar.build import families_file, served
from space_map_data.export.extrasolar.reader import ExportReader
from space_map_data.export.extrasolar.tiles import LISTED_STARS
from space_map_data.export.groups.family_pages import (
    FamilyGroups,
    FamilyPages,
    object_sitelink_rank,
    served_metadata,
    sitelink_rank,
)
from space_map_data.export.notable import NotableObject
from space_map_data.export.objects.stars import PREFIX, StarObject
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.extrasolar.families import of_spectral_type
from space_map_data.extrasolar.tables import METADATA
from space_map_data.utils.content_stamp import content_stamp
from space_map_data.utils.paths import EXTRASOLAR_DIR

logger = logging.getLogger(__name__)

PAGES = FamilyPages(
    FAMILY_SLUG_PREFIX, PARENTS, "published_star_count", "estimated_star_count"
)


def served_families_stamp(extrasolar_dir: Path = EXTRASOLAR_DIR) -> dict | None:
    """The family counts, a stamp of the family lists and the Metadata token
    of the served extrasolar export, None with no export served. The pages
    read the counts and the lists, and the families of their Wikipedia stars
    from the Metadata tiles."""
    # Under the lock, so both files come from one export.
    with served(extrasolar_dir):
        metadata = served_metadata(extrasolar_dir)
        if metadata is None:
            return None
        return {
            "families": metadata["families"],
            "lists": content_stamp(families_file(extrasolar_dir / "v1" / "x")),
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
    first. The brightest other stars of the family fill the rest of the list
    (`_add_brightest`)."""
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
        sitelinks, _ = object_sitelink_rank(wikidata_entities, sun.wikidata_qid)
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
            if mask >> bit & 1 and len(members) < LISTED_STARS:
                members.append(member)
    _add_brightest(reader, out, entries)
    return {slug: members for slug, members in out.items() if members}


def _add_brightest(
    reader: ExportReader,
    out: dict[str, list[NotableObject]],
    entries: dict[int, StarObject],
) -> None:
    """Fill each list up to LISTED_STARS with the brightest stars of its
    family in FAMILIES_FILE that it does not list yet. A star takes the name
    of its Metadata row, as its own page does."""
    brightest = json.loads(families_file(reader.root).read_text())["brightest"]
    published = {
        entry["slug"]: entry["published"] for entry in reader.metadata["families"]
    }
    added = 0
    short = []
    for family, stars in brightest.items():
        members = out[PAGES.slug(family)]
        known = {member.object_id for member in members}
        for star in stars:
            if len(members) >= LISTED_STARS:
                break
            object_id = f"{PREFIX}{star['id']}"
            if object_id in known:
                continue
            found = entries.get(star["id"])
            members.append(
                NotableObject(
                    object_id=object_id,
                    wikidata_qid=found.qid if found else None,
                    fallback_name=star["name"] or str(star["id"]),
                    diameter_km=None,
                    first_obs=None,
                    extrasolar=True,
                )
            )
            added += 1
        wanted = min(LISTED_STARS, published[family])
        if len(members) < wanted:
            short.append(f"{family} {len(members)}/{wanted}")
    logger.info("Star family pages: %d of the brightest stars added", added)
    # The export fills each list, so a short one means the two files disagree.
    if short:
        logger.warning("Star family pages short of their family: %s", ", ".join(short))
