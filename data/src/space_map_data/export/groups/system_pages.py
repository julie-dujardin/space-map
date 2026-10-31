"""The Star Systems and Planetary Systems category pages.

A star system is a root of the System table: stars that orbit each other. A
planetary system is a host with a planet of the IAU class planet, one for each
host, and the Solar System. A pair that a planet circles is on both pages.

A page lists the systems with a Wikipedia article, most sitelinks first. The
Solar System heads the planetary systems, and links to its category page.
"""

import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

from space_map_data.constants.categories import (
    CATEGORIES,
    PLANETARY_SYSTEMS_SLUG,
    PLANETS_SLUG,
    SOLAR_SYSTEM_SLUG,
    STAR_SYSTEMS_SLUG,
)
from space_map_data.export.extrasolar.build import served
from space_map_data.export.extrasolar.reader import ExportReader
from space_map_data.export.groups.family_pages import served_metadata, sitelink_rank
from space_map_data.export.groups.stats import GroupExtraStats
from space_map_data.export.names import Names, ObjectNames, entity_names
from space_map_data.export.notable import NotableObject
from space_map_data.export.objects.stars import PREFIX, StarObject
from space_map_data.extrasolar.tables import METADATA, SYSTEM
from space_map_data.utils.paths import EXTRASOLAR_DIR

logger = logging.getLogger(__name__)

# As many systems as the family pages list.
NOTABLE_SYSTEMS = 20
# A star system past a pair.
MULTIPLE_STARS = 3
# A planetary system past a lone planet.
MULTIPLE_PLANETS = 2


@dataclass
class SystemPages:
    """The two pages, by slug."""

    member_counts: dict[str, int] = field(default_factory=dict)
    notable_members: dict[str, list[NotableObject]] = field(default_factory=dict)
    extra_stats: dict[str, GroupExtraStats] = field(default_factory=dict)
    # The names of the systems that the stat cards name, by object id.
    card_names: dict[str, dict[str, Names]] = field(default_factory=dict)


def served_system_pages_stamp(extrasolar_dir: Path = EXTRASOLAR_DIR) -> dict | None:
    """The System token of the served export, None with no export served: the
    page counts the roots of its tiles."""
    metadata = served_metadata(extrasolar_dir)
    return None if metadata is None else metadata["tables"][SYSTEM.slug]["token"]


def build_system_pages(
    star_objects: list[StarObject],
    hosts: Counter[int],
    names: ObjectNames,
    extrasolar_dir: Path = EXTRASOLAR_DIR,
) -> SystemPages:
    """Counts, stats and lists of both pages. `hosts` has the planets of the
    class planet of each host. With no export served, the Planetary Systems
    page has the Solar System alone."""
    out = SystemPages()
    out.member_counts[PLANETARY_SYSTEMS_SLUG] = len(hosts) + 1
    out.extra_stats[PLANETARY_SYSTEMS_SLUG] = GroupExtraStats(
        multi_planet_system_count=1 + sum(n >= MULTIPLE_PLANETS for n in hosts.values())
    )
    entries = {star.id: star for star in star_objects}
    notable = partial(_notable, entries, names)
    out.notable_members[PLANETARY_SYSTEMS_SLUG] = [
        _solar_system(names),
        *notable(set(hosts) & set(entries)),
    ][:NOTABLE_SYSTEMS]
    root = extrasolar_dir / "v1" / "x"
    with served(extrasolar_dir):
        if not (root / "metadata.json").exists():
            logger.warning("Star Systems page without systems: no export at %s", root)
            return out
        reader = ExportReader(root)
        systems, multiple, most_stars = _root_counts(reader)
        rows = reader.rows(SYSTEM.slug, sorted(entries), ["depth"])
        most_planets = max(
            hosts, key=lambda id_: (hosts[id_], id_ in entries, id_), default=None
        )
        cards = _card_names(
            reader,
            entries,
            names,
            [id_ for id_ in (most_stars[1], most_planets) if id_ is not None],
        )
    out.member_counts[STAR_SYSTEMS_SLUG] = systems
    out.extra_stats[STAR_SYSTEMS_SLUG] = GroupExtraStats(
        multiple_star_system_count=multiple,
        most_stars_system=_card(most_stars[1], "stars", most_stars[0], cards),
    )
    out.card_names[STAR_SYSTEMS_SLUG] = {
        _object_id(most_stars[1]): cards[most_stars[1]]
    }
    if most_planets is not None:
        out.extra_stats[PLANETARY_SYSTEMS_SLUG].most_planets_system = _card(
            most_planets, "planets", hosts[most_planets], cards
        )
        out.card_names[PLANETARY_SYSTEMS_SLUG] = {
            _object_id(most_planets): cards[most_planets]
        }
    out.notable_members[STAR_SYSTEMS_SLUG] = notable(
        {id_ for id_, row in rows.items() if row["depth"] == 0}
    )
    logger.info(
        "System pages: %d star systems, %d planetary systems",
        systems,
        out.member_counts[PLANETARY_SYSTEMS_SLUG],
    )
    return out


def _solar_system(names: ObjectNames) -> NotableObject:
    """The Solar System as a member: its page is a group's."""
    spec = next(c for c in CATEGORIES if c.slug == SOLAR_SYSTEM_SLUG)
    return NotableObject(
        object_id="",
        wikidata_qid=spec.wikidata_qid,
        names=entity_names(names.entities.get_referenced(spec.wikidata_qid), spec.name),
        diameter_km=None,
        first_obs=None,
        # The Solar System page has a map for a picture.
        image_of=PLANETS_SLUG,
        group_slug=SOLAR_SYSTEM_SLUG,
    )


def _object_id(id_: int) -> str:
    return f"{PREFIX}{id_}"


def _card_names(
    reader: ExportReader,
    entries: dict[int, StarObject],
    names: ObjectNames,
    ids: list[int],
) -> dict[int, Names]:
    """The names of the pages of `ids`."""
    rows = reader.rows(METADATA.slug, ids, ["name"])
    return {
        id_: names.star(entries[id_])
        if id_ in entries
        else Names(rows[id_]["name"] or str(id_))
        for id_ in ids
    }


def _card(id_: int, key: str, n: int, cards: dict[int, Names]) -> dict:
    """A stat card that points at a system, as {primary_type, primary_id, name,
    <key>}."""
    return {
        "primary_type": "object",
        "primary_id": _object_id(id_),
        "name": cards[id_].name,
        key: n,
    }


def _root_counts(reader: ExportReader) -> tuple[int, int, tuple[int, int]]:
    """The star systems, those of MULTIPLE_STARS stars or more, and the stars
    and the ID of the system with the most."""

    def count(leaf: int) -> tuple[int, int, tuple[int, int]]:
        tile = reader.leaf(SYSTEM.slug, leaf)
        roots = tile.numpy("depth") == 0
        stars, ids = tile.numpy("stars")[roots], tile.numpy("id")[roots]
        if stars.size == 0:
            return 0, 0, (0, 0)
        at = int(stars.argmax())
        return (
            stars.size,
            int((stars >= MULTIPLE_STARS).sum()),
            (int(stars[at]), int(ids[at])),
        )

    leaves = range(len(reader.split(SYSTEM.slug).level))
    with ThreadPoolExecutor(8) as pool:
        counts = list(pool.map(count, leaves))
    return (
        sum(n for n, _, _ in counts),
        sum(n for _, n, _ in counts),
        max(most for _, _, most in counts),
    )


def _notable(
    entries: dict[int, StarObject], names: ObjectNames, ids: set[int]
) -> list[NotableObject]:
    """The systems of `ids` with a Wikipedia article, most sitelinks first."""
    stars = [entries[id_] for id_ in sorted(ids) if entries[id_].qid]
    rank = partial(sitelink_rank, names.entities)
    with ThreadPoolExecutor(8) as pool:
        ranks = list(pool.map(rank, [star.qid for star in stars]))
    found = sorted(
        (
            (sitelinks, star)
            for star, (sitelinks, article) in zip(stars, ranks, strict=True)
            if article
        ),
        key=lambda pair: (-pair[0], pair[1].id),
    )
    return [
        NotableObject(
            object_id=f"{PREFIX}{star.id}",
            wikidata_qid=star.qid,
            names=names.star(star),
            diameter_km=None,
            first_obs=None,
            extrasolar=True,
            sitelinks_count=sitelinks,
        )
        for sitelinks, star in found[:NOTABLE_SYSTEMS]
    ]
