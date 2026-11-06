"""Where a Point source row renders: the one rule for the export and the
ingest report.

A row takes its distance from the first of these that it has:
1. a distance from a paper, the `literature` source of the distance group;
2. the distance of its star system, the `star-systems` source of that group
   (`systems.distance`): two stars of a system differ by more in parallax
   noise than the system is wide, so the system outranks the star's own
   parallax, but not a paper;
3. a 5σ parallax, unless the row is flagged, or its distance group is a
   measured parallax that is more precise;
4. the distance group;
5. for a planet host, the distance of its exoplanet catalogue;
6. a 5σ parallax of a flagged row.
A row is flagged when its astrometry comes from Gaia and its `fidelity_v2` is
under 0.5. A Hipparcos or SIMBAD parallax has no fidelity. A flagged row
renders only when Hipparcos, SIMBAD or an exoplanet catalogue saw it, or by
step 1. Its parallax is suspect, so it comes last, also when Hipparcos or
SIMBAD saw the row. Other rows have no place.

`star_distance` turns a placement into parsecs, and `distance_error` gives
the error of that distance. A 5σ orbit parallax stands for the parallax of
steps 3 and 6, and for the catalogue distance of step 5.
"""

from typing import NamedTuple

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from space_map_data.extrasolar.sources.distances import SIMBAD_PARALLAX
from space_map_data.extrasolar.sources.gaia import (
    GAIA_DR3,
    GAIA_DR3_NAMED,
    MIN_FIDELITY,
)
from space_map_data.extrasolar.sources.gaia_orbits import ASTROMETRIC
from space_map_data.extrasolar.sources.literature import LITERATURE
from space_map_data.extrasolar.tables import STAR_SYSTEMS
from space_map_data.utils.arrays import find_sorted

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
# The Point source columns that `distance_error` reads besides COLUMNS.
ERROR_COLUMNS = ("host_distance_error",)
# The binary orbit columns of the orbit parallax.
ORBIT_PARALLAX_COLUMNS = (
    "id",
    "nss_solution_type",
    "parallax_nss",
    "parallax_nss_error",
)
# The parallax of an astrometric orbit solution, null for any other star.
ORBIT_PARALLAX = ("orbit_parallax", "orbit_parallax_error")


class Placement(NamedTuple):
    """Boolean arrays over the rows of a table."""

    # A parallax above 5σ, trusted or not.
    positioned: np.ndarray
    # Gaia astrometry with a fidelity under 0.5.
    flagged: np.ndarray
    # Not flagged, or seen by Hipparcos, SIMBAD or an exoplanet catalogue.
    seen: np.ndarray
    # Step 3.
    by_parallax: np.ndarray
    # Steps 1, 2 and 4.
    by_group: np.ndarray
    # Step 5.
    by_catalogue: np.ndarray
    # Step 6.
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
    chosen = np.isin(sources, (LITERATURE.name, STAR_SYSTEMS)) & group
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


def with_orbit_parallax(table: pa.Table, orbits: pa.Table | None) -> pa.Table:
    """Point source rows with ORBIT_PARALLAX from the table-2 rows `orbits`."""
    ids = table["id"].to_numpy()
    at = np.full(ids.size, -1, np.int64)
    if orbits is not None and orbits.num_rows:
        astrometric = pc.is_in(
            orbits["nss_solution_type"], value_set=pa.array(sorted(ASTROMETRIC))
        )
        orbits = orbits.filter(astrometric)
        order = np.argsort(orbits["id"].to_numpy())
        orbits = orbits.take(pa.array(order))
        at = find_sorted(orbits["id"].to_numpy(), ids)
    index = pa.array(at, mask=at < 0)
    for name, source in zip(ORBIT_PARALLAX, ORBIT_PARALLAX_COLUMNS[2:]):
        values = (
            pa.nulls(ids.size, pa.float32())
            if orbits is None or not orbits.num_rows
            else orbits[source].take(index)
        )
        table = table.append_column(name, values)
    return table


def distance_parallax(table: pa.Table) -> tuple[np.ndarray, np.ndarray]:
    """The parallax (mas) that gives each star its distance, and whether it is
    the orbit solution's. An orbit parallax under 5 times its error gives none."""
    orbit = _floats(table, "orbit_parallax")
    used = orbit / _floats(table, "orbit_parallax_error") > MIN_PARALLAX_SNR
    return np.where(used, orbit, _floats(table, "parallax")), used


def _from_parallax(where: Placement, orbit: np.ndarray) -> np.ndarray:
    return where.by_parallax | where.by_suspect | (where.by_catalogue & orbit)


def star_distance(table: pa.Table, where: Placement) -> tuple[np.ndarray, np.ndarray]:
    """The distance (pc) of each row that `where` places, NaN for the others,
    and whether an orbit parallax gives it."""
    parallax, orbit = distance_parallax(table)
    from_parallax = _from_parallax(where, orbit)
    with np.errstate(divide="ignore", invalid="ignore"):
        distance = np.select(
            [from_parallax, where.by_group, where.by_catalogue],
            [
                1000.0 / parallax,
                _floats(table, "distance"),
                _floats(table, "host_distance"),
            ],
            np.nan,
        )
    return distance, orbit & from_parallax


def distance_error(table: pa.Table, where: Placement) -> np.ndarray:
    """The relative error of the distance that `star_distance` gives each row,
    NaN where it is unknown. A distance group's error is half its bounds."""
    parallax, orbit = distance_parallax(table)
    parallax_error = np.where(
        orbit, _floats(table, "orbit_parallax_error"), _floats(table, "parallax_error")
    )
    spread = _floats(table, "distance_upper") - _floats(table, "distance_lower")
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.select(
            [_from_parallax(where, orbit), where.by_group, where.by_catalogue],
            [
                parallax_error / parallax,
                spread / (2 * _floats(table, "distance")),
                _floats(table, "host_distance_error") / _floats(table, "host_distance"),
            ],
            np.nan,
        )
