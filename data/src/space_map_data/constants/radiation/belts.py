"""Trapped-particle regions, as geometry a trajectory can be crossed against.

Four bodies here rather than the seven with fields, because a dynamo is not
enough: a belt also needs a trapping region big enough to hold a drift orbit,
and nothing to sweep it clean. Mercury's magnetosphere is too small to manage
the first except intermittently. Ganymede's sits inside Jupiter's and is a
shield rather than a trap. Uranus and Neptune have belts that one Voyager pass
each was not enough to bound.

Extents are L-shells — distance in planetary radii where the field line
crosses the magnetic equator — because that is the coordinate the whole
subject is written in, and because it is the one that stays fixed while a
tilted, offset dipole swings the belt around underneath it. Neptune's dipole
leans 47° and sits half a radius off centre, so a belt quoted in altitude
would be wrong twice a rotation.
"""

from space_map_data.constants.activity.schema import Measurement
from space_map_data.constants.radiation.schema import TrappedBelt

TRAPPED_BELTS: dict[str, TrappedBelt] = {
    # Mercury. A belt that comes and goes with the solar wind. Mercury's
    # magnetosphere is the smallest of any planet — the field stands the wind
    # off barely a thousand km up — and for most of the orbit there are no
    # closed drift paths at all. MESSENGER's record shows a structured
    # electron belt present about half the time near aphelion, where the
    # weaker wind lets the magnetosphere inflate, and rarely near perihelion.
    # The electrons peak near 93 keV, which is soft: this is a finding about
    # magnetospheres, not a hazard.
    "naif-199": TrappedBelt(
        sources=("wang_2026",),
        note="intermittent",
    ),
    # Earth. The extents are not carried yet — see the note in the data run —
    # but the crossing is, and it is the more useful of the two here: Apollo
    # 11's Van Allen dosimeter read 0.11 rad of skin dose across the whole
    # mission, both transits included. Half of that, for one outbound
    # crossing, is the arithmetic below and the reason it is marked modelled.
    #
    # A tenth of a mSv is nothing against a cruise, and that is the point. A
    # chemical departure clears the belts in hours and the dose does not
    # matter; a low-thrust spiral takes weeks to climb through the same
    # region and it dominates everything else the trip does.
    "naif-399": TrappedBelt(
        sources=("apollo_11_report",),
        crossing_dose_sv=Measurement(5.5e-4, "apollo_11_report", modelled=True),
        note="fast_crossing_is_cheap",
    ),
    # Jupiter. The inner edge is where stable trapping becomes possible at
    # all, 1.2 RJ. There is no outer edge: intensities fall away gradually
    # rather than stopping, and the moons make dents rather than boundaries —
    # Io's absorption at L = 5.9 cuts electron intensities by under a factor
    # of ten, and the ion belt picks up again outside it to peak at L ≈ 7.
    # The peak quoted is the MeV electrons, which are what a spacecraft dies
    # of; they maximise at L ≈ 3, inside every Galilean orbit.
    "naif-599": TrappedBelt(
        sources=("roussos_2020",),
        inner_radii=Measurement(1.2, "roussos_2020"),
        peak_radii=Measurement(3.0, "roussos_2020"),
        note="no_outer_edge",
    ),
    # Saturn. The counter-example that explains Jupiter. Saturn's proton belt
    # reaches from just above the cloud tops out to Tethys, and everything
    # solid in between — the A ring, then each inner moon — absorbs the
    # particles crossing its orbit, cutting the belt into six sectors instead
    # of letting one fill. The electron belt starts outside the A ring at
    # L = 2.27 for the same reason and peaks just beyond it. Tethys sets the
    # outer edge, which is a sharpness Jupiter has nothing like.
    "naif-699": TrappedBelt(
        sources=("roussos_2020",),
        inner_radii=Measurement(1.03, "roussos_2020"),
        outer_radii=Measurement(4.9, "roussos_2020"),
        peak_radii=Measurement(2.5, "roussos_2020"),
        note="swept_by_rings_and_moons",
    ),
}
