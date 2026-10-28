"""The star ingest: Gaia DR3, Hipparcos, SIMBAD, the IAU star names, the
exoplanet catalogues with their planets, the distance catalogues, the
literature table, the star systems, then Wikidata.

Gaia goes first, so a star that Gaia measured has its home and its cell from
Gaia. Gaia DR3 is two passes: the positionable stars of the chunks, then the
rows that the chunks leave out for want of a 5σ parallax, of the SIMBAD stars
and the planet hosts. Both get the same joins, and the rows carry the binary
orbits of table 2. A Hipparcos star takes its Gaia best neighbour, unless
SIMBAD gives that source to another star. A system's Hipparcos star with no
best neighbour takes the Gaia source of the primary that SIMBAD hands its
number to. Hipparcos is two passes: the new reduction, then the entries of
1997 that it drops. SIMBAD is two passes: its stars, then the HIP
numbers of its stars with a Gaia DR3 id. A HIP number whose Gaia best
neighbour SIMBAD gives to another star has no best neighbour. The distance
passes never mint, so they come after every pass that matches by position.
The star systems come after them: they read the stars that the passes made,
and a star that no pass places takes its system's distance. Wikidata goes
last: it is not permanent, so its claims settle on the joins of all the
other passes.

The metallicity catalogues (PASTEL, APOGEE DR17, the LAMOST DR10 M dwarfs) are
no pass: their rows join the Gaia rows by source_id, and PASTEL also the
Hipparcos rows by HIP number. `limit` reads only the first Gaia chunks that
hold that many stars, and the Hipparcos stars and names in the same pixels.
Such an ingest is partial: it retires nothing, but it still rebuilds the
tables from what it read. It never goes to REGISTRY_ROOT, because every later
ingest keeps the IDs that it mints.
"""

import logging
from collections import Counter
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
from space_map_data.extrasolar.exoplanets import ingest as exoplanets
from space_map_data.extrasolar.registry import Registry, RegistryError
from space_map_data.extrasolar.sources import (
    apogee,
    distances,
    gaia,
    hipparcos,
    lamost,
    literature,
    names,
    pastel,
    simbad,
    wikidata,
)
from space_map_data.extrasolar.sources.gaia import (
    GAIA_DR3,
    GAIA_DR3_NAMED,
    BestNeighbours,
    GaiaReader,
    SourceTable,
    in_ranges,
)
from space_map_data.extrasolar.sources.hipparcos import HIPPARCOS, HIPPARCOS_1997
from space_map_data.extrasolar.sources.names import IAU_WGSN
from space_map_data.extrasolar.sources.simbad import SIMBAD, SIMBAD_HIP
from space_map_data.extrasolar.sources.wikidata import WIKIDATA
from space_map_data.extrasolar.systems.ingest import (
    add_systems,
    check_inputs,
    read_inputs,
)
from space_map_data.extrasolar.tables import BINARY_ORBIT, METADATA, POINT_SOURCE
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


def _hip_best(best: BestNeighbours) -> dict[str, str]:
    return {str(hip): str(gaia) for hip, gaia in best.source_of().items()}


def ingest(
    root: Path = REGISTRY_ROOT,
    backup_root: Path = REGISTRY_BACKUP_DIR,
    limit: int | None = None,
    workers: int = READ_WORKERS,
    exoplanet_inputs: exoplanets.Inputs = exoplanets.DEFAULT_INPUTS,
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
    check_inputs()
    simbad_list = simbad.SimbadList.read()
    handed = simbad_list.handed()
    best = BestNeighbours.read()
    best = best.without(simbad.disputed_hip(simbad_list, handed, _hip_best(best)))
    best = best.with_pairs(
        simbad.handed_neighbours(simbad_list, handed, _hip_best(best))
    )
    reader = GaiaReader(best, workers=workers)
    chunks = reader.chunks(limit)
    ranges = None if limit is None else [pixel_range(path.name) for path in chunks]
    hip_stars = hipparcos.read_stars()
    # PASTEL needs astrometry. The 1997 entries that hip2 drops have none.
    astrometric = hip_stars.filter(pc.is_valid(hip_stars["ra_rad"]))
    pastel_stars = pastel.read_stars(chunks, astrometric, best, workers)
    by_gaia = pc.greater(pastel_stars["source_id"], 0)
    reader = replace(
        reader,
        joined=(
            SourceTable.of(pastel_stars.filter(by_gaia), pastel.COLUMNS),
            SourceTable.of(apogee.read_stars(), apogee.COLUMNS),
            SourceTable.of(lamost.read_stars(), lamost.COLUMNS),
        ),
    )
    stars, rough = hipparcos.engine_rows(
        hip_stars, best, pastel_stars.filter(pc.invert(by_gaia))
    )
    hip_names = {
        int(hip): name
        for rows in (stars, rough)
        for hip, name in zip(rows["catalogue_id"].to_pylist(), rows["name"].to_pylist())
    }
    positions = {
        hip: (ra, dec)
        for rows in (stars, rough)
        for hip, ra, dec in zip(
            rows["catalogue_id"].to_pylist(),
            rows["match_ra"].to_pylist(),
            rows["match_dec"].to_pylist(),
        )
    }
    hipparcos_hd = {str(hd) for hd in hip_stars["hd"].drop_null().to_pylist()}
    simbad_list.hold(
        {
            hip: mag
            for rows in (stars, rough)
            for hip, mag in zip(
                rows["catalogue_id"].to_pylist(), rows["match_mag"].to_pylist()
            )
            if mag is not None
        }
    )
    # `hold` takes rows away, which changes what the systems hand down.
    handed = simbad_list.handed()
    simbad_rows, simbad_hip_rows = simbad.engine_rows(
        simbad_list, handed, hipparcos_hd, _hip_best(best), positions
    )
    iau_rows = simbad.iau_rows(simbad_list, handed, simbad_rows)
    name_rows = names.engine_rows(positions, simbad=iau_rows)
    hd_positions = {**wikidata.hd_positions(stars), **wikidata.hd_positions(rough)}
    item_rows = wikidata.engine_rows(
        wikidata_stars.read_items(), positions, hd_positions
    )
    stars, rough = _keep(stars, ranges), _keep(rough, ranges)
    simbad_rows, name_rows = _keep(simbad_rows, ranges), _keep(name_rows, ranges)
    simbad_hip_rows = _keep(simbad_hip_rows, ranges)
    item_rows = _keep(item_rows, ranges)
    named = gaia.read_named()
    named_rows = _keep(reader.named_rows(named), ranges)
    # A partial ingest expects only the names in its pixels.
    name_ids = (
        names.read_names() if ranges is None else name_rows["catalogue_id"].to_pylist()
    )
    if ranges is not None:
        logger.info(
            "partial ingest: %d Gaia chunks, %d Hipparcos stars, %d names,"
            " %d Wikidata items",
            len(chunks),
            stars.num_rows + rough.num_rows,
            name_rows.num_rows,
            item_rows.num_rows,
        )
    complete = limit is None
    with IngestRun.start(root, backup_root) as run:
        read = exoplanets.read(reader, exoplanet_inputs)
        read.gaia_rows = _keep(read.gaia_rows, ranges)
        # The Gaia row of a host has its astrophysical parameters, so it wins.
        hosts = read.gaia_rows["catalogue_id"]
        named_rows = named_rows.filter(
            pc.invert(pc.is_in(named_rows["catalogue_id"], value_set=hosts))
        )
        stored = distances.StoredGaia(
            np.concatenate(
                [named["source_id"].to_numpy(), np.array(hosts.to_pylist(), np.int64)]
            )
        )
        distance_rows = [
            (source, _keep(rows, ranges))
            for source, rows in (
                (distances.REYLE_2021, distances.reyle_rows(stored)),
                (distances.ULTRACOOLSHEET, distances.ultracool_rows(stored)),
                (distances.HUNT_REFFERT_2024, distances.cluster_rows(stored)),
                (distances.MAGELLANIC_CLOUDS, distances.magellanic_rows(named)),
                (distances.BAILER_JONES_2021, distances.bailer_jones_rows(named)),
                (
                    literature.LITERATURE,
                    literature.engine_rows(positions, hd_positions),
                ),
                (
                    distances.SIMBAD_PARALLAX,
                    distances.simbad_parallax_rows(simbad_list, named),
                ),
            )
        ]
        run.add(GAIA_DR3, reader.batches(chunks), complete)
        run.add(GAIA_DR3_NAMED, [named_rows, read.gaia_rows], complete)
        run.add(HIPPARCOS, [stars], complete)
        run.add(HIPPARCOS_1997, [rough], complete)
        run.add(SIMBAD, [simbad_rows], complete)
        run.add(SIMBAD_HIP, [simbad_hip_rows], complete)
        run.add(IAU_WGSN, [name_rows], complete)
        # The hosts without ids look for twins among the stars of these passes.
        planets = exoplanets.prepare(
            read, run, hip_names, exoplanet_inputs, names.claimed(name_rows, iau_rows)
        )
        planets.host_rows = {
            name: _keep(rows, ranges) for name, rows in planets.host_rows.items()
        }
        exoplanets.add_passes(run, planets, complete)
        for source, rows in distance_rows:
            run.add(source, [rows], complete)
        # The systems read the rows of every pass that places a star.
        inputs, index = read_inputs(run, simbad_list, planets, read.hub, reader)
        found = add_systems(run, inputs, index, complete)
        del inputs, index
        run.extend(exoplanets.PlanetsExtension(planets, found))
        item_rows, moved = wikidata.to_systems(
            item_rows, simbad_list, found.plan.system_claims
        )
        found.items_moved(moved)
        # A source that is not permanent comes after the permanent sources.
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


def _point_part(path: Path) -> tuple[int, np.ndarray, Counter]:
    """The rows of a point-source file, the Hp of its Hipparcos-only stars,
    and its distances by source."""
    rows = pq.read_table(
        path,
        columns=[
            "astrometry_source",
            "gaia_photometry_source",
            "hp_mag",
            "distance_source",
        ],
    )
    hipparcos_names = pa.array([HIPPARCOS.name, HIPPARCOS_1997.name])
    alone = rows.filter(
        pc.and_(
            pc.is_in(rows["astrometry_source"], hipparcos_names),
            pc.is_null(rows["gaia_photometry_source"]),
        )
    )
    sources = Counter(rows["distance_source"].drop_null().to_pylist())
    return rows.num_rows, alone["hp_mag"].to_numpy(zero_copy_only=False), sources


def _rows(path: Path) -> int:
    return pq.ParquetFile(path).metadata.num_rows


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
    """Rows per table, ID lengths, distances by source, Hipparcos-only stars,
    names and items placed."""
    point = _scan(_table_paths(registry, POINT_SOURCE.slug), _point_part)
    metadata = _scan(_table_paths(registry, METADATA.slug), _metadata_part)
    orbits = _scan(_table_paths(registry, BINARY_ORBIT.slug), _rows)
    # numpy types `np.sum` of a list as a scalar.
    lengths = np.asarray(
        np.sum([counts for _, counts in metadata], axis=0, dtype=np.int64)
    )
    live = int(lengths.sum())
    lines = [
        "Extrasolar stars",
        f"point-source rows: {sum(n for n, _, _ in point):,}",
        f"binary-orbit rows: {sum(orbits):,}",
        f"metadata rows: {sum(n for n, _ in metadata):,} ({live:,} live)",
        "",
        "ID length (digits) of live IDs:",
    ]
    for length in np.flatnonzero(lengths).tolist():
        count = int(lengths[length])
        lines.append(f"  {length:>2}: {count:>12,} ({count / live:.1%})")

    distances_by_source = sum((found for _, _, found in point), Counter())
    lines += ["", "Distances by source:"]
    lines += [
        f"  {name}: {count:,}" for name, count in distances_by_source.most_common()
    ]
    hp = np.concatenate([np.zeros(0)] + [found for _, found, _ in point])
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
