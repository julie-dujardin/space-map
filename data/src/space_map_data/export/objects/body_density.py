"""The mean density of a body, from the mass and the radius that it shows.

The density is the `body_mass` pick over the volume of the ellipsoid that the
sidebar shows (`BodyRadius` a, b, c). A system mass is over the volume of the
body and its satellites together. So mass, size and density never contradict
each other. The density is nominal when the mass or a size is nominal, or when
a satellite of a system mass has no size or is not in the export. There is no
range check.
"""

import math
from collections.abc import Sequence
from typing import NamedTuple

from space_map_data.export.objects.body_mass import BodyMass, BodyMasses
from space_map_data.export.objects.body_radius import BodyRadii, BodyRadius
from space_map_data.models.object import Object

# A mean density keeps the digits that the mass and the radius support at best.
_DENSITY_DIGITS = 4


class BodyDensity(NamedTuple):
    g_cm3: float
    nominal: bool


def _volume_cm3(size: BodyRadius) -> float:
    return 4 / 3 * math.pi * size.a * size.b * size.c * 1e15


def mean_density(
    mass: BodyMass | None,
    size: BodyRadius | None,
    satellites: Sequence[BodyRadius | None] = (),
) -> BodyDensity | None:
    """The mean density (g/cm³) of a body of this mass and size, or None.

    ``satellites`` are the sizes of the satellites that share a system mass.
    """
    if mass is None or size is None:
        return None
    volume_cm3 = _volume_cm3(size)
    if volume_cm3 <= 0:
        return None
    nominal = mass.nominal or size.nominal
    for satellite in satellites:
        if satellite is None:
            nominal = True
        else:
            volume_cm3 += _volume_cm3(satellite)
            nominal = nominal or satellite.nominal
    density = mass.kg * 1e3 / volume_cm3
    return BodyDensity(float(f"{density:.{_DENSITY_DIGITS}g}"), nominal)


def density_of(
    obj: Object,
    mass: BodyMass | None,
    size: BodyRadius | None,
    masses: BodyMasses,
    radii: BodyRadii,
) -> BodyDensity | None:
    """The density of ``obj`` from its mass and size picks."""
    satellites: list[BodyRadius | None] = []
    if mass is not None and mass.system:
        # A system with no moon in the export has a moon of unknown size.
        satellites = [radii.pick(*moon) for moon in masses.satellites(obj.id)] or [None]
    return mean_density(mass, size, satellites)


def bundle_fields(density: BodyDensity | None) -> dict:
    """The object bundle's density fields."""
    if density is None:
        return {}
    out: dict = {"mean_density_g_cm3": density.g_cm3}
    if density.nominal:
        out["mean_density_nominal"] = True
    return out
