"""Trapped-particle regions, as geometry a trajectory can be crossed against.

Six bodies here rather than the seven with fields, because a dynamo is not
enough: a belt also needs a trapping region big enough to hold a drift orbit,
and nothing to sweep it clean. Mercury's magnetosphere is too small to manage
the first except intermittently, and it is here anyway because a part-time belt
is still a finding. Ganymede's sits inside Jupiter's and is a shield rather than
a trap, which is why it is the one absentee.

The entries are not equally well known. Jupiter's and Saturn's come from years
of orbiting; Uranus's and Neptune's from one Voyager 2 pass each, fitted into
JPL engineering models afterwards, which is enough to bound them but not enough
to survey them.

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
    # Earth. The extents are the outer belt's, because that is what a departure
    # crosses last and what sets where the region ends: Cluster and Double Star
    # put its inner edge at L = 3-5 and its outer edge anywhere from 4.5 to 9,
    # the most variable boundary in the system — a storm can pull it in to
    # L = 4 within hours. The inner belt sits below the slot at L = 2.5-3, and
    # the slot itself is 1 to 1.5 Earth radii thick and widens when the solar
    # wind is quiet.
    #
    # No inner edge. Cluster's perigee was L = 2 and it never went under it, so
    # where the inner belt stops against the atmosphere is not in that dataset
    # and is not quoted here from anywhere else.
    #
    # The crossing is the more useful number of the two: Apollo 11's Van Allen
    # dosimeter read 0.11 rad of skin dose across the whole mission, both
    # transits included. Half of that, for one outbound crossing, is the
    # arithmetic below and the reason it is marked modelled.
    #
    # A tenth of a mSv is nothing against a cruise, and that is the point. A
    # chemical departure clears the belts in hours and the dose does not
    # matter; a low-thrust spiral takes weeks to climb through the same
    # region and it dominates everything else the trip does.
    "naif-399": TrappedBelt(
        sources=("apollo_11_report", "ganushkina_2011"),
        outer_radii=Measurement(6.0, "ganushkina_2011", range=(4.5, 9.0)),
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
    # Uranus. One Voyager 2 pass is the whole record, and UMOD is a fit to it
    # rather than a survey. The peak is not resolved — the report says outright
    # that the absence of data inside 4 R_U is not an absence of radiation — so
    # only the outer extent is carried, the distance beyond which its authors
    # say a spacecraft is safe.
    #
    # The number that pass does give is a whole-crossing dose: about 100 rad(Si)
    # behind 100 mils of aluminium for Voyager 2's entire flyby, closest
    # approach 107,000 km from the centre. That is 1 Gy, against the 4,500 Gy
    # Pioneer 10 took at Jupiter. It is not carried as a field because the only
    # crossing figure this schema holds is a dose equivalent, and rad(Si)
    # absorbed behind aluminium is not one.
    "naif-799": TrappedBelt(
        sources=("garrett_2015",),
        outer_radii=Measurement(8.0, "garrett_2015"),
        note="one_flyby_only",
    ),
    # Neptune. The same single pass, but NMOD resolves what UMOD could not: a
    # dose rate against L with two peaks, the outer and larger at L = 7, and a
    # dip between them near L = 5. `belt_field.py` carries the whole curve.
    "naif-899": TrappedBelt(
        sources=("garrett_2017",),
        outer_radii=Measurement(9.0, "garrett_2017", range=(8.0, 10.0)),
        peak_radii=Measurement(7.0, "garrett_2017"),
        note="one_flyby_only",
    ),
}
