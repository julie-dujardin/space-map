"""A resolver over a committed registry and its tables, read-only.

`registry_planets` and `registry_orbits` read the planets and the Gaia
orbits that the builder takes from the ingest, from the tables instead.

It answers the builder from the registry's xids, positions and tables, for a
dry run outside an ingest. The caller holds `Registry.reader()`. It reads one
region at a time:
- a Gaia DR3 id goes to the region of its HEALPix cell, then, when it
  misses there and its cell is on the region's border, to the next region;
- the ids of the other catalogues come from one pass over every region,
  kept in memory, since they are few;
- a position match takes the registry positions of the row's region and its
  neighbours, with WDS_MATCHER. The ingest runs a pass of the engine instead.
"""

import logging
from collections import defaultdict
from collections.abc import Callable

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
from cdshealpix import nested

from space_map_data.extrasolar import sky
from space_map_data.extrasolar.exoplanets.catalogues import EU, OEC
from space_map_data.extrasolar.exoplanets.simbad import Simbad
from space_map_data.extrasolar.ids import CELL_LEVEL, cell_of
from space_map_data.extrasolar.match import Pairs, assign
from space_map_data.extrasolar.placement import COLUMNS, placement
from space_map_data.extrasolar.registry import Registry
from space_map_data.extrasolar.systems.nodes import GAIA_DR3
from space_map_data.extrasolar.systems.pairs import ORBIT_COLUMNS, orbit_pairs
from space_map_data.extrasolar.systems.planets import PLANETS_INPUT, planet_star_ids
from space_map_data.extrasolar.systems.resolve import FACTS
from space_map_data.extrasolar.systems.wds import WDS_MATCHER
from space_map_data.extrasolar.tables import CROSS_ID
from space_map_data.utils.arrays import find_sorted, floats

logger = logging.getLogger(__name__)

# A Gaia DR3 source_id holds its level-12 HEALPix pixel above this bit.
SOURCE_PIXEL_SHIFT = 35
SOURCE_LEVEL = 12
POINT_COLUMNS = [
    "id",
    *COLUMNS,
    "simbad_sp_type",
    "sp_type",
    "host_spectral_type",
    "non_single_star",
]


def gaia_keys(
    values: np.ndarray, region_ids: Callable[[int], tuple[np.ndarray, np.ndarray]]
) -> np.ndarray:
    """The key of each Gaia DR3 source_id, 0 where none.

    `region_ids` gives the sorted source_ids of a region and their keys. An
    id goes to the region of its HEALPix cell. An ID's cell comes from the
    J2016.0 position and can be the next cell over, so a miss on a region's
    border looks in the next region.
    """
    keys = np.zeros(values.size, np.int64)
    cell = values >> (SOURCE_PIXEL_SHIFT + 2 * (SOURCE_LEVEL - CELL_LEVEL))
    home = sky.region_of(cell)
    _lookup(
        values,
        keys,
        {r: np.flatnonzero(home == r) for r in np.unique(home)},
        region_ids,
    )
    missed = np.flatnonzero(keys == 0)
    if not missed.size:
        return keys
    around = nested.neighbours(cell[missed].astype(np.uint64), CELL_LEVEL)
    regions = np.where(around >= 0, sky.region_of(np.maximum(around, 0)), -1)
    by_region: dict[int, list[int]] = defaultdict(list)
    for at, row, mine in zip(missed.tolist(), regions.tolist(), home[missed].tolist()):
        for region in set(row) - {mine, -1}:
            by_region[region].append(at)
    _lookup(
        values,
        keys,
        {r: np.array(v, np.int64) for r, v in by_region.items()},
        region_ids,
    )
    return keys


def _lookup(
    values: np.ndarray,
    keys: np.ndarray,
    by_region: dict[int, np.ndarray],
    region_ids: Callable[[int], tuple[np.ndarray, np.ndarray]],
) -> None:
    for region in sorted(by_region):
        rows = by_region[region]
        rows = rows[keys[rows] == 0]
        if not rows.size:
            continue
        sorted_ids, sorted_keys = region_ids(int(region))
        at = find_sorted(sorted_ids, values[rows])
        hit = at >= 0
        keys[rows[hit]] = sorted_keys[at[hit]]


def point_facts(positions: pa.Table, point: pa.Table, meta: pa.Table) -> pa.Table:
    """FACTS from the positions (`key`, `ra`, `dec`, `pmra`, `pmdec`, `mag`),
    the Point source rows (POINT_COLUMNS) and the Metadata rows (`id`,
    `name`, `name_source`) of some objects."""
    point = point.take(pc.sort_indices(point["id"]))
    meta = meta.take(pc.sort_indices(meta["id"]))
    ids = positions["key"].to_numpy()
    at_point = find_sorted(point["id"].to_numpy(), ids)
    at_meta = find_sorted(meta["id"].to_numpy(), ids)
    placed = placement(point)
    parallax = floats(point, "parallax")
    distance = np.full(point.num_rows, np.nan)
    by_parallax = placed.by_parallax | placed.by_suspect
    distance[by_parallax] = 1000.0 / parallax[by_parallax]
    distance[placed.by_group] = floats(point, "distance")[placed.by_group]
    distance[placed.by_catalogue] = floats(point, "host_distance")[placed.by_catalogue]

    def pick(table: pa.Table, at: np.ndarray, name: str) -> pa.Array:
        index = pa.array(at, mask=at < 0)
        return table[name].take(index)

    spectral = pc.coalesce(
        pick(point, at_point, "simbad_sp_type"),
        pick(point, at_point, "sp_type"),
        pick(point, at_point, "host_spectral_type"),
    )
    point_distance = np.where(at_point >= 0, distance[np.maximum(at_point, 0)], np.nan)
    return pa.table(
        {
            "key": positions["key"],
            "ra": positions["ra"],
            "dec": positions["dec"],
            "pmra": positions["pmra"],
            "pmdec": positions["pmdec"],
            "mag": positions["mag"],
            "astrometry": pick(point, at_point, "astrometry_source"),
            "parallax": pick(point, at_point, "parallax"),
            "parallax_error": pick(point, at_point, "parallax_error"),
            "distance": pa.array(point_distance, from_pandas=True),
            "spectral_type": spectral,
            "non_single_star": pick(point, at_point, "non_single_star").cast(
                pa.int16()
            ),
            "name": pick(meta, at_meta, "name"),
            "name_source": pick(meta, at_meta, "name_source"),
        },
        schema=FACTS,
    )


class RegistryResolver:
    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self.regions = registry.part_regions("xids")
        self._others: dict[tuple[str, str], dict[str, int]] | None = None
        self.counts: dict[str, int] = defaultdict(int)

    def keys(self, catalogue: str, release: str, ids: pa.Array) -> np.ndarray:
        if (catalogue, release) == GAIA_DR3:
            keys = self._gaia(ids)
        else:
            known = self._other_ids().get((catalogue, release), {})
            keys = np.array([known.get(i, 0) for i in ids.to_pylist()], np.int64)
        found = keys > 0
        keys[found] = self.registry.live_end(keys[found])
        self.counts[f"keys asked {catalogue}/{release}"] += len(ids)
        self.counts[f"keys found {catalogue}/{release}"] += int(found.sum())
        return keys

    def _other_ids(self) -> dict[tuple[str, str], dict[str, int]]:
        if self._others is None:
            found: dict[tuple[str, str], dict[str, int]] = defaultdict(dict)
            for region in self.regions:
                xids = self.registry.read_xids(
                    region, ["catalogue", "release", "catalogue_id", "id"]
                )
                other = pc.invert(
                    pc.and_(
                        pc.equal(xids["catalogue"], GAIA_DR3[0]),
                        pc.equal(xids["release"], GAIA_DR3[1]),
                    )
                )
                xids = xids.filter(other)
                for c, r, v, i in zip(
                    xids["catalogue"].to_pylist(),
                    xids["release"].to_pylist(),
                    xids["catalogue_id"].to_pylist(),
                    xids["id"].to_pylist(),
                ):
                    found[(c, r)][v] = i
            self._others = dict(found)
            logger.info(
                "registry: %s",
                {f"{c}/{r}": len(v) for (c, r), v in self._others.items()},
            )
        return self._others

    def _gaia_region(self, region: int) -> tuple[np.ndarray, np.ndarray]:
        xids = self.registry.read_xids(
            region, ["catalogue", "release", "catalogue_id", "id"]
        )
        xids = xids.filter(
            pc.and_(
                pc.equal(xids["catalogue"], GAIA_DR3[0]),
                pc.equal(xids["release"], GAIA_DR3[1]),
            )
        )
        ids = xids["catalogue_id"].cast(pa.int64()).to_numpy()
        keys = xids["id"].to_numpy()
        order = np.argsort(ids, kind="stable")
        return ids[order], keys[order]

    def _gaia(self, ids: pa.Array) -> np.ndarray:
        return gaia_keys(ids.cast(pa.int64()).to_numpy(), self._gaia_region)

    def facts(self, keys: np.ndarray) -> pa.Table:
        keys = np.unique(np.asarray(keys, np.int64))
        keys = keys[keys > 0]
        regions = sky.region_of(cell_of(keys))
        tables = []
        for region in np.unique(regions).tolist():
            mine = pa.array(keys[regions == region])
            tables.append(self._region_facts(region, mine))
        if not tables:
            return FACTS.empty_table()
        return pa.concat_tables(tables)

    def _region_facts(self, region: int, keys: pa.Array) -> pa.Table:
        positions = self.registry.positions(region)
        positions = positions.filter(pc.is_in(positions["id"], value_set=keys))
        point = self.registry.read_table("point-source", region, POINT_COLUMNS)
        meta = self.registry.read_table(
            "metadata", region, ["id", "name", "name_source"]
        )
        assert point is not None and meta is not None
        point = point.filter(pc.is_in(point["id"], value_set=keys))
        meta = meta.filter(pc.is_in(meta["id"], value_set=keys))
        return point_facts(positions.rename_columns({"id": "key"}), point, meta)

    def match(self, rows: pa.Table) -> np.ndarray:
        ra, dec = floats(rows, "match_ra"), floats(rows, "match_dec")
        keys = np.zeros(rows.num_rows, np.int64)
        valid = np.isfinite(ra) & np.isfinite(dec)
        regions = np.full(rows.num_rows, -1, np.int64)
        regions[valid] = sky.region_of(sky.cells(ra[valid], dec[valid]))
        for region in np.unique(regions[valid]).tolist():
            at = np.flatnonzero(regions == region)
            hood = [region, *sky.neighbour_regions(region)]
            candidates = pa.concat_tables(
                [self.registry.positions(r) for r in hood if r >= 0]
            )
            keys[at] = self._match(rows.take(pa.array(at)), candidates)
        self.counts["matched by position"] += int((keys > 0).sum())
        return keys

    def _match(self, rows: pa.Table, candidates: pa.Table) -> np.ndarray:
        fine = sky.cells(
            floats(candidates, "ra"), floats(candidates, "dec"), sky.MATCH_LEVEL
        )
        order = np.argsort(fine, kind="stable")
        fine, candidates = fine[order], candidates.take(pa.array(order))
        ra, dec = floats(rows, "match_ra"), floats(rows, "match_dec")
        error = floats(rows, "match_error")
        radius = WDS_MATCHER.radius(error, np.full(ra.size, np.nan))
        row, low, high = sky.disc_ranges(ra, dec, radius)
        first = np.searchsorted(fine, low)
        count = np.searchsorted(fine, high) - first
        pair_row = np.repeat(row, count)
        offset = np.arange(count.sum()) - np.repeat(np.cumsum(count) - count, count)
        pair_cand = np.repeat(first, count) + offset
        apart = sky.separation(
            ra[pair_row],
            dec[pair_row],
            floats(candidates, "ra")[pair_cand],
            floats(candidates, "dec")[pair_cand],
        )
        inside = apart <= radius[pair_row]
        pair_row, pair_cand, apart = pair_row[inside], pair_cand[inside], apart[inside]
        pairs = Pairs(
            separation=apart,
            row_error=error[pair_row],
            row_size=np.full(pair_row.size, np.nan),
            row_mag=floats(rows, "match_mag")[pair_row],
            row_kind=pa.nulls(pair_row.size, pa.string()),
            key_error=floats(candidates, "pos_error")[pair_cand],
            key_size=floats(candidates, "size")[pair_cand],
            key_mag=floats(candidates, "mag")[pair_cand],
            key_kind=candidates["kind"].combine_chunks().take(pa.array(pair_cand)),
        )
        score = WDS_MATCHER.score(pairs)
        ids = candidates["id"].to_numpy()
        kept = assign(pair_row, ids[pair_cand], score)
        keys = np.zeros(rows.num_rows, np.int64)
        keys[pair_row[kept]] = ids[pair_cand[kept]]
        return keys


def registry_planets(registry: Registry, hub: Simbad) -> pa.Table:
    """PLANETS_INPUT from the registry's planets table."""
    columns = ["host", "number", "designation", "class", "mass", "period"]
    columns += ["binary_type", "cross_ids"]
    tables = [
        table
        for region in registry.table_regions("planets")
        if (table := registry.read_table("planets", region, columns)) is not None
    ]
    if not tables:
        return PLANETS_INPUT.empty_table()
    planets = pa.concat_tables(tables)
    star_ids = []
    for ids in planets["cross_ids"].to_pylist():
        names = [
            (i["catalogue"], i["catalogue_id"])
            for i in ids or []
            if i["catalogue"] in (EU, OEC)
        ]
        found = planet_star_ids(hub, names)
        star_ids.append([dict(zip(CROSS_ID.names, item)) for item in found] or None)
    planets = planets.drop(["cross_ids"]).append_column(
        "star_ids", pa.array(star_ids, pa.list_(CROSS_ID))
    )
    return planets.select(PLANETS_INPUT.names).cast(PLANETS_INPUT)


def registry_orbits(registry: Registry) -> pa.Table:
    """The PAIRS of the Gaia orbits of the registry's table 2."""
    columns = ["id", *ORBIT_COLUMNS]
    tables = [
        table
        for region in registry.table_regions("binary-orbit")
        if (table := registry.read_table("binary-orbit", region, columns)) is not None
    ]
    rows = pa.concat_tables(tables).rename_columns(["key", *ORBIT_COLUMNS])
    return orbit_pairs(rows)
