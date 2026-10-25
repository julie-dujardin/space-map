"""Gaia DR3 positions, fidelity, GSP-Phot radii, GSP-Spec and XP metallicities.

The companion tables join by source_id. Low-fidelity stars mint only when
matched by another catalogue. A star without a companion row stays, with null
values for that table. GSP-Spec gets the calibrations of Recio-Blanco et al.
2023 (A&A 674, A29); its flag chain stays as published, for the reader's cut.

Licence: CC BY-NC 3.0 IGO, credit ESA/Gaia/DPAC. Fidelity: Rybizki et al.
2022, MNRAS 510, 2597. XP metallicities: Andrae, Rix & Chandra 2023, ApJS 267,
8, CC BY 4.0.
"""

import logging
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
    gaia_astrophysical_parameters,
    gaia_bulk,
    gaia_cross_match,
    gaia_fidelity,
    gaia_source,
    gaia_xp_metallicity,
)
from space_map_data.extrasolar import sky
from space_map_data.extrasolar.engine import Source
from space_map_data.extrasolar.tables import CROSS_ID
from space_map_data.utils.arrays import floats, map_sorted

logger = logging.getLogger(__name__)

GAIA_DR3 = Source(name="gaia-dr3", catalogue="gaia", release="dr3", home=1, kind="star")
HIP = ("hip", "2007")

SOURCE_DIR = gaia_bulk.OUT_DIR / gaia_source.TABLE_PATH
FIDELITY_DIR = gaia_bulk.OUT_DIR / gaia_fidelity.TABLE_PATH
ASTROPHYSICAL_DIR = gaia_bulk.OUT_DIR / gaia_astrophysical_parameters.TABLE_PATH
XGBOOST_DIR = gaia_bulk.OUT_DIR / gaia_xp_metallicity.TABLE_PATH
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
GSPSPEC_COLUMNS = (
    *(
        f"{name}_gspspec{bound}"
        for name in ("mh", "fem", "logg")
        for bound in ("", "_lower", "_upper")
    ),
    "flags_gspspec",
)
ASTROPHYSICAL_COLUMNS = (
    "radius_gspphot",
    "radius_gspphot_lower",
    "radius_gspphot_upper",
    *GSPSPEC_COLUMNS,
)
GSPSPEC_CALIBRATED = ("mh_gspspec_calibrated", "feh_gspspec_calibrated")
# Recio-Blanco et al. 2023: [M/H] from the literature fit of Table 3, [Fe I/H]
# from Table 4, both polynomials of the uncalibrated log g in ascending powers.
MH_CALIBRATION = (0.274, -0.1373, -0.0050, 0.0048)
FEH_CALIBRATION = (0.3699, -0.0680, 0.0028, -0.0004)
FEH_LOGG_RANGE = (1.01, 4.85)
# Characters of flags_gspspec, from 0: extrapol, FeUpLim, FeUncer (Table 2).
EXTRAPOL, FE_UPPER_LIMIT, FE_UNCERTAINTY = 7, 27, 28
XGBOOST_COLUMNS = tuple(
    name for name in gaia_xp_metallicity.SCHEMA.names if name != "source_id"
)


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


def join_rows(stars: pa.Table, rows: pa.Table, names: Iterable[str]) -> pa.Table:
    """`stars` with the columns `names` of the row of the same source.

    A star without a row stays, with null values: no default may stand in for
    a missing radius or metallicity.
    """
    at = pc.index_in(stars["source_id"], value_set=rows["source_id"])
    for name in names:
        stars = stars.append_column(name, rows[name].take(at))
    return stars


def join_fidelity(stars: pa.Table, fidelity: pa.Table) -> pa.Table:
    return join_rows(stars, fidelity, FIDELITY_COLUMNS)


def _flag(flags: pa.ChunkedArray, at: int) -> np.ndarray:
    """One character of each flag chain as a number, 9 where there is none."""
    padded = pc.utf8_rpad(flags.fill_null(""), at + 1, "9")
    chars = pc.utf8_slice_codeunits(padded, at, at + 1)
    return pc.cast(chars, pa.int8()).to_numpy()


def calibrate_gspspec(stars: pa.Table) -> pa.Table:
    """`stars` with the calibrated GSP-Spec [M/H] and [Fe/H].

    [Fe/H] is [Fe/M] + [M/H] with the Fe I correction, null outside the log g
    range of the correction, or when the flags mark an extrapolation, an
    upper limit or a poor [Fe/M].
    """
    logg = floats(stars, "logg_gspspec")
    mh = floats(stars, "mh_gspspec") + np.polynomial.polynomial.polyval(
        logg, MH_CALIBRATION
    )
    flags = stars["flags_gspspec"]
    holds = (
        (logg >= FEH_LOGG_RANGE[0])
        & (logg <= FEH_LOGG_RANGE[1])
        & (_flag(flags, EXTRAPOL) == 0)
        & (_flag(flags, FE_UPPER_LIMIT) == 0)
        & (_flag(flags, FE_UNCERTAINTY) <= 1)
    )
    feh = (
        floats(stars, "fem_gspspec")
        + floats(stars, "mh_gspspec")
        + np.polynomial.polynomial.polyval(logg, FEH_CALIBRATION)
    )
    feh = np.where(holds, feh, np.nan)
    for name, values in zip(GSPSPEC_CALIBRATED, (mh, feh)):
        stars = stars.append_column(
            name, pa.array(values, pa.float32(), from_pandas=True)
        )
    return stars


def engine_rows(stars: pa.Table, best: BestNeighbours) -> pa.Table:
    """Pass rows with the companion columns and the Hipparcos claims."""
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
    columns |= {name: stars[name] for name in ASTROPHYSICAL_COLUMNS}
    columns |= {name: stars[name] for name in GSPSPEC_CALIBRATED}
    columns |= {name: stars[name] for name in XGBOOST_COLUMNS}
    return pa.table(columns)


def in_ranges(
    ra: np.ndarray, dec: np.ndarray, ranges: list[tuple[int, int]]
) -> np.ndarray:
    """Whether each position is in one of the closed level-8 pixel ranges."""
    pixel = sky.cells(ra, dec, gaia_source.PIXEL_LEVEL)
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
    astrophysical_dir: Path = ASTROPHYSICAL_DIR
    xgboost_dir: Path = XGBOOST_DIR
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
        parameters = pq.read_table(
            self.astrophysical_path(path), columns=["source_id", *ASTROPHYSICAL_COLUMNS]
        )
        xgboost = pq.read_table(
            self.xgboost_path(path), columns=["source_id", *XGBOOST_COLUMNS]
        )
        stars = join_rows(stars, fidelity, FIDELITY_COLUMNS)
        stars = calibrate_gspspec(join_rows(stars, parameters, ASTROPHYSICAL_COLUMNS))
        stars = join_rows(stars, xgboost, XGBOOST_COLUMNS)
        return engine_rows(stars, self.best)

    def astrophysical_path(self, path: Path) -> Path:
        name = path.name.replace(
            gaia_source.CHUNK_PREFIX, gaia_astrophysical_parameters.CHUNK_PREFIX
        )
        return self.astrophysical_dir / name

    def xgboost_path(self, path: Path) -> Path:
        name = path.name.replace(
            gaia_source.CHUNK_PREFIX, gaia_xp_metallicity.CHUNK_PREFIX
        )
        return self.xgboost_dir / name

    def batches(self, chunks: list[Path]) -> Iterator[pa.Table]:
        """The pass rows of `chunks`, one table per chunk."""
        companions = (
            ("fidelity", self.fidelity_path),
            ("astrophysical parameters", self.astrophysical_path),
            ("XGBoost parameters", self.xgboost_path),
        )
        for kind, companion in companions:
            missing = [p for p in chunks if not companion(p).exists()]
            if missing:
                raise FileNotFoundError(
                    f"{len(missing)} Gaia chunks have no {kind} chunk, first"
                    f" {companion(missing[0])}"
                )
        counts = dict.fromkeys(
            ("chunks", "rows", "flagged", "without_fidelity", "claims", "xgboost"), 0
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
                counts["xgboost"] += rows.num_rows - rows["mh_xgboost"].null_count
                if counts["chunks"] % 200 == 0:
                    logger.info(
                        "Gaia: %d/%d chunks read", counts["chunks"], len(chunks)
                    )
                yield rows
        self.counts = {key: int(value) for key, value in counts.items()}
        logger.info(
            "Gaia: %d rows, %d flagged as spurious (mint false), %d without a"
            " fidelity row, %d claim a Hipparcos number, %d have an XP metallicity",
            self.counts["rows"],
            self.counts["flagged"],
            self.counts["without_fidelity"],
            self.counts["claims"],
            self.counts["xgboost"],
        )
