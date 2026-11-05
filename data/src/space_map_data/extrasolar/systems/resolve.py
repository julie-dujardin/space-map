"""Members to stored objects: the resolver interface and the object facts.

The builder does no I/O on the registry or the engine. A `Resolver` gives it
the object of each catalogue id, matches positions, and gives the facts of
the objects that it found. In the ingest, these are the links of the run, a
pass of the engine that does not mint, and the rows of the run's tables.

A key is the object of the run: a minted ID, or a run key of a new object.
0 is no object. The builder never mints and never assumes that a key is an
ID.

The candidates of a node are the objects that its ids reach, best first:
1. its own SIMBAD object;
2. the SIMBAD component that one of its other ids names (a row with no
   listed children). SIMBAD lists the components of close pairs, where
   Hipparcos and HD have one entry for both;
3. its Gaia DR3 id, its rows in the planet catalogues, its HIP and HD
   numbers;
4. the links that the builder makes itself: a component of the same WDS id
   and letter in another source, when the separations agree, a match by
   position.
In one rank, the object that more of the node's ids reach comes first, so one
wrong id loses to the others. Then the lower key comes first.
"""

import math
from collections import defaultdict
from typing import NamedTuple, Protocol

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from space_map_data.extrasolar.systems.nodes import (
    GAIA_DR3,
    HD,
    HIP,
    OBJECT_CATALOGUES,
    PLANET_HOSTS,
    SIMBAD,
    SIMBAD_CATALOGUES,
    SIMBAD_OID,
)
from space_map_data.extrasolar.systems.simbad import SimbadIndex
from space_map_data.utils.arrays import find_sorted

# The facts of an object that the decisions read.
FACTS = pa.schema(
    [
        ("key", pa.int64()),
        # ICRS at J2016.0, deg, and mas/yr.
        ("ra", pa.float64()),
        ("dec", pa.float64()),
        ("pmra", pa.float32()),
        ("pmdec", pa.float32()),
        ("pmra_error", pa.float32()),
        ("pmdec_error", pa.float32()),
        # G, else an estimate of G.
        ("mag", pa.float32()),
        # The `astrometry_source` of Point source.
        ("astrometry", pa.string()),
        ("parallax", pa.float32()),
        ("parallax_error", pa.float32()),
        # Of the Gaia solution that gives the parallax, else null.
        ("ruwe", pa.float32()),
        # Parsecs where the object renders, by `placement`, else null.
        ("distance", pa.float64()),
        ("spectral_type", pa.string()),
        ("non_single_star", pa.int16()),
        ("name", pa.string()),
        ("name_source", pa.string()),
    ]
)
# Position rows for the matcher, with the columns of the engine's pass rows.
MATCH = pa.schema(
    [
        ("catalogue_id", pa.string()),
        ("mint", pa.bool_()),
        ("match_ra", pa.float64()),
        ("match_dec", pa.float64()),
        ("match_pmra", pa.float32()),
        ("match_pmdec", pa.float32()),
        ("match_mag", pa.float32()),
        ("match_error", pa.float32()),
        # Keys that the row never matches.
        ("match_exclude", pa.list_(pa.int64())),
    ]
)
GAIA_ASTROMETRY = frozenset({"gaia-dr3", "gaia-dr3-named"})
HIPPARCOS_ASTROMETRY = frozenset({"hipparcos-2007", "hipparcos-1997"})
OWN_ASTROMETRY = GAIA_ASTROMETRY | HIPPARCOS_ASTROMETRY

# Candidate ranks, best first.
OWN_OID, SIMBAD_PATH, LETTER, POSITION = 0, 1, 8, 9
RANKS = {
    SIMBAD_OID: OWN_OID,
    GAIA_DR3: 2,
    **{catalogue: 3 for catalogue in PLANET_HOSTS},
    HIP: 4,
    HD: 5,
}
# How a member reached its object, by rank, for the report.
HOW = {
    OWN_OID: "by id",
    SIMBAD_PATH: "by SIMBAD",
    2: "by id",
    3: "by id",
    4: "by id",
    5: "by id",
    LETTER: "by letter",
    POSITION: "by position",
}


class Resolver(Protocol):
    def keys(self, catalogue: str, release: str, ids: pa.Array) -> np.ndarray:
        """The key of each id of this catalogue release, 0 where none."""
        ...

    def match(self, rows: pa.Table, kind: tuple[str, str]) -> np.ndarray:
        """The key that each MATCH row matches by position, 0 where none and
        for a key of its `match_exclude`. `kind` is the id of the rows, `WDS_ID`
        or `MSC_ID`."""
        ...

    def facts(self, keys: np.ndarray) -> pa.Table:
        """The FACTS rows of these keys; a key with no row is left out."""
        ...


class Fact(NamedTuple):
    key: int
    ra: float
    dec: float
    pmra: float
    pmdec: float
    pmra_error: float
    pmdec_error: float
    mag: float
    astrometry: str | None
    parallax: float
    parallax_error: float
    ruwe: float
    distance: float
    spectral_type: str | None
    non_single_star: int | None
    name: str | None
    name_source: str | None


class Facts:
    """The facts of the objects, by key."""

    def __init__(self, table: pa.Table) -> None:
        order = np.argsort(table["key"].to_numpy(), kind="stable")
        self.table = table.take(pa.array(order))
        self.keys = self.table["key"].to_numpy()
        self._rows: dict[int, Fact] = {}

    def __len__(self) -> int:
        return self.keys.size

    def at(self, keys: np.ndarray) -> np.ndarray:
        """The row of each key, -1 where none."""
        return find_sorted(self.keys, np.asarray(keys, np.int64))

    def column(self, name: str, keys: np.ndarray) -> np.ndarray:
        """A numeric column for these keys, NaN where none."""
        at = self.at(keys)
        hit = at >= 0
        found = np.full(at.shape, np.nan)
        values = self.table[name].take(pa.array(at[hit]))
        found[hit] = values.cast(pa.float64()).fill_null(np.nan).to_numpy()
        return found

    def has(self, name: str, keys: np.ndarray, values: frozenset[str]) -> np.ndarray:
        """Whether the text column for each key is one of `values`."""
        at = self.at(keys)
        hit = at >= 0
        found = np.zeros(at.shape, bool)
        texts = self.table[name].take(pa.array(at[hit]))
        found[hit] = pc.is_in(texts, value_set=pa.array(sorted(values))).to_numpy()
        return found

    def texts(self, name: str, keys: np.ndarray) -> list[str | None]:
        at = self.at(keys)
        values = self.table[name].to_pylist()
        return [values[i] if i >= 0 else None for i in at.tolist()]

    def get(self, key: int) -> Fact | None:
        if key in self._rows:
            return self._rows[key]
        at = int(self.at(np.array([key]))[0])
        if at < 0:
            return None
        row = self.table.slice(at, 1).to_pylist()[0]

        def number(name: str) -> float:
            return math.nan if row[name] is None else float(row[name])

        fact = Fact(
            key=key,
            ra=number("ra"),
            dec=number("dec"),
            pmra=number("pmra"),
            pmdec=number("pmdec"),
            pmra_error=number("pmra_error"),
            pmdec_error=number("pmdec_error"),
            mag=number("mag"),
            astrometry=row["astrometry"],
            parallax=number("parallax"),
            parallax_error=number("parallax_error"),
            ruwe=number("ruwe"),
            distance=number("distance"),
            spectral_type=row["spectral_type"],
            non_single_star=row["non_single_star"],
            name=row["name"],
            name_source=row["name_source"],
        )
        self._rows[key] = fact
        return fact


def flatten_ids(
    table: pa.Table, column: str = "ids"
) -> tuple[np.ndarray, pa.Array, pa.Array, pa.Array]:
    """The row, catalogue, release and catalogue id of every id in `column`."""
    ids = table[column].combine_chunks()
    flat = pc.list_flatten(ids)
    rows = pc.list_parent_indices(ids).to_numpy()
    return (
        rows,
        flat.field("catalogue"),
        flat.field("release"),
        flat.field("catalogue_id"),
    )


def resolve_ids(
    resolver: Resolver,
    wanted: dict[tuple[str, str], set[str]],
) -> dict[tuple[str, str, str], int]:
    """The key of each wanted id that has one."""
    found: dict[tuple[str, str, str], int] = {}
    for (catalogue, release), ids in sorted(wanted.items()):
        values = sorted(ids)
        if not values:
            continue
        keys = resolver.keys(catalogue, release, pa.array(values, pa.string()))
        for value, key in zip(values, keys.tolist()):
            if key:
                found[(catalogue, release, value)] = key
    return found


def candidates(
    tables: list[pa.Table],
    resolver: Resolver,
    index: SimbadIndex,
    links: dict[tuple[str, str, str], tuple[int, int]],
) -> tuple[list[list[list[tuple[int, int]]]], list[dict[tuple[int, int], int]]]:
    """For each table and row, its (key, rank) candidates, best first. For
    each table, how many ids of a row reach a key, by (row, key), where more
    than one.

    `links` gives the (key, rank) of the ids that the builder linked.
    """
    flats = [flatten_ids(table) for table in tables]
    wanted: dict[tuple[str, str], set[str]] = defaultdict(set)
    via_simbad: dict[tuple[str, str, str], list[int]] = {}
    for rows, catalogue, release, value in flats:
        for c, r, v in zip(
            catalogue.to_pylist(), release.to_pylist(), value.to_pylist()
        ):
            if (c, r) in OBJECT_CATALOGUES:
                wanted[(c, r)].add(v)
            if (c, r) in SIMBAD_CATALOGUES and (c, r, v) not in via_simbad:
                oids = index.components(c, r, v)
                via_simbad[(c, r, v)] = oids
                wanted[SIMBAD_OID].update(str(oid) for oid in oids)
    keys = resolve_ids(resolver, wanted)
    out = []
    reaches = []
    for table, (rows, catalogue, release, value) in zip(tables, flats):
        # (key, rank, the index of the id that reaches it)
        found: list[list[tuple[int, int, int]]] = [[] for _ in range(table.num_rows)]
        source = table["source"][0].as_py() if table.num_rows else None
        for at, (row, c, r, v) in enumerate(
            zip(
                rows.tolist(),
                catalogue.to_pylist(),
                release.to_pylist(),
                value.to_pylist(),
            )
        ):
            if (key := keys.get((c, r, v))) and (c, r) in RANKS:
                found[row].append((key, RANKS[(c, r)], at))
            if source != SIMBAD and (c, r) in SIMBAD_CATALOGUES:
                for oid in via_simbad.get((c, r, v), []):
                    if key := keys.get((*SIMBAD_OID, str(oid))):
                        found[row].append((key, SIMBAD_PATH, at))
            if link := links.get((c, r, v)):
                found[row].append((*link, at))
        best = []
        reach: dict[tuple[int, int], int] = {}
        for row, items in enumerate(found):
            ordered, counts = _best_first(items)
            best.append(ordered)
            reach.update(((row, key), n) for key, n in counts.items() if n > 1)
        out.append(best)
        reaches.append(reach)
    return out, reaches


def _best_first(
    items: list[tuple[int, int, int]],
) -> tuple[list[tuple[int, int]], dict[int, int]]:
    """Each key once at its best rank, best first, and how many ids reach it."""
    best: dict[int, int] = {}
    reached_by: dict[int, set[int]] = defaultdict(set)
    for key, rank, at in items:
        best[key] = min(rank, best.get(key, rank))
        reached_by[key].add(at)
    counts = {key: len(found) for key, found in reached_by.items()}
    ordered = sorted(
        best.items(), key=lambda item: (item[1], -counts[item[0]], item[0])
    )
    return ordered, counts
