"""The mean density of a body, from the mass and the radius that it shows.

The density is the `body_mass` pick over the volume of the ellipsoid that the
sidebar shows (`BodyRadius` a, b, c), or over the volume of a paper's shape
model where it has one (Phobos, Itokawa). A system
mass is over the volume of the body and its satellites together. The density
is nominal when the mass is, when a size with no shape-model volume is, or
when a satellite of a system mass has no size or is not in the export. There
is no range check.
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
    # The papers ({title, url}) of the shape-model volumes it is over.
    volume_references: tuple[dict, ...] = ()


def _volume_cm3(size: BodyRadius) -> float:
    if size.volume_km3 is not None:
        return size.volume_km3 * 1e15
    return 4 / 3 * math.pi * size.a * size.b * size.c * 1e15


def _nominal(size: BodyRadius) -> bool:
    return size.nominal and size.volume_km3 is None


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
    nominal = mass.nominal or _nominal(size)
    references = [size.volume_reference]
    for satellite in satellites:
        if satellite is None:
            nominal = True
        else:
            volume_cm3 += _volume_cm3(satellite)
            nominal = nominal or _nominal(satellite)
            references.append(satellite.volume_reference)
    density = mass.kg * 1e3 / volume_cm3
    # A paper of two moons' volumes is cited once.
    cited = {r["url"]: r for r in references if r is not None}
    return BodyDensity(
        float(f"{density:.{_DENSITY_DIGITS}g}"), nominal, tuple(cited.values())
    )


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
    if density.volume_references:
        out["mean_density_volume_references"] = list(density.volume_references)
    return out
