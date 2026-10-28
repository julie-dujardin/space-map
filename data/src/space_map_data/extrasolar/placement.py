"""Where a Point source row renders: the one rule for the export and the
ingest report.

A row takes its distance from the first of these that it has:
1. a distance from a paper, the `literature` source of the distance group;
2. a 5σ parallax, unless the row is flagged, or its distance group is a
   measured parallax that is more precise;
3. the distance group;
4. for a planet host, the distance of its exoplanet catalogue;
5. a 5σ parallax of a flagged row.
The distance of a star's system is the last source of the distance group.
The ingest gives it only to a star of a system that no step places and that
step 3 then places, so for that star it is the last step.
A row is flagged when its astrometry comes from Gaia and its `fidelity_v2` is
under 0.5. A Hipparcos or SIMBAD parallax has no fidelity. A flagged row
renders only when Hipparcos, SIMBAD or an exoplanet catalogue saw it, or by
step 1. Its parallax is suspect, so it comes last, also when Hipparcos or
SIMBAD saw the row. Other rows have no place.
"""

from typing import NamedTuple

import numpy as np
import pyarrow as pa

from space_map_data.extrasolar.sources.distances import SIMBAD_PARALLAX
from space_map_data.extrasolar.sources.gaia import (
    GAIA_DR3,
    GAIA_DR3_NAMED,
    MIN_FIDELITY,
)
from space_map_data.extrasolar.sources.literature import LITERATURE

MIN_PARALLAX_SNR = 5.0
# The `distance_method` of a distance that a measured parallax gives.
MEASURED_PARALLAX = "parallax"
# How many times more precise than a Gaia parallax a group must be to win.
GAIA_MARGIN = 2.0
# The astrometry sources that the fidelity rates.
GAIA_ASTROMETRY = (GAIA_DR3.name, GAIA_DR3_NAMED.name)
# The Point source columns that `placement` reads.
COLUMNS = (
    "parallax",
    "parallax_error",
    "fidelity_v2",
    "astrometry_source",
    "hipparcos_photometry_source",
    "simbad_photometry_source",
    "host_star_source",
    "distance",
    "distance_lower",
    "distance_upper",
    "distance_source",
    "distance_method",
    "host_distance",
)


class Placement(NamedTuple):
    """Boolean arrays over the rows of a table."""

    # A parallax above 5σ, trusted or not.
    positioned: np.ndarray
    # Gaia astrometry with a fidelity under 0.5.
    flagged: np.ndarray
    # Not flagged, or seen by Hipparcos, SIMBAD or an exoplanet catalogue.
    seen: np.ndarray
    # Step 2.
    by_parallax: np.ndarray
    # Steps 1 and 3.
    by_group: np.ndarray
    # Step 4.
    by_catalogue: np.ndarray
    # Step 5.
    by_suspect: np.ndarray

    @property
    def placed(self) -> np.ndarray:
        return self.by_parallax | self.by_group | self.by_catalogue | self.by_suspect


def _floats(table: pa.Table, name: str) -> np.ndarray:
    return table[name].to_numpy().astype(np.float64)


def _valid(table: pa.Table, name: str) -> np.ndarray:
    return table[name].is_valid().to_numpy(zero_copy_only=False)


def placement(table: pa.Table) -> Placement:
    """Where the rows of `table` render."""
    snr = _floats(table, "parallax") / _floats(table, "parallax_error")
    positioned = snr > MIN_PARALLAX_SNR
    astrometry = table["astrometry_source"].to_numpy(zero_copy_only=False)
    flagged = np.isin(astrometry, GAIA_ASTROMETRY) & (
        _floats(table, "fidelity_v2") < MIN_FIDELITY
    )
    seen = (
        ~flagged
        | _valid(table, "hipparcos_photometry_source")
        | _valid(table, "simbad_photometry_source")
        | _valid(table, "host_star_source")
    )
    group = _floats(table, "distance") > 0
    sources = table["distance_source"].to_numpy(zero_copy_only=False)
    chosen = (sources == LITERATURE.name) & group
    # A more precise measured parallax of the same star wins (α Cen B:
    # Hipparcos 2007 ±3%, the 10 pc sample ±0.2%). The distance catalogues
    # copy Gaia's parallax with its error rounded down, so against Gaia
    # astrometry the group must be twice as precise. SIMBAD's parallax on a
    # row with its own is Gaia DR2's, with errors too small. A distance from a
    # prior or from a group of stars stays below the star's own parallax.
    # Point source's single-star values decide, as for the 5σ test.
    methods = table["distance_method"].to_numpy(zero_copy_only=False)
    distance = _floats(table, "distance")
    spread = _floats(table, "distance_upper") - _floats(table, "distance_lower")
    margin = np.where(np.isin(astrometry, GAIA_ASTROMETRY), GAIA_MARGIN, 1.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        better = (
            group
            & (methods == MEASURED_PARALLAX)
            & (sources != SIMBAD_PARALLAX.name)
            & (margin * spread / (2 * distance) < 1 / snr)
        )
    by_parallax = positioned & ~flagged & ~chosen & ~better
    by_group = (seen | chosen) & ~by_parallax & group
    by_catalogue = ~by_parallax & ~by_group & (_floats(table, "host_distance") > 0)
    by_suspect = seen & flagged & positioned & ~by_group & ~by_catalogue
    return Placement(
        positioned, flagged, seen, by_parallax, by_group, by_catalogue, by_suspect
    )
