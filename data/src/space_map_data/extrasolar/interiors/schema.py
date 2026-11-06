"""The Interior table's slug, columns and distribution tier.

The tile writers import this module and not `table`, which reads the grid
and the inputs.
"""

import pyarrow as pa

from space_map_data.constants.manifests.catalogues import load_catalogues
from space_map_data.extrasolar.tables import TableDef

SLUG = "interior"
# The manifest group of the stellar models, and the grid in it.
GROUP = "stellar-models"
(MIST,) = load_catalogues(GROUP)
# The tier that the grid's terms allow.
DISTRIBUTION = MIST.distribution


def _floats(*names: str) -> tuple[pa.Field, ...]:
    return tuple(pa.field(name, pa.float32()) for name in names)


def _range(name: str) -> tuple[pa.Field, ...]:
    return _floats(f"{name}_lower", f"{name}_upper")


def _valued(name: str) -> tuple[pa.Field, ...]:
    return _floats(name) + _range(name)


# Masses in solar masses, the radius in solar radii, the envelope base as
# fractions of the star's radius and mass, the Teff and the centre
# temperature in K, the centre density in g/cm³, the centre abundances as mass
# fractions. `feh` is the [Fe/H] that the fit used. `teff_source` and
# `luminosity_source` name the source of its Teff and L.
INTERIOR = TableDef(
    number=None,
    slug=SLUG,
    groups=(),
    computed=(
        pa.field("tier", pa.int8()),
        pa.field("curated", pa.string()),
        pa.field("stage", pa.string()),
        pa.field("feh", pa.float32()),
        pa.field("feh_source", pa.string()),
        pa.field("teff", pa.float32()),
        pa.field("teff_source", pa.string()),
        pa.field("luminosity_source", pa.string()),
        *_valued("mass"),
        *_valued("radius"),
        *_valued("envelope_base_radius"),
        *_valued("envelope_base_mass"),
        *_range("convective_core_mass"),
        *_range("helium_core_mass"),
        *_valued("centre_temperature"),
        *_valued("centre_density"),
        *_range("centre_x"),
        *_range("centre_y"),
    ),
)
