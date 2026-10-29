"""Planet family (``planet-``) group pages.

One page per family of ``constants/planets/families.py``. The extrasolar
export tags the planets, so the counts and the planets that a page lists come
from its served planet files, as for the star families. A page lists the
planets with a Wikipedia article first, then other planets of the family,
nearest host first.
"""

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from space_map_data.constants.planets.families import (
    FAMILIES,
    FAMILY_SLUG_PREFIX,
    PARENTS,
    ROOT_FAMILY,
)
from space_map_data.export.extrasolar.build import served
from space_map_data.export.extrasolar.reader import ExportReader
from space_map_data.export.groups.family_pages import (
    FamilyGroups,
    FamilyPages,
    served_metadata,
    sitelink_rank,
)
from space_map_data.export.notable import NotableObject
from space_map_data.export.objects.stars import (
    PREFIX,
    PlanetObject,
    planet_object,
    planet_page_names,
)
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.utils.paths import EXTRASOLAR_DIR

logger = logging.getLogger(__name__)

# As many planets as the star families list.
NOTABLE_PLANETS = 20

PAGES = FamilyPages(
    FAMILY_SLUG_PREFIX, PARENTS, "published_planet_count", "estimated_planet_count"
)


def served_planet_families_stamp(extrasolar_dir: Path = EXTRASOLAR_DIR) -> dict | None:
    """The family counts and the planets token of the served extrasolar
    export, None with no planets served. The pages count the families and
    list planets from the planet files, so they change with either."""
    metadata = served_metadata(extrasolar_dir)
    planets = None if metadata is None else metadata.get("planets")
    if planets is None:
        return None
    return {"families": planets["families"], "planets": planets["token"]}


@dataclass(frozen=True)
class _Planet:
    """What a list needs of a served planet."""

    object_id: str
    name: str
    # Its page; None without one.
    entry: PlanetObject | None
    families: tuple[str, ...]
    # pc; None when the render tree does not draw the host.
    distance: float | None

    @property
    def qid(self) -> str | None:
        return self.entry.qid if self.entry else None


def build_planet_family_groups(
    wikidata_entities: WikidataEntityCache,
    extrasolar_dir: Path = EXTRASOLAR_DIR,
) -> FamilyGroups:
    """Counts, child families and listed planets of every planet- page.

    With no planets served, the pages have their text only.
    """
    out = FamilyGroups()
    root = extrasolar_dir / "v1" / "x"
    with served(extrasolar_dir):
        if not (root / "metadata.json").exists():
            logger.warning("Planet family pages without planets: no export at %s", root)
            return out
        reader = ExportReader(root)
        if "planets" not in reader.metadata:
            logger.warning("Planet family pages without planets: none served")
            return out
        listed = reader.metadata["planets"]["families"]
        planets = _served_planets(reader)

    out.notable_members = _notable_planets(planets, wikidata_entities)
    PAGES.count(
        out,
        ((entry["slug"], entry["published"], entry["estimated"]) for entry in listed),
    )
    logger.info(
        "Planet family pages: %d families, %d with planets, %d with listed planets",
        len(FAMILIES),
        sum(1 for n in out.member_counts.values() if n),
        len(out.notable_members),
    )
    return out


def _served_planets(reader: ExportReader) -> list[_Planet]:
    """Every served planet with a published family."""
    hosts = reader.planet_hosts()
    keys = sorted({host["system"] for host in hosts.values()})
    with ThreadPoolExecutor(8) as pool:
        systems = list(pool.map(reader.system, keys))
    out = []
    for system in systems:
        distances = {host["id"]: host["distance"] for host in system["hosts"]}
        for planet in system["planets"]:
            if not planet["families"]:
                continue
            out.append(
                _Planet(
                    f"{PREFIX}{planet['host']}-b-{planet['number']}",
                    planet["name"],
                    planet_object(planet) if planet["object"] else None,
                    tuple(planet["families"]),
                    distances[planet["host"]],
                )
            )
    return out


def _notable_planets(
    planets: list[_Planet], wikidata_entities: WikidataEntityCache
) -> dict[str, list[NotableObject]]:
    """The planets that each family but the root lists. A published family
    only: a page lists what the measured values say.

    The planets with a Wikipedia article in a language of the site come
    first, most sitelinks first. Other planets of the family fill the rest
    of the list, nearest host first.
    """
    entries = [planet for planet in planets if planet.qid]
    rank = partial(sitelink_rank, wikidata_entities)
    with ThreadPoolExecutor(8) as pool:
        ranks = dict(zip(entries, pool.map(rank, [p.qid for p in entries])))
    first = sorted(
        (planet for planet in entries if ranks[planet][1]),
        key=lambda planet: (-ranks[planet][0], planet.object_id),
    )
    chosen = set(first)
    rest = sorted(
        (planet for planet in planets if planet not in chosen),
        key=lambda planet: (
            planet.distance is None,
            planet.distance or 0.0,
            planet.object_id,
        ),
    )
    out: dict[str, list[NotableObject]] = defaultdict(list)
    for planet in (*first, *rest):
        # Every planet with a family is in the root, so its list would only
        # be the best-known planets.
        lists = [
            members
            for family in planet.families
            if family != ROOT_FAMILY
            and len(members := out[PAGES.slug(family)]) < NOTABLE_PLANETS
        ]
        if not lists:
            continue
        # Only for a listed planet: the entities stay in a shared cache.
        member = NotableObject(
            object_id=planet.object_id,
            wikidata_qid=planet.qid,
            fallback_name=planet.name,
            diameter_km=None,
            first_obs=None,
            extrasolar=True,
            page_names=(
                planet_page_names(
                    wikidata_entities.get_listed_star(planet.qid), planet.entry
                )
                if planet.entry
                else {}
            ),
            sitelinks_count=ranks[planet][0] if planet in chosen else None,
        )
        for members in lists:
            members.append(member)
    return dict(out)
