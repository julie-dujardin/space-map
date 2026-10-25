"""The IAU working definition of an exoplanet, as a class of each object.

The definition of IAU Commission F2 (2003, amended in 2018; text on
https://www.iau.org/CommissionF2/CommissionF2/Documents.aspx, history in
Lecavelier des Etangs & Lissauer 2022, New Astron. Rev. 94, 101641):

1. Objects with true masses below the limiting mass for thermonuclear fusion
   of deuterium (currently 13 Jupiter masses at solar metallicity) that orbit
   stars, brown dwarfs or stellar remnants and that have a mass ratio with the
   central object below the L4/L5 instability (M/Mcentral < 2/(25+√621) ≈
   1/25) are "planets", no matter how they formed.
2. Substellar objects with true masses above that limit are "brown dwarfs".
3. Free-floating objects below that limit are "sub-brown dwarfs".

An object below 13 MJ with a mass ratio at or above the L4/L5 limit is not a
planet. The review calls each such pair a binary of a sub-brown dwarf and a
slightly more massive object, so its class here is sub-brown dwarf.

The mass is the true mass when one exists, else the minimum mass (m sin i),
else a catalogue's estimate. The basis column says which one the class used.
A minimum mass under 13 MJ can hide a brown dwarf, so the basis matters.
"""

import math

PLANET = "planet"
BROWN_DWARF = "brown dwarf"
SUB_BROWN_DWARF = "sub-brown dwarf"

# MJ: the deuterium-burning limit at solar metallicity.
DEUTERIUM_LIMIT = 13.0
# The L4/L5 stability limit of the mass ratio, 2 / (25 + √621).
MASS_RATIO_LIMIT = 2 / (25 + math.sqrt(621))
# MJ: the objects kept under /x/<host>/b/<n>.
MAX_MASS = 60.0
# Jupiter's mass in solar masses (IAU 2015 nominal GM values).
JUPITER_IN_SUNS = 1.266_865_3e17 / 1.327_124_4e20

TRUE, MINIMUM, ESTIMATED, NONE = (
    "true mass",
    "minimum mass",
    "estimated mass",
    "no mass",
)
BASIS = {"true": TRUE, "minimum": MINIMUM, "estimate": ESTIMATED}


def mass_ratio(mass: float | None, central: float | None) -> float | None:
    """The mass ratio of an object of `mass` MJ to `central` solar masses."""
    if mass is None or central is None or central <= 0:
        return None
    return mass * JUPITER_IN_SUNS / central


def classify(
    mass: float | None, kind: str | None, central: float | None
) -> tuple[str, str, float | None]:
    """The class, the basis of the class, and the mass ratio.

    `mass` is in MJ, `kind` is "true", "minimum" or "estimate", `central` is
    the mass of the central object in solar masses. With no mass the object
    stays a planet, as its catalogues call it.
    """
    if mass is None:
        return PLANET, NONE, None
    basis = BASIS.get(kind or "", ESTIMATED)
    ratio = mass_ratio(mass, central)
    if mass >= DEUTERIUM_LIMIT:
        return BROWN_DWARF, basis, ratio
    if ratio is not None and ratio >= MASS_RATIO_LIMIT:
        return SUB_BROWN_DWARF, basis, ratio
    return PLANET, basis, ratio
