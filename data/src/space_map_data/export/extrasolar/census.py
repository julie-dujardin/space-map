"""The objects of the extrasolar export by kind, for `/about/data`: how many
there are, the bytes of their files, and the objects that each source feeds.

An object's kind is its home table, so each ID counts once: a star has its
home in Point source, also when it is a point that holds two or more stars,
and a resolved star system in System. A source feeds an object when one of
its values comes from it. Wikidata is left out: every object with an item has
an object entry, and the main export counts the items from the entries.
"""

from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from space_map_data.extrasolar.exoplanets.table import GROUPS as PLANET_GROUPS
from space_map_data.extrasolar.ids import table_of
from space_map_data.extrasolar.registry import Registry
from space_map_data.extrasolar.sky import REGION_COUNT
from space_map_data.extrasolar.sources.wikidata import WIKIDATA
from space_map_data.extrasolar.tables import (
    BINARY_ORBIT,
    METADATA,
    POINT_SOURCE,
    SYSTEM,
    TableDef,
)

STAR, STAR_SYSTEM, PLANET = "star", "star_system", "planet"

KIND_OF_HOME = {POINT_SOURCE.number: STAR, SYSTEM.number: STAR_SYSTEM}
# The tables whose rows are all stars. Metadata and System hold both kinds.
_STAR_TABLES = (POINT_SOURCE.slug, BINARY_ORBIT.slug)
_SHARED_TABLES = (METADATA.slug, SYSTEM.slug)
# Another pass of a catalogue counts as that catalogue.
_CATALOGUE_OF_PASS = {
    "gaia-dr3-named": "gaia-dr3",
    "simbad-hip": "simbad",
    "simbad-parallax": "simbad",
}
# Groups of the star tables that a pass carries for a catalogue of their own,
# which the star panels credit apart.
_CATALOGUE_OF_GROUP = {
    "xgboost": "andrae-2023",
    "pastel": "pastel-2020",
    "apogee": "apogee-dr17",
    "lamost": "lamost-dr10",
    "xhip_metallicity": "xhip",
    "fidelity": "rybizki-2022",
    "orbit": "gaia-dr3-nss",
    "masses": "gaia-dr3-nss",
}
# The planets table names its planets outside its groups.
_PLANET_SOURCES = ("name_source", *(group.source_column for group in PLANET_GROUPS))

type Runner = Callable[[Callable, list, str], list]


def source_key(value: str, group: str | None = None) -> str | None:
    """The source of a value that the pass `value` brought, in `group` of a
    star table. None for Wikidata."""
    if value == WIKIDATA.name:
        return None
    by_group = _CATALOGUE_OF_GROUP.get(group) if group else None
    return by_group or _CATALOGUE_OF_PASS.get(value, value)


def read_columns(table: TableDef) -> tuple[str, ...]:
    """The columns of `table` that the census reads."""
    columns = ["id", *(group.source_column for group in table.groups)]
    if table is METADATA:
        columns.append("alias_target")
    return tuple(columns)


@dataclass
class Census:
    """`objects` holds the `count` and the `sources` of each kind. `rows`
    counts the live rows of Metadata and System by (table, kind)."""

    objects: dict[str, dict]
    rows: Counter[tuple[str, str]]


def region_census(
    job: tuple[Registry, int],
) -> tuple[Counter[tuple[str, str]], dict[str, Counter[str]]]:
    """The live rows of Metadata and System in one region by kind, and the
    objects of each kind that each source feeds."""
    registry, region = job
    rows_of: Counter[tuple[str, str]] = Counter()
    found: defaultdict[str, defaultdict[str, list[np.ndarray]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for table in (METADATA, POINT_SOURCE, BINARY_ORBIT, SYSTEM):
        rows = registry.read_table(table.slug, region, list(read_columns(table)))
        if rows is None:
            continue
        ids = rows["id"].to_numpy()
        home = table_of(ids)
        if table.slug in _SHARED_TABLES:
            live = (
                rows["alias_target"].is_null().to_numpy(zero_copy_only=False)
                if table is METADATA
                else np.ones(ids.size, bool)
            )
            for number, kind in KIND_OF_HOME.items():
                rows_of[table.slug, kind] += int((live & (home == number)).sum())
        # The rows of each source in this table, over all its groups.
        fed: dict[str, np.ndarray] = {}
        for group in table.groups:
            column = rows[group.source_column]
            for value in pc.unique(column).drop_null().to_pylist():
                key = source_key(value, group.name)
                if key is None:
                    continue
                has = pc.equal(column, value).fill_null(False).to_numpy()
                fed[key] = fed[key] | has if key in fed else has
        for key, has in fed.items():
            for number, kind in KIND_OF_HOME.items():
                picked = ids[has & (home == number)]
                if picked.size:
                    found[kind][key].append(picked)
    sources: dict[str, Counter[str]] = defaultdict(Counter)
    for kind, by_key in found.items():
        for key, parts in by_key.items():
            sources[kind][key] = np.unique(np.concatenate(parts)).size
    return rows_of, sources


def _planet_sources(table: pa.Table) -> Counter[str]:
    keys = list(zip(table["host"].to_pylist(), table["number"].to_pylist()))
    fed: defaultdict[str, set[tuple[int, int]]] = defaultdict(set)
    for column in _PLANET_SOURCES:
        for key, value in zip(keys, table[column].to_pylist()):
            if value is not None and (source := source_key(value)):
                fed[source].add(key)
    return Counter({source: len(planets) for source, planets in fed.items()})


def census(registry: Registry, run: Runner, planets: pa.Table | None) -> Census:
    """The objects of each kind, the sources most objects first. Each live
    ID has one Metadata row. `planets` is the planets table."""
    jobs = [(registry, region) for region in range(REGION_COUNT)]
    rows: Counter[tuple[str, str]] = Counter()
    sources: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for part_rows, part_sources in run(region_census, jobs, "census"):
        rows.update(part_rows)
        for kind, fed in part_sources.items():
            sources[kind].update(fed)
    count = Counter({kind: rows[METADATA.slug, kind] for kind in KIND_OF_HOME.values()})
    if planets is not None:
        count[PLANET] = planets.num_rows
        sources[PLANET] = _planet_sources(planets)
    objects = {
        kind: {
            "count": count[kind],
            "sources": dict(
                sorted(sources[kind].items(), key=lambda item: (-item[1], item[0]))
            ),
        }
        for kind in (STAR, STAR_SYSTEM, PLANET)
        if count[kind]
    }
    return Census(objects, rows)


def with_bytes(
    counted: Census,
    table_bytes: dict[str, int],
    tree_bytes: int,
    planet_bytes: int,
) -> dict[str, dict]:
    """The census with `size_bytes`, the bytes of each kind's files. The
    render tree draws the stars. The Metadata and System tiles go to the stars
    and the star systems by their rows. The sky cultures are not objects."""
    size: Counter[str] = Counter({STAR: tree_bytes, PLANET: planet_bytes})
    for slug in _STAR_TABLES:
        size[STAR] += table_bytes.get(slug, 0)
    for slug in _SHARED_TABLES:
        rows = {kind: counted.rows[slug, kind] for kind in KIND_OF_HOME.values()}
        for kind, n in rows.items():
            if n:
                size[kind] += round(table_bytes.get(slug, 0) * n / sum(rows.values()))
    return {
        kind: {
            "count": entry["count"],
            "size_bytes": size[kind],
            "sources": entry["sources"],
        }
        for kind, entry in counted.objects.items()
    }
