"""Tidal heating, body by body.

A moon on a circular orbit gets none of this: the bulge has to move to do any
work, and it only moves if the orbit is eccentric or the spin is tilted. So
every entry below either names a resonance that keeps the eccentricity from
damping away, or explains why the heating is a leftover rather than a supply.

The heating rate itself is rarely measured. What is measured is the heat coming
*out* — Io's infrared radiometry, Enceladus's south polar emission — and on
those two bodies the tide is so dominant that the observed loss is taken as the
production. Everywhere else the numbers are modelled, and are left out here
rather than shipped as though a spacecraft had weighed them. `role` is the
honest resolution for most of the list.

Powers are watts and fluxes W m⁻², matching `Volcanism.endogenic_power_w` so
the two can be read against each other: on Io they are the same number, which
is the whole finding.
"""

from space_map_data.constants.activity.schema import Measurement, TidalHeating

TIDAL_HEATING: dict[str, TidalHeating] = {
    # Moon. Earth raises a tide on it and always has, but the Moon is cold and
    # therefore barely dissipative, so the heating does nothing to its present
    # thermal state. Kept in the table because its absence is the control on
    # Io: the same orbital distance, a planet 300 times lighter, and no
    # resonance to keep the eccentricity up.
    "naif-301": TidalHeating(
        raised_by="naif-399",
        role="negligible",
        role_sources=("nimmo_2025",),
    ),
    # Earth. The rare case where the tide is dissipated in an ocean rather than
    # in rock, and the only body where it is measured by satellite altimetry
    # rather than modelled. 3.7 TW is the whole astronomical tide, lunar and
    # solar; about a quarter of it goes into internal waves in the deep ocean
    # and the rest into friction in shallow seas. Set against 47 TW of internal
    # heat, the tide is a twelfth of Earth's energy budget — and it is the
    # reason the day is lengthening.
    "naif-399": TidalHeating(
        raised_by="naif-301",
        role="minor",
        role_sources=("munk_1998",),
        power_w=Measurement(3.7e12, "munk_1998"),
        note="ocean_tides",
    ),
    # Io. The measurement, not a model: Veeder gives "an average total power of
    # 1.05 × 10¹⁴ W (2.5 W m⁻²)" from infrared radiometry over a decade, which
    # is thirty times Earth's flux and more than any other body in the system
    # by two orders of magnitude. No uncertainty is attached to it there; the
    # 105 ± 12 TW seen in later work is Davies's restatement, so the bracket is
    # left off rather than credited to a paper that does not carry it. Juno's
    # Love number gives the other half of the story — k₂ of 0.125 is *small*,
    # too small for the global magma ocean the heating was long thought to
    # require, and Q of 11.4 is the lossiest interior ever measured. Io is
    # mostly solid rock being kneaded, not a ball of melt.
    "naif-501": TidalHeating(
        raised_by="naif-599",
        role="dominant",
        role_sources=("matsuyama_2022",),
        power_w=Measurement(1.05e14, "veeder_1994"),
        flux_w_per_m2=Measurement(2.5, "veeder_1994"),
        k2=Measurement(0.125, "park_2025", range=(0.078, 0.172)),
        q=Measurement(11.4, "park_2025", range=(7.8, 15.0)),
        resonance_with=("naif-502", "naif-503"),
        resonance_source="matsuyama_2022",
        note="laplace_resonance",
    ),
    # Europa. Second in the same resonance, and the tide is what keeps its
    # ocean liquid, but nobody has weighed it: published dissipation rates
    # depend on an ice-shell thickness that is itself only known to within a
    # factor of ten. The one firm surface number is the shell, about 20 km from
    # impact craters.
    "naif-502": TidalHeating(
        raised_by="naif-599",
        role="significant",
        role_sources=("nimmo_2025",),
        resonance_with=("naif-501", "naif-503"),
        resonance_source="matsuyama_2022",
        note="laplace_resonance",
    ),
    # Ganymede. Third in the resonance and far enough out that present-day
    # heating is negligible — but its grooved terrain records a pulse of tidal
    # heating around 2 Ga, when the resonance was being assembled. The ocean it
    # has now is kept liquid by radiogenic heat and depth, not by the tide.
    "naif-503": TidalHeating(
        raised_by="naif-599",
        role="past",
        role_sources=("nimmo_2025",),
        resonance_with=("naif-501", "naif-502"),
        resonance_source="matsuyama_2022",
        note="ancient_heating_pulse",
    ),
    # Mimas. The surprise of 2024. Its surface is the most heavily cratered in
    # the Saturn system and shows nothing, but the way its orbit precesses only
    # works if there is a global ocean under 20-30 km of ice — and the ocean
    # has to be young, because an older one would have deformed the shell
    # enough to see. Between 2 and 25 Myr old, which is nothing.
    "naif-601": TidalHeating(
        raised_by="naif-699",
        role="significant",
        role_sources=("lainey_2024",),
        note="young_ocean",
    ),
    # Enceladus. 15.8 GW leaving the south polar terrain, measured by Cassini's
    # far-infrared spectrometer, against 0.34 GW of radiogenic heat in the
    # whole body — a factor of fifty, and the reason nobody doubts the tide is
    # the source. The global mean flux of 0.04 W m⁻² badly understates the
    # tiger stripes themselves, where it is concentrated into four fractures.
    # The Dione resonance is what holds the eccentricity up, though the
    # equilibrium rate it can sustain is short of what is observed, which is
    # the open problem.
    "naif-602": TidalHeating(
        raised_by="naif-699",
        role="dominant",
        role_sources=("howett_2011",),
        power_w=Measurement(1.58e10, "howett_2011", range=(1.27e10, 1.89e10)),
        flux_w_per_m2=Measurement(0.04, "nimmo_2025"),
        resonance_with=("naif-604",),
        resonance_source="nimmo_2018",
        note="south_polar_terrain",
    ),
    # Dione. The other end of the Enceladus resonance, which means it is being
    # heated too, and its own fractured trailing hemisphere and possible ocean
    # are the evidence. Nothing is erupting.
    "naif-604": TidalHeating(
        raised_by="naif-699",
        role="minor",
        role_sources=("nimmo_2018",),
        resonance_with=("naif-602",),
        resonance_source="nimmo_2018",
    ),
    # Titan. In no eccentricity resonance, and its own eccentricity is small
    # enough that the tide is modest — the ocean under it is deep and salty
    # rather than tidally stoked. Kept for the contrast with Enceladus, which
    # is a fiftieth of its size and puts out more heat.
    "naif-606": TidalHeating(
        raised_by="naif-699",
        role="minor",
        role_sources=("nimmo_2025",),
    ),
    # Triton. Captured from the Kuiper belt onto a retrograde, wildly eccentric
    # orbit, and the circularisation of that orbit is thought to have melted
    # the moon through. That episode is over — the orbit is circular now — but
    # the orbit is still *inclined*, so the bulge moves north and south each
    # revolution, and obliquity tides may be what keeps Triton's surface only
    # ~10 Myr old.
    "naif-801": TidalHeating(
        raised_by="naif-899",
        role="past",
        role_sources=("nimmo_2025",),
        note="obliquity_tides",
    ),
    # Charon. Pluto and Charon are doubly synchronous — each keeps one face to
    # the other, which is where tidal evolution ends and heating stops. What is
    # left is the early episode, while the two were still spinning down, and
    # Charon's tectonised Vulcan Planitia is the record of it.
    "naif-901": TidalHeating(
        raised_by="naif-999",
        role="past",
        role_sources=("nimmo_2025",),
        note="dual_synchronous",
    ),
}
