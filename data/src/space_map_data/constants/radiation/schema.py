"""Types for how much ionizing radiation a place delivers, and where it comes from.

Dose is the one property of a destination that nothing about it looks like.
Two airless grey moons a light-hour apart differ by six orders of magnitude,
and the difference is entirely in whether a planet nearby is holding charged
particles in place. `kind` names what is in charge of the dose, because that —
not the number — is what decides whether shielding helps.

Everything is dose *equivalent* in sieverts per day, which is deliberately not
what most of this literature publishes. Human spaceflight publishes Sv behind
a named instrument; spacecraft engineering publishes rad(Si) behind aluminium;
astrobiology publishes Gy absorbed in ice at a stated depth. The three are not
the same quantity and cannot be converted into one another, so an entry exists
here only where a source gives a figure for a body-sized target, and each one
carries the shielding it was measured behind. Where the literature has only a
TID curve or an ice dose, the entry keeps its `kind` and its note and leaves
the number empty rather than inventing a conversion.
"""

from typing import NamedTuple

from space_map_data.constants.activity.schema import Measurement

# `RadiationEnvironment.kind` values — what supplies most of the dose.
#
# Galactic cosmic rays, arriving from everywhere and stopped by almost
# nothing. The floor everywhere in the solar system, and the whole story on an
# airless body with no field near it.
COSMIC = "cosmic"
# A planetary magnetic field holding particles in place. The only mechanism
# that produces doses which are lethal in minutes rather than decades, and the
# only one where shielding mass is worth carrying.
TRAPPED = "trapped"
# Enough atmosphere overhead that little of either reaches the ground. What
# separates Earth, Venus and Titan from every other surface.
SHIELDED = "shielded"

DOSE_KINDS = frozenset({COSMIC, TRAPPED, SHIELDED})


class DoseRate(NamedTuple):
    """A dose-equivalent rate together with what was between it and the sky.

    The shielding is part of the number, not context for it. Against cosmic
    rays a hull barely matters, so a shielded measurement stands in for the
    unshielded rate; against trapped particles it is the difference between a
    lander that lasts a month and one that lasts an hour. Quoting either
    figure without saying which it is makes those two cases look alike.
    """

    sv_per_day: Measurement
    # Areal density between the traveller and space, in g/cm². 0 is standing
    # outside with only the body's own bulk blocking the lower half of the
    # sky. None where the source does not say, which is common: instrument
    # shielding is usually a distribution over solid angle rather than a
    # depth.
    shielding_g_cm2: float | None = None


class TrappedBelt(NamedTuple):
    """The region a field holds particles in — what a ship crosses to get out.

    Extents are in planetary radii on the magnetic equator, which is how this
    literature reports them (as L-shells). They are here as geometry rather
    than as a dose because a crossing's cost depends on how fast it is flown,
    and that is the trajectory's business, not the planet's. `crossing_dose_sv`
    is the exception: a figure someone actually flew.
    """

    sources: tuple[str, ...]
    # Where stable trapping begins. Usually set by the top of the atmosphere
    # or by a ring absorbing everything below it.
    inner_radii: Measurement | None = None
    # Where it ends. Often absent on purpose — Jupiter's belts have no edge,
    # they just fade, and a number would invent one.
    outer_radii: Measurement | None = None
    peak_radii: Measurement | None = None
    # Dose equivalent from one transit, in Sv, measured on a flown mission.
    crossing_dose_sv: Measurement | None = None
    note: str | None = None


class RadiationEnvironment(NamedTuple):
    kind: str
    kind_sources: tuple[str, ...]
    # Standing on it. Includes the body blocking the lower half of the sky,
    # which is worth about a factor of two on an airless surface.
    surface_dose: DoseRate | None = None
    # In a close circular orbit: the whole sky, and inside the belts where
    # there are any.
    orbit_dose: DoseRate | None = None
    note: str | None = None
