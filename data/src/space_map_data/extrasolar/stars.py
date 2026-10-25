"""The star ingest: Gaia DR3, then Hipparcos, the IAU star names and Wikidata.

Gaia goes first, so a star that Gaia measured has its home and its cell from
Gaia. The metallicity catalogues (APOGEE DR17, the LAMOST DR10 M dwarfs) are
no pass: their rows join the Gaia rows by source_id. `limit` reads only the
first Gaia chunks that hold that many stars, and the Hipparcos stars and names
in the same pixels. Such an ingest is partial:
it retires nothing, but it still rebuilds the tables from what it read. It
never goes to REGISTRY_ROOT, because every later ingest keeps the IDs that it
mints.
"""

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from itertools import pairwise
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from space_map_data.download.providers.stars import wikidata_stars
from space_map_data.download.providers.stars.gaia_source import pixel_range
from space_map_data.extrasolar.engine import IngestResult, IngestRun
from space_map_data.extrasolar.registry import Registry, RegistryError
from space_map_data.extrasolar.sources import apogee, hipparcos, lamost, names, wikidata
from space_map_data.extrasolar.sources.gaia import (
    GAIA_DR3,
    BestNeighbours,
    GaiaReader,
    SourceTable,
    in_ranges,
)
from space_map_data.extrasolar.sources.hipparcos import HIPPARCOS
from space_map_data.extrasolar.sources.names import IAU_WGSN
from space_map_data.extrasolar.sources.wikidata import WIKIDATA
from space_map_data.extrasolar.tables import METADATA, POINT_SOURCE
from space_map_data.utils.paths import REGISTRY_BACKUP_DIR, REGISTRY_ROOT

logger = logging.getLogger(__name__)

# Threads that read the Gaia chunks while the engine stages them.
READ_WORKERS = 8
MAGNITUDE_BINS = (2, 4, 6, 8, 10)


def _keep(table: pa.Table, ranges: list[tuple[int, int]] | None) -> pa.Table:
    if ranges is None:
        return table
    ra = table["match_ra"].to_numpy(zero_copy_only=False)
    dec = table["match_dec"].to_numpy(zero_copy_only=False)
    return table.filter(pa.array(in_ranges(ra, dec, ranges)))


def ingest(
    root: Path = REGISTRY_ROOT,
    backup_root: Path = REGISTRY_BACKUP_DIR,
    limit: int | None = None,
    workers: int = READ_WORKERS,
) -> tuple[IngestResult, str]:
    """Run the star ingest; returns its result and a summary of the stars."""
    if limit is not None:
        if root.resolve() == REGISTRY_ROOT.resolve():
            raise RegistryError(
                f"a partial ingest never goes to the default registry {root}:"
                " use another root"
            )
        if any(e["complete"] for e in Registry(root).ingests):
            raise RegistryError(
                f"{root} holds a complete ingest, and a partial one would rebuild"
                " its tables from part of the input: use another root"
            )
    best = BestNeighbours.read()
    reader = GaiaReader(best, workers=workers)
    chunks = reader.chunks(limit)
    ranges = None if limit is None else [pixel_range(path.name) for path in chunks]
    reader = replace(
        reader,
        joined=(
            SourceTable.of(apogee.read_stars(), apogee.COLUMNS),
            SourceTable.of(lamost.read_stars(), lamost.COLUMNS),
        ),
    )
    stars = hipparcos.engine_rows(hipparcos.read_stars(), best)
    positions = dict(
        zip(
            stars["catalogue_id"].to_pylist(),
            zip(stars["match_ra"].to_pylist(), stars["match_dec"].to_pylist()),
        )
    )
    name_rows = names.engine_rows(positions)
    item_rows = wikidata.engine_rows(
        wikidata_stars.read_items(), positions, wikidata.hd_positions(stars)
    )
    stars, name_rows = _keep(stars, ranges), _keep(name_rows, ranges)
    item_rows = _keep(item_rows, ranges)
    # A partial ingest expects only the names in its pixels.
    name_ids = (
        names.read_names() if ranges is None else name_rows["catalogue_id"].to_pylist()
    )
    if ranges is not None:
        logger.info(
            "partial ingest: %d Gaia chunks, %d Hipparcos stars, %d names,"
            " %d Wikidata items",
            len(chunks),
            stars.num_rows,
            name_rows.num_rows,
            item_rows.num_rows,
        )
    complete = limit is None
    with IngestRun.start(root, backup_root) as run:
        run.add(GAIA_DR3, reader.batches(chunks), complete)
        run.add(HIPPARCOS, [stars], complete)
        run.add(IAU_WGSN, [name_rows], complete)
        run.add(WIKIDATA, [item_rows], complete)
        result = run.commit()
    return result, summary(Registry(root), name_ids, item_rows.num_rows)


def _scan[T](paths: list[Path], work: Callable[[Path], T]) -> list[T]:
    with ThreadPoolExecutor(8) as pool:
        return list(pool.map(work, paths))


def _table_paths(registry: Registry, slug: str) -> list[Path]:
    directory = registry.table_dir(slug)
    return [] if directory is None else sorted(directory.glob("*.parquet"))


def _digits(ids: np.ndarray) -> np.ndarray:
    """The number of decimal digits of each positive ID."""
    return np.searchsorted(10 ** np.arange(1, 17, dtype=np.int64), ids, "right") + 1


def _point_part(path: Path) -> tuple[int, np.ndarray]:
    """The rows of a point-source file, and the Hp of its Hipparcos-only stars."""
    rows = pq.read_table(path, columns=["astrometry_source", "hp_mag"])
    alone = rows.filter(pc.equal(rows["astrometry_source"], HIPPARCOS.name))
    return rows.num_rows, alone["hp_mag"].to_numpy(zero_copy_only=False)


def _metadata_part(path: Path) -> tuple[int, np.ndarray]:
    """The rows of a metadata file, and its live IDs counted by length."""
    rows = pq.read_table(path, columns=["id", "alias_target"])
    live = rows.filter(pc.is_null(rows["alias_target"]))["id"].to_numpy()
    return rows.num_rows, np.bincount(_digits(live), minlength=18)


def _catalogue_part(catalogue: str) -> Callable[[Path], list[str]]:
    def read(path: Path) -> list[str]:
        rows = pq.read_table(
            path, columns=["catalogue_id"], filters=[("catalogue", "=", catalogue)]
        )
        return rows["catalogue_id"].to_pylist()

    return read


def summary(registry: Registry, name_ids: list[str], items: int) -> str:
    """Rows per table, ID lengths, Hipparcos-only stars, names and items placed."""
    point = _scan(_table_paths(registry, POINT_SOURCE.slug), _point_part)
    metadata = _scan(_table_paths(registry, METADATA.slug), _metadata_part)
    # numpy types `np.sum` of a list as a scalar.
    lengths = np.asarray(
        np.sum([counts for _, counts in metadata], axis=0, dtype=np.int64)
    )
    live = int(lengths.sum())
    lines = [
        "Extrasolar stars",
        f"point-source rows: {sum(n for n, _ in point):,}",
        f"metadata rows: {sum(n for n, _ in metadata):,} ({live:,} live)",
        "",
        "ID length (digits) of live IDs:",
    ]
    for length in np.flatnonzero(lengths).tolist():
        count = int(lengths[length])
        lines.append(f"  {length:>2}: {count:>12,} ({count / live:.1%})")

    hp = np.concatenate([np.zeros(0)] + [found for _, found in point])
    lines += ["", f"Hipparcos stars without a Gaia DR3 row: {hp.size:,}"]
    edges = (-np.inf, *MAGNITUDE_BINS, np.inf)
    for low, high in pairwise(edges):
        count = int(((hp >= low) & (hp < high)).sum())
        if low == -np.inf:
            label = f"Hp < {high:g}"
        elif high == np.inf:
            label = f"Hp ≥ {low:g}"
        else:
            label = f"Hp {low:g}–{high:g}"
        lines.append(f"  {label}: {count:,}")
    lines.append(f"  no Hp: {int(np.isnan(hp).sum()):,}")

    files = [
        path
        for region in registry.part_regions("xids")
        for path in registry.part_files("xids", region)
    ]
    found = {
        name
        for names_of in _scan(files, _catalogue_part(IAU_WGSN.catalogue))
        for name in names_of
    }
    unplaced = sorted(set(name_ids) - found)
    lines += ["", f"IAU names: {len(found):,} placed, {len(unplaced):,} unplaced"]
    lines += [f"  {name}" for name in unplaced]
    # Only the links of the last ingest hold for a source that is not permanent.
    latest = registry.segment_dir(registry.last_ingest) / "xids"
    latest = sorted(latest.glob("*.parquet"))
    placed = sum(
        len(qids) for qids in _scan(latest, _catalogue_part(WIKIDATA.catalogue))
    )
    lines += ["", f"Wikidata items: {placed:,} placed of {items:,} with a claim"]
    return "\n".join(lines) + "\n"
