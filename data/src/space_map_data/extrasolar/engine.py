"""One ingest run: catalogue rows in, committed IDs and tables out.

    with IngestRun.start() as run:
        run.add(GAIA_DR3, gaia_batches)
        run.add(HIPPARCOS, hipparcos_batches)
        result = run.commit()

Each `add` is a pass over one source. Passes go in source priority order: the
first source of an object gives it its home table and its cell. A pass stages
its rows by sky region, then resolves them region by region against the
registry and the earlier passes, the neighbouring regions included:

1. A catalogue id seen before keeps its object.
2. A claim, a catalogue's own cross-match to an id of another catalogue,
   links the row to the object that holds that id. A claim of an object that
   another row of the pass took, or that holds another id of the row's own
   catalogue, is a conflict. The ingest logs and counts it, and does not
   apply it.
3. A row with no link goes to the source's matcher, which searches the
   positions of the registry and of the earlier passes. The pairs of the
   whole pass are assigned together, so the result does not depend on the
   order of the regions. A row that claims an id nobody holds does not match
   an object that holds another id of that catalogue, unless the source of
   that catalogue is a subset. The claimed id then joins the matched object.
4. A row that is still free becomes a new object of the run. A row with
   `mint` false gets an ID only when a minting row joins its object.

A source that is not permanent, such as Wikidata, adds data to the objects
that its claims reach, and does nothing else: it never mints, never matches by
position and never joins objects. Its links hold until the next ingest, which
makes them again from its rows and ignores the old ones. Of its rows that
claim one object, the first in input order keeps it. The others lose their
claims, and the ingest logs each one.

A row that links two objects joins them. Each join is logged with its
evidence and shown in the report. When both are minted IDs, the older one
survives (the earlier ingest, then the lower number) and the other becomes its
alias. Each merge is logged with both IDs and its evidence, kept in the
ingest log and shown in the report. It stays unreviewed until
`space-map-extrasolar review`.

`commit` then works region by region. Each new object with a table row takes
the next free serial in its home table and cell: brightest first, ties by
catalogue id. A rerun of a first ingest therefore gives the same IDs. Every
table is rebuilt and merged by source order, the live IDs with no row left
retire, and the manifest commits the segment and the tables together. A
failure before that leaves the previous registry and tables in force.

Input batches are Arrow tables with the columns of MATCH_FIELDS, plus the
columns of every group whose source order names the source.

An extension adds content that hangs on the IDs, such as the planets of the
host stars. At commit the engine gives it the ID of each row of the sources
it names, writes the registry parts and tables it returns in the region of
their key ID, and commits them with the rest.
"""

import logging
import shutil
import subprocess
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, Self

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from space_map_data.extrasolar import sky
from space_map_data.extrasolar.ids import (
    CELL_BITS,
    cell_of,
    encode,
    serial_of,
    table_of,
)
from space_map_data.extrasolar.match import Matcher, Pairs, assign
from space_map_data.extrasolar.registry import (
    ALIAS,
    CLAIM,
    IDS,
    LIVE,
    MERGES,
    MERGES_FILE,
    MINT,
    POSITION,
    POSITIONS,
    REPORT_FILE,
    RETIRED,
    STATUS_CODES,
    XIDS,
    IdStates,
    Registry,
    RegistryError,
    ingest_name,
    latest_index,
    sort_by_cell,
)
from space_map_data.extrasolar.report import render_report
from space_map_data.extrasolar.sky import region_of
from space_map_data.extrasolar.store import read_parquet, region_file
from space_map_data.extrasolar.tables import (
    CROSS_ID,
    METADATA,
    OBJECT_CATALOGUES,
    SOURCE_COLUMN,
    TABLES,
    TableDef,
    merge_by_source_order,
)
from space_map_data.utils.arrays import find_sorted, floats, map_sorted
from space_map_data.utils.files import write_parquet
from space_map_data.utils.paths import PROJECT_ROOT, REGISTRY_BACKUP_DIR, REGISTRY_ROOT

logger = logging.getLogger(__name__)

MATCH_FIELDS = (
    # The row's own id in its catalogue. Only a row that does not mint can
    # lack one.
    pa.field("catalogue_id", pa.string()),
    # False: the row gets an ID only when a minting row joins its object.
    pa.field("mint", pa.bool_()),
    # ICRS at J2016.0, in degrees.
    pa.field("match_ra", pa.float64()),
    pa.field("match_dec", pa.float64()),
    # mas/yr.
    pa.field("match_pmra", pa.float32()),
    pa.field("match_pmdec", pa.float32()),
    pa.field("match_mag", pa.float32()),
    # Position error at J2016.0 and radius of the extent, in arcsec.
    pa.field("match_error", pa.float32()),
    pa.field("match_size", pa.float32()),
    # The type for matching. Null takes the kind of the source.
    pa.field("match_kind", pa.string()),
    # Ids of the same object in other catalogues, from a certain cross-match.
    pa.field("claims", pa.list_(CROSS_ID)),
)
REQUIRED = ("catalogue_id", "mint", "match_ra", "match_dec")
MATCH_NAMES = [f.name for f in MATCH_FIELDS]
CELL = "_cell"
KEY = "key"
# The input order of the rows of a source that is not permanent.
SEQ = "_seq"

# Rows held in memory before the staging writes them out.
FLUSH_ROWS = 2_000_000
# Rows of the regions kept in memory for lookups and matching, for the
# registry and for the earlier passes each.
CACHE_ROWS = 10_000_000
# Share of the live IDs that one ingest may retire unless told otherwise.
MAX_RETIRED_SHARE = 0.01
REPORT_EXAMPLES = 20

# A new object of the run has a negative key until it is minted. The key holds
# the pass, the region and a sequence number, so the region of a key needs no
# lookup, and of two keys the one of the earlier pass is the larger.
_REGION_SHIFT = 40
_PASS_SHIFT = 50
_REGION_MASK = (1 << (_PASS_SHIFT - _REGION_SHIFT)) - 1
_ROW_BITS = 32

PENDING = pa.schema(
    [
        (KEY, pa.int64()),
        ("cell", pa.int64()),
        ("ra", pa.float64()),
        ("dec", pa.float64()),
        ("pmra", pa.float32()),
        ("pmdec", pa.float32()),
        ("mag", pa.float32()),
        ("pos_error", pa.float32()),
        ("size", pa.float32()),
        ("kind", pa.string()),
        ("source", pa.string()),
        ("catalogue", pa.string()),
        ("catalogue_id", pa.string()),
        ("mintable", pa.bool_()),
    ]
)
RUN_XIDS = pa.schema(
    [
        ("catalogue", pa.string()),
        ("release", pa.string()),
        ("catalogue_id", pa.string()),
        (KEY, pa.int64()),
        ("link", pa.string()),
        ("score", pa.float32()),
    ]
)
CLAIM_MISSES = pa.schema(
    [
        ("row", pa.int64()),
        ("catalogue", pa.string()),
        ("release", pa.string()),
        ("catalogue_id", pa.string()),
    ]
)
CANDIDATES = pa.schema(
    [
        (KEY, pa.int64()),
        # The cell of the position at sky.MATCH_LEVEL.
        ("fine", pa.int64()),
        ("ra", pa.float64()),
        ("dec", pa.float64()),
        ("mag", pa.float32()),
        ("pos_error", pa.float32()),
        ("size", pa.float32()),
        ("kind", pa.string()),
    ]
)
VIEW_XIDS = pa.schema(
    [
        ("catalogue", pa.string()),
        ("release", pa.string()),
        ("catalogue_id", pa.string()),
        (KEY, pa.int64()),
        ("order", pa.int64()),
    ]
)
INHERITED = pa.schema(
    [
        ("catalogue", pa.string()),
        ("release", pa.string()),
        ("catalogue_id", pa.string()),
        (KEY, pa.int64()),
    ]
)


def pending_key(pass_: int, region: int, seq: np.ndarray) -> np.ndarray:
    value = (pass_ << _PASS_SHIFT) | (region << _REGION_SHIFT) | seq.astype(np.int64)
    return -1 - value


def key_region(key: np.ndarray) -> np.ndarray:
    """The region of minted IDs (positive) and of run keys (negative)."""
    key = np.asarray(key, np.int64)
    pending = ((-1 - key) >> _REGION_SHIFT) & _REGION_MASK
    return np.where(key > 0, region_of(cell_of(key)), pending)


def code_version() -> tuple[str | None, bool]:
    """The commit of the code, and whether the tree has changes."""
    try:
        commit = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        logger.warning("no git commit for the ingest log: %s", error)
        return None, True
    return commit, bool(status.strip())


def _has_catalogue(cross_ids: pa.Array, catalogues: frozenset[str]) -> pa.Array:
    """For each list of cross-ids, whether one is of `catalogues`."""
    flat = pc.list_flatten(cross_ids)
    found = pc.is_in(flat.field("catalogue"), pa.array(sorted(catalogues)))
    parents = pc.list_parent_indices(cross_ids).to_numpy()
    has = np.zeros(len(cross_ids), bool)
    has[parents[found.to_numpy(zero_copy_only=False)]] = True
    return pa.array(has)


def _bools(table: pa.Table, name: str) -> np.ndarray:
    return table[name].fill_null(False).to_numpy()


def _candidates(table: pa.Table) -> pa.Table:
    """Match candidates from positions keyed by `key`, sorted by fine cell."""
    fine = sky.cells(floats(table, "ra"), floats(table, "dec"), sky.MATCH_LEVEL)
    columns = [table[KEY], pa.array(fine, pa.int64())]
    columns += [table[name] for name in CANDIDATES.names[2:]]
    return pa.table(columns, schema=CANDIDATES).take(np.argsort(fine, kind="stable"))


@dataclass(frozen=True)
class Source:
    """A catalogue release that feeds the registry and the tables."""

    # The name in the source orders and source columns of the tables.
    name: str
    catalogue: str
    release: str
    # The home table of the IDs it mints.
    home: int
    # None: its rows are never matched by position.
    matcher: Matcher | None = None
    kind: str | None = None
    # False: its rows only add data to the objects that they claim, and its
    # links hold until the next ingest.
    permanent: bool = True
    # True: the ingest stores only part of the catalogue, so an id that no
    # object holds can name a stored object under another id.
    subset: bool = False


@dataclass
class PassState:
    number: int
    source: Source
    complete: bool
    fields: list[pa.Field]
    regions: set[int] = field(default_factory=set)
    batches: int = 0
    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    # Keys that a row of this pass took by a claim, with that row.
    claimed: dict[int, str] = field(default_factory=dict)
    # Catalogue ids of the rows whose claims another row keeps.
    lost: set[str] = field(default_factory=set)
    # The key of each claim, by region, that `_settle` looked up.
    hits: dict[int, np.ndarray] = field(default_factory=dict)
    next_seq: dict[int, int] = field(default_factory=dict)
    # Position pairs: (region << 32 | sorted row), candidate key, score.
    pair_rows: list[np.ndarray] = field(default_factory=list)
    pair_keys: list[np.ndarray] = field(default_factory=list)
    pair_scores: list[np.ndarray] = field(default_factory=list)


@dataclass
class IngestResult:
    ingest: int
    entry: dict
    report: str
    # Why the backup failed, None when it is done. The ingest stays committed.
    backup_error: str | None = None


@dataclass
class ExtensionResult:
    """What an extension adds to the ingest."""

    # Registry part name → records, and table slug → rows. The ID in the
    # column that `key` names gives the region of a row. Rows keep their
    # order inside a region.
    parts: dict[str, pa.Table]
    tables: dict[str, pa.Table]
    key: str
    # Counts for the ingest log.
    counts: dict[str, int]
    report: str
    # Changes that a person checks before the export publishes them.
    unreviewed: int = 0


class Extension(Protocol):
    """Content of an ingest that hangs on the IDs of the rows of some sources."""

    name: str
    sources: tuple[str, ...]

    def build(
        self,
        registry: Registry,
        ids: dict[str, pa.Table],
        ingest: int,
        complete: bool,
    ) -> ExtensionResult:
        """`ids` holds, per source, the `catalogue_id` and `id` of each row.

        The ID is 0 for a row whose object got none.
        """
        ...


ROW_IDS = pa.schema([("catalogue_id", pa.string()), ("id", pa.int64())])


@dataclass
class _View:
    """What the registry and the earlier passes hold in some regions."""

    # Sorted by order, so the last copy of a catalogue id is the latest.
    xids: pa.Table
    # Keys whose ID is retired.
    dead: np.ndarray
    # Sorted by cell.
    candidates: pa.Table

    def of(self, catalogue: str, release: str) -> pa.Table:
        return self.xids.filter(
            pc.and_(
                pc.equal(self.xids["catalogue"], catalogue),
                pc.equal(self.xids["release"], release),
            )
        )

    def lookup(
        self, catalogue: str, release: str, catalogue_ids: pa.Array
    ) -> tuple[np.ndarray, np.ndarray]:
        """(key, dead) of each catalogue id: key 0 where none or retired."""
        xids = self.of(catalogue, release)
        n = len(catalogue_ids)
        if not xids.num_rows:
            return np.zeros(n, np.int64), np.zeros(n, bool)
        at = latest_index(catalogue_ids, xids["catalogue_id"].combine_chunks())
        keys = np.where(at >= 0, xids[KEY].to_numpy()[np.maximum(at, 0)], 0)
        dead = np.isin(keys, self.dead) & (keys != 0)
        return np.where(dead, 0, keys), dead

    def holders(self, catalogue: str, release: str) -> np.ndarray:
        """The keys that already hold an id of this catalogue release."""
        return np.unique(self.of(catalogue, release)[KEY].to_numpy())

    def catalogues(self, keys: list[int]) -> dict[int, set[tuple[str, str]]]:
        found: dict[int, set[tuple[str, str]]] = {key: set() for key in keys}
        picked = self.xids.filter(pc.is_in(self.xids[KEY], pa.array(keys, pa.int64())))
        for key, catalogue, release in zip(
            picked[KEY].to_pylist(),
            picked["catalogue"].to_pylist(),
            picked["release"].to_pylist(),
        ):
            found[key].add((catalogue, release))
        return found


class _Kept:
    """Maps the keys that rows joined to the key kept for their object."""

    def __init__(self, kept: dict[int, int]) -> None:
        self.keys = np.array(sorted(kept), np.int64)
        self.values = np.array([kept[k] for k in self.keys.tolist()], np.int64)

    def __call__(self, keys: np.ndarray) -> np.ndarray:
        return map_sorted(self.keys, self.values, keys, keys)


class IngestRun:
    """One ingest. Make it with `start` in a `with` block; `commit` ends it."""

    def __init__(
        self,
        registry: Registry,
        backup_root: Path,
        tables: Sequence[TableDef],
        metadata: TableDef,
    ) -> None:
        self.registry = registry
        self.backup_root = backup_root
        self.tables = tuple(tables)
        self.metadata = metadata
        self.all_tables = (metadata, *self.tables)
        self.ingest = registry.last_ingest + 1
        self.staging = registry.dir / "staging" / ingest_name(self.ingest)
        self.passes: list[PassState] = []
        self.sources: dict[str, Source] = {}
        # Pairs of keys that one row links, with the evidence.
        self.unions: list[tuple[int, int, str]] = []
        self.union_catalogues: dict[int, set[tuple[str, str]]] = {}
        # Run keys that a minting row joined after their own pass.
        self.mintable_joins: set[int] = set()
        self.conflicts: list[str] = []
        # The evidence of each join of two objects.
        self.joins: list[str] = []
        self._cache: dict[int, tuple[pa.Table, pa.Table, np.ndarray]] = {}
        self._cache_rows = 0
        self._run_cache: dict[int, tuple[pa.Table, pa.Table]] = {}
        self._run_cache_rows = 0
        self._kept = _Kept({})
        self.extensions: list[Extension] = []
        self._row_ids: dict[str, list[pa.Table]] = defaultdict(list)
        self._extension_slugs: list[str] = []
        self._writer = None
        self._committed = False
        self._done = False

    @classmethod
    def start(
        cls,
        root: Path = REGISTRY_ROOT,
        backup_root: Path = REGISTRY_BACKUP_DIR,
        tables: Sequence[TableDef] = TABLES,
        metadata: TableDef = METADATA,
    ) -> IngestRun:
        """Take the minting lock and remove what a failed run left behind."""
        registry = Registry(root)
        writer = registry.writer()
        writer.__enter__()
        try:
            registry.clean()
            run = cls(registry, backup_root, tables, metadata)
        except BaseException:
            writer.__exit__(None, None, None)
            raise
        run._writer = writer
        logger.info("extrasolar ingest %d in %s", run.ingest, root)
        return run

    def __enter__(self) -> Self:
        return self

    def __exit__(self, kind, error, trace) -> None:
        if not self._done:
            self.abort()

    def abort(self) -> None:
        """Remove the files of the run and release the lock."""
        if not self._committed:
            logger.warning(
                "extrasolar ingest %d stopped before its commit", self.ingest
            )
            shutil.rmtree(self.staging, ignore_errors=True)
            shutil.rmtree(self.registry.segment_dir(self.ingest), ignore_errors=True)
            for slug in self._slugs():
                shutil.rmtree(
                    self.registry.tables_dir / slug / ingest_name(self.ingest),
                    ignore_errors=True,
                )
        self._release()

    def _release(self) -> None:
        self._done = True
        if self._writer is not None:
            self._writer.__exit__(None, None, None)
            self._writer = None

    def _slugs(self) -> list[str]:
        return [table.slug for table in self.all_tables] + self._extension_slugs

    def extend(self, extension: Extension) -> None:
        """Add an extension, which builds its content at commit."""
        unknown = set(extension.sources) - set(self.sources)
        if unknown:
            raise ValueError(f"{extension.name}: no pass of {sorted(unknown)}")
        self.extensions.append(extension)

    def _pass_dir(self, number: int) -> Path:
        return self.staging / f"p{number:02d}"

    def _table_dir(self, table: TableDef) -> Path:
        return self.registry.tables_dir / table.slug / ingest_name(self.ingest)

    # Staging

    def add(
        self,
        source: Source,
        batches: Iterable[pa.Table | pa.RecordBatch],
        complete: bool = True,
    ) -> dict[str, int]:
        """Run one pass over `source`; returns its counts.

        `complete` is false when the batches hold only part of the source. An
        ingest with a partial pass retires no ID.
        """
        if source.name in self.sources:
            raise ValueError(f"{source.name} is already in this ingest")
        if not source.permanent and source.matcher is not None:
            raise ValueError(f"{source.name} is not permanent and has a matcher")
        # A source that is not permanent settles its claims on the joins of
        # the passes before it.
        if source.permanent and not all(s.permanent for s in self.sources.values()):
            raise ValueError(
                f"{source.name} is permanent and comes after a source that is not"
            )
        self.sources[source.name] = source
        state = PassState(
            len(self.passes), source, complete, self._source_fields(source)
        )
        self.passes.append(state)
        self._stage(state, batches)
        self._run_cache.clear()
        self._run_cache_rows = 0
        if not source.permanent:
            self._settle(state)
        for region in sorted(state.regions):
            self._resolve(state, region)
        self._finish_pass(state)
        logger.info("%s: %s", source.name, dict(state.counts))
        return dict(state.counts)

    def _source_fields(self, source: Source) -> list[pa.Field]:
        """The table columns that the rows of `source` carry."""
        fields: dict[str, pa.Field] = {}
        for table in self.all_tables:
            for group in table.groups_of(source.name):
                for column in group.columns:
                    if column.name in (*MATCH_NAMES, CELL, KEY, SEQ):
                        raise ValueError(f"{column.name} is a name the engine uses")
                    if fields.setdefault(column.name, column).type != column.type:
                        raise ValueError(f"{column.name} has two types")
        return list(fields.values())

    def _stage(self, state: PassState, batches: Iterable[pa.Table | pa.RecordBatch]):
        buffered: dict[int, list[pa.Table]] = defaultdict(list)
        held = 0
        for batch in batches:
            table = self._conform(state, pa.table(batch))
            if not table.num_rows:
                continue
            region = region_of(table[CELL].to_numpy())
            order = np.argsort(region, kind="stable")
            region = region[order]
            table = table.take(order)
            starts = np.flatnonzero(np.r_[True, region[1:] != region[:-1]])
            for start, end in zip(starts, np.r_[starts[1:], region.size]):
                buffered[int(region[start])].append(table.slice(start, end - start))
            held += table.num_rows
            if held >= FLUSH_ROWS:
                self._flush(state, buffered)
                held = 0
        self._flush(state, buffered)

    def _conform(self, state: PassState, table: pa.Table) -> pa.Table:
        source = state.source
        names = table.column_names
        missing = [name for name in REQUIRED if name not in names]
        missing += [f.name for f in state.fields if f.name not in names]
        if missing:
            raise ValueError(f"{source.name}: columns missing: {missing}")
        columns = {}
        for column in (*MATCH_FIELDS, *state.fields):
            if column.name in names:
                columns[column.name] = table[column.name].cast(column.type)
            else:
                columns[column.name] = pa.nulls(table.num_rows, column.type)
        columns["mint"] = columns["mint"].fill_null(False)
        if source.kind is not None:
            columns["match_kind"] = columns["match_kind"].fill_null(source.kind)
        table = pa.table(columns)
        if pc.any(pc.and_(table["mint"], pc.is_null(table["catalogue_id"]))).as_py():
            raise ValueError(f"{source.name}: a minting row has no catalogue id")
        ra, dec = floats(table, "match_ra"), floats(table, "match_dec")
        valid = np.isfinite(ra) & np.isfinite(dec) & (np.abs(dec) <= 90)
        if not valid.all():
            dropped = int((~valid).sum())
            logger.warning("%s: %d rows without a valid position", source.name, dropped)
            state.counts["invalid"] += dropped
            table = table.filter(pa.array(valid))
            ra, dec = ra[valid], dec[valid]
        if not source.permanent:
            if pc.any(table["mint"]).as_py() or table["catalogue_id"].null_count:
                raise ValueError(
                    f"{source.name}: a row mints or has no catalogue id,"
                    " and the source is not permanent"
                )
            start = state.counts["rows"]
            table = table.append_column(
                SEQ, pa.array(np.arange(start, start + table.num_rows))
            )
        state.counts["rows"] += table.num_rows
        return table.append_column(CELL, pa.array(sky.cells(ra, dec)))

    def _flush(self, state: PassState, buffered: dict[int, list[pa.Table]]) -> None:
        for region, parts in buffered.items():
            directory = self._pass_dir(state.number) / "in" / f"{region:03d}"
            write_parquet(
                pa.concat_tables(parts), directory / f"{state.batches:06d}.parquet"
            )
            state.regions.add(region)
        state.batches += 1
        buffered.clear()

    def _staged(
        self, number: int, region: int, columns: list[str] | None = None
    ) -> pa.Table:
        directory = self._pass_dir(number) / "in" / f"{region:03d}"
        paths = sorted(directory.glob("*.parquet"))
        return pa.concat_tables([pq.read_table(p, columns=columns) for p in paths])

    def _match_rows(
        self, number: int, region: int, columns: list[str] | None = None
    ) -> tuple[pa.Table, np.ndarray]:
        """The match columns, or `columns`, of a staged region sorted by
        catalogue id, and the order.

        The sort makes the run keys independent of the batch order.
        """
        rows = self._staged(number, region, columns or [*MATCH_NAMES, CELL])
        order = pc.sort_indices(
            rows, sort_keys=[("catalogue_id", "ascending", "at_end")]
        ).to_numpy()
        return rows.take(order), order

    def _keys_path(self, number: int, region: int) -> Path:
        return region_file(self._pass_dir(number) / "keys", region)

    def _read_keys(self, number: int, region: int) -> np.ndarray:
        return pq.read_table(self._keys_path(number, region))[KEY].to_numpy()

    def _write_keys(
        self, number: int, region: int, keys: np.ndarray, order: np.ndarray
    ) -> None:
        """Write keys of sorted rows in the staged row order."""
        staged = np.empty(keys.size, np.int64)
        staged[order] = keys
        write_parquet(pa.table({KEY: staged}), self._keys_path(number, region))

    # Views

    def _hood(self, region: int) -> list[int]:
        return [region, *sky.neighbour_regions(region)]

    def _registry_region(self, region: int) -> tuple[pa.Table, pa.Table, np.ndarray]:
        """The xids by live key, the candidates and the dead keys of a region."""
        if region in self._cache:
            self._cache[region] = self._cache.pop(region)
            return self._cache[region]
        registry = self.registry
        states = registry.id_states([region])
        xids = registry.read_xids(
            region,
            ["catalogue", "release", "catalogue_id", "id", "ingest"],
            rebuild=True,
        )
        keys = registry.live_end(xids["id"].to_numpy())
        view_xids = pa.table(
            [
                xids["catalogue"],
                xids["release"],
                xids["catalogue_id"],
                pa.array(keys, pa.int64()),
                xids["ingest"].cast(pa.int64()),
            ],
            schema=VIEW_XIDS,
        )
        positions = registry.positions(region, states)
        candidates = _candidates(positions.rename_columns({"id": KEY}))
        entry = (view_xids, candidates, self._dead(keys, region, states))
        self._cache[region] = entry
        self._cache_rows += view_xids.num_rows + candidates.num_rows
        while self._cache_rows > CACHE_ROWS and len(self._cache) > 1:
            oldest = next(iter(self._cache))
            dropped = self._cache.pop(oldest)
            self._cache_rows -= dropped[0].num_rows + dropped[1].num_rows
        return entry

    def _dead(self, keys: np.ndarray, region: int, states: IdStates) -> np.ndarray:
        """The keys whose ID is retired. `states` are those of `region`."""
        keys = np.unique(keys)
        # An alias can lead to an ID in another region.
        regions = np.unique(key_region(keys)).tolist()
        if regions != [region]:
            states = self.registry.id_states(regions)
        return keys[states.has_status(keys, RETIRED)]

    def _run_region(self, state: PassState, region: int) -> tuple[pa.Table, pa.Table]:
        """The xids and candidates of the earlier passes in a region."""
        if region in self._run_cache:
            self._run_cache[region] = self._run_cache.pop(region)
            return self._run_cache[region]
        xid_files, pending_files = [], []
        for earlier in self.passes[: state.number]:
            base = self._pass_dir(earlier.number)
            xid_files += sorted((base / "xids" / f"{region:03d}").glob("*.parquet"))
            pending_files += sorted(
                (base / "pending" / f"{region:03d}").glob("*.parquet")
            )
        xids = read_parquet(xid_files, RUN_XIDS, VIEW_XIDS.names[:4])
        xids = xids.append_column(
            "order", pa.array(np.full(xids.num_rows, self.ingest), pa.int64())
        )
        pending = read_parquet(pending_files, PENDING)
        entry = (xids, _candidates(pending))
        self._run_cache[region] = entry
        self._run_cache_rows += xids.num_rows + entry[1].num_rows
        while self._run_cache_rows > CACHE_ROWS and len(self._run_cache) > 1:
            oldest = next(iter(self._run_cache))
            dropped = self._run_cache.pop(oldest)
            self._run_cache_rows -= dropped[0].num_rows + dropped[1].num_rows
        return entry

    def _view(self, state: PassState, regions: Iterable[int]) -> _View:
        xids, candidates, dead = [], [], []
        for region in regions:
            reg_xids, reg_candidates, reg_dead = self._registry_region(region)
            run_xids, run_candidates = self._run_region(state, region)
            xids += [reg_xids, run_xids]
            candidates += [reg_candidates, run_candidates]
            dead.append(reg_dead)
        all_xids = pa.concat_tables(xids)
        all_xids = all_xids.take(pc.sort_indices(all_xids["order"]))
        all_candidates = pa.concat_tables(candidates)
        all_candidates = all_candidates.take(pc.sort_indices(all_candidates["fine"]))
        return _View(all_xids, np.concatenate(dead), all_candidates)

    # Resolving

    def _resolve(self, state: PassState, region: int) -> None:
        source = state.source
        rows, order = self._match_rows(state.number, region)
        ids = rows["catalogue_id"].combine_chunks()
        if pc.count(ids).as_py() != pc.count_distinct(ids).as_py():
            raise ValueError(f"{source.name}: a catalogue id is in the input twice")
        # A source that is not permanent looked up its claims in `_settle`.
        view = self._view(state, self._hood(region)) if source.permanent else None

        if view is not None:
            keys, dead = view.lookup(source.catalogue, source.release, ids)
        else:
            keys, dead = np.zeros(len(ids), np.int64), np.zeros(len(ids), bool)
        if dead.any():
            logger.warning(
                "%s: %d catalogue ids belong to retired IDs and get new ones",
                source.name,
                int(dead.sum()),
            )
            state.counts["retired_hits"] += int(dead.sum())
        state.counts["by_id"] += int((keys != 0).sum())
        mints = _bools(rows, "mint")
        self.mintable_joins.update(keys[(keys < 0) & mints].tolist())

        claim_hit, misses = self._claims(state, region, view, rows, keys, mints)
        state.counts["by_claim"] += int(claim_hit.sum())
        free = np.flatnonzero(keys == 0)
        deferred = np.zeros(0, np.int64)
        if (
            free.size
            and view is not None
            and source.matcher is not None
            and view.candidates.num_rows
        ):
            deferred = self._pairs(state, region, view, rows, free, misses)
        if misses is not None:
            misses = misses.set_column(
                0, "row", pa.array(order[misses["row"].to_numpy()], pa.int64())
            )
            write_parquet(
                misses, region_file(self._pass_dir(state.number) / "claims", region)
            )
        fresh = np.setdiff1d(free, deferred)
        keys[fresh] = self._new_objects(state, region, rows, fresh, "0")

        named = ids.is_valid().to_numpy(zero_copy_only=False)
        by_claim = np.flatnonzero(claim_hit & named)
        new = fresh[named[fresh]]
        self._write_xids(
            state,
            region,
            [
                self._xids(source, ids, keys, by_claim, CLAIM),
                self._xids(source, ids, keys, new, MINT),
            ],
            "0",
        )
        self._write_keys(state.number, region, keys, order)

    def _claims(
        self,
        state: PassState,
        region: int,
        view: _View | None,
        rows: pa.Table,
        keys: np.ndarray,
        mints: np.ndarray,
    ) -> tuple[np.ndarray, pa.Table | None]:
        """Link rows through their claims; `keys` is updated in place.

        Without a view, the claims take the keys that `_settle` found.
        Returns the rows that a claim alone linked, and the claimed ids that
        nothing holds yet, with their sorted row.
        """
        source = state.source
        own = (source.catalogue, source.release)
        claim_hit = np.zeros(rows.num_rows, bool)
        claims = rows["claims"].combine_chunks()
        if not pc.sum(pc.list_value_length(claims)).as_py():
            return claim_hit, None
        flat, parent, hit, usable = self._claim_hits(source, view, claims)
        if view is None:
            hit = state.hits.pop(region)
        catalogue, release = flat.field("catalogue"), flat.field("release")
        claimed_id = flat.field("catalogue_id")
        if state.lost:
            lost = pc.is_in(rows["catalogue_id"], pa.array(sorted(state.lost)))
            lost = lost.fill_null(False).to_numpy(zero_copy_only=False)[parent]
            hit[lost] = 0
            usable[lost] = False

        # No old link of a source that is not permanent holds.
        holders = set(view.holders(*own).tolist()) if view is not None else set()
        starts = np.flatnonzero(np.r_[True, parent[1:] != parent[:-1]])
        ends = np.r_[starts[1:], parent.size]
        row_ids = rows["catalogue_id"].take(parent[starts]).to_pylist()
        texts = pc.binary_join_element_wise(
            catalogue, release, claimed_id, "/"
        ).to_pylist()
        for start, end, row_id in zip(starts, ends, row_ids):
            at = int(parent[start])
            own_key = int(keys[at])
            name = f"{source.catalogue}/{source.release}/{row_id}"
            # A rejected link is a conflict. It never joins two objects.
            links: dict[int, str] = {}
            for c in range(start, end):
                target = int(hit[c])
                if not target or target == own_key or target in links:
                    continue
                if target in state.claimed:
                    self._conflict(
                        f"{name} claims {texts[c]} → {target}, which"
                        f" {state.claimed[target]} took in this pass"
                    )
                elif target in holders:
                    self._conflict(
                        f"{name} claims {texts[c]} → {target}, which already holds"
                        f" an id of {source.catalogue} {source.release}"
                    )
                else:
                    links[target] = texts[c]
            if not own_key and not links:
                continue
            primary = own_key or next(iter(links))
            if not own_key:
                keys[at] = primary
                claim_hit[at] = True
                if mints[at] and primary < 0:
                    self.mintable_joins.add(primary)
            for target in links:
                state.claimed[target] = name
            evidence = "; ".join(
                ([f"{name} → {own_key}"] if own_key else [name])
                + [f"claims {text} → {target}" for target, text in links.items()]
            )
            for target in links:
                if target != primary:
                    # Without a view, `_settle` left one target per row.
                    assert view is not None
                    self._union(view, primary, target, own, evidence)

        missed = np.flatnonzero((hit == 0) & usable)
        # A row that never mints has no use for the ids that nothing holds.
        if not missed.size or not source.permanent:
            return claim_hit, None
        misses = pa.table(
            [
                pa.array(parent[missed], pa.int64()),
                catalogue.take(missed),
                release.take(missed),
                claimed_id.take(missed),
            ],
            schema=CLAIM_MISSES,
        )
        return claim_hit, misses

    def _claim_hits(
        self, source: Source, view: _View | None, claims: pa.ListArray
    ) -> tuple[pa.StructArray, np.ndarray, np.ndarray, np.ndarray]:
        """The claims, flat, with the row of each, the key that holds its id
        (0 for none, and for all without a view) and whether it can link."""
        own = (source.catalogue, source.release)
        flat = pc.list_flatten(claims)
        parent = pc.list_parent_indices(claims).to_numpy()
        catalogue, release = flat.field("catalogue"), flat.field("release")
        claimed_id = flat.field("catalogue_id")
        hit = np.zeros(len(flat), np.int64)
        usable = claimed_id.is_valid().to_numpy(zero_copy_only=False)
        for pair in sorted(set(zip(catalogue.to_pylist(), release.to_pylist()))):
            picked = np.flatnonzero(
                pc.and_(pc.equal(catalogue, pair[0]), pc.equal(release, pair[1]))
                .fill_null(False)
                .to_numpy(zero_copy_only=False)
            )
            if pair == own or None in pair:
                logger.debug(
                    "%s: %d claims to %s ignored", source.name, picked.size, pair
                )
                usable[picked] = False
                continue
            if view is not None:
                hit[picked], _ = view.lookup(pair[0], pair[1], claimed_id.take(picked))
        return flat, parent, hit, usable

    def _settle(self, state: PassState) -> None:
        """Give each object that rows of the pass claim to the first such row.

        For a source that is not permanent. The other rows lose their claims.
        A row whose claims reach two keys loses them too, because such a
        source never joins objects. Keys that the earlier passes join are one
        object. The keys that the claims reach are kept for `_claims`.
        """
        source = state.source
        roots = self._join()[0]
        claimants: dict[int, list[tuple[int, str, int]]] = defaultdict(list)
        for region in sorted(state.regions):
            rows, _ = self._match_rows(
                state.number, region, ["catalogue_id", "claims", SEQ]
            )
            claims = rows["claims"].combine_chunks()
            if not pc.sum(pc.list_value_length(claims)).as_py():
                continue
            view = self._view(state, self._hood(region))
            _, parent, hit, _ = self._claim_hits(source, view, claims)
            state.hits[region] = hit
            targets: dict[int, set[int]] = defaultdict(set)
            for row, key in zip(parent.tolist(), hit.tolist()):
                if key:
                    targets[row].add(key)
            ids = rows["catalogue_id"].to_pylist()
            seqs = rows[SEQ].to_pylist()
            for row in sorted(targets, key=seqs.__getitem__):
                keys = targets[row]
                name = f"{source.catalogue}/{source.release}/{ids[row]}"
                if len(keys) > 1:
                    self._conflict(
                        f"{name} claims {len(keys)} objects, and a {source.name}"
                        " row never joins objects"
                    )
                    state.lost.add(ids[row])
                    continue
                key = keys.pop()
                claimants[roots.get(key, key)].append((seqs[row], ids[row], key))
        prefix = f"{source.catalogue}/{source.release}"
        for rows_of in claimants.values():
            (_, first, kept), *others = sorted(rows_of)
            for _, other, key in others:
                logger.warning(
                    "%s: %s/%s keeps %d, which %s/%s also claims%s",
                    source.name,
                    prefix,
                    first,
                    kept,
                    prefix,
                    other,
                    ""
                    if key == kept
                    else f" through {key}, which this ingest joins to it",
                )
                state.lost.add(other)
                state.counts["outranked"] += 1

    def _union(
        self,
        view: _View,
        primary: int,
        target: int,
        own: tuple[str, str],
        evidence: str,
    ) -> None:
        found = view.catalogues([primary, target])
        found[primary].add(own)
        for key, catalogues in found.items():
            self.union_catalogues.setdefault(key, set()).update(catalogues)
        self.unions.append((primary, target, evidence))

    def _conflict(self, text: str) -> None:
        logger.warning("conflict: %s", text)
        self.conflicts.append(text)

    def _pairs(
        self,
        state: PassState,
        region: int,
        view: _View,
        rows: pa.Table,
        free: np.ndarray,
        misses: pa.Table | None,
    ) -> np.ndarray:
        """Score the candidates of the free rows; returns the rows with a pair.

        `misses` are the claimed ids that nothing holds, by sorted row.
        """
        source = state.source
        matcher = source.matcher
        assert matcher is not None
        sub = rows.take(free)
        ra, dec = floats(sub, "match_ra"), floats(sub, "match_dec")
        error, size = floats(sub, "match_error"), floats(sub, "match_size")
        radius = matcher.radius(error, size)
        row, low, high = sky.disc_ranges(ra, dec, radius)
        hood = self._hood(region)
        reach = set(sky.regions_of_ranges(low, high))
        if not reach <= set(hood):
            view = self._view(state, sorted(reach | set(hood)))
        candidates = view.candidates
        cells = candidates["fine"].to_numpy()
        first = np.searchsorted(cells, low)
        count = np.searchsorted(cells, high) - first
        pair_row = np.repeat(row, count)
        offset = np.arange(count.sum()) - np.repeat(np.cumsum(count) - count, count)
        pair_cand = np.repeat(first, count) + offset

        keys = candidates[KEY].to_numpy()
        excluded = np.concatenate(
            [
                view.holders(source.catalogue, source.release),
                np.array(list(state.claimed), np.int64),
            ]
        )
        keep = ~np.isin(keys[pair_cand], excluded)
        if misses is not None:
            missed_row = misses["row"].to_numpy()
            catalogues = misses["catalogue"].to_pylist()
            releases = misses["release"].to_pylist()
            subsets = {
                (s.catalogue, s.release) for s in self.sources.values() if s.subset
            }
            for catalogue, release in sorted(set(zip(catalogues, releases)) - subsets):
                picked = [
                    c == catalogue and r == release
                    for c, r in zip(catalogues, releases)
                ]
                # The claim names another object of that catalogue.
                keep &= ~(
                    np.isin(free[pair_row], missed_row[picked])
                    & np.isin(keys[pair_cand], view.holders(catalogue, release))
                )
        pair_row, pair_cand = pair_row[keep], pair_cand[keep]
        separation = sky.separation(
            ra[pair_row],
            dec[pair_row],
            candidates["ra"].to_numpy()[pair_cand],
            candidates["dec"].to_numpy()[pair_cand],
        )
        inside = separation <= radius[pair_row]
        pair_row, pair_cand = pair_row[inside], pair_cand[inside]
        pairs = Pairs(
            separation=separation[inside],
            row_error=error[pair_row],
            row_size=size[pair_row],
            row_mag=floats(sub, "match_mag")[pair_row],
            row_kind=sub["match_kind"].combine_chunks().take(pair_row),
            key_error=floats(candidates, "pos_error")[pair_cand],
            key_size=floats(candidates, "size")[pair_cand],
            key_mag=floats(candidates, "mag")[pair_cand],
            key_kind=candidates["kind"].combine_chunks().take(pair_cand),
        )
        score = matcher.score(pairs)
        ok = np.isfinite(score)
        state.pair_rows.append((region << _ROW_BITS) | free[pair_row[ok]])
        state.pair_keys.append(keys[pair_cand[ok]])
        state.pair_scores.append(score[ok])
        return np.unique(free[pair_row[ok]])

    def _new_objects(
        self, state: PassState, region: int, rows: pa.Table, at: np.ndarray, part: str
    ) -> np.ndarray:
        """Make new objects of the sorted rows `at`; returns their keys."""
        if not at.size:
            return np.zeros(0, np.int64)
        start = state.next_seq.get(region, 0)
        keys = pending_key(state.number, region, np.arange(start, start + at.size))
        state.next_seq[region] = start + at.size
        sub = rows.take(at)
        source = state.source
        pending = pa.table(
            [
                pa.array(keys, pa.int64()),
                sub[CELL],
                sub["match_ra"],
                sub["match_dec"],
                sub["match_pmra"],
                sub["match_pmdec"],
                sub["match_mag"],
                sub["match_error"],
                sub["match_size"],
                sub["match_kind"],
                pa.array([source.name] * at.size, pa.string()),
                pa.array([source.catalogue] * at.size, pa.string()),
                sub["catalogue_id"],
                sub["mint"],
            ],
            schema=PENDING,
        )
        directory = self._pass_dir(state.number) / "pending" / f"{region:03d}"
        write_parquet(pending, directory / f"{part}.parquet")
        state.counts["new"] += at.size
        return keys

    def _xids(
        self,
        source: Source,
        ids: pa.Array,
        keys: np.ndarray,
        at: np.ndarray,
        link: str,
        score: np.ndarray | None = None,
    ) -> pa.Table:
        return pa.table(
            [
                pa.array([source.catalogue] * at.size, pa.string()),
                pa.array([source.release] * at.size, pa.string()),
                ids.take(at),
                pa.array(keys[at], pa.int64()),
                pa.array([link] * at.size, pa.string()),
                pa.nulls(at.size, pa.float32())
                if score is None
                else pa.array(score, pa.float32()),
            ],
            schema=RUN_XIDS,
        )

    def _write_xids(
        self, state: PassState, region: int, tables: list[pa.Table], part: str
    ) -> None:
        tables = [table for table in tables if table.num_rows]
        if tables:
            directory = self._pass_dir(state.number) / "xids" / f"{region:03d}"
            write_parquet(pa.concat_tables(tables), directory / f"{part}.parquet")

    def _finish_pass(self, state: PassState) -> None:
        """Assign the position pairs of the pass, and record the claimed ids."""
        if state.pair_rows:
            self._assign_pairs(state)
        source = state.source
        for region in sorted(state.regions):
            path = region_file(self._pass_dir(state.number) / "claims", region)
            if not path.exists():
                continue
            misses = pq.read_table(path)
            keys = self._read_keys(state.number, region)[misses["row"].to_numpy()]
            xids = pa.table(
                [
                    misses["catalogue"],
                    misses["release"],
                    misses["catalogue_id"],
                    pa.array(keys, pa.int64()),
                    pa.array([CLAIM] * misses.num_rows, pa.string()),
                    pa.nulls(misses.num_rows, pa.float32()),
                ],
                schema=RUN_XIDS,
            )
            named = pc.binary_join_element_wise(
                xids["catalogue"], xids["release"], xids["catalogue_id"], "/"
            )
            first = np.unique(named.to_numpy(zero_copy_only=False), return_index=True)[
                1
            ]
            if first.size < xids.num_rows:
                self._conflict(
                    f"{source.name}: {xids.num_rows - first.size} claimed ids in"
                    f" region {region} are claimed twice; the first claim is kept"
                )
                xids = xids.take(np.sort(first))
            self._write_xids(state, region, [xids], "2")

    def _assign_pairs(self, state: PassState) -> None:
        source = state.source
        refs = np.concatenate(state.pair_rows)
        keys = np.concatenate(state.pair_keys)
        scores = np.concatenate(state.pair_scores)
        all_refs = np.unique(refs)
        keep = ~np.isin(keys, list(state.claimed))
        refs, keys, scores = refs[keep], keys[keep], scores[keep]
        kept = assign(refs, keys, scores)
        order = np.argsort(refs[kept])
        won_refs = refs[kept][order]
        won_keys, won_scores = keys[kept][order], scores[kept][order]
        state.pair_rows.clear()
        state.pair_keys.clear()
        state.pair_scores.clear()

        regions = all_refs >> _ROW_BITS
        for region in np.unique(regions).tolist():
            positions = all_refs[regions == region] & ((1 << _ROW_BITS) - 1)
            rows, order = self._match_rows(state.number, region)
            ids = rows["catalogue_id"].combine_chunks()
            mints = _bools(rows, "mint")
            keys_here = self._read_keys(state.number, region)[order]
            won = find_sorted(won_refs, (region << _ROW_BITS) | positions)
            got = positions[won >= 0]
            keys_here[got] = won_keys[won[won >= 0]]
            state.counts["by_position"] += got.size
            joined = keys_here[got]
            self.mintable_joins.update(joined[mints[got] & (joined < 0)].tolist())
            fresh = positions[won < 0]
            keys_here[fresh] = self._new_objects(state, region, rows, fresh, "1")
            named = ids.is_valid().to_numpy(zero_copy_only=False)
            matched = got[named[got]]
            self._write_xids(
                state,
                region,
                [
                    self._xids(
                        source,
                        ids,
                        keys_here,
                        matched,
                        POSITION,
                        won_scores[won[won >= 0]][named[got]],
                    ),
                    self._xids(source, ids, keys_here, fresh[named[fresh]], MINT),
                ],
                "1",
            )
            self._write_keys(state.number, region, keys_here, order)

    # Commit

    def commit(
        self, max_retired: int | None = None, examples: int = REPORT_EXAMPLES
    ) -> IngestResult:
        """Mint, rebuild the tables, retire, commit, then back up.

        `max_retired` caps the IDs the ingest may retire, by default 1% of the
        live IDs. Retiring is final, so a run over the cap stops before its
        commit. A failed backup leaves the ingest committed. The result and its
        report then give the error and the command that copies it.
        """
        try:
            result = self._commit(max_retired, examples)
        except BaseException:
            self.abort()
            raise
        self._release()
        return result

    def _commit(self, max_retired: int | None, examples: int) -> IngestResult:
        complete = all(state.complete for state in self.passes)
        kept, merges = self._groups()
        self._kept = _Kept(kept)
        self._route(merges)
        # A loser is a minted ID, so it sits in the region of its own cell.
        losers: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for loser, survivor in sorted(
            (loser, survivor) for survivor, loser, _ in merges
        ):
            losers[region_of(cell_of(loser))].append((loser, survivor))
        joins = np.array(sorted(self.mintable_joins), np.int64)
        totals: dict[str, int] = defaultdict(int)
        retired: list[int] = []
        for region in self._commit_regions():
            self._build_region(
                region, losers.get(region, []), joins, complete, totals, retired
            )
        if not complete and totals["without_data"]:
            logger.warning(
                "partial ingest: %d live IDs have no row and are not retired",
                totals["without_data"],
            )
        cap = (
            max_retired
            if max_retired is not None
            else int(totals["live_before"] * MAX_RETIRED_SHARE)
        )
        if len(retired) > cap:
            for id_ in retired[:examples]:
                logger.warning("would retire %d", id_)
            raise RegistryError(
                f"the ingest would retire {len(retired)} IDs, over the cap of {cap};"
                " pass max_retired to allow it"
            )

        segment = self.registry.segment_dir(self.ingest)
        segment.mkdir(parents=True, exist_ok=True)
        built = [
            self._build_extension(extension, complete) for extension in self.extensions
        ]
        if merges:
            write_parquet(
                pa.table(
                    [
                        pa.array([m[0] for m in merges], pa.int64()),
                        pa.array([m[1] for m in merges], pa.int64()),
                        pa.array([m[2] for m in merges], pa.string()),
                    ],
                    schema=MERGES,
                ),
                segment / MERGES_FILE,
                sync=True,
            )
        commit, dirty = code_version()
        entry = {
            "ingest": self.ingest,
            "date": datetime.now(UTC).isoformat(),
            "commit": commit,
            "dirty": dirty,
            "complete": complete,
            "sources": [
                {
                    "source": state.source.name,
                    "catalogue": state.source.catalogue,
                    "release": state.source.release,
                    "permanent": state.source.permanent,
                    "complete": state.complete,
                    **dict(state.counts),
                }
                for state in self.passes
            ],
            "counts": {
                "minted": totals["minted"],
                "matched": sum(
                    state.counts["by_claim"] + state.counts["by_position"]
                    for state in self.passes
                ),
                "absorbed": totals["absorbed"],
                "joined": len(self.joins),
                "merged": len(merges),
                "retired": len(retired),
                "unminted": totals["unminted"],
                "conflicts": len(self.conflicts),
                "live": totals["live_before"]
                + totals["minted"]
                - len(merges)
                - len(retired),
            },
            "reviewed": None,
        }
        if built:
            entry["extensions"] = {
                extension.name: {**result.counts, "unreviewed": result.unreviewed}
                for extension, result in zip(self.extensions, built)
            }
        report = render_report(
            entry, merges, retired, self.conflicts, examples, self.joins
        )
        report += "".join(result.report for result in built)
        (segment / REPORT_FILE).write_text(report)
        self.registry.commit(entry, {slug: self.ingest for slug in self._slugs()})
        self._committed = True
        self._remove_old_tables()
        shutil.rmtree(self.staging, ignore_errors=True)
        unreviewed = any(result.unreviewed for result in built)
        level = (
            logging.WARNING if merges or self.conflicts or unreviewed else logging.INFO
        )
        for line in report.splitlines():
            logger.log(level, "%s", line)
        backup_error = self._backup()
        if backup_error is not None:
            report += (
                f"backup: FAILED ({backup_error}). The ingest is committed."
                f" Copy it with `{self._backup_command()}`.\n"
            )
        return IngestResult(self.ingest, entry, report, backup_error)

    def _backup(self) -> str | None:
        """Back up the committed ingest. Returns why it failed, None when done."""
        try:
            self.registry.backup(self.backup_root)
        except Exception as error:
            # The ingest is committed, so a failed copy does not fail it.
            message = f"{type(error).__name__}: {error}"
            logger.error(
                "ingest %d is committed, but its backup to %s failed (%s)."
                " Copy it with `%s`.",
                self.ingest,
                self.backup_root,
                message,
                self._backup_command(),
            )
            return message
        return None

    def _backup_command(self) -> str:
        command = ["space-map-extrasolar"]
        if self.registry.root != REGISTRY_ROOT:
            command += ["--root", str(self.registry.root)]
        if self.backup_root != REGISTRY_BACKUP_DIR:
            command += ["--backup-root", str(self.backup_root)]
        return " ".join([*command, "backup"])

    def _remove_old_tables(self) -> None:
        for slug in self._slugs():
            for version in sorted((self.registry.tables_dir / slug).glob("*")):
                if version.name != ingest_name(self.ingest):
                    shutil.rmtree(version)

    def _build_extension(self, extension: Extension, complete: bool) -> ExtensionResult:
        """Build an extension and write its parts and tables by region."""
        ids = {
            name: pa.concat_tables(self._row_ids[name])
            if self._row_ids[name]
            else ROW_IDS.empty_table()
            for name in extension.sources
        }
        result = extension.build(self.registry, ids, self.ingest, complete)
        segment = self.registry.segment_dir(self.ingest)
        outputs = [(segment / part, rows) for part, rows in result.parts.items()]
        for slug, rows in result.tables.items():
            if slug in self._slugs():
                raise ValueError(f"{extension.name}: table {slug} exists")
            self._extension_slugs.append(slug)
            directory = self.registry.tables_dir / slug / ingest_name(self.ingest)
            directory.mkdir(parents=True, exist_ok=True)
            outputs.append((directory, rows))
        for directory, rows in outputs:
            if not rows.num_rows:
                continue
            regions = region_of(cell_of(rows[result.key].to_numpy()))
            for region in np.unique(regions).tolist():
                write_parquet(
                    rows.filter(pa.array(regions == region)),
                    region_file(directory, region),
                    sync=True,
                )
        return result

    def _join(
        self,
    ) -> tuple[dict[int, int], dict[int, list[str]], list[str], list[str]]:
        """Join the keys that rows link, in the order of the links.

        Returns each joined key → the root of its object, the evidence of each
        root, the links refused because both objects hold an id of one
        catalogue release, and the evidence of each join. It records nothing.
        Each pass calls it again.
        """
        parent: dict[int, int] = {}

        def find(key: int) -> int:
            while parent.get(key, key) != key:
                key = parent[key]
            return key

        catalogues = {key: set(found) for key, found in self.union_catalogues.items()}
        evidence: dict[int, list[str]] = defaultdict(list)
        refused: list[str] = []
        joined: list[str] = []
        for a, b, text in self.unions:
            root_a, root_b = find(a), find(b)
            if root_a == root_b:
                continue
            shared = catalogues.get(root_a, set()) & catalogues.get(root_b, set())
            if shared:
                refused.append(
                    f"{text}: both objects hold {sorted(shared)}, not joined"
                )
                continue
            parent[root_b] = root_a
            parent.setdefault(root_a, root_a)
            joined.append(text)
            catalogues[root_a] = catalogues.get(root_a, set()) | catalogues.pop(
                root_b, set()
            )
            evidence[root_a] += evidence.pop(root_b, []) + [text]
        return {key: find(key) for key in parent}, evidence, refused, joined

    def _groups(self) -> tuple[dict[int, int], list[tuple[int, int, str]]]:
        """Join the keys that rows link, and record each join and conflict.

        Returns each joined key → the key kept for its object, and the merges
        as (survivor, loser, evidence).
        """
        roots, evidence, refused, self.joins = self._join()
        for text in self.joins:
            logger.warning("join: %s", text)
        for text in refused:
            self._conflict(text)
        members: dict[int, list[int]] = defaultdict(list)
        for key, root in roots.items():
            members[root].append(key)

        kept: dict[int, int] = {}
        merges: list[tuple[int, int, str]] = []
        for root, keys in sorted(members.items()):
            minted = sorted(key for key in keys if key > 0)
            if len(minted) > 1:
                regions = np.unique(key_region(np.array(minted))).tolist()
                states = self.registry.id_states(regions)
                first = states.first_ingest[states.find(np.array(minted))]
                survivor = min(zip(first.tolist(), minted))[1]
                why = " | ".join(evidence[root])
                for loser in minted:
                    if loser != survivor:
                        merges.append((survivor, loser, why))
                        logger.warning(
                            "merge: %d becomes an alias of %d; %s", loser, survivor, why
                        )
                rep = survivor
            elif minted:
                rep = minted[0]
            else:
                rep = max(keys)
            for key in keys:
                kept[key] = rep
            pending = [key for key in keys if key < 0]
            if rep < 0 and (
                self.mintable_joins.intersection(pending)
                or self._created_mintable(pending)
            ):
                self.mintable_joins.add(rep)
        return kept, merges

    def _created_mintable(self, keys: list[int]) -> bool:
        """Whether a minting row made any of these run objects."""
        wanted = pa.array(keys, pa.int64())
        for region in np.unique(key_region(np.array(keys))).tolist():
            for state in self.passes:
                directory = self._pass_dir(state.number) / "pending" / f"{region:03d}"
                files = sorted(directory.glob("*.parquet"))
                pending = read_parquet(files, PENDING, [KEY, "mintable"])
                pending = pending.filter(pc.is_in(pending[KEY], wanted))
                if pc.any(pending["mintable"]).as_py():
                    return True
        return False

    def _route(self, merges: list[tuple[int, int, str]]) -> None:
        """Move the rows and xids whose kept key is in another region."""
        for state in self.passes:
            base = self._pass_dir(state.number)
            for region in sorted(state.regions):
                kept = self._kept(self._read_keys(state.number, region))
                target = key_region(kept)
                moving = np.flatnonzero(target != region)
                if moving.size:
                    rows = self._staged(state.number, region).take(moving)
                    rows = rows.append_column(KEY, pa.array(kept[moving]))
                    self._write_routed(
                        "rows", state.number, region, rows, target[moving]
                    )
                files = sorted((base / "xids" / f"{region:03d}").glob("*.parquet"))
                xids = read_parquet(files, RUN_XIDS)
                kept = self._kept(xids[KEY].to_numpy())
                target = key_region(kept)
                moving = np.flatnonzero(target != region)
                if moving.size:
                    xids = xids.set_column(3, KEY, pa.array(kept)).take(moving)
                    self._write_routed(
                        "xids", state.number, region, xids, target[moving]
                    )

        # Metadata lists the catalogue ids of an alias under its live ID.
        aliases = dict(self.registry.aliases())
        aliases.update({loser: survivor for survivor, loser, _ in merges})
        losers = np.array(sorted(aliases), np.int64)
        for region in np.unique(key_region(losers)).tolist():
            xids = self.registry.read_xids(region, rebuild=True)
            xids = xids.filter(pc.is_in(xids["id"], pa.array(losers)))
            ends = self._kept(self.registry.live_end(xids["id"].to_numpy()))
            target = key_region(ends)
            moving = np.flatnonzero(target != region)
            if moving.size:
                inherited = pa.table(
                    [
                        xids["catalogue"],
                        xids["release"],
                        xids["catalogue_id"],
                        pa.array(ends, pa.int64()),
                    ],
                    schema=INHERITED,
                ).take(moving)
                self._write_routed("inherited", 0, region, inherited, target[moving])

    def _write_routed(
        self, kind: str, number: int, region: int, table: pa.Table, target: np.ndarray
    ) -> None:
        for to in np.unique(target).tolist():
            directory = self.staging / "routed" / kind / f"{to:03d}"
            write_parquet(
                table.filter(pa.array(target == to)),
                directory / f"p{number:02d}-{region:03d}.parquet",
            )

    def _routed(
        self, kind: str, region: int, number: int | None = None
    ) -> pa.Table | None:
        directory = self.staging / "routed" / kind / f"{region:03d}"
        prefix = "" if number is None else f"p{number:02d}-"
        paths = sorted(directory.glob(f"{prefix}*.parquet"))
        return pa.concat_tables([pq.read_table(p) for p in paths]) if paths else None

    def _commit_regions(self) -> list[int]:
        found = set(self.registry.part_regions("ids"))
        for state in self.passes:
            found |= state.regions
        for kind in ("rows", "xids", "inherited"):
            directory = self.staging / "routed" / kind
            if directory.is_dir():
                found.update(int(path.name) for path in directory.iterdir())
        return sorted(found)

    def _region_rows(self, region: int) -> dict[str, pa.Table]:
        """The staged rows of each source whose kept key is in `region`."""
        found: dict[str, pa.Table] = {}
        for state in self.passes:
            parts = []
            if region in state.regions:
                rows = self._staged(state.number, region)
                kept = self._kept(self._read_keys(state.number, region))
                here = key_region(kept) == region
                parts.append(
                    rows.filter(pa.array(here)).append_column(KEY, pa.array(kept[here]))
                )
            routed = self._routed("rows", region, state.number)
            if routed is not None:
                parts.append(routed)
            if parts:
                found[state.source.name] = pa.concat_tables(parts)
        return found

    def _merge_tables(self, rows_of: dict[str, pa.Table]) -> dict[str, pa.Table]:
        """Each table's rows of `region`, merged by source order, by kept key."""
        merged: dict[str, pa.Table] = {}
        for table in self.all_tables:
            parts = []
            for name, rows in rows_of.items():
                groups = table.groups_of(name)
                if not groups:
                    continue
                fed = {column.name for group in groups for column in group.columns}
                # A row with no value here gives no row. Dropping it first keeps
                # the merge of a sparse table small.
                has = np.zeros(rows.num_rows, bool)
                for column_name in fed:
                    has |= rows[column_name].is_valid().to_numpy(zero_copy_only=False)
                if not has.any():
                    continue
                if not has.all():
                    rows = rows.filter(pa.array(has))
                columns = {
                    "id": rows[KEY],
                    SOURCE_COLUMN: pa.array([name] * rows.num_rows, pa.string()),
                }
                for column in table.group_fields:
                    columns[column.name] = (
                        rows[column.name]
                        if column.name in fed
                        else pa.nulls(rows.num_rows, column.type)
                    )
                parts.append(pa.table(columns))
            if parts:
                merged[table.slug] = merge_by_source_order(
                    table, pa.concat_tables(parts)
                )
        return merged

    def _build_region(
        self,
        region: int,
        losers: list[tuple[int, int]],
        joins: np.ndarray,
        complete: bool,
        totals: dict[str, int],
        retired: list[int],
    ) -> None:
        """Mint, build the tables and write the segment of one region.

        `losers` are the merges of the region as (loser, survivor), sorted.
        `joins` are the run keys that a minting row joined.
        """
        records = self.registry.read_part("ids", region)
        states = IdStates.build(records)
        old_live = states.id[states.status == STATUS_CODES[LIVE]]
        totals["live_before"] += old_live.size

        rows_of = self._region_rows(region)
        merged = self._merge_tables(rows_of)
        wanted = {name for e in self.extensions for name in e.sources}
        extension_rows = {
            name: rows.select(["catalogue_id", KEY])
            for name, rows in rows_of.items()
            if name in wanted
        }
        del rows_of
        with_data = np.unique(
            np.concatenate(
                [np.zeros(0, np.int64)]
                + [
                    merged[t.slug]["id"].to_numpy()
                    for t in self.tables
                    if t.slug in merged
                ]
            )
        )

        # The new objects kept in this region, minted when they have a row.
        files = []
        for state in self.passes:
            directory = self._pass_dir(state.number) / "pending" / f"{region:03d}"
            files += sorted(directory.glob("*.parquet"))
        pending = read_parquet(files, PENDING)
        keys = pending[KEY].to_numpy()
        kept = self._kept(keys)
        is_kept = kept == keys
        mintable = _bools(pending, "mintable") | np.isin(keys, joins)
        to_mint = is_kept & mintable & np.isin(keys, with_data)
        totals["unminted"] += int((is_kept & ~to_mint).sum())
        totals["absorbed"] += int((~is_kept & (kept > 0)).sum())
        new = pending.filter(pa.array(to_mint))
        new_ids = self._serials(new, records)
        totals["minted"] += new_ids.size

        minted_keys = new[KEY].to_numpy()
        known = with_data[with_data > 0]
        final_keys = np.concatenate([minted_keys, known])
        order = np.argsort(final_keys)
        final_keys = final_keys[order]
        final_ids = np.concatenate([new_ids, known])[order]

        def to_ids(keys: np.ndarray) -> np.ndarray:
            return map_sorted(final_keys, final_ids, keys, 0)

        for name, rows in extension_rows.items():
            self._row_ids[name].append(
                pa.table(
                    [rows["catalogue_id"], pa.array(to_ids(rows[KEY].to_numpy()))],
                    schema=ROW_IDS,
                )
            )

        out: dict[str, pa.Table] = {}
        for slug, rows in merged.items():
            ids = to_ids(rows["id"].to_numpy())
            out[slug] = rows.set_column(0, "id", pa.array(ids)).filter(
                pa.array(ids > 0)
            )
        live_ids = np.unique(
            np.concatenate(
                [np.zeros(0, np.int64)]
                + [out[t.slug]["id"].to_numpy() for t in self.tables if t.slug in out]
            )
        )
        mask = np.zeros(live_ids.size, np.uint32)
        for table in self.tables:
            if table.slug in out and table.number is not None:
                has = np.isin(live_ids, out[table.slug]["id"].to_numpy())
                mask[has] |= np.uint32(1 << table.number)

        loser_ids = np.array([loser for loser, _ in losers], np.int64)
        gone = old_live[~np.isin(old_live, live_ids) & ~np.isin(old_live, loser_ids)]
        totals["without_data"] += gone.size
        retiring = gone if complete else np.zeros(0, np.int64)
        retired += retiring.tolist()

        statuses = (
            [LIVE] * new_ids.size + [ALIAS] * len(losers) + [RETIRED] * retiring.size
        )
        id_records = pa.table(
            [
                pa.array(np.concatenate([new_ids, loser_ids, retiring]), pa.int64()),
                pa.array(statuses, pa.string()),
                pa.array(
                    [None] * new_ids.size
                    + [survivor for _, survivor in losers]
                    + [None] * retiring.size,
                    pa.int64(),
                ),
                pa.array(np.full(len(statuses), self.ingest), pa.uint32()),
            ],
            schema=IDS,
        )
        run_xids = self._run_xids(region)
        xid_ids = to_ids(run_xids[KEY].to_numpy())
        keep = xid_ids > 0
        run_xids = run_xids.filter(pa.array(keep))
        xid_records = pa.table(
            [
                run_xids["catalogue"],
                run_xids["release"],
                run_xids["catalogue_id"],
                pa.array(xid_ids[keep], pa.int64()),
                run_xids["link"],
                run_xids["score"],
                pa.array(np.full(run_xids.num_rows, self.ingest), pa.uint32()),
            ],
            schema=XIDS,
        )
        position_records = pa.table(
            [
                pa.array(new_ids, pa.int64()),
                *(new[name] for name in POSITIONS.names[1:-1]),
                pa.array(np.full(new_ids.size, self.ingest), pa.uint32()),
            ],
            schema=POSITIONS,
        )
        segment = self.registry.segment_dir(self.ingest)
        for part, records_of in (
            ("ids", id_records),
            ("xids", xid_records),
            ("positions", position_records),
        ):
            if records_of.num_rows:
                path = region_file(segment / part, region)
                write_parquet(sort_by_cell(records_of), path, sync=True)

        out[self.metadata.slug] = self._metadata(
            region,
            out.get(self.metadata.slug),
            live_ids,
            mask,
            states,
            losers,
            xid_records,
        )
        for table in self.all_tables:
            rows = out.get(table.slug)
            if rows is not None and rows.num_rows:
                path = region_file(self._table_dir(table), region)
                write_parquet(sort_by_cell(rows.cast(table.schema)), path, sync=True)

    def _run_xids(self, region: int) -> pa.Table:
        """The xids of the run whose kept key is in `region`."""
        tables = []
        for state in self.passes:
            directory = self._pass_dir(state.number) / "xids" / f"{region:03d}"
            xids = read_parquet(sorted(directory.glob("*.parquet")), RUN_XIDS)
            kept = self._kept(xids[KEY].to_numpy())
            here = key_region(kept) == region
            tables.append(
                xids.set_column(3, KEY, pa.array(kept)).filter(pa.array(here))
            )
            routed = self._routed("xids", region, state.number)
            if routed is not None:
                tables.append(routed)
        return pa.concat_tables(tables) if tables else RUN_XIDS.empty_table()

    def _serials(self, new: pa.Table, records: pa.Table) -> np.ndarray:
        """IDs of new objects: the next free serials, brightest first."""
        if not new.num_rows:
            return np.zeros(0, np.int64)
        homes = np.array(
            [self.sources[name].home for name in new["source"].to_pylist()], np.int64
        )
        cells = new["cell"].to_numpy()
        slot = (homes << CELL_BITS) | cells
        keyed = pa.table(
            {
                "slot": slot,
                "mag": new["mag"],
                "catalogue": new["catalogue"],
                # Ids of equal length sort as numbers when they are numbers.
                "length": pc.utf8_length(new["catalogue_id"]),
                "catalogue_id": new["catalogue_id"],
            }
        )
        order = pc.sort_indices(
            keyed,
            sort_keys=[(name, "ascending", "at_end") for name in keyed.column_names],
        ).to_numpy()
        slot_sorted = slot[order]
        starts = np.flatnonzero(np.r_[True, slot_sorted[1:] != slot_sorted[:-1]])
        rank = np.arange(slot.size) - np.repeat(
            starts, np.diff(np.r_[starts, slot.size])
        )

        # Serials are never reused, so retired and alias IDs count.
        ids = records["id"].to_numpy()
        used = (table_of(ids) << CELL_BITS) | cell_of(ids)
        base = np.zeros(slot.size, np.int64)
        if ids.size:
            by_slot = np.lexsort((serial_of(ids), used))
            used, serials = used[by_slot], serial_of(ids)[by_slot]
            last = np.r_[np.flatnonzero(used[1:] != used[:-1]), used.size - 1]
            base = map_sorted(used[last], serials[last] + 1, slot_sorted, 0)
        serial = np.empty(slot.size, np.int64)
        serial[order] = base + rank
        return encode(serial, homes, cells)

    def _metadata(
        self,
        region: int,
        named: pa.Table | None,
        live_ids: np.ndarray,
        mask: np.ndarray,
        states: IdStates,
        losers: list[tuple[int, int]],
        new_xids: pa.Table,
    ) -> pa.Table:
        """A row for each live ID with data, and one for each alias."""
        schema = self.metadata.schema
        n = live_ids.size
        ids = pa.array(live_ids, pa.int64())
        columns: dict[str, pa.Array] = {"id": ids}
        at = None
        if named is not None:
            at = pc.index_in(ids, value_set=named["id"].combine_chunks())
        for group in self.metadata.groups:
            for name in (*group.names, group.source_column):
                if at is None or named is None:
                    columns[name] = pa.nulls(n, schema.field(name).type)
                else:
                    columns[name] = named[name].take(at)
        columns["cross_ids"] = self._cross_ids(region, live_ids, new_xids)
        columns["mask"] = pa.array(mask, pa.uint32())
        columns["object"] = _has_catalogue(columns["cross_ids"], OBJECT_CATALOGUES)
        columns["alias_target"] = pa.nulls(n, pa.int64())
        live = pa.table(columns, schema=schema)

        old = states.status == STATUS_CODES[ALIAS]
        alias_ids = np.concatenate(
            [states.id[old], np.array([loser for loser, _ in losers], np.int64)]
        )
        targets = np.concatenate(
            [states.target[old], np.array([target for _, target in losers], np.int64)]
        )
        m = alias_ids.size
        aliases = pa.table(
            {
                name: pa.nulls(m, schema.field(name).type)
                for name in schema.names
                if name not in ("id", "mask", "alias_target")
            }
            | {
                "id": pa.array(alias_ids, pa.int64()),
                "mask": pa.array(np.zeros(m, np.uint32)),
                "alias_target": pa.array(targets, pa.int64()),
            }
        ).select(schema.names)
        return pa.concat_tables([live, aliases.cast(schema)])

    def _cross_ids(
        self, region: int, live_ids: np.ndarray, new_xids: pa.Table
    ) -> pa.Array:
        """The catalogue ids of each live ID, as a list per ID."""
        old = self.registry.read_xids(
            region, ["catalogue", "release", "catalogue_id", "id"], rebuild=True
        )
        ends = self._kept(self.registry.live_end(old["id"].to_numpy()))
        parts = [
            old.set_column(3, "id", pa.array(ends, pa.int64())),
            new_xids.select(["catalogue", "release", "catalogue_id", "id"]),
        ]
        inherited = self._routed("inherited", region)
        if inherited is not None:
            parts.append(
                inherited.rename_columns(["catalogue", "release", "catalogue_id", "id"])
            )
        xids = pa.concat_tables(parts)
        xids = xids.filter(pc.is_in(xids["id"], pa.array(live_ids, pa.int64())))
        keys = ["id", "catalogue", "release", "catalogue_id"]
        xids = (
            xids.group_by(keys).aggregate([]).sort_by([(k, "ascending") for k in keys])
        )
        cross = pa.StructArray.from_arrays(
            [xids[name].combine_chunks() for name in keys[1:]], fields=list(CROSS_ID)
        )
        ids = xids["id"].to_numpy()
        starts = np.flatnonzero(np.r_[True, ids[1:] != ids[:-1]]) if ids.size else ids
        lists = pa.ListArray.from_arrays(
            pa.array(np.r_[starts, ids.size], pa.int32()),
            cross,
            type=pa.list_(CROSS_ID),
        )
        at = find_sorted(ids[starts], live_ids)
        return lists.take(pa.array(at, mask=at < 0))
