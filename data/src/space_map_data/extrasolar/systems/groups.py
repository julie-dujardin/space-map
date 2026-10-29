"""The kind of a group object that has a point of its own beside its members.

SIMBAD, the MSC or WDS can have one object for a whole pair beside the
objects of its stars. When that object has a point of its own, the point is
one of three kinds:
- PRIMARY: the primary star, or a point that holds the light of each member.
- BACKGROUND: a member's parallax and the point's clearly disagree
  (`disagree`). That member is not at the distance of the point. The veto
  removes each member that disagrees with its primary before this test.
- COMBINED: the light of its members. Its astrometry is not Gaia's, each
  member is a Gaia point, and its magnitude is the combined magnitude of the
  members within COMBINED_MAG. A Gaia source is one star, so it never holds
  the light of other Gaia sources. The test uses no separation, because a
  Hipparcos 1997 position can be far from the stars.
The point stays a member of its system for each kind. The kind goes to the
event and to the report.
"""

import math
from collections.abc import Sequence

from space_map_data.extrasolar.systems.parallax import disagree
from space_map_data.extrasolar.systems.resolve import GAIA_ASTROMETRY, Fact

GROUP_OBJECT = "group object beside its members"
PRIMARY, BACKGROUND, COMBINED = "primary", "background members", "combined light"
KINDS = (PRIMARY, BACKGROUND, COMBINED)
# A G estimate from Hipparcos and a variable star can be off by this many
# magnitudes.
COMBINED_MAG = 0.75


def combined_mag(mags: Sequence[float]) -> float:
    """The magnitude of the summed light."""
    return -2.5 * math.log10(sum(10 ** (-0.4 * mag) for mag in mags))


def group_kind(own: Fact | None, members: Sequence[Fact | None]) -> tuple[str, str]:
    """The kind of the point `own` beside the points `members` that it does
    not hold, and its evidence."""
    if own is None:
        return PRIMARY, "the point has no facts"
    if not members:
        return PRIMARY, "the point holds the light of each member"
    found = [m for m in members if m is not None]
    far = [m for m in found if disagree(own, m)]
    if far:
        return BACKGROUND, f"parallax {_parallax(own)}, " + ", ".join(
            f"{m.key} {_parallax(m)}" for m in far
        )
    mags = [m.mag for m in found]
    if len(found) < len(members) or not all(math.isfinite(m) for m in mags):
        return PRIMARY, "a member has no magnitude"
    if not math.isfinite(own.mag):
        return PRIMARY, "the point has no magnitude"
    together = combined_mag(mags)
    evidence = (
        f"{own.astrometry} {own.mag:.2f} mag, its members {together:.2f} mag together"
    )
    if (
        own.astrometry not in GAIA_ASTROMETRY
        and all(m.astrometry in GAIA_ASTROMETRY for m in found)
        and abs(own.mag - together) <= COMBINED_MAG
    ):
        return COMBINED, evidence
    return PRIMARY, evidence


def _parallax(fact: Fact) -> str:
    return f"{fact.parallax:.2f} ± {fact.parallax_error:.2f} mas"
