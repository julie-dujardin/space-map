"""`space-map-export --only extrasolar`: the registry's tables as served files.

The export builds into `v1/.x-staging/` beside the served `v1/x/` and swaps it
into place only when every check passes. A failed run leaves the previous
export as it was. The checks:

- no ingest has merges that no one has reviewed;
- every row holds an ID that the registry has, with the status the row shows;
- every ID that the previous export serves is still served with all its
  catalogue ids, or is an alias or retired in the registry. The ids of a
  source that is not permanent, such as Wikidata, may change. The previous
  export stands for the live site until the serving is decided;
- the matched sky cultures come from the registry ingest that the export
  reads;
- every planet host and system is live with its rows, and every planet that
  the previous export serves is still served, or its number is retired or an
  alias, or its host is no longer live.

The export holds a shared lock on the registry for the whole run, so no
ingest starts and no table version changes under it. Every job gets the
registry object that the export read under the lock, so all jobs read the
table versions that metadata.json names.

Render scratch goes in `.build/` beside `v1/`. The planets read the render
rows of their hosts from it, and then it is removed.
"""

import fcntl
import json
import logging
import multiprocessing
import shutil
import time
from collections import Counter
from collections.abc import Callable, Generator, Iterable
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from space_map_data.constants.stars.families import FAMILIES, STAR_FAMILY_PAGES
from space_map_data.download.providers.stars import msc, wds
from space_map_data.download.providers.stars.iau_names import PAGE_URL as IAU_URL
from space_map_data.export.extrasolar import (
    container,
    planets,
    render,
    skycultures,
    tiles,
)
from space_map_data.export.extrasolar.container import Written
from space_map_data.export.extrasolar.tiles import (
    MAX_ROWS,
    Previous,
    Problems,
    Split,
    UnitJob,
)
from space_map_data.extrasolar.registry import Registry, RegistryError
from space_map_data.extrasolar.sky import REGION_COUNT, REGION_SHIFT
from space_map_data.extrasolar.store import fsync_dir
from space_map_data.extrasolar.tables import METADATA, TABLES
from space_map_data.utils.paths import EXTRASOLAR_DIR, REGISTRY_ROOT

logger = logging.getLogger(__name__)

METADATA_FILE = "metadata.json"
# Gaia DR3 is CC BY-NC 3.0 IGO, and every table and tree holds Gaia values.
DISTRIBUTION = "non-commercial"
FRAME = "ICRS equatorial axes, origin at the solar system barycentre, epoch J2016.0"
LITERATURE_URL = (
    "https://github.com/julie-dujardin/space-map/blob/main/data/src/space_map_data"
    "/constants/stars/literature.py"
)
CREDITS = (
    {
        "name": "Gaia Data Release 3",
        "organisation": "ESA/Gaia/DPAC",
        "source": "https://www.cosmos.esa.int/web/gaia/dr3",
        "license": "CC BY-NC 3.0 IGO",
        "attribution": (
            "This work has made use of data from the European Space Agency (ESA)"
            " mission Gaia (https://www.cosmos.esa.int/gaia), processed by the"
            " Gaia Data Processing and Analysis Consortium (DPAC,"
            " https://www.cosmos.esa.int/web/gaia/dpac/consortium)."
        ),
        "citation": "Gaia Collaboration, Vallenari et al. 2023, A&A 674, A1",
    },
    {
        "name": "Astrometric fidelity of Gaia EDR3",
        "organisation": "Rybizki et al. 2022",
        "source": "https://doi.org/10.1093/mnras/stab3588",
        "license": "CC BY-NC 3.0 IGO",
        "citation": "Rybizki et al. 2022, MNRAS 510, 2597",
    },
    {
        "name": "Gaia DR3 binary orbits and masses",
        "organisation": "Gaia Collaboration, Arenou et al. 2023",
        "source": "https://ui.adsabs.harvard.edu/abs/2023A&A...674A..34G",
        "license": "CC BY-NC 3.0 IGO",
        "citation": "Gaia Collaboration, Arenou et al. 2023, A&A 674, A34",
    },
    {
        "name": "Metallicities from Gaia XP spectra",
        "organisation": "Andrae, Rix & Chandra 2023",
        "source": "https://doi.org/10.5281/zenodo.7945154",
        "license": "CC BY 4.0",
        "citation": "Andrae, Rix & Chandra 2023, ApJS 267, 8",
    },
    {
        "name": "The PASTEL catalogue, 2020 version (B/pastel)",
        "organisation": "Soubiran et al. 2016",
        "source": "https://cdsarc.cds.unistra.fr/viz-bin/cat/B/pastel",
        "citation": "Soubiran et al. 2016, A&A 591, A118",
    },
    # SIMBAD places the PASTEL designations, joins the planet catalogues and
    # gives the named stars.
    skycultures.SIMBAD,
    {
        "name": "APOGEE DR17",
        "organisation": "SDSS-IV",
        "source": "https://www.sdss4.org/dr17/irspec/",
        "attribution": (
            "Funding for the Sloan Digital Sky Survey IV has been provided by the"
            " Alfred P. Sloan Foundation, the U.S. Department of Energy Office of"
            " Science, and the Participating Institutions."
        ),
        "citation": "Abdurro'uf et al. 2022, ApJS 259, 35",
    },
    {
        "name": "M dwarfs of LAMOST DR10 via Cycle-StarNet",
        "organisation": "Zhang et al. 2025",
        "source": "https://doi.org/10.5281/zenodo.14030249",
        "license": "CC BY 4.0",
        "citation": "Zhang, Zhang, Ting et al. 2025, ApJS 277, 47",
    },
    # The Gaia DR3 id of each LAMOST spectrum.
    {
        "name": "LAMOST DR10 v2.0 LRS catalogue of M stars",
        "organisation": "National Astronomical Observatories, Chinese Academy of Sciences",
        "source": "https://www.lamost.org/dr10/v2.0/",
        "attribution": (
            "Guoshoujing Telescope (the Large Sky Area Multi-Object Fiber"
            " Spectroscopic Telescope LAMOST) is a National Major Scientific Project"
            " built by the Chinese Academy of Sciences. Funding for the project has"
            " been provided by the National Development and Reform Commission."
            " LAMOST is operated and managed by the National Astronomical"
            " Observatories, Chinese Academy of Sciences."
        ),
    },
    {
        "name": "Hipparcos, the new reduction (I/311)",
        "organisation": "ESA",
        "source": "https://cdsarc.cds.unistra.fr/viz-bin/cat/I/311",
        "citation": "van Leeuwen 2007, A&A 474, 653",
    },
    {
        "name": "The Hipparcos and Tycho Catalogues (I/239)",
        "organisation": "ESA",
        "source": "https://cdsarc.cds.unistra.fr/viz-bin/cat/I/239",
        "citation": "ESA 1997, ESA SP-1200",
    },
    {
        "name": "Extended Hipparcos Compilation, XHIP (V/137D)",
        "organisation": "Anderson & Francis 2012",
        "source": "https://cdsarc.cds.unistra.fr/viz-bin/cat/V/137D",
        "citation": "Anderson & Francis 2012, Astronomy Letters 38, 331",
    },
    {
        "name": "The 10 parsec sample in the Gaia era (J/A+A/650/A201)",
        "organisation": "Reylé et al. 2021",
        "source": "https://cdsarc.cds.unistra.fr/viz-bin/cat/J/A+A/650/A201",
        "license": "CC BY 4.0",
        "citation": "Reylé et al. 2021, A&A 650, A201",
    },
    {
        "name": "The UltracoolSheet 2.1.0",
        "organisation": "Best et al. 2025",
        "source": "https://doi.org/10.5281/zenodo.4169085",
        "license": "CC BY 4.0",
        "citation": "Best et al. 2025, The UltracoolSheet, Zenodo",
    },
    {
        "name": "Cleaned open cluster catalogue (J/A+A/686/A42)",
        "organisation": "Hunt & Reffert 2024",
        "source": "https://cdsarc.cds.unistra.fr/viz-bin/cat/J/A+A/686/A42",
        "license": "CC BY-NC 3.0 IGO",
        "citation": "Hunt & Reffert 2024, A&A 686, A42",
    },
    {
        "name": "Distance to the Large Magellanic Cloud",
        "organisation": "Pietrzyński et al. 2019",
        "source": "https://doi.org/10.1038/s41586-019-0999-4",
        "citation": "Pietrzyński et al. 2019, Nature 567, 200",
    },
    {
        "name": "Distance to the Small Magellanic Cloud",
        "organisation": "Graczyk et al. 2020",
        "source": "https://doi.org/10.3847/1538-4357/abbb2b",
        "citation": "Graczyk et al. 2020, ApJ 904, 13",
    },
    {
        "name": "Geometric distances to Gaia EDR3 stars",
        "organisation": "Bailer-Jones et al. 2021",
        "source": "https://doi.org/10.3847/1538-3881/abd806",
        "license": "CC BY-NC 3.0 IGO",
        "citation": "Bailer-Jones et al. 2021, AJ 161, 147",
    },
    # The star systems: their pairs, hierarchy and component letters.
    {
        "name": "The Washington Double Star Catalog",
        "organisation": "U.S. Naval Observatory",
        "source": wds.HOME_URL,
        "attribution": wds.ACKNOWLEDGEMENT,
        "citation": "Mason et al. 2001, AJ 122, 3466",
    },
    {
        "name": "The Multiple Star Catalogue (MSC)",
        "organisation": "Tokovinin 2018",
        "source": msc.PAGE_URL,
        "citation": "Tokovinin 2018, ApJS 235, 6",
    },
    # One credit for every paper of the literature table. Each star's page
    # cites the paper of its value.
    {
        "name": "Published papers",
        "organisation": "Cited on each star's page",
        "source": LITERATURE_URL,
    },
    {
        "name": "IAU Catalog of Star Names",
        "organisation": "IAU Working Group on Star Names",
        "source": IAU_URL,
    },
    {
        "name": "Wikidata",
        "organisation": "Wikidata contributors",
        "source": "https://www.wikidata.org/",
        "license": "CC0 1.0",
    },
)


class ExportRefused(Exception):
    pass


@dataclass(frozen=True)
class Layout:
    root: Path

    @property
    def live(self) -> Path:
        return self.root / "v1" / "x"

    @property
    def staging(self) -> Path:
        return self.root / "v1" / ".x-staging"

    @property
    def old(self) -> Path:
        return self.root / "v1" / ".x-old"

    @property
    def scratch(self) -> Path:
        return self.root / ".build"

    @property
    def lock(self) -> Path:
        return self.root / ".lock"


@contextmanager
def _read_registry(root: Path) -> Generator[Registry]:
    """The registry under its reader lock. An error of `reader` refuses the export."""
    with ExitStack() as stack:
        try:
            registry = stack.enter_context(Registry(root).reader())
        except RegistryError as error:
            raise ExportRefused(str(error)) from None
        yield registry


@contextmanager
def _locked(layout: Layout) -> Generator[None]:
    layout.root.mkdir(parents=True, exist_ok=True)
    with layout.lock.open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ExportRefused(f"another export writes to {layout.root}") from None
        yield


@contextmanager
def served(root: Path) -> Generator[None]:
    """Read access to the served export below `root`: an export that starts
    meanwhile refuses, and one that runs is waited for, so none swaps the
    files under the reader."""
    lock = Layout(root).lock
    if not root.exists():
        yield
        return
    with lock.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_SH)
        yield


def _recover(layout: Layout) -> None:
    """Undo what a stopped export left."""
    if layout.old.exists():
        if layout.live.exists():
            logger.warning("removing the replaced export %s", layout.old)
            shutil.rmtree(layout.old)
        else:
            logger.warning("restoring %s, which a stopped swap left", layout.old)
            layout.old.rename(layout.live)
    for path in (layout.staging, layout.scratch):
        if path.exists():
            logger.warning("removing what a failed export left: %s", path)
            shutil.rmtree(path)


@contextmanager
def _pool(workers: int) -> Generator[ProcessPoolExecutor | None]:
    if workers <= 1:
        yield None
        return
    # spawn: the parent holds Arrow threads.
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(workers, mp_context=context) as pool:
        yield pool


def _run[J, R](
    workers: int, task: Callable[[J], R], jobs: list[J], label: str
) -> list[R]:
    """`task` over `jobs` in worker processes, results in job order."""
    started = time.monotonic()
    results = []
    with _pool(workers) as pool:
        mapped: Iterable[R] = (
            map(task, jobs) if pool is None else pool.map(task, jobs, chunksize=1)
        )
        step = max(1, len(jobs) // 10)
        for done, result in enumerate(mapped, 1):
            results.append(result)
            if done % step == 0 or done == len(jobs):
                logger.info(
                    "%s: %d of %d, %.0f s",
                    label,
                    done,
                    len(jobs),
                    time.monotonic() - started,
                )
    return results


def _previous(layout: Layout) -> tuple[dict | None, Split | None]:
    """The metadata.json and the Metadata split table of the served export."""
    path = layout.live / METADATA_FILE
    if not path.exists():
        return None, None
    metadata = json.loads(path.read_text())
    if metadata["format"] != container.VERSION:
        raise ExportRefused(
            f"the served export has format {metadata['format']}; this code reads"
            f" {container.VERSION}"
        )
    path = layout.live / metadata["tables"][METADATA.slug]["split"]
    split = Split.from_bits(container.read(path).numpy("split"), str(path))
    return metadata, split


def _previous_paths(split: Split, regions: tuple[int, ...]) -> tuple[str, ...]:
    low = regions[0] << REGION_SHIFT
    high = (regions[-1] + 1) << REGION_SHIFT
    first, last = split.leaf_of(np.array([low, high - 1]))
    return tuple(
        tiles.tile_path(METADATA.slug, int(split.level[k]), int(split.pixel[k]))
        for k in range(int(first), int(last) + 1)
    )


def _count_job(job: tuple[Registry, str, int]) -> np.ndarray:
    return tiles.region_counts(*job)


@dataclass
class TableResult:
    slug: str
    split: Split
    files: list[Written]
    rows: int
    # Metadata only: the stars of each family, published then estimated.
    family_counts: np.ndarray | None = None


def _build_tables(
    registry: Registry,
    layout: Layout,
    workers: int,
    previous: Split | None,
    problems: Problems,
) -> list[TableResult]:
    results = []
    for table in (METADATA, *TABLES):
        slug = table.slug
        jobs = [(registry, slug, region) for region in range(REGION_COUNT)]
        counts = _run(workers, _count_job, jobs, f"{slug}: cell counts")
        split = Split.build(np.concatenate(counts), MAX_ROWS[slug])
        logger.info(
            "%s: %d tiles from %d split bits", slug, split.level.size, split.bits.size
        )
        split_file = container.write(
            layout.staging, f"{slug}/{tiles.SPLIT_FILE}", split.payload()
        )
        unit_jobs = [
            UnitJob(
                registry,
                slug,
                unit,
                layout.staging,
                None
                if previous is None or slug != METADATA.slug
                else Previous(layout.live, _previous_paths(previous, unit.regions)),
            )
            for unit in tiles.units(split)
        ]
        built = _run(workers, tiles.build_unit, unit_jobs, f"{slug}: tiles")
        files = [split_file]
        rows = dropped = 0
        family_counts = None
        for result in built:
            files += result.files
            rows += result.rows
            dropped += result.dropped_aliases
            problems.update(result.problems)
            if result.family_counts is not None:
                family_counts = (
                    result.family_counts
                    if family_counts is None
                    else family_counts + result.family_counts
                )
        if dropped:
            logger.warning("%s: %d aliases without a live end left out", slug, dropped)
        results.append(TableResult(slug, split, files, rows, family_counts))
    return results


@dataclass
class TreeResult:
    nodes: list[render.Node]
    files: list[Written]
    counts: Counter


def _build_tree(registry: Registry, layout: Layout, workers: int) -> TreeResult:
    """The render tree. Its render rows stay in the scratch for the planets."""
    scratch = layout.scratch
    jobs = [render.RowsJob(registry, r, scratch) for r in range(REGION_COUNT)]
    counts: Counter = Counter()
    for _, region_counts in _run(workers, render.region_rows, jobs, "render rows"):
        counts.update(region_counts)
    for reason, count in counts.items():
        logger.info("render rows: %s %d", reason, count)

    started = time.monotonic()
    sizes = [
        np.load(render.scratch_file(scratch, r, "key"), mmap_mode="r").size
        for r in range(REGION_COUNT)
    ]
    keys = np.empty(sum(sizes), np.uint64)
    ranges = np.empty(sum(sizes), np.float32)
    at = 0
    for region, size in enumerate(sizes):
        keys[at : at + size] = np.load(render.scratch_file(scratch, region, "key"))
        ranges[at : at + size] = np.load(render.scratch_file(scratch, region, "range"))
        at += size
    node_of, nodes = render.assign(keys, ranges)
    del keys, ranges
    at = 0
    for region, size in enumerate(sizes):
        np.save(render.scratch_file(scratch, region, "node"), node_of[at : at + size])
        at += size
    del node_of
    logger.info(
        "render tree: %d nodes, depth %d, %.0f s",
        len(nodes),
        max(node.depth for node in nodes) if nodes else 0,
        time.monotonic() - started,
    )

    groups = render.batches(nodes) if nodes else []
    edges = tuple([group.start for group in groups] + [len(nodes)])
    split_jobs = [render.SplitJob(scratch, r, edges) for r in range(REGION_COUNT)]
    _run(workers, render.split_region, split_jobs, "render batches")
    batch_jobs = [
        render.BatchJob(
            scratch, b, layout.staging, group.start, tuple(nodes[i] for i in group)
        )
        for b, group in enumerate(groups)
    ]
    files = [
        item
        for written in _run(workers, render.build_batch, batch_jobs, "render nodes")
        for item in written
    ]
    return TreeResult(nodes, files, counts)


def _patch_job(job: tuple[Path, str, list[str]]) -> int:
    root, token, paths = job
    for path in paths:
        container.patch_token(root / path, token)
    return len(paths)


def _patch(root: Path, groups: dict[str, list[Written]], workers: int) -> dict:
    tokens = {name: container.token_of(files) for name, files in groups.items()}
    jobs = []
    for name, files in groups.items():
        paths = [item.path for item in files]
        for at in range(0, len(paths), 5000):
            jobs.append((root, tokens[name], paths[at : at + 5000]))
    _run(workers, _patch_job, jobs, "tokens")
    return tokens


def _sizes(files: list[Written]) -> dict:
    sizes = np.array([item.size for item in files], np.int64)
    rows = np.array([item.rows for item in files], np.int64)
    return {
        "files": int(sizes.size),
        "bytes": int(sizes.sum()),
        "median_bytes": int(np.median(sizes)) if sizes.size else 0,
        "p90_bytes": int(np.percentile(sizes, 90)) if sizes.size else 0,
        "max_bytes": int(sizes.max()) if sizes.size else 0,
        "median_rows": int(np.median(rows)) if rows.size else 0,
    }


def _metadata(
    registry: Registry,
    tables_built: list[TableResult],
    tree: TreeResult,
    tokens: dict[str, str],
    cultures: skycultures.Result | None,
    planet_files: planets.Result | None,
) -> dict:
    tables_out = {}
    for result in tables_built:
        table = tiles.table_def(result.slug)
        tables_out[result.slug] = {
            "number": table.number,
            "token": tokens[result.slug],
            "split": f"{result.slug}/{tiles.SPLIT_FILE}",
            "tile": f"{result.slug}/{{level}}/{{pixel}}.bin.gz",
            "max_rows": MAX_ROWS[result.slug],
            "rows": result.rows,
            "tiles": int(result.split.level.size),
            "columns": [
                {"name": name, "type": kind} for name, kind in tiles.column_types(table)
            ],
            "distribution": DISTRIBUTION,
        }
    family_counts = next(
        r.family_counts for r in tables_built if r.family_counts is not None
    )
    nodes = tree.nodes
    metadata = {
        "format": container.VERSION,
        "exported": datetime.now(UTC).isoformat(timespec="seconds"),
        "registry": {"ingest": registry.last_ingest, "host": registry.manifest["host"]},
        "tables": tables_out,
        "trees": {
            render.TREE: {
                "token": tokens[render.TREE],
                "root": render.node_path("r"),
                "node": render.node_path("{name}"),
                "ids": render.ids_path("{name}"),
                "centre": list(render.ROOT_CENTRE),
                "half_size": render.HALF_SIZE,
                "node_rows": render.NODE_ROWS,
                "range_limit_mag": render.RANGE_LIMIT_MAG,
                "units": "pc",
                "frame": FRAME,
                "classes": dict(render.CLASSES),
                "nodes": len(nodes),
                "depth": max((node.depth for node in nodes), default=0),
                "rows": sum(node.rows for node in nodes),
                "columns": [
                    {"name": name, "type": kind} for name, kind in render.NODE_COLUMNS
                ],
                "id_columns": [
                    {"name": name, "type": kind} for name, kind in render.ID_COLUMNS
                ],
                "distribution": DISTRIBUTION,
            }
        },
        "families": [
            {
                "slug": slug,
                "wikidata": list(STAR_FAMILY_PAGES[slug]),
                "published": int(family_counts[0, bit]),
                "estimated": int(family_counts[1, bit]),
            }
            for bit, slug in enumerate(FAMILIES)
        ],
        "credits": list(CREDITS),
    }
    if cultures is not None:
        metadata[skycultures.TABLE] = {**cultures.entry, "frame": FRAME}
    if planet_files is not None:
        entry = dict(planet_files.entry)
        # The planet catalogues also fill the host rows of Point source.
        metadata["credits"] += entry.pop("credits")
        metadata[planets.SECTION] = {
            **entry,
            "frame": FRAME,
            "distribution": DISTRIBUTION,
        }
    return metadata


def _swap(layout: Layout) -> None:
    replaced = layout.live.exists()
    if replaced:
        layout.live.rename(layout.old)
    try:
        layout.staging.rename(layout.live)
    except BaseException:
        if replaced:
            layout.old.rename(layout.live)
        raise
    fsync_dir(layout.live.parent)
    if replaced:
        shutil.rmtree(layout.old)


@dataclass
class Built:
    tables: list[TableResult]
    tree: TreeResult
    cultures: skycultures.Result | None
    planet_files: planets.Result | None
    tokens: dict[str, str]


def _refuse(problems: Problems) -> None:
    if problems:
        for line in problems.lines():
            logger.error("check failed: %s", line)
        raise ExportRefused(
            "the checks failed, the served export is unchanged:\n"
            + "\n".join(problems.lines())
        )


def _export(
    registry: Registry, layout: Layout, workers: int, cultures_dir: Path | None
) -> Built:
    """Build into staging, check, and swap. Removes staging on a failure."""
    _recover(layout)
    stale = skycultures.check(registry, cultures_dir or skycultures.CULTURES_DIR)
    if stale is not None:
        raise ExportRefused(stale)
    previous_metadata, previous = _previous(layout)
    if previous_metadata is None:
        logger.info("no export at %s: nothing to compare with", layout.live)
    try:
        problems = Problems()
        built = _build_tables(registry, layout, workers, previous, problems)
        _refuse(problems)
        tree = _build_tree(registry, layout, workers)
        planet_files = planets.build(
            registry,
            layout.staging,
            layout.scratch,
            lambda task, jobs, label: _run(workers, task, jobs, label),
            layout.live,
        )
        shutil.rmtree(layout.scratch)
        if planet_files is not None:
            _refuse(planet_files.problems)
            for reason, count in sorted(planet_files.counts.items()):
                logger.info("planets: %s %d", reason, count)
        cultures = skycultures.build(registry, layout.staging, cultures_dir)
        groups = {result.slug: result.files for result in built}
        groups[render.TREE] = tree.files
        tokens = _patch(layout.staging, groups, workers)
        if cultures is not None:
            tokens[skycultures.TABLE] = cultures.entry["token"]
        if planet_files is not None:
            tokens[planets.SECTION] = planet_files.entry["token"]
        metadata = _metadata(registry, built, tree, tokens, cultures, planet_files)
        (layout.staging / METADATA_FILE).write_text(
            json.dumps(metadata, indent=1) + "\n"
        )
        _swap(layout)
    except BaseException:
        for path in (layout.staging, layout.scratch):
            if path.exists():
                shutil.rmtree(path)
        raise
    return Built(built, tree, cultures, planet_files, tokens)


def export_extrasolar(
    registry_root: Path = REGISTRY_ROOT,
    out_root: Path = EXTRASOLAR_DIR,
    workers: int = 8,
    cultures_dir: Path | None = None,
) -> dict:
    """Export the registry's tables to `out_root/v1/x/`. Returns the report.

    `cultures_dir` holds the matched sky cultures; None reads the default.
    """
    started = time.monotonic()
    with _read_registry(registry_root) as registry:
        unreviewed = registry.unreviewed()
        if unreviewed:
            raise ExportRefused(
                f"ingests {unreviewed} have merges that no one has reviewed; check"
                " them, then run space-map-extrasolar review <ingest>"
            )
        layout = Layout(out_root)
        with _locked(layout):
            result = _export(registry, layout, workers, cultures_dir)
    built, tree, cultures = result.tables, result.tree, result.cultures
    tile_files = {
        r.slug: [f for f in r.files if not f.path.endswith(tiles.SPLIT_FILE)]
        for r in built
    }
    report = {
        "seconds": round(time.monotonic() - started),
        "tokens": result.tokens,
        "tables": {slug: _sizes(files) for slug, files in tile_files.items()},
        "split_bytes": {
            r.slug: next(f.size for f in r.files if f.path.endswith(tiles.SPLIT_FILE))
            for r in built
        },
        "nodes": _sizes([f for f in tree.files if "/node/" in f.path]),
        "ids": _sizes([f for f in tree.files if "/id/" in f.path]),
        "render": dict(tree.counts),
        "families": {
            slug: [int(n) for n in counts]
            for r in built
            if r.family_counts is not None
            for slug, counts in zip(FAMILIES, r.family_counts.T)
        },
        "depths": dict(sorted(Counter(node.depth for node in tree.nodes).items())),
    }
    culture_files = [] if cultures is None else cultures.files
    report["skycultures"] = _sizes(culture_files)
    report["skycultures_left_out"] = [] if cultures is None else cultures.left_out
    planet_files = [] if result.planet_files is None else result.planet_files.files
    report["planet_systems"] = _sizes(
        [f for f in planet_files if f.path != planets.INDEX_FILE]
    )
    report["planet_index_bytes"] = sum(
        f.size for f in planet_files if f.path == planets.INDEX_FILE
    )
    report["planets"] = (
        {} if result.planet_files is None else dict(result.planet_files.counts)
    )
    report["files"] = (
        sum(len(r.files) for r in built)
        + len(tree.files)
        + len(culture_files)
        + len(planet_files)
        + 1
    )
    report["bytes"] = (
        sum(f.size for r in built for f in r.files)
        + sum(f.size for f in tree.files)
        + sum(f.size for f in culture_files)
        + sum(f.size for f in planet_files)
    )
    return report


def export_extrasolar_only(
    workers: int,
    registry_root: Path = REGISTRY_ROOT,
    out_root: Path = EXTRASOLAR_DIR,
) -> None:
    """The CLI run. A registry other than the default one writes its matched
    sky cultures to `<root>/skycultures`, as the ingest does, and may not
    write to the served export."""
    default_root = registry_root.resolve() == REGISTRY_ROOT.resolve()
    if not default_root and out_root.resolve() == EXTRASOLAR_DIR.resolve():
        raise ExportRefused(
            f"{registry_root} is not the default registry: name an output root"
            f" other than {EXTRASOLAR_DIR}"
        )
    cultures_dir = None if default_root else registry_root / "skycultures"
    report = export_extrasolar(registry_root, out_root, workers, cultures_dir)
    logger.info("extrasolar export:\n%s", json.dumps(report, indent=1))
