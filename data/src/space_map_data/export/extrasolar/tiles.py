"""Record tiles: each table cut into HEALPix pixels.

A tile is a nested pixel at a level from 0 to 10 and holds the rows whose ID
has its cell inside the pixel. The 12 level-0 pixels are the roots. A pixel
splits in four while it holds more rows than the table's threshold, down to
level 10, the level of the cells.

The split table has one bit per pixel of the tree, 1 for a pixel that splits.
The bits are in pre-order: root 0, then the subtree of each of its children
in nested order (4p to 4p + 3) if it splits, then root 1, and so on. The
leaves in that order are in cell order, so a client finds the tile of a cell
by binary search on the first cell of each leaf.

Rows in a tile are sorted by ID. A Metadata tile holds the alias rows at the
alias's own cell, with the end of the alias chain as alias_target. An alias
whose chain ends at an ID that is not live has no row, as a retired ID.
"""

import logging
import struct
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from space_map_data.export.extrasolar import container
from space_map_data.export.extrasolar.container import Column, Written
from space_map_data.extrasolar.ids import CELL_LEVEL, CELL_MASK
from space_map_data.extrasolar.registry import ALIAS, LIVE, RETIRED, Registry
from space_map_data.extrasolar.sky import REGION_LEVEL, REGION_SHIFT, region_of
from space_map_data.extrasolar.tables import METADATA, TABLES, TableDef

logger = logging.getLogger(__name__)

ROOTS = 12
# A table's tile splits while it holds more rows than this. A Point source
# row takes about 185 B after gzip and a Metadata row about 22 B, so the
# median tiles are about 64 kB and 73 kB.
MAX_ROWS = {METADATA.slug: 7_500, "point-source": 900}
# String columns with few distinct values, besides the group source columns.
DICTIONARY = frozenset(
    {"class", "phot_variable_flag", "libname_gspphot", "feh_xhip_quality"}
)
TILE_INFO = struct.Struct("<IBBxx")
SPLIT_FILE = "split.bin.gz"
EXAMPLES = 10


def table_def(slug: str) -> TableDef:
    return {table.slug: table for table in (METADATA, *TABLES)}[slug]


def dictionary_columns(table: TableDef) -> frozenset[str]:
    return DICTIONARY | {group.source_column for group in table.groups}


def column_types(table: TableDef) -> list[tuple[str, str]]:
    names = dictionary_columns(table)
    return [(f.name, container.column_type(f, names)) for f in table.schema]


def tile_path(slug: str, level: int, pixel: int) -> str:
    return f"{slug}/{level}/{pixel}.bin.gz"


def first_cell(level: np.ndarray, pixel: np.ndarray) -> np.ndarray:
    return pixel.astype(np.int64) << (2 * (CELL_LEVEL - level.astype(np.int64)))


@dataclass(frozen=True)
class Split:
    """The tile tree of a table: the split bits and the leaves in cell order."""

    bits: np.ndarray
    level: np.ndarray
    pixel: np.ndarray

    @classmethod
    def build(cls, counts: np.ndarray, max_rows: int) -> Split:
        """The tree of a table with `counts` rows in each level-10 cell."""
        sums = {CELL_LEVEL: np.asarray(counts, np.int64)}
        for level in range(CELL_LEVEL - 1, -1, -1):
            sums[level] = sums[level + 1].reshape(-1, 4).sum(axis=1)
        splits = {level: sums[level] > max_rows for level in range(CELL_LEVEL)}
        return cls._walk(
            lambda level, pixel: level < CELL_LEVEL and bool(splits[level][pixel])
        )

    @classmethod
    def from_bits(cls, bits: np.ndarray, source: str) -> Split:
        """The tree of a split table. `source` names the file in errors."""
        stream = iter(np.asarray(bits, bool).tolist())

        def splits(level: int, pixel: int) -> bool:
            bit = next(stream, None)
            if bit is None:
                raise container.FormatError(f"{source}: the split table ends early")
            if bit and level == CELL_LEVEL:
                raise container.FormatError(f"{source}: a level-10 pixel splits")
            return bit

        split = cls._walk(splits)
        if next(stream, None) is not None:
            raise container.FormatError(f"{source}: the split table has bits left over")
        return split

    @classmethod
    def _walk(cls, splits) -> Split:
        bits: list[bool] = []
        levels: list[int] = []
        pixels: list[int] = []
        stack = [(0, pixel) for pixel in range(ROOTS - 1, -1, -1)]
        while stack:
            level, pixel = stack.pop()
            split = splits(level, pixel)
            bits.append(split)
            if split:
                stack.extend((level + 1, 4 * pixel + k) for k in (3, 2, 1, 0))
            else:
                levels.append(level)
                pixels.append(pixel)
        return cls(
            np.array(bits, bool), np.array(levels, np.uint8), np.array(pixels, np.int64)
        )

    @property
    def first(self) -> np.ndarray:
        return first_cell(self.level, self.pixel)

    def leaf_of(self, cells: np.ndarray) -> np.ndarray:
        return np.searchsorted(self.first, cells, side="right") - 1

    def payload(self) -> bytes:
        return container.encode(
            container.KIND_SPLIT,
            self.bits.size,
            [Column("split", "bits", self.bits)],
        )


@dataclass(frozen=True)
class Unit:
    """Leaves built together: the leaves of one region, or one leaf larger than
    a region with every region inside it."""

    regions: tuple[int, ...]
    level: np.ndarray
    pixel: np.ndarray


def units(split: Split) -> list[Unit]:
    first = split.first
    level = split.level.astype(np.int64)
    low = first >> REGION_SHIFT
    span = 1 << (2 * np.maximum(REGION_LEVEL - level, 0))
    out = []
    starts = np.flatnonzero(np.r_[True, low[1:] != low[:-1]])
    for start, end in zip(starts, np.r_[starts[1:], low.size]):
        regions = tuple(range(int(low[start]), int(low[start] + span[start])))
        out.append(Unit(regions, split.level[start:end], split.pixel[start:end]))
    return out


@dataclass
class Problems:
    """What the publish checks found: counts and some examples of each kind."""

    counts: Counter = field(default_factory=Counter)
    examples: dict[str, list[str]] = field(default_factory=dict)

    def add(self, kind: str, items: list[str] | np.ndarray, count: int | None = None):
        items = [str(item) for item in list(items)[:EXAMPLES]]
        total = len(items) if count is None else count
        if not total:
            return
        self.counts[kind] += total
        kept = self.examples.setdefault(kind, [])
        kept += items[: EXAMPLES - len(kept)]

    def update(self, other: Problems) -> None:
        for kind, count in other.counts.items():
            self.add(kind, other.examples.get(kind, []), count)

    def __bool__(self) -> bool:
        return bool(self.counts)

    def lines(self) -> list[str]:
        return [
            f"{kind}: {count:,} (e.g. {', '.join(self.examples.get(kind, []))})"
            for kind, count in sorted(self.counts.items())
        ]


@dataclass(frozen=True)
class Previous:
    """The Metadata tiles that the previous export serves for one unit."""

    root: Path
    paths: tuple[str, ...]


@dataclass(frozen=True)
class UnitJob:
    registry: Registry
    slug: str
    unit: Unit
    out: Path
    previous: Previous | None = None


@dataclass
class UnitResult:
    files: list[Written]
    rows: int
    dropped_aliases: int
    problems: Problems


def _states_of(registry: Registry, ids: np.ndarray):
    regions = sorted(set(region_of(ids & CELL_MASK).tolist()))
    return registry.id_states(regions)


def collapse_aliases(registry: Registry, rows: pa.Table) -> tuple[pa.Table, int]:
    """Metadata rows with each alias naming the live end of its chain. Aliases
    that end at an ID that is not live are dropped."""
    target = rows["alias_target"].combine_chunks()
    is_alias = target.is_valid().to_numpy(zero_copy_only=False)
    if not is_alias.any():
        return rows, 0
    ends = registry.live_end(target.filter(pa.array(is_alias)).to_numpy())
    live = _states_of(registry, ends).has_status(ends, LIVE)
    new_target = np.zeros(rows.num_rows, np.int64)
    new_target[is_alias] = ends
    keep = np.ones(rows.num_rows, bool)
    keep[np.flatnonzero(is_alias)[~live]] = False
    dropped = int((~live).sum())
    if dropped:
        lost = rows["id"].to_numpy()[np.flatnonzero(is_alias)[~live]]
        logger.warning(
            "%d aliases end at an ID that is not live and get no row, e.g. %s",
            dropped,
            lost[:EXAMPLES].tolist(),
        )
    column = pa.array(new_target, pa.int64(), mask=~is_alias)
    at = rows.schema.get_field_index("alias_target")
    rows = rows.set_column(at, rows.schema.field(at), column)
    return rows.filter(pa.array(keep)), dropped


def check_ids(
    registry: Registry, slug: str, regions: tuple[int, ...], rows: pa.Table
) -> Problems:
    """The rows hold only IDs that the registry has with the status they show."""
    problems = Problems()
    ids = rows["id"].to_numpy()
    inside = np.isin(region_of(ids & CELL_MASK), regions)
    problems.add("row outside its region file", ids[~inside], int((~inside).sum()))
    states = registry.id_states(regions)
    at = states.find(ids)
    problems.add("ID not in the registry", ids[at < 0], int((at < 0).sum()))
    expect = np.full(ids.size, LIVE, object)
    if slug == METADATA.slug:
        alias = rows["alias_target"].is_valid().to_numpy(zero_copy_only=False)
        expect[alias] = ALIAS
        target = rows["alias_target"].filter(pa.array(alias)).to_numpy()
        target_live = _states_of(registry, target).has_status(target, LIVE)
        problems.add(
            "alias target not live", target[~target_live], int((~target_live).sum())
        )
    for status in (LIVE, ALIAS):
        want = (expect == status) & (at >= 0)
        wrong = want & ~states.has_status(ids, status)
        problems.add(
            f"{status} row of an ID that the registry does not hold as {status}",
            ids[wrong],
            int(wrong.sum()),
        )
    return problems


def _flat_cross_ids(rows: pa.Table) -> pa.Table:
    lengths = pc.list_value_length(rows["cross_ids"]).fill_null(0).to_numpy()
    items = pc.list_flatten(rows["cross_ids"]).combine_chunks()
    return pa.table(
        {
            "id": np.repeat(rows["id"].to_numpy(), lengths),
            "catalogue": items.field("catalogue"),
            "release": items.field("release"),
            "catalogue_id": items.field("catalogue_id"),
        }
    )


def check_previous(
    registry: Registry, regions: tuple[int, ...], rows: pa.Table, previous: Previous
) -> Problems:
    """Each ID that the previous export serves is still served with its
    catalogue ids, or is an alias or retired in the registry. The ids of a
    source that is not permanent may change."""
    problems = Problems()
    tables = []
    for path in previous.paths:
        old = container.read(previous.root / path).table()
        tables.append(old.select(["id", "cross_ids", "alias_target"]))
    if not tables:
        return problems
    old = pa.concat_tables(tables)
    old_ids = old["id"].to_numpy()
    old = old.filter(pa.array(np.isin(region_of(old_ids & CELL_MASK), regions)))
    old_ids = old["id"].to_numpy()
    new_ids = rows["id"].to_numpy()
    states = registry.id_states(regions)

    excused = states.has_status(old_ids, ALIAS) | states.has_status(old_ids, RETIRED)
    missing = ~np.isin(old_ids, new_ids) & ~excused
    problems.add("served ID missing", old_ids[missing], int(missing.sum()))

    new_live = rows["alias_target"].is_null().to_numpy(zero_copy_only=False)
    old_live = old["alias_target"].is_null().to_numpy(zero_copy_only=False)
    both = old_live & np.isin(old_ids, new_ids[new_live]) & ~excused
    keys = ["id", "catalogue", "release", "catalogue_id"]
    lost = _flat_cross_ids(old.filter(pa.array(both))).join(
        _flat_cross_ids(rows.filter(pa.array(new_live))), keys, join_type="left anti"
    )
    # The links of a source that is not permanent can change at each ingest.
    for catalogue, release in sorted(registry.temporary_catalogues):
        lost = lost.filter(
            pc.invert(
                pc.and_(
                    pc.equal(lost["catalogue"], catalogue),
                    pc.equal(lost["release"], release),
                )
            )
        )
    changed = np.unique(lost["id"].to_numpy())
    problems.add("served ID lost catalogue ids", changed, int(changed.size))
    return problems


def tile_payload(table: TableDef, level: int, pixel: int, rows: pa.Table) -> bytes:
    columns = [
        Column(name, kind, rows[name].cast(table.schema.field(name).type))
        for name, kind in column_types(table)
    ]
    info = TILE_INFO.pack(pixel, level, table.number or 0)
    return container.encode(container.KIND_TILE, rows.num_rows, columns, info)


def build_unit(job: UnitJob) -> UnitResult:
    """Write the tiles of one unit and run the checks on its rows."""
    registry = job.registry
    table = table_def(job.slug)
    parts = [registry.read_table(job.slug, region) for region in job.unit.regions]
    tables = [part for part in parts if part is not None]
    rows = pa.concat_tables(tables) if tables else table.schema.empty_table()
    del parts, tables
    dropped = 0
    if job.slug == METADATA.slug:
        rows, dropped = collapse_aliases(registry, rows)
    problems = check_ids(registry, job.slug, job.unit.regions, rows)
    if job.previous is not None:
        problems.update(check_previous(registry, job.unit.regions, rows, job.previous))

    ids = rows["id"].to_numpy()
    first = first_cell(job.unit.level, job.unit.pixel)
    leaf = np.searchsorted(first, ids & CELL_MASK, side="right") - 1
    order = np.lexsort((ids, leaf))
    leaf = leaf[order]
    rows = rows.take(pa.array(order))
    bounds = np.searchsorted(leaf, np.arange(first.size + 1))
    files = []
    for k, (level, pixel) in enumerate(zip(job.unit.level, job.unit.pixel)):
        part = rows.slice(int(bounds[k]), int(bounds[k + 1] - bounds[k]))
        payload = tile_payload(table, int(level), int(pixel), part)
        files.append(
            container.write(
                job.out, tile_path(job.slug, int(level), int(pixel)), payload
            )
        )
    return UnitResult(files, rows.num_rows, dropped, problems)


def region_counts(registry: Registry, slug: str, region: int) -> np.ndarray:
    """The rows of `slug` in each cell of `region`."""
    rows = registry.read_table(slug, region, ["id"])
    size = 1 << REGION_SHIFT
    if rows is None:
        return np.zeros(size, np.int64)
    cells = (rows["id"].to_numpy() & CELL_MASK) - (region << REGION_SHIFT)
    return np.bincount(cells, minlength=size)
