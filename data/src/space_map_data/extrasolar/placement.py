"""Where a Point source row renders: the one rule for the export and the
ingest report.

A row renders at its parallax when the parallax is above 5σ and the row is
trusted: its `fidelity_v2` is not under 0.5, or it has a Hipparcos match,
which a spurious Gaia source does not have. A planet host that the parallax
does not place renders at the distance of its exoplanet catalogue. Other
rows have no place.
"""

from typing import NamedTuple

import numpy as np
import pyarrow as pa

from space_map_data.extrasolar.sources.gaia import MIN_FIDELITY

MIN_PARALLAX_SNR = 5.0
# The Point source columns that `placement` reads.
COLUMNS = (
    "parallax",
    "parallax_error",
    "fidelity_v2",
    "hipparcos_photometry_source",
    "host_distance",
)


class Placement(NamedTuple):
    """Boolean arrays over the rows of a table."""

    # A parallax above 5σ, trusted or not.
    positioned: np.ndarray
    # Placed by the parallax.
    by_parallax: np.ndarray
    # A planet host placed at the distance of its exoplanet catalogue.
    by_catalogue: np.ndarray


def _floats(table: pa.Table, name: str) -> np.ndarray:
    return table[name].to_numpy().astype(np.float64)


def placement(table: pa.Table) -> Placement:
    """Where the rows of `table` render."""
    snr = _floats(table, "parallax") / _floats(table, "parallax_error")
    positioned = snr > MIN_PARALLAX_SNR
    fidelity = _floats(table, "fidelity_v2")
    hipparcos = (
        table["hipparcos_photometry_source"].is_valid().to_numpy(zero_copy_only=False)
    )
    trusted = ~(fidelity < MIN_FIDELITY) | hipparcos
    by_parallax = positioned & trusted
    by_catalogue = ~by_parallax & (_floats(table, "host_distance") > 0)
    return Placement(positioned, by_parallax, by_catalogue)
