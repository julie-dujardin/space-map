"""The star values of the literature table as an ingest source.

A row of the source holds the values of one star of the table
(`constants/stars/literature.py`). It claims the star by the key of its
entry, never mints and never matches by position. Its own id is that key, so
the star has a `literature` cross-id, and the export knows from it which works
to cite in the star's object entry. Its pass comes after the distance passes,
so that no later pass can match a row that reaches no star by position.
"""

from collections.abc import Mapping

import numpy as np
import pyarrow as pa

from space_map_data.constants.stars.literature import DISTANCES, Distance, StarKey
from space_map_data.extrasolar.engine import Source
from space_map_data.extrasolar.sources import distances
from space_map_data.extrasolar.sources.hipparcos import GAIA_DR3, HD
from space_map_data.extrasolar.sources.names import HIP
from space_map_data.extrasolar.sources.wikidata import gaia_position

LITERATURE = Source(name="literature", catalogue="literature", release="star", home=1)


def catalogue_id(key: StarKey) -> str:
    """The id of the row of a star: its key as `catalogue/release/id`."""
    return "/".join(key)


def key_of(literature_id: str) -> StarKey:
    """The key of the star of a `literature` cross-id."""
    catalogue, release, number = literature_id.split("/", 2)
    return catalogue, release, number


def _position(
    key: StarKey,
    hip_positions: dict[str, tuple[float, float]],
    hd_positions: dict[str, tuple[float, float]],
) -> tuple[float, float]:
    """A position of the star, good to a region for the claim lookup."""
    catalogue, number = key[:2], key[2]
    if catalogue == GAIA_DR3:
        return gaia_position(number)
    positions = {HIP: hip_positions, HD: hd_positions}.get(catalogue)
    if positions is None:
        raise ValueError(f"literature: {catalogue_id(key)} is not a Gaia, HIP or HD id")
    if number not in positions:
        raise ValueError(f"literature: no star has {catalogue_id(key)}")
    return positions[number]


def engine_rows(
    hip_positions: dict[str, tuple[float, float]],
    hd_positions: dict[str, tuple[float, float]],
    table: Mapping[StarKey, Distance] = DISTANCES,
) -> pa.Table:
    """A row for each star of the table, with its distance."""
    keys = list(table)
    found = np.array(
        [_position(key, hip_positions, hd_positions) for key in keys], np.float64
    ).reshape(-1, 2)
    values = np.array(
        [(d.value, d.lower, d.upper) for d in table.values()], np.float64
    ).reshape(-1, 3)
    percentiles = np.array(
        [(d.lower_percentile, d.upper_percentile) for d in table.values()], np.float64
    ).reshape(-1, 2)
    return distances.rows(
        found[:, 0],
        found[:, 1],
        [*keys],
        values[:, 0],
        values[:, 1],
        values[:, 2],
        [d.method for d in table.values()],
        catalogue_ids=[catalogue_id(key) for key in keys],
        lower_percentile=percentiles[:, 0],
        upper_percentile=percentiles[:, 1],
    )
