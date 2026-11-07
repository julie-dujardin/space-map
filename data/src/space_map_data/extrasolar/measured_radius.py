"""A star's radius where a paper or a measured angular diameter gives it.

A star's radius (`export.extrasolar.radius`) takes it first, and the interior
fit takes a luminosity from it. The frontend's `measuredRadiusSolar` follows
the same rule.
"""

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from space_map_data.constants.planets.families import SOLAR_RADIUS_KM
from space_map_data.extrasolar.sources.jmdc import JMDC
from space_map_data.extrasolar.sources.literature import LITERATURE
from space_map_data.extrasolar.tables import STAR_SYSTEMS
from space_map_data.utils.arrays import floats

# A diameter becomes a radius by a paper's or its system's distance, else by a
# parallax of this many sigma: the distance of a saturated supergiant from a
# prior can be off tenfold.
MIN_PARALLAX_SIGMA = 5
MAS_TO_RAD = np.pi / 180 / 3.6e6
KM_PER_PC = 3.0856775814914e13
# The sources of a measured radius, in their order.
MEASURED_SOURCES = (LITERATURE.name, JMDC.name)

# What `measured_radius` reads.
MEASURED_COLUMNS = (
    "radius_literature",
    "angular_diameter",
    "parallax",
    "parallax_error",
    "distance",
    "distance_source",
)


def measured_radius(rows: pa.Table) -> tuple[np.ndarray, np.ndarray]:
    """The radius of each of `rows` in nominal solar radii, NaN where none,
    and its source, None where none: a paper's, then JMDC's angular diameter
    at the star's distance."""
    paper = floats(rows, "radius_literature")
    parallax, error = floats(rows, "parallax"), floats(rows, "parallax_error")
    by_parallax = np.where(
        (error > 0) & (parallax >= MIN_PARALLAX_SIGMA * error),
        1000 / np.where(parallax > 0, parallax, 1.0),
        np.nan,
    )
    chosen = pc.is_in(
        rows["distance_source"], value_set=pa.array([LITERATURE.name, STAR_SYSTEMS])
    ).fill_null(False)
    distance = np.where(
        chosen.to_numpy(zero_copy_only=False), floats(rows, "distance"), by_parallax
    )
    diameter = floats(rows, "angular_diameter") * MAS_TO_RAD / 2 * distance
    diameter *= KM_PER_PC / SOLAR_RADIUS_KM
    radius = np.full(rows.num_rows, np.nan)
    source = np.full(rows.num_rows, None, object)
    for values, name in zip((paper, diameter), MEASURED_SOURCES, strict=True):
        take = np.isnan(radius) & np.isfinite(values) & (values > 0)
        radius[take] = values[take]
        source[take] = name
    return radius, source
