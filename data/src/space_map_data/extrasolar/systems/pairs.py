"""The pair sources: El-Badry, Rix & Heintz 2021 and the Gaia DR3 orbits.

Each row of a pair source is one pair of two Gaia DR3 stars, so its normal
form is one table of pairs (PAIRS), not of nodes. A pair of El-Badry is two
Gaia sources, so two points. A Gaia orbit is one source, so one point that
holds both stars, and its companion has no id.

`key1` and `key2` hold the objects of the stars when the caller knows them
(a Gaia orbit row of table 2 has the ID of its star). Else they are 0, and
the builder resolves `gaia1` and `gaia2`.
"""

import logging
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from space_map_data.download.providers.stars import el_badry
from space_map_data.extrasolar.sources.gaia_orbits import (
    ASTROMETRIC,
    ECLIPSING,
)
from space_map_data.extrasolar.systems.nodes import (
    ASTROMETRIC_ORBIT,
    EL_BADRY,
    GAIA_ORBITS,
    PARALLAX,
    PROPER_MOTION,
    SPECTROSCOPIC_ORBIT,
)
from space_map_data.extrasolar.systems.nodes import ECLIPSING as ECLIPSING_KNOWN

logger = logging.getLogger(__name__)

PAIRS = pa.schema(
    [
        ("source", pa.string()),
        # The source's key of the pair.
        ("system", pa.string()),
        ("gaia1", pa.int64()),
        ("gaia2", pa.int64()),
        ("key1", pa.int64()),
        ("key2", pa.int64()),
        # Both stars are in one point.
        ("point", pa.bool_()),
        # J2016.0 ICRS in degrees, mas, G mag.
        ("ra1", pa.float64()),
        ("dec1", pa.float64()),
        ("ra2", pa.float64()),
        ("dec2", pa.float64()),
        ("parallax1", pa.float32()),
        ("parallax2", pa.float32()),
        ("g_mag1", pa.float32()),
        ("g_mag2", pa.float32()),
        # Solar masses.
        ("mass1", pa.float32()),
        ("mass2", pa.float32()),
        # Arcsec and d.
        ("separation", pa.float64()),
        ("period", pa.float64()),
        ("eccentricity", pa.float32()),
        # El-Badry's probability of a chance alignment.
        ("chance", pa.float32()),
        # The Gaia solution type, or El-Badry's binary type.
        ("kind", pa.string()),
        ("known", pa.string()),
    ]
)

# A pair with this R or more is left out as a possible chance alignment.
MAX_CHANCE = 0.1
EL_BADRY_COLUMNS = [
    "source_id1",
    "source_id2",
    "ra1",
    "dec1",
    "ra2",
    "dec2",
    "parallax1",
    "parallax2",
    "phot_g_mean_mag1",
    "phot_g_mean_mag2",
    "sep_arcsec",
    "R_chance_align",
    "binary_type",
]
# The Gaia orbit columns that the builder reads.
ORBIT_COLUMNS = ("nss_solution_type", "period", "eccentricity", "m1", "m2")


def _column(table: pa.Table, name: str, kind: pa.DataType) -> pa.Array:
    return table[name].combine_chunks().cast(kind)


def _nulls(n: int, kind: pa.DataType) -> pa.Array:
    return pa.nulls(n, kind)


def read_el_badry(
    path: Path = el_badry.OUT_DIR / el_badry.PAIRS_FILE,
    max_chance: float = MAX_CHANCE,
) -> pa.Table:
    """The pairs of El-Badry et al. with R under `max_chance`."""
    raw = el_badry.read_pairs(path, columns=EL_BADRY_COLUMNS)
    chance = raw["R_chance_align"].to_numpy()
    keep = chance < max_chance
    logger.info(
        "El-Badry: %d pairs, %d with R < %s, %d left out",
        raw.num_rows,
        int(keep.sum()),
        max_chance,
        int((~keep).sum()),
    )
    raw = raw.filter(pa.array(keep))
    return el_badry_pairs(raw)


def el_badry_pairs(raw: pa.Table) -> pa.Table:
    """PAIRS from rows with the columns of EL_BADRY_COLUMNS."""
    n = raw.num_rows
    gaia1 = _column(raw, "source_id1", pa.int64())
    gaia2 = _column(raw, "source_id2", pa.int64())
    system = pc.binary_join_element_wise(
        gaia1.cast(pa.string()), gaia2.cast(pa.string()), "+"
    )
    return pa.table(
        {
            "source": pa.array(np.full(n, EL_BADRY, object), pa.string()),
            "system": system,
            "gaia1": gaia1,
            "gaia2": gaia2,
            "key1": pa.array(np.zeros(n, np.int64)),
            "key2": pa.array(np.zeros(n, np.int64)),
            "point": pa.array(np.zeros(n, bool)),
            "ra1": _column(raw, "ra1", pa.float64()),
            "dec1": _column(raw, "dec1", pa.float64()),
            "ra2": _column(raw, "ra2", pa.float64()),
            "dec2": _column(raw, "dec2", pa.float64()),
            "parallax1": _column(raw, "parallax1", pa.float32()),
            "parallax2": _column(raw, "parallax2", pa.float32()),
            "g_mag1": _column(raw, "phot_g_mean_mag1", pa.float32()),
            "g_mag2": _column(raw, "phot_g_mean_mag2", pa.float32()),
            "mass1": _nulls(n, pa.float32()),
            "mass2": _nulls(n, pa.float32()),
            "separation": _column(raw, "sep_arcsec", pa.float64()),
            "period": _nulls(n, pa.float64()),
            "eccentricity": _nulls(n, pa.float32()),
            "chance": _column(raw, "R_chance_align", pa.float32()),
            "kind": _column(raw, "binary_type", pa.string()),
            "known": pa.array(
                np.full(n, f"{PROPER_MOTION}, {PARALLAX}", object), pa.string()
            ),
        },
        schema=PAIRS,
    )


def _family_known(types: pa.Array) -> pa.Array:
    known = np.full(len(types), SPECTROSCOPIC_ORBIT, object)
    values = np.array(types.to_pylist(), object)
    known[np.isin(values, sorted(ASTROMETRIC))] = ASTROMETRIC_ORBIT
    known[np.isin(values, sorted(ECLIPSING))] = ECLIPSING_KNOWN
    return pa.array(known, pa.string())


def orbit_pairs(rows: pa.Table) -> pa.Table:
    """PAIRS from Gaia orbit rows: `source_id` or `key`, and ORBIT_COLUMNS.

    The rows of gaia_orbits.Orbits have `source_id`; the rows of table 2
    have the ID of the star as `key`.
    """
    n = rows.num_rows
    names = rows.schema.names
    gaia = (
        _column(rows, "source_id", pa.int64())
        if "source_id" in names
        else _nulls(n, pa.int64())
    )
    key = (
        _column(rows, "key", pa.int64())
        if "key" in names
        else pa.array(np.zeros(n, np.int64))
    )
    system = pc.if_else(gaia.is_valid(), gaia.cast(pa.string()), key.cast(pa.string()))
    types = _column(rows, "nss_solution_type", pa.string())
    return pa.table(
        {
            "source": pa.array(np.full(n, GAIA_ORBITS, object), pa.string()),
            "system": system,
            "gaia1": gaia,
            "gaia2": _nulls(n, pa.int64()),
            "key1": key,
            "key2": pa.array(np.zeros(n, np.int64)),
            "point": pa.array(np.ones(n, bool)),
            "ra1": _nulls(n, pa.float64()),
            "dec1": _nulls(n, pa.float64()),
            "ra2": _nulls(n, pa.float64()),
            "dec2": _nulls(n, pa.float64()),
            "parallax1": _nulls(n, pa.float32()),
            "parallax2": _nulls(n, pa.float32()),
            "g_mag1": _nulls(n, pa.float32()),
            "g_mag2": _nulls(n, pa.float32()),
            "mass1": _column(rows, "m1", pa.float32()),
            "mass2": _column(rows, "m2", pa.float32()),
            "separation": _nulls(n, pa.float64()),
            "period": _column(rows, "period", pa.float64()),
            "eccentricity": _column(rows, "eccentricity", pa.float32()),
            "chance": _nulls(n, pa.float32()),
            "kind": types,
            "known": _family_known(types),
        },
        schema=PAIRS,
    )
