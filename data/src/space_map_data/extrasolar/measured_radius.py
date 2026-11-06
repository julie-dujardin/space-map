"""A star's radius where a paper or a measured angular diameter gives it.

The star lineup, the star families and the interior fit read it. It is the
`measuredRadiusSolar` of the frontend, which the star page shows.
"""

import numpy as np

from space_map_data.constants.planets.families import SOLAR_RADIUS_KM
from space_map_data.extrasolar.sources.literature import LITERATURE
from space_map_data.extrasolar.tables import STAR_SYSTEMS

# A diameter becomes a radius by a paper's distance or a parallax of this many
# sigma: the distance of a saturated supergiant from a prior can be off tenfold.
MIN_PARALLAX_SIGMA = 5
MAS_TO_RAD = np.pi / 180 / 3.6e6
KM_PER_PC = 3.0856775814914e13

# What `measured_radius` reads.
MEASURED_COLUMNS = [
    "radius_literature",
    "angular_diameter",
    "parallax",
    "parallax_error",
    "distance",
    "distance_source",
]


def _distance_pc(row: dict) -> float | None:
    if row["distance_source"] in (LITERATURE.name, STAR_SYSTEMS):
        return row["distance"]
    parallax, error = row["parallax"], row["parallax_error"]
    if parallax and error and parallax >= MIN_PARALLAX_SIGMA * error:
        return 1000 / parallax
    return None


def measured_radius(row: dict) -> tuple[float, str] | None:
    """A star's radius in solar radii where a paper or a measured diameter
    gives it, and which of `literature` and `interferometry` did."""
    if row["radius_literature"]:
        return row["radius_literature"], "literature"
    distance = _distance_pc(row)
    if row["angular_diameter"] and distance:
        radius_km = row["angular_diameter"] * MAS_TO_RAD / 2 * distance * KM_PER_PC
        return radius_km / SOLAR_RADIUS_KM, "interferometry"
    return None
