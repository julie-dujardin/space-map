"""Tidal heating, body by body.

A circular orbit gets none of this — the bulge only moves, and does work, if
the orbit is eccentric or the spin tilted. Each entry names the resonance that
keeps the eccentricity up, or says why the heating is a leftover.

The rate itself is rarely measured; what's measured is the heat coming *out*
(Io's infrared radiometry, Enceladus's south polar emission), and only on
those two is the tide so dominant that observed loss can stand for
production. Elsewhere the numbers are modelled and left out, so `role` is the
honest resolution for most of the list.

Powers are watts, fluxes W m⁻², matching `Volcanism.endogenic_power_w` so the
two read against each other — on Io they're the same number.
"""

from space_map_data.constants.activity.schema import Measurement, TidalHeating

TIDAL_HEATING: dict[str, TidalHeating] = {
    # Moon. Earth raises a tide, but the Moon is cold and barely dissipative,
    # so it does nothing to its present thermal state. Kept as the control on
    # Io: same orbital distance, a planet 300 times lighter, no resonance to
    # keep the eccentricity up.
    "naif-301": TidalHeating(
        raised_by="naif-399",
        role="negligible",
        role_sources=("nimmo_2025",),
    ),
    # Earth. Dissipated in the ocean rather than rock, and the only body
    # measured by satellite altimetry rather than modelled. 3.7 TW is the
    # whole lunar+solar tide — a twelfth of Earth's 47 TW internal heat budget,
    # and the reason the day is lengthening.
    "naif-399": TidalHeating(
        raised_by="naif-301",
        role="minor",
        role_sources=("munk_1998",),
        power_w=Measurement(3.7e12, "munk_1998"),
        note="ocean_tides",
    ),
    # Io. The measurement, not a model: Veeder's 1.05×10¹⁴ W (2.5 W m⁻²) from
    # a decade of infrared radiometry, thirty times Earth's flux. No
    # uncertainty attached there; the ±12 TW seen elsewhere is Davies's later
    # restatement, so it's left off. Juno's Love number k₂ = 0.125 is too
    # small for the global magma ocean once assumed, and Q = 11.4 is the
    # lossiest interior measured anywhere — solid rock being kneaded.
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
    # Europa. Second in the resonance; the tide keeps its ocean liquid, but
    # nobody has weighed it — dissipation depends on an ice-shell thickness
    # known only to within a factor of ten. The firm number is the shell
    # itself, about 20 km from impact craters.
    "naif-502": TidalHeating(
        raised_by="naif-599",
        role="significant",
        role_sources=("nimmo_2025",),
        resonance_with=("naif-501", "naif-503"),
        resonance_source="matsuyama_2022",
        note="laplace_resonance",
    ),
    # Ganymede. Third in the resonance and far enough out that present-day
    # heating is negligible, but grooved terrain records a heating pulse
    # around 2 Ga as the resonance assembled. Its ocean now is kept liquid by
    # radiogenic heat and depth, not the tide.
    "naif-503": TidalHeating(
        raised_by="naif-599",
        role="past",
        role_sources=("nimmo_2025",),
        resonance_with=("naif-501", "naif-502"),
        resonance_source="matsuyama_2022",
        note="ancient_heating_pulse",
    ),
    # Mimas. The surprise of 2024: its surface is the most heavily cratered in
    # the Saturn system and shows nothing, but its orbital precession only
    # works with a global ocean under 20-30 km of ice — and a young one, 2-25
    # Myr, since an older ocean would have deformed the shell visibly.
    "naif-601": TidalHeating(
        raised_by="naif-699",
        role="significant",
        role_sources=("lainey_2024",),
        note="young_ocean",
    ),
    # Enceladus. ~4.7 GW leaving the south polar terrain (Spencer's resolved
    # scans; the range and the earlier 15.8 GW are explained on the volcanism
    # entry) against 0.34 GW radiogenic — a factor of ten even at the floor,
    # why nobody doubts the tide is the source. The 0.04 W m⁻² global mean
    # badly understates the tiger stripes, where it's concentrated into four
    # fractures. The Dione resonance holds the eccentricity up, but its
    # equilibrium rate falls short of what's observed — the open problem.
    "naif-602": TidalHeating(
        raised_by="naif-699",
        role="dominant",
        role_sources=("howett_2011",),
        power_w=Measurement(4.7e9, "spencer_2013", range=(4.2e9, 1.89e10)),
        flux_w_per_m2=Measurement(0.04, "nimmo_2025"),
        resonance_with=("naif-604",),
        resonance_source="nimmo_2018",
        note="south_polar_terrain",
    ),
    # Dione. The other end of the Enceladus resonance, so it's heated too —
    # evidence is its fractured trailing hemisphere and possible ocean.
    # Nothing is erupting.
    "naif-604": TidalHeating(
        raised_by="naif-699",
        role="minor",
        role_sources=("nimmo_2018",),
        resonance_with=("naif-602",),
        resonance_source="nimmo_2018",
    ),
    # Titan. In no eccentricity resonance and modest eccentricity, so the tide
    # is modest — its ocean is deep and salty, not tidally stoked. Kept for
    # the contrast with Enceladus, a fiftieth its size but putting out more
    # heat.
    "naif-606": TidalHeating(
        raised_by="naif-699",
        role="minor",
        role_sources=("nimmo_2025",),
    ),
    # Triton. Captured onto a retrograde, wildly eccentric orbit; its
    # circularisation is thought to have melted the moon through. That episode
    # is over — the orbit is circular now, but still *inclined*, so obliquity
    # tides may be what keeps the surface only ~10 Myr old.
    "naif-801": TidalHeating(
        raised_by="naif-899",
        role="past",
        role_sources=("nimmo_2025",),
        note="obliquity_tides",
    ),
    # Charon. Pluto and Charon are doubly synchronous — tidal evolution ends
    # once each keeps one face to the other. What's left is the earlier
    # spin-down episode, recorded in Charon's tectonised Vulcan Planitia.
    "naif-901": TidalHeating(
        raised_by="naif-999",
        role="past",
        role_sources=("nimmo_2025",),
        note="dual_synchronous",
    ),
}
