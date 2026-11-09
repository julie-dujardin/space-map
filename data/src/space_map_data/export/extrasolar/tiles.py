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
from collections.abc import Callable
from dataclasses import dataclass, field
from operator import itemgetter
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from space_map_data.constants.stars.families import FAMILIES, ROOT_FAMILY
from space_map_data.export.extrasolar import citations, container, radius, render
from space_map_data.export.extrasolar.container import Column, Written
from space_map_data.extrasolar import families, surface
from space_map_data.extrasolar.ids import CELL_LEVEL, CELL_MASK, table_of
from space_map_data.extrasolar.interiors.schema import INTERIOR
from space_map_data.extrasolar.measured_radius import MEASURED_COLUMNS
from space_map_data.extrasolar.registry import ALIAS, LIVE, RETIRED, Registry
from space_map_data.extrasolar.sky import REGION_LEVEL, REGION_SHIFT, region_of
from space_map_data.extrasolar.store import region_file, with_computed
from space_map_data.extrasolar.systems.assemble import HELD, NODE_CLASSES
from space_map_data.extrasolar.tables import (
    METADATA,
    POINT_SOURCE,
    REFERENCE,
    SYSTEM,
    SYSTEM_ORBIT,
    SYSTEM_STAR,
    SYSTEM_TABLE,
    TABLES,
    TableDef,
)

logger = logging.getLogger(__name__)

ROOTS = 12
# A table's tile splits while it holds more rows than this. After gzip a
# Point source row takes about 260 B, a Metadata row about 22 B, a Binary
# orbit row about 300 B, a System row about 82 B and an Interior row about
# 40 B. So the median tiles are about 92 kB, 73 kB, 34 kB, 51 kB and, at most,
# 60 kB. The Binary orbit and System rows are sparse on the sky, and at these
# counts their largest tiles, 111 kB and 124 kB, stay under the largest Point
# source tile. Every table needs an entry: the export leaves out no table.
MAX_ROWS = {
    METADATA.slug: 7_500,
    "point-source": 900,
    "binary-orbit": 300,
    "system": 1_500,
    INTERIOR.slug: 1_500,
}
# String columns with few distinct values, besides the group source columns.
DICTIONARY = frozenset(
    {
        "class",
        "radius_source",
        "phot_variable_flag",
        "libname_gspphot",
        "distance_method",
        "simbad_otype",
        "simbad_system_otype",
        "feh_xhip_quality",
        "nss_solution_type",
        "combination_method",
        "m1_ref",
        "flag",
        "flags_flame",
        "flags_flame_spec",
        "spectraltype_esphs",
        "flags_esphs",
        "classlabel_espels",
        "classlabel_espels_flag",
        "evidence",
        "stage",
        "feh_source",
        "teff_source",
        "luminosity_source",
        "logg_source",
        "apparent_v_source",
        "extinction_source",
        "sources.item",
        "members.kind",
        "members.letter",
        "members.source",
        "members.known.item",
        "tree.class",
        "orbit.phase",
        "orbit.centre",
        "orbit.assumed.item",
        "orbit.computed.item",
        *(
            f"{name}.{f.name}"
            for name, kind in (("orbit", SYSTEM_ORBIT), ("star", SYSTEM_STAR))
            for f in kind
            if f.name.endswith("_source")
        ),
        *(
            f"{name}.references.{f.name}"
            for name in ("orbit", "star")
            for f in citations.CITATION
            if f.name != "reference"
        ),
    }
)
# Columns that the export computes, after the columns of the table.
COMPUTED = {
    METADATA.slug: (*families.FIELDS, *radius.FIELDS),
    POINT_SOURCE.slug: surface.FIELDS,
}
# Columns of the registry that no client reads, so the tiles leave them out.
DROPPED = {
    POINT_SOURCE.slug: frozenset(
        {
            "phot_g_mean_flux_over_error",
            "phot_bp_mean_flux_over_error",
            "phot_rp_mean_flux_over_error",
            "grvs_mag",
            "grvs_mag_error",
            "hp_mag_error",
            "b_v_error",
            "v_i_error",
            "host_k_mag",
            *(
                f"{name}_gspphot{bound}"
                for name in ("ag", "ebpminrp")
                for bound in ("", "_lower", "_upper")
            ),
            "bc_flame",
            "bc_flame_spec",
        }
    )
}
# The Point source columns of the family masks, of the brightest stars and of
# the radius, each once: they share some.
FAMILY_COLUMNS = tuple(
    dict.fromkeys((*families.COLUMNS, *render.MAG_COLUMNS, *radius.COLUMNS))
)
FAMILY_SCHEMA = pa.schema([POINT_SOURCE.schema.field(name) for name in FAMILY_COLUMNS])
# The System columns of the held stars, and of the points that hold them.
HELD_COLUMNS = ("id", "parent", "star")
NODE_COLUMNS = (*HELD_COLUMNS, "point", "members")
# The Point source columns of the points that a held star stands for.
LED_POINT_COLUMNS = ("id", *MEASURED_COLUMNS, *radius.GAIA_COLUMNS)
# The length of each family list. A family page lists as many stars.
LISTED_STARS = 20
# The G, ID and name of a star of a family list.
type Listed = tuple[float, int, str | None]
TILE_INFO = struct.Struct("<IBBxx")
SPLIT_FILE = "split.bin.gz"
EXAMPLES = 10
# The Metadata columns that a unit returns for some IDs.
NAME_COLUMNS = ["id", "name", "class"]


# The tables that the export writes from its own scratch files, not from the
# registry.
EXPORT_TABLES = (INTERIOR,)


def table_def(slug: str) -> TableDef:
    return {table.slug: table for table in (METADATA, *TABLES, *EXPORT_TABLES)}[slug]


def dictionary_columns(table: TableDef) -> frozenset[str]:
    return DICTIONARY | {group.source_column for group in table.groups}


def _served_type(kind: pa.DataType) -> pa.DataType:
    """A type with each REFERENCE as a CITATION."""
    if kind == REFERENCE:
        return citations.CITATION
    if pa.types.is_struct(kind):
        return pa.struct([f.with_type(_served_type(f.type)) for f in kind])
    if pa.types.is_list(kind):
        return pa.list_(_served_type(kind.value_type))
    return kind


def served_field(field_: pa.Field) -> pa.Field:
    """A column as the tiles serve it. The container has no struct type, so a
    struct column is a list of at most one item."""
    kind = _served_type(field_.type)
    return field_.with_type(pa.list_(kind) if pa.types.is_struct(kind) else kind)


def _served_value(value, kind: pa.DataType):
    """A value of type `kind` as `_served_type` gives its type."""
    if value is None:
        return None
    if kind == REFERENCE:
        return citations.cite(value)
    if pa.types.is_struct(kind):
        return {f.name: _served_value(value[f.name], f.type) for f in kind}
    if pa.types.is_list(kind):
        return [_served_value(item, kind.value_type) for item in value]
    return value


def served_values(field_: pa.Field, values: pa.Array | pa.ChunkedArray) -> pa.Array:
    """The values of a table column as `served_field` gives its type."""
    served = served_field(field_)
    if served.type == field_.type:
        return values.cast(field_.type)
    rows = [_served_value(value, field_.type) for value in values.to_pylist()]
    if pa.types.is_struct(field_.type):
        rows = [None if row is None else [row] for row in rows]
    return pa.array(rows, served.type)


def tile_schema(table: TableDef) -> pa.Schema:
    dropped = DROPPED.get(table.slug, frozenset())
    schema = pa.schema([served_field(f) for f in table.schema if f.name not in dropped])
    for computed in COMPUTED.get(table.slug, ()):
        schema = schema.append(computed)
    return schema


def column_types(table: TableDef) -> list[tuple[str, str]]:
    """Every column of a tile in file order, the item columns of a list after
    the list."""
    names = dictionary_columns(table)
    return [
        column
        for field_ in tile_schema(table)
        for column in container.column_types(field_, names)
    ]


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
    # More checks of the unit's rows.
    check: Callable[[pa.Table], Problems] | None = None
    # Metadata only: the sorted IDs whose NAME_COLUMNS the unit returns.
    names: np.ndarray | None = None
    # The scratch files of an export table, None for a registry table.
    rows_dir: Path | None = None
    # Metadata only: the export's scratch, for the radii (`radius.save`).
    scratch: Path | None = None
    # The scratch files of COMPUTED columns that an earlier step wrote.
    computed_dir: Path | None = None
    # Metadata only: the family masks of the Point source rows, which the
    # interior step wrote.
    families_dir: Path | None = None


@dataclass
class FamilyStars:
    """The stars of each family in some Metadata rows. `counts` holds the
    number of published stars of each family, then of estimated stars.
    `brightest` holds the brightest published stars of each family, by bit.
    `unranked` counts the held stars with a published family and no magnitude,
    which `brightest` leaves out."""

    counts: np.ndarray
    brightest: dict[int, list[Listed]]
    unranked: int = 0

    def merge(self, other: FamilyStars) -> FamilyStars:
        """The family stars of both sets of rows."""
        return FamilyStars(
            self.counts + other.counts,
            {
                bit: sorted(
                    self.brightest.get(bit, []) + other.brightest.get(bit, []),
                    key=itemgetter(0, 1),
                )[:LISTED_STARS]
                for bit in self.brightest.keys() | other.brightest.keys()
            },
            self.unranked + other.unranked,
        )


@dataclass
class UnitResult:
    files: list[Written]
    rows: int
    dropped_aliases: int
    problems: Problems
    # Metadata only.
    family_stars: FamilyStars | None = None
    names: pa.Table | None = None


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
    kinds = dict(column_types(table))
    stored = {f.name: f for f in table.schema}
    columns = [
        column
        for field_ in tile_schema(table)
        for column in container.columns_of(
            field_,
            served_values(stored[field_.name], rows[field_.name])
            if field_.name in stored
            else rows[field_.name].cast(field_.type),
            kinds,
        )
    ]
    info = TILE_INFO.pack(pixel, level, table.number or 0)
    return container.encode(container.KIND_TILE, rows.num_rows, columns, info)


def build_unit(job: UnitJob) -> UnitResult:
    """Write the tiles of one unit and run the checks on its rows."""
    registry = job.registry
    table = table_def(job.slug)
    parts = [
        _read_part(registry, job.slug, region, job.rows_dir)
        for region in job.unit.regions
    ]
    tables = [part for part in parts if part is not None]
    rows = pa.concat_tables(tables) if tables else table.schema.empty_table()
    del parts, tables
    dropped = 0
    if job.slug == METADATA.slug:
        rows, dropped = collapse_aliases(registry, rows)
    problems = check_ids(registry, job.slug, job.unit.regions, rows)
    if job.check is not None:
        problems.update(job.check(rows))
    if job.previous is not None:
        problems.update(check_previous(registry, job.unit.regions, rows, job.previous))
    family_stars = names = None
    if job.names is not None:
        names = names_of(rows, job.names)
    if job.families_dir is not None:
        rows, family_stars = with_families(
            registry, job.unit.regions, rows, problems, job.families_dir
        )
    if job.scratch is not None:
        radius.save(job.scratch, job.unit.regions, rows)
    if job.computed_dir is not None:
        rows = with_computed(rows, job.unit.regions, job.computed_dir)

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
    return UnitResult(files, rows.num_rows, dropped, problems, family_stars, names)


def names_of(rows: pa.Table, ids: np.ndarray) -> pa.Table:
    """NAME_COLUMNS of the live Metadata `rows` with one of `ids`."""
    wanted = np.isin(rows["id"].to_numpy(), ids)
    wanted &= rows["alias_target"].is_null().to_numpy(zero_copy_only=False)
    return rows.filter(pa.array(wanted)).select(NAME_COLUMNS)


def _read(
    registry: Registry,
    table: TableDef,
    regions: tuple[int, ...],
    columns: tuple[str, ...],
) -> pa.Table:
    """The `columns` of the rows of `table` in `regions`."""
    names = list(columns)
    parts = [registry.read_table(table.slug, region, names) for region in regions]
    return pa.concat_tables(
        [
            table.schema.empty_table().select(names),
            *(part for part in parts if part is not None),
        ]
    )


def led_point_rows(
    registry: Registry, regions: tuple[int, ...], system: pa.Table, points: pa.Table
) -> pa.Table:
    """LED_POINT_COLUMNS of the points that a held star of `system` stands
    for (`radius.led_points`): from `points`, the Point source rows of
    `regions`, else from the region of the point's ID. A held star's ID has
    the cell of its point's position, which can be outside the region of the
    cell where the point's ID was minted.

    A compact point gives no Gaia radius: its type is the star's, and the
    star's own type may not say it (`families.compact`)."""
    wanted = radius.led_points(system)
    names = list(FAMILY_COLUMNS)
    found = points.select(names).filter(pc.is_in(points["id"], value_set=wanted))
    missing = np.setdiff1d(wanted.to_numpy(), found["id"].to_numpy())
    others = set(region_of(missing & CELL_MASK).tolist()) - set(regions)
    if others:
        rows = _read(registry, POINT_SOURCE, tuple(sorted(others)), FAMILY_COLUMNS)
        rows = rows.filter(pc.is_in(rows["id"], value_set=pa.array(missing)))
        found = pa.concat_tables([found, rows])
    if lost := len(wanted) - found.num_rows:
        logger.warning("held stars stand for %d points with no Point source row", lost)
    published, estimated = families.masks(found, pa.nulls(found.num_rows, pa.string()))
    compact = pa.array(families.compact(published | estimated))
    for name in radius.GAIA_COLUMNS:
        column = found[name]
        found = found.set_column(
            found.schema.get_field_index(name),
            name,
            pc.if_else(compact, pa.scalar(None, column.type), column),
        )
    return found.select(list(LED_POINT_COLUMNS))


def led_point_ids(
    registry: Registry, regions: tuple[int, ...], system: pa.Table
) -> np.ndarray:
    """The IDs of the points of `system` that a held star stands for
    (`radius.led_points`), also a held star whose System row is outside
    `regions`: it is read from the region of its ID."""
    points = system.filter(system["point"].fill_null(False))
    members = pc.list_flatten(points["members"])
    is_held = pc.equal(pc.struct_field(members, "kind"), HELD)
    held = pc.struct_field(members, "id").filter(is_held).drop_null().to_numpy()
    missing = np.setdiff1d(held, system["id"].to_numpy())
    others = set(region_of(missing & CELL_MASK).tolist()) - set(regions)
    stars = system.select(list(HELD_COLUMNS))
    if others:
        rows = _read(registry, SYSTEM, tuple(sorted(others)), HELD_COLUMNS)
        rows = rows.filter(pc.is_in(rows["id"], value_set=pa.array(missing)))
        stars = pa.concat_tables([stars, rows])
    return radius.led_points(stars).to_numpy()


def held_rows(system: pa.Table, points: pa.Table) -> pa.Table:
    """Family rows of the held stars in the System rows `system`. `points`
    are the points that they stand for (`led_point_rows`).

    A held star has no Point source row, so its row is null but for its ID,
    its spectral type, its magnitudes and the columns of its radius
    (`radius.held_columns`). The rules that read other columns give nothing.
    Its G and V go in the columns of the last source of `render.magnitudes`,
    which takes G, else V, with no estimate.
    """
    held = system.filter(system["star"].is_valid())
    star = held["star"]
    values = {
        "id": held["id"],
        families.SPECTRAL_TYPES[0]: pc.struct_field(star, "spectral_type"),
        "host_g_mag": pc.struct_field(star, "g_mag"),
        "host_v_mag": pc.struct_field(star, "v_mag"),
        **radius.held_columns(held, points),
    }
    return pa.table(
        [
            values[f.name] if f.name in values else pa.nulls(held.num_rows, f.type)
            for f in FAMILY_SCHEMA
        ],
        schema=FAMILY_SCHEMA,
    )


def _star_masks(
    points: pa.Table,
    held: pa.Table,
    rows: pa.Table,
    regions: tuple[int, ...],
    families_dir: Path,
) -> tuple[np.ndarray, np.ndarray]:
    """The published and the estimated family masks of the Point source rows
    `points`, then of the held stars `held`. Those of the Point source rows
    are the interior step's, in `families_dir`, so no row is classified
    twice. A held star's come from its `held_rows` row and its class in the
    Metadata `rows`."""
    saved = with_computed(points.select(["id"]), regions, families_dir)
    saved_published, saved_estimated = (
        saved[field.name].to_numpy() for field in families.MASK_FIELDS
    )
    at = pc.index_in(held["id"], value_set=rows["id"].combine_chunks())
    published, estimated = families.masks(held, rows["class"].take(at))
    return (
        np.concatenate([saved_published, published]),
        np.concatenate([saved_estimated, estimated]),
    )


def with_families(
    registry: Registry,
    regions: tuple[int, ...],
    rows: pa.Table,
    problems: Problems,
    families_dir: Path,
) -> tuple[pa.Table, FamilyStars]:
    """Metadata `rows` with their family masks, spectral type and radius
    (`radius.star_radius`), and the stars of each family. `families_dir`
    holds the masks of the Point source rows (`_star_masks`).

    A held star reads its System row. A point that holds several stars has
    no family or type, and no radius when it stands for a held star
    (`led_point_ids`). Another row without a Point source row, such as a
    resolved system or an alias, has none of them.
    """
    points = _read(registry, POINT_SOURCE, regions, FAMILY_COLUMNS)
    system = _read(registry, SYSTEM, regions, NODE_COLUMNS)
    led_rows = led_point_rows(registry, regions, system, points)
    held_stars = held_rows(system, led_rows)
    stars = pa.concat_tables([points, held_stars])
    published = np.zeros(rows.num_rows, np.uint64)
    estimated = np.zeros(rows.num_rows, np.uint64)
    spectral = pa.nulls(rows.num_rows, pa.string())
    sizes = pa.nulls(rows.num_rows, pa.float32())
    size_sources = pa.nulls(rows.num_rows, pa.string())
    mag = np.full(rows.num_rows, np.nan)
    if stars.num_rows:
        star_published, star_estimated = _star_masks(
            points, held_stars, rows, regions, families_dir
        )
        at = pc.index_in(stars["id"], value_set=rows["id"].combine_chunks())
        found = at.is_valid().to_numpy(zero_copy_only=False)
        lost = stars["id"].to_numpy()[~found]
        problems.add("star row without a Metadata row", lost, lost.size)
        stars = stars.filter(pa.array(found))
        at = at.filter(pa.array(found)).to_numpy()
        classes = rows["class"].take(pa.array(at))
        node = pc.is_in(classes, value_set=pa.array(NODE_CLASSES))
        node = node.to_numpy(zero_copy_only=False)
        star_published, star_estimated = star_published[found], star_estimated[found]
        transits = pc.is_in(
            stars["id"], value_set=radius.transit_hosts(registry, regions)
        ).to_numpy(zero_copy_only=False)
        size, size_source = radius.star_radius(
            stars, star_published | star_estimated, transits
        )
        led = np.isin(stars["id"].to_numpy(), led_point_ids(registry, regions, system))
        place = _places(at, rows.num_rows)
        unsized = pa.array(node & led)
        size = pc.if_else(unsized, pa.scalar(None, size.type), size)
        size_source = pc.if_else(unsized, pa.scalar(None, pa.string()), size_source)
        sizes, size_sources = size.take(place), size_source.take(place)
        is_star = ~node
        stars, at = stars.filter(pa.array(is_star)), at[is_star]
        published[at] = star_published[is_star]
        estimated[at] = star_estimated[is_star]
        spectral = families.spectral_type(stars).take(_places(at, rows.num_rows))
        # Only a star with a published family can be listed.
        listed = published[at] != 0
        mag[at[listed]] = render.magnitudes(stars.filter(pa.array(listed)))[0]
    computed = (published, estimated, spectral, sizes, size_sources)
    for column, values in zip(COMPUTED[METADATA.slug], computed, strict=True):
        rows = rows.append_column(column, pa.array(values, column.type))
    counts = np.stack([families.counts(published), families.counts(estimated)])
    held = table_of(rows["id"].to_numpy()) == SYSTEM_TABLE
    unranked = held & np.isnan(mag) & (published != 0)
    ranked = np.where(unranked, families.NONE, published)
    return rows, FamilyStars(counts, brightest(rows, ranked, mag), int(unranked.sum()))


def _places(at: np.ndarray, n: int) -> pa.Array:
    """The index into `at` of each of `n` rows, null for a row not in it."""
    index = np.full(n, -1)
    index[at] = np.arange(at.size)
    return pa.array(index, mask=index < 0)


def brightest(
    rows: pa.Table, published: np.ndarray, mag: np.ndarray
) -> dict[int, list[Listed]]:
    """The LISTED_STARS brightest of the Metadata `rows` in each published
    family but the root, by bit, brightest first.

    `mag` is the G of each row. A row without G comes last, and a tie goes by
    ID, so the lists do not depend on how the rows are cut into jobs.
    """
    tagged = np.flatnonzero(published)
    masks = published[tagged]
    ids = rows["id"].to_numpy()[tagged]
    mag = mag[tagged]
    mag[np.isnan(mag)] = np.inf
    out = {}
    for bit, family in enumerate(FAMILIES):
        if family == ROOT_FAMILY:
            continue
        at = np.flatnonzero(masks & families.BIT[family])
        if not at.size:
            continue
        if at.size > LISTED_STARS:
            # The stars tied at the cut stay, so the ID picks among them.
            cut = np.partition(mag[at], LISTED_STARS - 1)[LISTED_STARS - 1]
            at = at[mag[at] <= cut]
        at = at[np.lexsort((ids[at], mag[at]))[:LISTED_STARS]]
        names = rows["name"].take(pa.array(tagged[at])).to_pylist()
        out[bit] = list(zip(mag[at].tolist(), ids[at].tolist(), names))
    return out


def _read_part(
    registry: Registry,
    slug: str,
    region: int,
    rows_dir: Path | None,
    columns: list[str] | None = None,
) -> pa.Table | None:
    """The rows of `slug` in `region`, from `rows_dir` when it is given."""
    if rows_dir is None:
        return registry.read_table(slug, region, columns)
    path = region_file(rows_dir, region)
    return pq.read_table(path, columns=columns) if path.exists() else None


def region_counts(
    registry: Registry, slug: str, region: int, rows_dir: Path | None = None
) -> np.ndarray:
    """The rows of `slug` in each cell of `region`."""
    rows = _read_part(registry, slug, region, rows_dir, ["id"])
    size = 1 << REGION_SHIFT
    if rows is None:
        return np.zeros(size, np.int64)
    cells = (rows["id"].to_numpy() & CELL_MASK) - (region << REGION_SHIFT)
    return np.bincount(cells, minlength=size)
