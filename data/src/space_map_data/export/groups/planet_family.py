"""Planet family (``planet-``) group pages, and the planets of the Planets
category page.

One page per family of ``constants/planets/families.py``. The extrasolar
export tags the exoplanets, so their counts and the exoplanets that a page
lists come from its served planet files, as for the star families. The
planets of the Solar System get their families from the same rules
(``export/solar_planets.py``) and add to the counts and the lists.

The Planets category page is the root of the tree: the families without a
parent are below it. It counts every planet, the Solar System's and the
served exoplanets of the IAU class ``planet``, and it has the stats and the
plot of all of them.

A list puts the planets with a Wikipedia article first, most sitelinks
first, then the other planets, nearest host first.
"""

import gzip
import logging
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

import orjson

from space_map_data.constants.categories import PLANETS_SLUG
from space_map_data.constants.planets.families import (
    EARTH_MASSES_PER_JUPITER,
    EARTH_RADII_PER_JUPITER,
    FAMILIES,
    FAMILY_SLUG_PREFIX,
    PARENTS,
)
from space_map_data.export.extrasolar.build import served
from space_map_data.export.extrasolar.planet_families import known
from space_map_data.export.extrasolar.reader import ExportReader
from space_map_data.export.groups.family_pages import (
    FamilyGroups,
    FamilyPages,
    object_sitelink_rank,
    served_metadata,
    sitelink_rank,
)
from space_map_data.export.groups.stats import GroupExtraStats
from space_map_data.export.notable import NotableObject
from space_map_data.export.objects.stars import (
    PREFIX,
    PlanetObject,
    planet_object,
    planet_page_names,
)
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.extrasolar.exoplanets.catalogues import (
    MINIMUM_MASS,
    TRUE_MASS,
)
from space_map_data.extrasolar.exoplanets.iau import PLANET
from space_map_data.utils.paths import EXTRASOLAR_DIR

logger = logging.getLogger(__name__)

# As many planets as the star families list.
NOTABLE_PLANETS = 20

PAGES = FamilyPages(
    FAMILY_SLUG_PREFIX,
    PARENTS,
    "published_planet_count",
    "estimated_planet_count",
    root=PLANETS_SLUG,
)

PLOT_FILE = "__planet_plot__.json.gz"
# How the plot knows a value.
MEASURED, MINIMUM, ESTIMATED = 0, 1, 2
# Significant digits of a plotted value.
PLOT_DIGITS = 4


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
class SolarPlanets:
    """The planets of the Solar System: their category members in
    heliocentric order, and their planet records by object id."""

    members: list[NotableObject]
    records: dict[str, dict]


@dataclass
class PlanetsPage:
    """The Planets category page: every planet."""

    member_count: int
    notable_members: list[NotableObject]
    # The Solar System planets on their own, in heliocentric order.
    solar_members: list[NotableObject]
    stats: GroupExtraStats
    # Columns of PLOT_FILE.
    plot: dict


@dataclass
class PlanetGroups(FamilyGroups):
    """The family pages and the Planets page."""

    planets: PlanetsPage | None = None


@dataclass
class _Planet:
    """What the pages need of a planet."""

    object_id: str
    name: str
    qid: str | None
    # Its published families.
    families: tuple[str, ...]
    # It has an estimated family and no published one.
    estimated_only: bool
    # pc; 0 in the Solar System, None when the render tree does not draw the
    # host.
    distance: float | None
    # (value, how it is known) of the mass (M⊕), the radius (R⊕) and the
    # semi-major axis (AU); (None, None) without a value.
    mass: tuple[float | None, int | None]
    radius: tuple[float | None, int | None]
    axis: tuple[float | None, int | None]
    # An exoplanet's object entry; None without one.
    entry: PlanetObject | None = None
    # A Solar System planet's category member.
    body: NotableObject | None = None
    # The kind of a measured mass: true or minimum.
    mass_kind: str | None = None


def build_planet_family_groups(
    wikidata_entities: WikidataEntityCache,
    solar: SolarPlanets,
    extrasolar_dir: Path = EXTRASOLAR_DIR,
) -> PlanetGroups:
    """Counts, child families and listed planets of every planet- page, and
    the Planets page.

    With no planets served, the pages count and list the Solar System only.
    """
    out = PlanetGroups()
    exoplanets: list[_Planet] = []
    listed: list[dict] = []
    root = extrasolar_dir / "v1" / "x"
    with served(extrasolar_dir):
        if not (root / "metadata.json").exists():
            logger.warning("Planet pages without exoplanets: no export at %s", root)
        else:
            reader = ExportReader(root)
            if "planets" not in reader.metadata:
                logger.warning("Planet pages without exoplanets: none served")
            else:
                listed = reader.metadata["planets"]["families"]
                exoplanets = _served_planets(reader)
    planets = [*_solar_planets(solar), *exoplanets]

    exo_counts = {entry["slug"]: entry for entry in listed}
    solar_counts = Counter(f for p in planets if p.body for f in p.families)
    PAGES.count(
        out,
        (
            (
                family,
                exo_counts.get(family, {}).get("published", 0) + solar_counts[family],
                exo_counts.get(family, {}).get("estimated", 0),
            )
            for family in FAMILIES
        ),
    )
    ranked = _ranked(planets, wikidata_entities)
    out.notable_members = _family_lists(ranked, wikidata_entities)
    out.planets = _planets_page(planets, ranked, wikidata_entities, out.member_counts)
    logger.info(
        "Planet pages: %d planets (%d exoplanets), %d families, %d with planets,"
        " %d with listed planets",
        len(planets),
        len(exoplanets),
        len(FAMILIES),
        sum(1 for n in out.member_counts.values() if n),
        len(out.notable_members),
    )
    return out


def _plotted(
    record: dict, name: str, scale: float = 1.0
) -> tuple[float | None, int | None]:
    """A value of a planet record for the plot and the stats, and how it is
    known. A limit or an assumed value is no value."""
    found = known(record, name, scale)
    if found is None or found.point is None:
        return None, None
    if not found.measured:
        return found.point, ESTIMATED
    if name == "mass" and record["values"].get("mass_kind") == MINIMUM_MASS:
        return found.point, MINIMUM
    return found.point, MEASURED


def _planet(
    record: dict,
    object_id: str,
    name: str,
    distance: float | None,
    entry: PlanetObject | None = None,
    body: NotableObject | None = None,
) -> _Planet:
    mass = _plotted(record, "mass", EARTH_MASSES_PER_JUPITER)
    return _Planet(
        object_id=object_id,
        name=name,
        qid=body.wikidata_qid if body else (entry.qid if entry else None),
        families=tuple(record["families"]),
        estimated_only=bool(not record["families"] and record["families_estimated"]),
        distance=distance,
        mass=mass,
        radius=_plotted(record, "radius", EARTH_RADII_PER_JUPITER),
        axis=_plotted(record, "semi_major_axis"),
        entry=entry,
        body=body,
        mass_kind={MEASURED: TRUE_MASS, MINIMUM: MINIMUM_MASS}.get(mass[1]),
    )


def _solar_planets(solar: SolarPlanets) -> list[_Planet]:
    """The planets of the Solar System that have a planet record."""
    return [
        _planet(
            solar.records[member.object_id],
            member.object_id,
            member.fallback_name,
            0.0,
            body=member,
        )
        for member in solar.members
        if member.object_id in solar.records
    ]


def _served_planets(reader: ExportReader) -> list[_Planet]:
    """Every served planet of the IAU class planet, by system file, then
    host and number."""
    hosts = reader.planet_hosts()
    keys = sorted({host["system"] for host in hosts.values()})
    with ThreadPoolExecutor(8) as pool:
        systems = list(pool.map(reader.system, keys))
    out = []
    for system in systems:
        distances = {host["id"]: host["distance"] for host in system["hosts"]}
        for planet in system["planets"]:
            if planet["class"] != PLANET:
                continue
            out.append(
                _planet(
                    planet,
                    f"{PREFIX}{planet['host']}-b-{planet['number']}",
                    planet["name"],
                    distances[planet["host"]],
                    entry=planet_object(planet) if planet["object"] else None,
                )
            )
    return out


def _rank(planet: _Planet, wikidata_entities: WikidataEntityCache) -> tuple[int, bool]:
    """The sitelinks of the planet's item, and whether one is an article in a
    language of the site."""
    rank = sitelink_rank if planet.body is None else object_sitelink_rank
    return rank(wikidata_entities, planet.qid)


def _ranked(
    planets: list[_Planet], wikidata_entities: WikidataEntityCache
) -> list[tuple[_Planet, int | None]]:
    """Every planet in list order, with its sitelinks when an article puts it
    first. The planets with a Wikipedia article in a language of the site
    come first, most sitelinks first. The others follow, nearest host first."""
    entries = [planet for planet in planets if planet.qid]
    with ThreadPoolExecutor(8) as pool:
        ranks = dict(
            zip(
                (p.object_id for p in entries),
                pool.map(lambda p: _rank(p, wikidata_entities), entries),
            )
        )
    first = sorted(
        (p for p in entries if ranks[p.object_id][1]),
        key=lambda p: (-ranks[p.object_id][0], p.object_id),
    )
    chosen = {p.object_id for p in first}
    rest = sorted(
        (p for p in planets if p.object_id not in chosen),
        key=lambda p: (p.distance is None, p.distance or 0.0, p.object_id),
    )
    return [(p, ranks[p.object_id][0]) for p in first] + [(p, None) for p in rest]


def _member(
    planet: _Planet,
    sitelinks: int | None,
    wikidata_entities: WikidataEntityCache,
) -> NotableObject:
    """The list entry of a planet. A Solar System planet keeps its category
    member. An exoplanet takes the names of its page."""
    if planet.body is not None:
        return replace(planet.body, sitelinks_count=sitelinks)
    return NotableObject(
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
        sitelinks_count=sitelinks,
    )


def _family_lists(
    ranked: list[tuple[_Planet, int | None]], wikidata_entities: WikidataEntityCache
) -> dict[str, list[NotableObject]]:
    """The planets that each family page lists. A published family only: a
    page lists what the measured values say."""
    out: dict[str, list[NotableObject]] = defaultdict(list)
    for planet, sitelinks in ranked:
        lists = [
            members
            for family in planet.families
            if len(members := out[PAGES.slug(family)]) < NOTABLE_PLANETS
        ]
        if not lists:
            continue
        # Only for a listed planet: the entities stay in a shared cache.
        member = _member(planet, sitelinks, wikidata_entities)
        for members in lists:
            members.append(member)
    return {slug: members for slug, members in out.items() if members}


def _planets_page(
    planets: list[_Planet],
    ranked: list[tuple[_Planet, int | None]],
    wikidata_entities: WikidataEntityCache,
    member_counts: dict[str, int],
) -> PlanetsPage:
    """The Planets page: every planet, its list, its stats and its plot."""
    solar_members = [p.body for p in planets if p.body is not None]
    stats = GroupExtraStats(
        solar_member_count=len(solar_members),
        exoplanet_count=len(planets) - len(solar_members),
        published_planet_count=sum(1 for p in planets if p.families),
        estimated_planet_count=sum(1 for p in planets if p.estimated_only),
        planet_family_count=sum(1 for n in member_counts.values() if n),
    )
    # A card shows no uncertainty, so it takes a planet whose true mass is
    # measured too: a radius alone can be a disk's glow (HD 100546 b).
    largest = _largest(
        [p for p in planets if p.mass[1] == MEASURED], "radius", lambda p: p.radius
    )
    if largest is not None:
        stats.largest_planet = largest
    heaviest = _largest(planets, "mass", lambda p: p.mass)
    if heaviest is not None:
        stats.most_massive_planet = heaviest
    return PlanetsPage(
        member_count=len(planets),
        notable_members=[
            _member(planet, sitelinks, wikidata_entities)
            for planet, sitelinks in ranked[:NOTABLE_PLANETS]
        ],
        solar_members=solar_members,
        stats=stats,
        plot=_plot(planets),
    )


def _largest(planets: list[_Planet], name: str, value) -> dict | None:
    """The planet with the largest measured `name`, as {primary_type,
    primary_id, name, <name>_earth}. A minimum mass is measured, and a mass
    names its kind."""
    found = [p for p in planets if value(p)[1] in (MEASURED, MINIMUM)]
    if not found:
        return None
    best = max(found, key=lambda p: (value(p)[0], p.object_id))
    out = {
        "primary_type": "object",
        "primary_id": best.object_id,
        "name": best.name,
        f"{name}_earth": _round(value(best)[0]),
    }
    if name == "mass":
        out["mass_kind"] = best.mass_kind
    return out


def _round(x: float | None) -> float | None:
    return None if x is None else float(f"{x:.{PLOT_DIGITS}g}")


def _plot(planets: list[_Planet]) -> dict:
    """Columns of every planet, Solar System first: the mass (M⊕), the radius
    (R⊕) and the semi-major axis (AU), each with how it is known. `solar`
    names the planets of the first rows."""
    names = ("mass", "radius", "semi_major_axis")
    columns: dict[str, list] = {
        column: [] for name in names for column in (name, f"{name}_flag")
    }
    for planet in planets:
        for name, (value, flag) in zip(
            names, (planet.mass, planet.radius, planet.axis), strict=True
        ):
            columns[name].append(_round(value))
            columns[f"{name}_flag"].append(flag)
    return {
        **columns,
        "solar": [p.object_id for p in planets if p.body is not None],
    }


def write_planet_plot(out_dir: Path, plot: dict) -> None:
    """Write groups/__planet_plot__.json.gz."""
    path = out_dir / "groups" / PLOT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(orjson.dumps(plot)))
    logger.info("Wrote the planet plot: %d planets → %s", len(plot["mass"]), path.name)
