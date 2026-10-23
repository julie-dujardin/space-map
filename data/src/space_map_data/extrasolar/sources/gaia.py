"""Gaia DR3 as an ingest source: the positionable stars with their fidelity.

Each gaia_source chunk has a fidelity chunk with the same pixel range. Both are
read together and joined on `source_id`. Every star is a row of the pass. A
star with `fidelity_v2` under 0.5 has `mint` false: it gets an ID only when
another catalogue matches it. A star without a fidelity row mints.

A star that `hipparcos2_best_neighbour` names claims its Hipparcos number.

Licence: CC BY-NC 3.0 IGO, credit ESA/Gaia/DPAC. Fidelity: Rybizki et al.
2022, MNRAS 510, 2597.
"""

import logging
import re
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pcsv
import pyarrow.parquet as pq

from space_map_data.download.providers.stars import (
    gaia_bulk,
    gaia_cross_match,
    gaia_fidelity,
    gaia_source,
)
from space_map_data.extrasolar import sky
from space_map_data.extrasolar.arrays import map_sorted
from space_map_data.extrasolar.engine import Source
from space_map_data.extrasolar.tables import CROSS_ID

logger = logging.getLogger(__name__)

GAIA_DR3 = Source(name="gaia-dr3", catalogue="gaia", release="dr3", home=1, kind="star")
HIP = ("hip", "2007")

SOURCE_DIR = gaia_bulk.OUT_DIR / gaia_source.TABLE_PATH
FIDELITY_DIR = gaia_bulk.OUT_DIR / gaia_fidelity.TABLE_PATH
BEST_NEIGHBOUR = (
    gaia_bulk.OUT_DIR
    / gaia_cross_match.TREE
    / "hipparcos2_best_neighbour"
    / "Hipparcos2BestNeighbour.csv.gz"
)

EPOCH = 2016.0
MIN_FIDELITY = 0.5
# parallax_over_error is parallax / parallax_error, so it is not kept.
COLUMNS = tuple(name for name in gaia_source.COLUMNS if name != "parallax_over_error")
FIDELITY_COLUMNS = ("fidelity_v2", "norm_dg")
PIXEL_LEVEL = 8
_PIXELS = re.compile(r"_(\d+)-(\d+)\.parquet$")


@dataclass(frozen=True)
class BestNeighbours:
    """The best Gaia source of each Hipparcos star, sorted by source."""

    source_id: np.ndarray
    hip: np.ndarray

    @classmethod
    def read(cls, path: Path = BEST_NEIGHBOUR) -> BestNeighbours:
        table = pcsv.read_csv(
            path,
            convert_options=pcsv.ConvertOptions(
                include_columns=["source_id", "original_ext_source_id"],
                column_types={
                    "source_id": pa.int64(),
                    "original_ext_source_id": pa.int64(),
                },
            ),
        )
        source_id = table["source_id"].to_numpy()
        hip = table["original_ext_source_id"].to_numpy()
        order = np.argsort(source_id)
        logger.info("%d Hipparcos best neighbours", source_id.size)
        return cls(source_id[order], hip[order])

    def hip_of(self, source_id: np.ndarray) -> np.ndarray:
        """The Hipparcos number of each source, 0 where none."""
        return map_sorted(self.source_id, self.hip, source_id, 0)

    def source_of(self) -> dict[int, int]:
        return dict(zip(self.hip.tolist(), self.source_id.tolist()))


def single_claims(catalogue: str, release: str, ids: np.ndarray) -> pa.Array:
    """A list of one claim for each row with an id, null where the id is 0."""
    has = ids != 0
    values = pa.StructArray.from_arrays(
        [
            pa.array(np.full(int(has.sum()), catalogue), pa.string()),
            pa.array(np.full(int(has.sum()), release), pa.string()),
            pc.cast(pa.array(ids[has]), pa.string()),
        ],
        fields=list(CROSS_ID),
    )
    offsets = pa.array(np.r_[0, np.cumsum(has)].astype(np.int32))
    return pa.ListArray.from_arrays(
        offsets, values, type=pa.list_(CROSS_ID), mask=pa.array(~has)
    )


def join_fidelity(stars: pa.Table, fidelity: pa.Table) -> pa.Table:
    """`stars` with the fidelity columns of the same source, null where none."""
    at = pc.index_in(stars["source_id"], value_set=fidelity["source_id"])
    for name in FIDELITY_COLUMNS:
        stars = stars.append_column(name, fidelity[name].take(at))
    return stars


def engine_rows(stars: pa.Table, best: BestNeighbours) -> pa.Table:
    """The pass rows of Gaia stars that carry their fidelity columns."""
    source_id = stars["source_id"].to_numpy()
    ids = pc.cast(stars["source_id"], pa.string())
    error = np.hypot(
        stars["ra_error"].to_numpy(zero_copy_only=False),
        stars["dec_error"].to_numpy(zero_copy_only=False),
    )
    n = stars.num_rows
    columns = {
        "catalogue_id": ids,
        # A star without a fidelity row is kept.
        "mint": pc.fill_null(
            pc.greater_equal(stars["fidelity_v2"], MIN_FIDELITY), True
        ),
        "match_ra": stars["ra"],
        "match_dec": stars["dec"],
        "match_pmra": stars["pmra"],
        "match_pmdec": stars["pmdec"],
        "match_mag": stars["phot_g_mean_mag"],
        "match_error": pa.array(error / 1000, pa.float32()),
        "claims": single_claims(*HIP, best.hip_of(source_id)),
        "epoch": pa.array(np.full(n, EPOCH, np.float32)),
        "name": pc.binary_join_element_wise("Gaia DR3", ids, " "),
        "class": pa.array(np.full(n, "star"), pa.string()),
    }
    columns |= {name: stars[name] for name in COLUMNS if name != "source_id"}
    columns |= {name: stars[name] for name in FIDELITY_COLUMNS}
    return pa.table(columns)


def pixel_range(path: Path) -> tuple[int, int]:
    """The level-8 pixels of a chunk, from its name, as a closed range."""
    match = _PIXELS.search(path.name)
    if match is None:
        raise ValueError(f"{path.name} names no pixel range")
    return int(match[1]), int(match[2])


def in_ranges(
    ra: np.ndarray, dec: np.ndarray, ranges: list[tuple[int, int]]
) -> np.ndarray:
    """Whether each position is in one of the closed level-8 pixel ranges."""
    pixel = sky.cells(ra, dec, PIXEL_LEVEL)
    inside = np.zeros(pixel.size, bool)
    for low, high in ranges:
        inside |= (pixel >= low) & (pixel <= high)
    return inside


def _ordered[T, R](
    pool: ThreadPoolExecutor, work: Callable[[T], R], items: Iterable[T], ahead: int
) -> Iterator[R]:
    """`map` over a pool with at most `ahead` results waiting, in order."""
    queue = iter(items)
    pending: deque[Future[R]] = deque()
    try:
        for item in queue:
            pending.append(pool.submit(work, item))
            if len(pending) >= ahead:
                yield pending.popleft().result()
        while pending:
            yield pending.popleft().result()
    finally:
        for future in pending:
            future.cancel()


@dataclass
class GaiaReader:
    """Reads the Gaia chunks on a thread pool and counts what it gives."""

    best: BestNeighbours
    source_dir: Path = SOURCE_DIR
    fidelity_dir: Path = FIDELITY_DIR
    workers: int = 8
    counts: dict[str, int] = field(default_factory=dict)

    def chunks(self, limit: int | None = None) -> list[Path]:
        """Every chunk in pixel order, or the first ones that hold `limit` rows."""
        paths = sorted(self.source_dir.glob(f"{gaia_source.CHUNK_PREFIX}*.parquet"))
        if not paths:
            raise FileNotFoundError(f"no Gaia chunks in {self.source_dir}")
        if limit is None:
            return paths
        picked, rows = [], 0
        for path in paths:
            picked.append(path)
            rows += pq.ParquetFile(path).metadata.num_rows
            if rows >= limit:
                break
        return picked

    def fidelity_path(self, path: Path) -> Path:
        name = path.name.replace(gaia_source.CHUNK_PREFIX, gaia_fidelity.CHUNK_PREFIX)
        return self.fidelity_dir / name

    def read_chunk(self, path: Path) -> pa.Table:
        stars = pq.read_table(path, columns=list(COLUMNS))
        fidelity = pq.read_table(
            self.fidelity_path(path), columns=["source_id", *FIDELITY_COLUMNS]
        )
        return engine_rows(join_fidelity(stars, fidelity), self.best)

    def batches(self, chunks: list[Path]) -> Iterator[pa.Table]:
        """The pass rows of `chunks`, one table per chunk."""
        missing = [p for p in chunks if not self.fidelity_path(p).exists()]
        if missing:
            raise FileNotFoundError(
                f"{len(missing)} Gaia chunks have no fidelity chunk, first"
                f" {self.fidelity_path(missing[0])}"
            )
        counts = dict.fromkeys(
            ("chunks", "rows", "flagged", "without_fidelity", "claims"), 0
        )
        with ThreadPoolExecutor(self.workers) as pool:
            for rows in _ordered(pool, self.read_chunk, chunks, 2 * self.workers):
                counts["chunks"] += 1
                counts["rows"] += rows.num_rows
                counts["flagged"] += rows.num_rows - pc.sum(rows["mint"]).as_py()
                without = pc.is_null(rows["fidelity_v2"])
                if pc.any(without).as_py():
                    ids = rows["catalogue_id"].filter(without).to_pylist()
                    logger.warning("Gaia DR3 stars without a fidelity row: %s", ids)
                    counts["without_fidelity"] += len(ids)
                counts["claims"] += rows.num_rows - rows["claims"].null_count
                if counts["chunks"] % 200 == 0:
                    logger.info(
                        "Gaia: %d/%d chunks read", counts["chunks"], len(chunks)
                    )
                yield rows
        self.counts = {key: int(value) for key, value in counts.items()}
        logger.info(
            "Gaia: %d rows, %d flagged as spurious (mint false), %d without a"
            " fidelity row, %d claim a Hipparcos number",
            self.counts["rows"],
            self.counts["flagged"],
            self.counts["without_fidelity"],
            self.counts["claims"],
        )
