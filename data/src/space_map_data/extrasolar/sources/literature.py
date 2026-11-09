"""The star values of the literature table as an ingest source.

A row of the source holds the values of one star of the table
(`constants/stars/literature.py`). It claims the star by the key of its
entry, never mints and never matches by position. Its own id is that key, so
the star has a `literature` cross-id, and the export knows from it which works
to cite in the star's object entry. Its pass comes after the distance passes,
so that no later pass can match a row that reaches no star by position.

The white dwarfs of the 40 pc sample of O'Brien et al. 2024 (Table A1) come
from its download. A star of the table that has its own paper keeps that
paper's values. Only the ingest reads the download: the export cites a
measured value by the paper group that holds it (`measured_reference`).
"""

import csv
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pyarrow as pa

from space_map_data.constants.stars.literature import (
    DISTANCES,
    LOGGS,
    MASSES,
    RADII,
    TEFFS,
    Bounds,
    Distance,
    Measured,
    Radius,
    StarKey,
)
from space_map_data.download.providers.stars import obrien_white_dwarfs
from space_map_data.extrasolar.engine import Source
from space_map_data.extrasolar.sources import distances
from space_map_data.extrasolar.sources.hipparcos import GAIA_DR3, HD
from space_map_data.extrasolar.sources.names import HIP
from space_map_data.extrasolar.sources.simbad import SIMBAD
from space_map_data.extrasolar.sources.wikidata import gaia_position

LITERATURE = Source(name="literature", catalogue="literature", release="star", home=1)
SIMBAD_OID = (SIMBAD.catalogue, SIMBAD.release)
# The tables of measured values, by the name of their columns.
MEASURED_TABLES = {"teff": TEFFS, "logg": LOGGS, "mass": MASSES}
# The tables that have a lower and an upper bound in place of a 1σ error.
BOUNDED = frozenset({"mass"})
# The value and error columns of each table in O'Brien et al. 2024 Table A1:
# the fit before the paper's low-mass correction. The correction changes Teff
# and mass but not log g, so the three come from one fit.
OBRIEN_COLUMNS = {
    "teff": ("gaia_teff", "gaia_teff_err"),
    "logg": ("gaia_logg", "gaia_logg_err"),
    "mass": ("gaia_mass", "gaia_mass_err"),
}
OBRIEN_2024 = "obrien_2024"


def catalogue_id(key: StarKey) -> str:
    """The id of the row of a star: its key as `catalogue/release/id`."""
    return "/".join(key)


def key_of(literature_id: str) -> StarKey:
    """The key of the star of a `literature` cross-id."""
    catalogue, release, number = literature_id.split("/", 2)
    return catalogue, release, number


def white_dwarfs(
    directory: Path = obrien_white_dwarfs.OUT_DIR,
) -> dict[str, dict[StarKey, Measured]]:
    """The measured values of each white dwarf of O'Brien et al. 2024 with a
    fit, by table name."""
    out: dict[str, dict[StarKey, Measured]] = {name: {} for name in OBRIEN_COLUMNS}
    path = directory / obrien_white_dwarfs.TABLE_FILE
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            key = (*GAIA_DR3, row[obrien_white_dwarfs.ID_COLUMN])
            for name, (value, error) in OBRIEN_COLUMNS.items():
                if not row[value].strip():
                    continue
                if key in out[name]:
                    raise ValueError(f"{path}: {catalogue_id(key)} twice")
                found = row[error].strip()
                out[name][key] = Measured(
                    float(row[value]), float(found) if found else None, OBRIEN_2024
                )
    return out


def measured_tables(
    directory: Path = obrien_white_dwarfs.OUT_DIR,
) -> dict[str, dict[StarKey, Measured | Bounds]]:
    """MEASURED_TABLES over the white dwarfs of O'Brien et al. 2024."""
    sample = white_dwarfs(directory)
    return {
        name: {**sample[name], **values} for name, values in MEASURED_TABLES.items()
    }


def measured_reference(name: str, key: StarKey) -> str:
    """The work of a measured value of table `name` that the source gave the
    star of `key`: its own paper's, else the sample's, as `measured_tables`
    merges them. The export cites it from the ingested value, so it needs no
    download."""
    own = MEASURED_TABLES[name].get(key)
    return OBRIEN_2024 if own is None else own.reference


def _position(
    key: StarKey,
    hip_positions: dict[str, tuple[float, float]],
    hd_positions: dict[str, tuple[float, float]],
    simbad_positions: dict[str, tuple[float, float]],
) -> tuple[float, float]:
    """A position of the star, good to a region for the claim lookup."""
    catalogue, number = key[:2], key[2]
    if catalogue == GAIA_DR3:
        return gaia_position(number)
    positions = {HIP: hip_positions, HD: hd_positions, SIMBAD_OID: simbad_positions}
    positions = positions.get(catalogue)
    if positions is None:
        raise ValueError(
            f"literature: {catalogue_id(key)} is not a Gaia, HIP, HD or SIMBAD id"
        )
    if number not in positions:
        raise ValueError(f"literature: no star has {catalogue_id(key)}")
    return positions[number]


def engine_rows(
    hip_positions: dict[str, tuple[float, float]],
    hd_positions: dict[str, tuple[float, float]],
    simbad_positions: dict[str, tuple[float, float]],
    table: Mapping[StarKey, Distance] = DISTANCES,
    radii: Mapping[StarKey, Radius] = RADII,
    measured: Mapping[str, Mapping[StarKey, Measured | Bounds]] = MEASURED_TABLES,
) -> pa.Table:
    """A row for each star of the tables, with its distance, its radius and
    its measured values, which `measured` holds by table name. The positions
    are by HIP number, HD number and SIMBAD oid."""
    keys = list(
        dict.fromkeys([*table, *radii, *(k for m in measured.values() for k in m)])
    )
    none = Distance(float("nan"), float("nan"), float("nan"), None, "")
    given = [table.get(key, none) for key in keys]
    found = np.array(
        [_position(key, hip_positions, hd_positions, simbad_positions) for key in keys],
        np.float64,
    ).reshape(-1, 2)
    values = np.array([(d.value, d.lower, d.upper) for d in given], np.float64).reshape(
        -1, 3
    )
    percentiles = np.array(
        [(d.lower_percentile, d.upper_percentile) for d in given], np.float64
    ).reshape(-1, 2)
    rows = distances.rows(
        found[:, 0],
        found[:, 1],
        [*keys],
        values[:, 0],
        values[:, 1],
        values[:, 2],
        [d.method for d in given],
        catalogue_ids=[catalogue_id(key) for key in keys],
        lower_percentile=percentiles[:, 0],
        upper_percentile=percentiles[:, 1],
        distance_required=False,
    )
    radius = [radii[key].value if key in radii else None for key in keys]
    rows = rows.append_column("radius_literature", pa.array(radius, pa.float32()))
    for name, values in measured.items():
        found = [values.get(key) for key in keys]
        for column, part in _parts(name, found).items():
            rows = rows.append_column(
                f"{name}_literature{column}", pa.array(part, pa.float32())
            )
    return rows


def _bounds(entry: Measured | Bounds) -> tuple[float | None, float | None]:
    """The lower and upper bound of a value. A 1σ error gives the value ∓ the
    error."""
    if isinstance(entry, Bounds):
        return entry.lower, entry.upper
    if entry.error is None:
        return None, None
    return entry.value - entry.error, entry.value + entry.error


def _parts(
    name: str, found: list[Measured | Bounds | None]
) -> dict[str, list[float | None]]:
    """The columns of one table, by suffix. A BOUNDED table has a lower and an
    upper bound, the others a 1σ error."""
    parts: dict[str, list[float | None]] = {
        "": [None if v is None else v.value for v in found]
    }
    if name not in BOUNDED:
        parts["_error"] = [v.error if isinstance(v, Measured) else None for v in found]
        return parts
    spread = [(None, None) if v is None else _bounds(v) for v in found]
    parts["_lower"] = [low for low, _ in spread]
    parts["_upper"] = [high for _, high in spread]
    return parts
