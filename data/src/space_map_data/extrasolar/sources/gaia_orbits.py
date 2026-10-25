"""Gaia DR3 binary orbits and masses, one solution per star, for table 2.

A source with more than one solution in nss_two_body_orbit keeps one, by
SOLUTION_ORDER: astrometric solutions first, because only they give the orbit
in space, then spectroscopic, then eclipsing. The masses of binary_masses join
by source_id. A source with two mass rows keeps the one whose combination
method names the type of the kept solution.

Licence: CC BY-NC 3.0 IGO, credit ESA/Gaia/DPAC. Orbits: Gaia Collaboration,
Arenou et al. 2023, A&A 674, A34.
"""

import logging
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from space_map_data.download.providers.stars import (
    gaia_binary_masses,
    gaia_bulk,
    gaia_source,
    gaia_two_body_orbit,
)
from space_map_data.extrasolar.tables import BINARY_ORBIT, NSS_ASTROMETRY
from space_map_data.utils.arrays import find_sorted

logger = logging.getLogger(__name__)

ORBIT_DIR = gaia_bulk.OUT_DIR / gaia_two_body_orbit.TABLE_PATH
MASSES_DIR = gaia_bulk.OUT_DIR / gaia_binary_masses.TABLE_PATH
ORBIT_PREFIX = "NssTwoBodyOrbit_"
MASSES_PREFIX = "BinaryMasses-"

# First wins. A validated orbit goes before its unvalidated form.
SOLUTION_ORDER = (
    "AstroSpectroSB1",
    "OrbitalTargetedSearchValidated",
    "OrbitalAlternativeValidated",
    "Orbital",
    "OrbitalTargetedSearch",
    "OrbitalAlternative",
    "SB2",
    "SB2C",
    "SB1",
    "SB1C",
    "EclipsingSpectro",
    "EclipsingBinary",
)
ASTROMETRIC = frozenset(SOLUTION_ORDER[:6])
ECLIPSING = frozenset(SOLUTION_ORDER[-2:])
# The terms of a combination method that name each solution type.
# binary_masses gives Orbital masses also to AstroSpectroSB1 solutions.
METHOD_TERMS = {
    "AstroSpectroSB1": {"AstroSpectroSB1", "Orbital"},
    **{name: {"Orbital"} for name in SOLUTION_ORDER[1:6]},
    "SB2": {"SB2"},
    "SB2C": {"SB2"},
    "SB1": {"SB1"},
    "SB1C": {"SB1"},
    "EclipsingSpectro": {"EclipsingSpectro"},
    "EclipsingBinary": {"Eclipsing"},
}
ORBIT_GROUP, MASS_GROUP = BINARY_ORBIT.groups
COLUMNS = tuple(field.name for field in BINARY_ORBIT.group_fields)
PUBLISHED = {stored: name for name, stored in NSS_ASTROMETRY.items()}
LEFT_OUT = "left_out"
# Vectors parsed at once. The split text of a vector takes up to about 2 kB.
PARSE_ROWS = 50_000

# A column of the solutions by its published name.
Columns = Callable[[str], pa.ChunkedArray]


def starts(sorted_keys: np.ndarray) -> np.ndarray:
    """Whether each key of a sorted array is the first of its run."""
    return np.diff(sorted_keys, prepend=sorted_keys[:1] - 1) != 0


def family(solution_type: str) -> str:
    if solution_type in ASTROMETRIC:
        return "astrometric"
    return "eclipsing" if solution_type in ECLIPSING else "spectroscopic"


def part_paths(directory: Path, prefix: str) -> list[Path]:
    paths = sorted(directory.glob(f"{prefix}*.parquet"))
    if not paths:
        raise FileNotFoundError(f"no {prefix}*.parquet in {directory}")
    return paths


def column_reader(paths: list[Path]) -> Columns:
    """Reads one column at a time, so the whole table is never in memory."""

    def column(name: str) -> pa.ChunkedArray:
        parts = [pq.read_table(path, columns=[name]) for path in paths]
        return pa.concat_tables(parts)[name]

    return column


def parse_vectors(text: pa.ChunkedArray | pa.Array) -> pa.Array:
    """Published vectors such as "[0.5,NaN]" as float32 lists."""
    text = pc.utf8_trim(text, "[]")
    if isinstance(text, pa.ChunkedArray):
        text = text.combine_chunks()
    parts = pc.split_pattern(text, ",")
    items = pc.list_flatten(parts)
    parent = pc.list_parent_indices(parts).to_numpy()
    # An empty vector splits into one empty string.
    filled = pc.not_equal(items, "").to_numpy(zero_copy_only=False)
    counts = np.bincount(parent[filled], minlength=len(text))
    offsets = pa.array(np.r_[0, np.cumsum(counts)].astype(np.int32))
    values = pc.cast(items.filter(pa.array(filled)), pa.float32())
    return pa.ListArray.from_arrays(offsets, values, mask=text.is_null())


def _orbit_columns(column: Columns, kept: pa.Array) -> dict[str, pa.Array]:
    """The orbit columns of the rows `kept`, in table 2's names and types."""
    columns = {}
    for field in ORBIT_GROUP.columns:
        values = column(PUBLISHED.get(field.name, field.name)).take(kept)
        if field.name == "corr_vec":
            columns[field.name] = pa.concat_arrays(
                [
                    parse_vectors(values.slice(start, PARSE_ROWS))
                    for start in range(0, len(values), PARSE_ROWS)
                ]
                or [pa.array([], field.type)]
            )
        else:
            columns[field.name] = values.combine_chunks().cast(field.type)
    return columns


@dataclass(frozen=True)
class Orbits:
    """The kept solution of each source with its masses, sorted by source.

    `rows` has `source_id`, the columns of table 2 and `left_out`, the types
    of the other solutions of the source.
    """

    rows: pa.Table
    counts: dict[str, int]

    @classmethod
    def read(cls, orbit_dir: Path = ORBIT_DIR, masses_dir: Path = MASSES_DIR) -> Orbits:
        column = column_reader(part_paths(orbit_dir, ORBIT_PREFIX))
        masses = [pq.read_table(p) for p in part_paths(masses_dir, MASSES_PREFIX)]
        return cls.build(column, pa.concat_tables(masses))

    @classmethod
    def build(cls, column: Columns, masses: pa.Table) -> Orbits:
        """`column` gives each column of nss_two_body_orbit by its name."""
        types = column("nss_solution_type").combine_chunks()
        unknown = set(pc.unique(types).to_pylist()) - set(SOLUTION_ORDER)
        if unknown:
            raise ValueError(f"orbit solution types with no rank: {sorted(unknown)}")
        rank = pc.index_in(types, value_set=pa.array(SOLUTION_ORDER)).to_numpy()
        source = column("source_id").to_numpy()
        order = np.lexsort((rank, source))
        source = source[order]
        first = starts(source)
        group = np.cumsum(first) - 1
        others = np.flatnonzero(~first)
        per_source = np.bincount(group[others], minlength=int(first.sum()))
        offsets = np.r_[0, np.cumsum(per_source)]
        left_out = pa.ListArray.from_arrays(
            pa.array(offsets.astype(np.int32)), types.take(pa.array(order[others]))
        )
        kept = pa.array(order[first])
        kept_source = source[first]
        kept_types = types.take(kept)

        columns = {"source_id": pa.array(kept_source, pa.int64())}
        columns |= _orbit_columns(column, kept)
        mass_columns, counts = _masses(masses, kept_source, kept_types)
        columns |= mass_columns
        columns[LEFT_OUT] = left_out
        counts |= {"solutions": source.size, "sources": kept_source.size}
        logger.info(
            "Gaia orbits: %d solutions of %d sources; masses: %s",
            source.size,
            kept_source.size,
            counts,
        )
        return cls(pa.table(columns), counts)

    @property
    def source_id(self) -> np.ndarray:
        return self.rows["source_id"].to_numpy()

    def join(self, stars: pa.Table) -> pa.Table:
        """`stars` with the columns of table 2, null where a star has none."""
        at = find_sorted(self.source_id, stars["source_id"].to_numpy())
        index = pa.array(at, mask=at < 0)
        for name in COLUMNS:
            stars = stars.append_column(name, self.rows[name].take(index))
        return stars

    def report(self, joined: np.ndarray, ranges: list[tuple[int, int]]) -> dict:
        """Counts of the sources that rows took, and of those left outside.

        `joined` are the source ids that got a row, `ranges` the level-8 pixel
        ranges of the chunks read.
        """
        ids = self.source_id
        pixel = ids >> gaia_source.PIXEL_SHIFT
        read = np.zeros(ids.size, bool)
        for low, high in ranges:
            read |= (pixel >= low) & (pixel <= high)
        took = np.isin(ids, joined)
        types = self.rows["nss_solution_type"].to_pylist()
        left_out = self.rows[LEFT_OUT].to_pylist()
        rows = Counter(family(types[k]) for k in np.flatnonzero(took).tolist())
        pairs = Counter(
            f"{types[k]} over {other}"
            for k in np.flatnonzero(took).tolist()
            for other in left_out[k]
        )
        outside = Counter(family(types[k]) for k in np.flatnonzero(read & ~took))
        has_masses = self.rows["m1"].is_valid().to_numpy(zero_copy_only=False)
        out = {
            "joined": int(took.sum()),
            "joined_by_family": dict(rows),
            "with_masses": int((took & has_masses).sum()),
            "left_out": sum(pairs.values()),
            "left_out_by_pair": dict(pairs.most_common()),
            "outside": int((read & ~took).sum()),
            "outside_by_family": dict(outside),
        }
        logger.info(
            "Gaia orbits: %d joined %s, %d with masses; %d solutions left out %s;"
            " %d sources of the chunks read are not among the stars %s",
            out["joined"],
            out["joined_by_family"],
            out["with_masses"],
            out["left_out"],
            out["left_out_by_pair"],
            out["outside"],
            out["outside_by_family"],
        )
        return out


def _masses(
    masses: pa.Table, kept_source: np.ndarray, kept_types: pa.Array
) -> tuple[dict[str, pa.Array], dict[str, int]]:
    """The mass columns for each kept solution, and counts of the mass rows."""
    at = find_sorted(kept_source, masses["source_id"].to_numpy())
    without = at < 0
    if without.any():
        logger.warning(
            "Gaia masses: %d rows of sources with no orbit solution, e.g. %s",
            int(without.sum()),
            masses["source_id"].to_numpy()[without][:10].tolist(),
        )
    masses = masses.filter(pa.array(~without))
    at = at[~without]
    method = masses["combination_method"].combine_chunks()
    solution = kept_types.take(pa.array(at))
    named_pairs = [
        f"{m}|{t}"
        for m in pc.unique(method).drop_null().to_pylist()
        for t in SOLUTION_ORDER
        if METHOD_TERMS[t] & set(filter(None, re.split(r"[+()]", m)))
    ]
    named = pc.is_in(
        pc.binary_join_element_wise(method, solution, "|"),
        value_set=pa.array(named_pairs, pa.string()),
    )
    named = named.fill_null(False).to_numpy(zero_copy_only=False)
    order = np.lexsort((~named, at))
    first = starts(at[order])
    chosen = order[first]
    if (~first).any():
        dropped = order[~first]
        logger.info(
            "Gaia masses: %d second rows of a source left out: %s",
            dropped.size,
            dict(
                Counter(
                    f"{m} for {t}"
                    for m, t in zip(
                        method.take(pa.array(dropped)).to_pylist(),
                        solution.take(pa.array(dropped)).to_pylist(),
                    )
                )
            ),
        )
    unnamed = chosen[~named[chosen]]
    if unnamed.size:
        logger.info(
            "Gaia masses: %d rows kept from another solution of the source: %s",
            unnamed.size,
            dict(
                Counter(
                    f"{m} for {t}"
                    for m, t in zip(
                        method.take(pa.array(unnamed)).to_pylist(),
                        solution.take(pa.array(unnamed)).to_pylist(),
                    )
                )
            ),
        )
    index = np.full(kept_source.size, -1, np.int64)
    index[at[chosen]] = chosen
    take = pa.array(index, mask=index < 0)
    columns = {
        field.name: masses[field.name].take(take).cast(field.type)
        for field in MASS_GROUP.columns
    }
    counts = {
        "mass_rows": int(masses.num_rows + without.sum()),
        "mass_rows_without_solution": int(without.sum()),
        "mass_rows_left_out": int((~first).sum()),
        "masses_from_another_solution": int(unnamed.size),
    }
    return columns, counts
