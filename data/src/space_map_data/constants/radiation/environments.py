"""Per-body dose rates — what a traveller takes, standing there or orbiting.

The numeric coverage here is deliberately thin and will stay that way. Four
places in the solar system have had a dosimeter built for a human body sat on
them or flown through them — deep space, low Earth orbit, the lunar surface
and Gale crater — and everywhere else the literature measures something else:
ionizing dose in silicon for spacecraft parts, or absorbed dose in ice at a
stated depth for buried organics. Neither converts into a human's sievert, so
the rest of the table carries a `kind` and a note and no number.

That is not a gap to be filled by modelling; it is the state of the subject.
The four numbers that do exist span a factor of three, and the one estimate
that joins them — Europa's — is six orders of magnitude above all of them.
"""

from space_map_data.constants.activity.schema import Measurement
from space_map_data.constants.radiation.schema import (
    COSMIC,
    SHIELDED,
    TRAPPED,
    DoseRate,
    RadiationEnvironment,
)

# Free space at 1 AU, behind a real spacecraft. RAD ran through MSL's cruise
# and this is what it read inside the cruise stage: the only long-baseline
# dose-equivalent measurement of interplanetary space ever made behind
# human-scale shielding, and the number every cruise estimate in the travel
# planner is a duration multiplied by.
#
# This is the 2019 reanalysis, not the figure Zeitlin published in 2013 — the
# original 1.84 mSv/day came down about 15% once the RTG background was
# removed from the LET spectrum and the silicon-to-water conversion was
# revised. Guo's review carries the corrected value and the reason for it; the
# older number is still the one in wide circulation.
#
# Two caveats travel with it. It covers December 2011 to July 2012, the rise
# towards solar cycle 24's maximum, when the Sun's field sweeps cosmic rays
# out of the inner system most effectively; the same instrument at solar
# minimum would read appreciably higher, and Guo puts a Hohmann round trip at
# 0.65 Sv near maximum against 1.59 Sv near minimum. And RAD's shielding was
# not a depth but a distribution over solid angle — part of the sky under
# 10 g/cm², part of it through a full hydrazine tank — so no single g/cm² can
# be quoted for it.
INTERPLANETARY_DOSE = DoseRate(
    Measurement(1.58e-3, "guo_2021", range=(1.36e-3, 1.80e-3)),
)

RADIATION_ENVIRONMENTS: dict[str, RadiationEnvironment] = {
    # Mercury. No atmosphere and, for dose purposes, no field: the
    # magnetosphere stands off the solar wind only a thousand-odd km up and
    # for most of the orbit has no closed drift paths to trap anything in. So
    # the surface sees galactic cosmic rays like the Moon does, plus solar
    # particle events at three times the flux Earth gets for being three times
    # closer in. Nobody has measured either at the surface.
    "naif-199": RadiationEnvironment(
        kind=COSMIC,
        kind_sources=("wang_2026",),
        note="solar_proximity",
    ),
    # Venus. Ninety-two bars over your head is about a hundred thousand g/cm²,
    # a hundred times Earth's column and the thickest shield in the solar
    # system. Herbst's profiles are computed for the cloud deck, 51 to 62 km
    # up, where the dose is already below a terrestrial airliner's; the
    # surface is far below that and nobody has bothered to compute it. The
    # induced magnetosphere contributes nothing — it has no trapping region.
    "naif-299": RadiationEnvironment(
        kind=SHIELDED,
        kind_sources=("herbst_2020",),
        note="thickest_atmosphere",
    ),
    # Earth. The surface figure is the cosmic-ray component of natural
    # background alone, not total background: it is the number that compares
    # with the other bodies here, all of which have no radon and no potassium
    # in their rocks to speak of. Terrestrial sources roughly quintuple it.
    #
    # In orbit the atmosphere is gone and the belts are not, so low Earth
    # orbit reads seven hundred times the ground. Two-thirds of that is
    # cosmic rays that the field no longer deflects; the rest is the South
    # Atlantic Anomaly, where the offset dipole dips the inner proton belt
    # low enough for the station to fly through its skirt several times a day.
    "naif-399": RadiationEnvironment(
        kind=SHIELDED,
        kind_sources=("unscear_2008",),
        surface_dose=DoseRate(
            Measurement(1.07e-6, "unscear_2008"),
            shielding_g_cm2=1033.0,
        ),
        orbit_dose=DoseRate(Measurement(7.31e-4, "zhang_2020")),
        note="south_atlantic_anomaly",
    ),
    # The Moon. Chang'e-4's LND is the first dosimeter anyone has landed on
    # another world's surface and read out as a dose equivalent, and it is the
    # cleanest number in this table: 57.1 µSv/h behind essentially nothing.
    # It is 2.6 times what the ISS reads and more than twice Gale crater's,
    # which is the whole argument for Mars having an atmosphere and the Moon
    # not.
    #
    # It was taken in January 2019, the floor of the deepest solar minimum of
    # the space age, so unlike the Mars and cruise figures it is near the top
    # of its own cycle rather than the bottom.
    "naif-301": RadiationEnvironment(
        kind=COSMIC,
        kind_sources=("zhang_2020",),
        surface_dose=DoseRate(
            Measurement(1.369e-3, "zhang_2020", range=(1.115e-3, 1.623e-3)),
            shielding_g_cm2=0.0,
        ),
        note="solar_minimum_measurement",
    ),
    # Mars. Twenty-odd g/cm² of CO₂ is not much of a shield, but it is the
    # difference between the lunar figure and this one: RAD reads half what
    # LND does and about a third of what it read itself during the cruise. The
    # rest of the reduction is Mars blocking the lower half of the sky.
    #
    # The range here is not Hassler's error bar — it is the solar cycle. RAD
    # has now watched a full one from the ground, and Guo's review puts the
    # dose equivalent rate between 0.25 and 0.95 mSv/day depending on where in
    # it you land, a factor of four that dwarfs the ±0.12 on any single
    # measurement. The value is Hassler's 300-sol average from near solar
    # maximum, which sits low in that span.
    #
    # Gale crater is 4.4 km below the areoid and so carries more atmosphere
    # than most of the planet; the dose on the volcanoes is higher. RAD also
    # watches it breathe with the seasonal pressure cycle.
    "naif-499": RadiationEnvironment(
        kind=COSMIC,
        kind_sources=("hassler_2014",),
        surface_dose=DoseRate(
            Measurement(6.4e-4, "hassler_2014", range=(2.5e-4, 9.5e-4)),
        ),
        note="varies_with_solar_cycle",
    ),
    # Jupiter. No surface to stand on and the worst radiation environment in
    # the solar system to orbit in. The belts are `belts.py`; what matters
    # here is that any close orbit is inside them.
    "naif-599": RadiationEnvironment(
        kind=TRAPPED,
        kind_sources=("roussos_2020",),
        note="worst_in_system",
    ),
    # Io. Deepest inside the belts of the four and the source of most of what
    # is in them — the torus it feeds is what the rest of the magnetosphere is
    # made of. It is also the one moon whose surface flux cannot be compared
    # with the others: Johnson's table gives Io 1×10⁹ keV cm⁻² s⁻¹ against
    # Europa's 5×10¹⁰, but Io's entry counts ions only, where every other
    # entry counts ions and electrons above 10 keV. Reading that column as a
    # ranking puts Io fifty times below Europa, which is the opposite of what
    # every dose estimate says. No number until one exists on equal terms.
    "naif-501": RadiationEnvironment(
        kind=TRAPPED,
        kind_sources=("johnson_2004",),
        note="feeds_the_belts",
    ),
    # Europa. The number that makes this table worth having, and the only one
    # in it read off a chart: Figure 6.5 of the lander study plots dose rate
    # in silicon against aluminium thickness at the trailing hemisphere, and
    # at the thinnest shielding it draws — about 0.4 mm, or 0.11 g/cm² — the
    # total is around 10⁵ rad/day. That is 10³ Gy, and the flux is electrons,
    # for which the quality factor is one, so it stands as roughly 1,000
    # Sv/day: a median lethal dose in about seven minutes, and a million times
    # what deep space delivers. Modelled, because it is a GIRE-2p output read
    # off a log axis and converted, not a measurement.
    #
    # The same curve is the argument for shielding: ten millimetres of
    # aluminium takes it down two orders of magnitude, which is why the lander
    # has a vault and why nothing else in this table behaves like it. JPL's
    # figure already halves the belt dose to account for Europa blocking the
    # lower half of the sky, the effect Paranicas quantified — a site on the
    # surface takes less than a spacecraft in the same orbit.
    #
    # Do not derive a rate from the study's 1.7 Mrad mission TID: that covers
    # the Jupiter tour as well as the 20-to-40-day surface phase, and dividing
    # it by the surface lifetime overstates the surface by several times.
    "naif-502": RadiationEnvironment(
        kind=TRAPPED,
        kind_sources=("europa_lander_sdt_2016", "paranicas_2007"),
        surface_dose=DoseRate(
            Measurement(
                1.0e3,
                "europa_lander_sdt_2016",
                range=(5.0e2, 2.0e3),
                modelled=True,
            ),
            shielding_g_cm2=0.11,
        ),
        note="lethal_in_minutes",
    ),
    # Ganymede. The only moon with a magnetosphere of its own, and it works:
    # the dipole deflects incoming electrons off the equator and funnels them
    # onto the polar caps, so latitude matters more here than anywhere else in
    # the table. On the same footing as Europa's 5×10¹⁰ keV cm⁻² s⁻¹, the
    # poles take 5×10⁹ and the equator 2×10⁸ — a factor of twenty-five between
    # two points on one moon, and an equator two hundred and fifty times
    # quieter than Europa. JUICE is going into orbit around it.
    "naif-503": RadiationEnvironment(
        kind=TRAPPED,
        kind_sources=("johnson_2004",),
        note="shielded_by_own_field",
    ),
    # Callisto. Far enough out to sit near the edge of the trapping region and
    # miss the worst of it: 2×10⁸ keV cm⁻² s⁻¹, the same as Ganymede's equator
    # and two hundred and fifty times below Europa, reached without needing a
    # field of its own. It is the only Galilean a crew could work on, which is
    # why every study of a Jupiter-system base puts one here.
    "naif-504": RadiationEnvironment(
        kind=TRAPPED,
        kind_sources=("johnson_2004",),
        note="outside_the_worst",
    ),
    # Saturn. Belts an order of magnitude gentler than Jupiter's, and for a
    # specific reason: the rings and the inner moons sit inside them and
    # absorb the particles, cutting the belt into sectors rather than letting
    # it fill.
    "naif-699": RadiationEnvironment(
        kind=TRAPPED,
        kind_sources=("roussos_2020",),
        note="cut_by_rings",
    ),
    # Titan. The best-shielded solid surface in the solar system after
    # Venus's, and unlike Venus's one you could stand on. 1.45 bar under
    # 1.35 m/s² is about 10,700 g/cm² overhead, ten times Earth's column, and
    # Gronoff's cascade puts the cosmic-ray ionization peak at 65 km altitude
    # — the Pfotzer maximum sits sixty-five kilometres above the ground, with
    # the whole troposphere still to go. Saturn's belts end at Tethys, far
    # inside Titan's orbit, so nothing else arrives either. No one has
    # computed a surface dose, so there is no number.
    "naif-606": RadiationEnvironment(
        kind=SHIELDED,
        kind_sources=("gronoff_2011",),
        note="thick_and_standable",
    ),
    # Uranus and Neptune. Both have belts, both were characterised from a
    # single Voyager 2 pass each, and JPL's models of them report ionizing
    # dose in silicon against L-shell rather than anything a body absorbs.
    # Intensities are moderate — well below Jupiter's — but the tilted,
    # offset dipoles mean the belts are not where a reader would put them.
    "naif-799": RadiationEnvironment(
        kind=TRAPPED,
        kind_sources=("garrett_2015",),
        note="one_flyby_only",
    ),
    "naif-899": RadiationEnvironment(
        kind=TRAPPED,
        kind_sources=("garrett_2017",),
        note="one_flyby_only",
    ),
}
