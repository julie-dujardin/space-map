"""The Interior table of the extrasolar export: one row for each star whose
interior is known or fitted.

The export writes the rows of each sky region to a scratch file, then cuts
them into tiles as it cuts the registry's tables. A star of
`constants/interior/stars.py` comes first: its row has tier 0 and holds its
interior in `curated`, as JSON in the shape of a body's `interior` block. A
fitted row has tier 1 to 3 (`inputs`). Tier 3 holds the radius, the zone
radii and the masses only, since its metallicity can be assumed. A star
outside the grid, or with no tier, Teff or luminosity, has no row. Nor has a
star whose Teff or L is too wide to place it on the HR diagram
(`inputs.MAX_SIGMA_LOG_TEFF`, `inputs.MAX_SIGMA_LOG_L`). A curated star must
have its home in Point source and must not be an `inputs.EXCLUDED` point.

The core masses and the centre abundances are ranges only. On the main
sequence the age is weak, and a single value would hide that.
"""

import json
import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from space_map_data.constants.interior.references import INTERIOR_SOURCES
from space_map_data.constants.interior.stars import STAR_INTERIORS
from space_map_data.extrasolar import placement
from space_map_data.extrasolar.ids import CELL_MASK
from space_map_data.extrasolar.interiors import grid, inputs, photometry
from space_map_data.extrasolar.interiors.fit import fit
from space_map_data.extrasolar.interiors.schema import INTERIOR
from space_map_data.extrasolar.registry import Registry
from space_map_data.extrasolar.sky import REGION_COUNT, region_of
from space_map_data.extrasolar.store import region_file
from space_map_data.extrasolar.tables import BINARY_ORBIT, POINT_SOURCE, SYSTEM

logger = logging.getLogger(__name__)

CURATED_TIER = 0
FITTED_TIERS = (1, 2, 3)
# The works of the grid, and the works of each Teff and L route, by their
# keys in INTERIOR_SOURCES. Torres 2010 corrects Flower's coefficients.
GRID_WORKS = ("dotter_2026", "choi_2016")
ROUTE_WORKS = {
    photometry.CASAGRANDE_2010: ("casagrande_2010",),
    photometry.FLOWER_1996: ("flower_1996", "torres_2010"),
    inputs.BOLOMETRIC: ("flower_1996", "torres_2010"),
}
CITATIONS = {
    "dotter_2026": "Dotter et al. 2026, ApJS 283, 64",
    "choi_2016": "Choi et al. 2016, ApJ 823, 102",
    "casagrande_2010": "Casagrande et al. 2010, A&A 512, A54",
    "flower_1996": "Flower 1996, ApJ 469, 355",
    "torres_2010": "Torres 2010, AJ 140, 1158",
}
# The site of the grid asks to cite the papers and states no licence.
MIST_CREDIT = {
    "name": "MIST v2.5 stellar evolution tracks",
    "organisation": "MESA Isochrones and Stellar Tracks",
    "source": "https://mist.science/",
    "citation": "; ".join(CITATIONS[key] for key in GRID_WORKS),
}
WORK_NAMES = {
    "casagrande_2010": (
        "An absolutely calibrated Teff scale from the infrared flux method",
        "Casagrande et al. 2010",
    ),
    "flower_1996": (
        (
            "Transformations from theoretical Hertzsprung-Russell diagrams to"
            " color-magnitude diagrams"
        ),
        "Flower 1996",
    ),
    "torres_2010": (
        "On the use of empirical bolometric corrections for stars",
        "Torres 2010",
    ),
}


# The grid quantity of each column, and whether it ships a value.
_COLUMNS = {
    "mass": ("mass", True),
    "radius": ("log_radius", True),
    "envelope_base_radius": ("envelope_base_radius", True),
    "envelope_base_mass": ("envelope_base_mass", True),
    "convective_core_mass": ("convective_core_mass", False),
    "helium_core_mass": ("helium_core_mass", False),
    "centre_temperature": ("log_centre_temperature", True),
    "centre_density": ("log_centre_density", True),
    "centre_x": ("centre_x", False),
    "centre_y": ("centre_y", False),
}
# Columns that tier 3 leaves empty.
CENTRE_COLUMNS = frozenset(
    {"centre_temperature", "centre_density", "centre_x", "centre_y"}
)
_FRACTIONS = frozenset(
    {"envelope_base_radius", "envelope_base_mass", "centre_x", "centre_y"}
)
# The rounding of each column, to what its range supports: decimals for the
# masses (M☉), the fractions and [Fe/H] (dex), significant digits for the
# radius and the centre temperature and density. Rounded values compress
# better.
DECIMALS = {
    "feh": 2,
    "mass": 3,
    "convective_core_mass": 3,
    "helium_core_mass": 3,
    **dict.fromkeys(_FRACTIONS, 3),
}
SIGNIFICANT = {"radius": 3, "centre_temperature": 3, "centre_density": 3}
# A 0 in these columns means a fully convective star, so a value above 0
# never rounds to 0.
ABOVE_ZERO = frozenset(grid.AT_ZERO)


# Why a curated star is not in its region's Point source rows.
NO_HOME = "no Point source row"


class Curated(NamedTuple):
    """A star of STAR_INTERIORS that the registry holds."""

    # The STAR_INTERIORS key as "catalogue/release/id".
    name: str
    # The `curated` value.
    block: str


def curated(registry: Registry) -> dict[int, Curated]:
    """Each star of STAR_INTERIORS that the registry holds, by ID. Two
    entries of one star are an error."""
    # Here, not at the top: the export's objects package is heavy, and the
    # export's workers do not need it.
    from space_map_data.export.objects.interior import from_layers

    out, names = {}, {}
    for catalogue, release in sorted({key[:2] for key in STAR_INTERIORS}):
        keys = [key for key in STAR_INTERIORS if key[:2] == (catalogue, release)]
        found = registry.lookup(catalogue, release, [key[2] for key in keys])
        for key, id_ in zip(keys, found.tolist(), strict=True):
            name = "/".join(key)
            if not id_:
                logger.warning("interior: no live star has %s; it has no row", name)
                continue
            if id_ in names:
                raise ValueError(
                    f"interior: {names[id_]} and {name} are both star {id_}"
                )
            names[id_] = name
            out[id_] = Curated(
                name,
                json.dumps(from_layers(name, STAR_INTERIORS[key]), ensure_ascii=False),
            )
    return out


def _read(registry: Registry, region: int) -> pa.Table:
    table = registry.read_table(POINT_SOURCE.slug, region, list(inputs.COLUMNS))
    if table is None:
        table = POINT_SOURCE.schema.empty_table().select(list(inputs.COLUMNS))
    orbits = registry.read_table(
        BINARY_ORBIT.slug, region, list(placement.ORBIT_PARALLAX_COLUMNS)
    )
    systems = registry.read_table(SYSTEM.slug, region, list(inputs.SYSTEM_COLUMNS))
    return inputs.with_binary_points(
        placement.with_orbit_parallax(table, orbits), systems
    )


def rows(table: pa.Table, tables: grid.Tables) -> tuple[pa.Table, Counter]:
    """The fitted rows of the Point source rows `table`, and the counts of
    what happened to the rows."""
    counts: Counter = Counter()
    given = inputs.read(table)
    for reason, n in zip(*np.unique(given.out[given.out != ""], return_counts=True)):
        counts[f"no tier: {reason}"] = int(n)
    tiered = given.tier != inputs.NO_TIER
    no_teff = tiered & ~np.isfinite(given.log_teff)
    no_l = tiered & ~no_teff & ~np.isfinite(given.log_l)
    wide = (
        tiered
        & ~no_teff
        & ~no_l
        & (
            (given.sigma_log_teff > inputs.MAX_SIGMA_LOG_TEFF)
            | (given.sigma_log_l > inputs.MAX_SIGMA_LOG_L)
        )
    )
    counts["no Teff"] = int(no_teff.sum())
    counts["no luminosity"] = int(no_l.sum())
    counts["inputs too uncertain"] = int(wide.sum())
    todo = np.flatnonzero(tiered & ~no_teff & ~no_l & ~wide)
    result = fit(
        tables,
        given.log_teff[todo],
        given.sigma_log_teff[todo],
        given.log_l[todo],
        given.sigma_log_l[todo],
        given.feh[todo],
        given.sigma_feh[todo],
    )
    counts["outside the grid: [Fe/H]"] = int((~result.feh_inside).sum())
    counts["outside the grid: HR diagram"] = int(
        (result.feh_inside & ~result.inside).sum()
    )
    keep = result.inside
    at = todo[keep]
    tier = given.tier[at]
    for value in FITTED_TIERS:
        counts[f"tier {value}"] = int((tier == value).sum())
    for name in ("teff_source", "luminosity_source"):
        sources, n = np.unique(getattr(given, name)[at].astype(str), return_counts=True)
        counts.update({f"{name}: {s}": int(k) for s, k in zip(sources, n)})

    stages = np.array((*grid.STAGES, None), object)
    columns: dict[str, np.ndarray] = {
        "id": table["id"].to_numpy()[at],
        "tier": tier,
        "curated": np.full(at.size, None, object),
        "stage": stages[np.minimum(result.stage[keep], len(grid.STAGES))],
        "feh": _rounded("feh", given.feh[at]),
        "feh_source": given.feh_source[at],
        "teff_source": given.teff_source[at],
        "luminosity_source": given.luminosity_source[at],
    }
    index = {name: k for k, name in enumerate(grid.QUANTITIES)}
    for name, (quantity, valued) in _COLUMNS.items():
        k = index[quantity]
        parts = {"_lower": result.lower[keep, k], "_upper": result.upper[keep, k]}
        if valued:
            parts[""] = result.value[keep, k]
        for suffix, values in parts.items():
            if quantity.startswith("log_"):
                values = 10.0**values
            values = np.clip(values, 0.0, 1.0 if name in _FRACTIONS else np.inf)
            if name in CENTRE_COLUMNS:
                values = np.where(tier == 3, np.nan, values)
            columns[f"{name}{suffix}"] = _rounded(name, values)
    return _table(columns), counts


def _rounded(name: str, values: np.ndarray) -> np.ndarray:
    if name in DECIMALS:
        out = np.round(values, DECIMALS[name])
        if name in ABOVE_ZERO:
            out = np.where((out == 0) & (values > 0), 10.0 ** -DECIMALS[name], out)
        return out
    digits = SIGNIFICANT[name]
    with np.errstate(invalid="ignore", divide="ignore"):
        step = 10.0 ** (np.floor(np.log10(np.abs(values))) - digits + 1)
        return np.where(values == 0, 0.0, np.round(values / step) * step)


def _check_curated(
    points: pa.Table, ids: np.ndarray, stars: dict[int, Curated]
) -> None:
    """Raise ValueError for a star of `ids` with no row in the Point source
    rows `points`, or with an EXCLUDED reason. The frontend shows no interior
    for such a point."""
    held = points.filter(pc.is_in(points["id"], value_set=pa.array(ids)))
    reasons = dict(zip(held["id"].to_pylist(), inputs.read(held).out.tolist()))
    for id_ in ids.tolist():
        why = reasons.get(id_, NO_HOME)
        if why == NO_HOME or why in inputs.EXCLUDED:
            raise ValueError(
                f"interior: {stars[id_].name} is star {id_}, which can have no"
                f" Interior row: {why}"
            )


def with_curated(
    fitted: pa.Table, points: pa.Table, region: int, stars: dict[int, Curated]
) -> pa.Table:
    """`fitted` with the curated rows of `region` in place of their fitted
    rows, sorted by ID. `points` holds the Point source rows of `region`."""
    ids = np.array(sorted(stars), np.int64)
    ids = ids[region_of(ids & CELL_MASK) == region]
    _check_curated(points, ids, stars)
    kept = fitted.filter(pa.array(~np.isin(fitted["id"].to_numpy(), ids)))
    columns: dict[str, np.ndarray] = {
        field.name: np.full(
            ids.size, np.nan if pa.types.is_floating(field.type) else None, object
        )
        for field in INTERIOR.schema
    }
    columns["id"] = ids
    columns["tier"] = np.full(ids.size, CURATED_TIER, np.int8)
    columns["curated"] = np.array([stars[int(i)].block for i in ids], object)
    joined = pa.concat_tables([kept, _table(columns)])
    return joined.take(pa.array(np.argsort(joined["id"].to_numpy(), kind="stable")))


def _table(columns: dict[str, np.ndarray]) -> pa.Table:
    arrays = []
    for field in INTERIOR.schema:
        values = columns[field.name]
        if pa.types.is_floating(field.type):
            values = np.asarray(values, np.float64)
            arrays.append(pa.array(values, field.type, mask=np.isnan(values)))
        else:
            arrays.append(pa.array(values, field.type))
    return pa.table(arrays, schema=INTERIOR.schema)


@dataclass(frozen=True)
class RegionJob:
    registry: Registry
    region: int
    out: Path
    curated: dict[int, Curated]
    tables_dir: Path


def region_rows(job: RegionJob) -> Counter:
    """Write the Interior rows of one region to its scratch file."""
    points = _read(job.registry, job.region)
    fitted, counts = rows(points, grid.load(job.tables_dir))
    written = with_curated(fitted, points, job.region, job.curated)
    ids = np.array(list(job.curated), np.int64)
    counts["curated"] = int((region_of(ids & CELL_MASK) == job.region).sum())
    counts["curated in place of a fit"] = int(
        np.isin(fitted["id"].to_numpy(), ids).sum()
    )
    pq.write_table(written, region_file(job.out, job.region))
    return counts


type Runner = Callable[[Callable, list, str], list]


def write_rows(registry: Registry, out: Path, run: Runner) -> Counter:
    """The Interior rows of every region in `out`, one scratch file each, and
    the counts of what happened to the rows. Raises grid.GridError when the
    MIST download is not whole."""
    tables_dir = grid.ready(grid.TRACKS_DIR, grid.TABLES_ROOT)
    out.mkdir(parents=True, exist_ok=True)
    stars = curated(registry)
    jobs = [
        RegionJob(registry, region, out, stars, tables_dir)
        for region in range(REGION_COUNT)
    ]
    counts: Counter = Counter()
    for found in run(region_rows, jobs, "interior rows"):
        counts.update(found)
    for reason, n in sorted(counts.items()):
        logger.info("interior rows: %s %d", reason, n)
    return counts


def credits(counts: Counter) -> list[dict]:
    """The credits of the works that the rows of `counts` use: the grid when
    the table holds a fitted row, and the works of each Teff and L route that
    a row took."""
    if not any(counts[f"tier {tier}"] for tier in FITTED_TIERS):
        return []
    used = [
        key
        for route, keys in ROUTE_WORKS.items()
        if counts[f"teff_source: {route}"] or counts[f"luminosity_source: {route}"]
        for key in keys
    ]
    return [MIST_CREDIT] + [
        {
            "name": WORK_NAMES[key][0],
            "organisation": WORK_NAMES[key][1],
            "source": INTERIOR_SOURCES[key].url,
            "citation": CITATIONS[key],
        }
        for key in dict.fromkeys(used)
    ]
