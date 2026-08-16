"""Volcanism and tectonics, body by body.

The interesting column is `status`, not the numbers. Whether Venus is erupting
*right now* rests on two surface changes in Magellan's radar; whether the Moon
erupted in the last hundred million years turns on crater counts that may be
measuring roughness, not age. Collapsing that into active/inactive would throw
away what the evidence actually supports, so the vocabulary keeps five rungs
and each comment says which rung its evidence reaches and why.

Cryovolcanism is the same word for a different machine — brine and ammonia
where Earth has basalt — with the same fields, since the observables (vents,
plumes, resurfacing rate, youngest dated activity) are the same.

Vent counts are survey snapshots and carry `as_of`: nobody has counted the
volcanoes of any world, only what an instrument resolved on the days it looked.
"""

from space_map_data.constants.activity.schema import (
    CRYO,
    SILICATE,
    BodyActivity,
    Measurement,
    Tectonics,
    Volcanism,
)

GEOLOGIC_ACTIVITY: dict[str, BodyActivity] = {
    # Mercury. Effusive volcanism built the northern smooth plains and stopped
    # by about 3.5 Ga, once the planet cooled and contracted enough that magma
    # could no longer reach through a lithosphere in compression. Tectonics
    # outlived it: up to 7 km of radial shrinkage in thrust faults, with
    # scarps crisp enough to be under 50 Myr old — the only one-plate planet
    # with a case for active faulting.
    "naif-199": BodyActivity(
        volcanism=Volcanism(
            kind=SILICATE,
            status="extinct",
            status_sources=("byrne_2016",),
            youngest_activity_years=Measurement(3.5e9, "byrne_2016"),
        ),
        tectonics=Tectonics(
            style="contractional_lid",
            status="probable",
            sources=("watters_2016",),
            radial_contraction_km=Measurement(7.0, "byrne_2014", upper_limit=True),
            note="global_contraction",
        ),
    ),
    # Venus. The hard case, and the reason `probable` exists. Nobody has seen
    # an eruption; the direct case is one vent on Maat Mons that grew from
    # 2.2 to 4.0 km² and turned irregular between two Magellan passes eight
    # months apart in 1991, found while examining ~1.5% of the surface —
    # read as Venus being less active than Io but not a small fraction of
    # Earth. Radar backscatter changes at Sif Mons and Niobe Planitia are a
    # second, independent detection.
    #
    # The eruption count is Earth's 1980-2021 record scaled by mass and area
    # (`modelled=True`); erupted volume is derived from the cratering record
    # and atmospheric chemistry, so it isn't flagged. Surface age (250 Ma to
    # 1 Ga depending on crater model) is the counterweight: the planet was
    # resurfaced wholesale once and has been mostly quiet since.
    "naif-299": BodyActivity(
        volcanism=Volcanism(
            kind=SILICATE,
            status="probable",
            status_sources=("herrick_2023", "sulcanese_2024"),
            eruptions_per_year=Measurement(120.0, "byrne_2022", modelled=True),
            erupted_volume_km3_per_year=Measurement(
                1.0, "gillmann_2024", range=(0.1, 10.0)
            ),
            surface_age_years=Measurement(6.0e8, "gillmann_2024", range=(2.5e8, 1.0e9)),
            note="no_eruption_observed",
        ),
        # `mobile_lid` records the mapped deformation (coronae, rifts,
        # localised trenches), not a settled regime — there isn't one. Rivals:
        # a quiescent stagnant-lid phase of an episodic cycle fitting the same
        # crater statistics, or equilibrium resurfacing under a weak crust.
        tectonics=Tectonics(
            style="mobile_lid",
            status="probable",
            sources=("gulcher_2020", "gillmann_2024"),
            note="regime_debated",
        ),
    ),
    # Earth. Both counts are the Smithsonian's catalogue, not physical
    # constants — 1,196 Holocene volcanoes and 79.2 eruptions/yr (2010-2024
    # mean), rederived from the downloaded record by `download/providers/
    # gvp.py` and checked by the constants test. The 47 TW is the whole
    # planet's heat loss; volcanism carries only a fraction, most conducting
    # out through the sea floor.
    "naif-399": BodyActivity(
        volcanism=Volcanism(
            kind=SILICATE,
            status="active",
            status_sources=("gvp_votw",),
            known_centres=Measurement(1196.0, "gvp_votw", as_of="WFS, 2026-08-06"),
            eruptions_per_year=Measurement(
                79.2, "gvp_votw", as_of="mean 2010-2024, WFS 2026-08-06"
            ),
            endogenic_power_w=Measurement(
                4.7e13, "davies_2010", range=(4.5e13, 4.9e13)
            ),
            heat_flux_w_per_m2=Measurement(0.08, "nimmo_2025"),
        ),
        # The only body here whose surface is destroyed as fast as it's made.
        tectonics=Tectonics(
            style="plate_tectonics",
            status="active",
            sources=("bird_2003",),
        ),
    ),
    # Moon. Mare volcanism ended around 1 Ga on the usual reading, but seventy
    # irregular nearside patches have crater counts implying eruptions within
    # the last 100 Myr — contested, since the same morphology can come from
    # ancient magmatic foam with no crater-retaining surface. Recorded extinct
    # with the young date as an upper limit, not a claim. The thrust scarps
    # are firmer: Apollo-recorded moonquakes cluster near faults young enough
    # to cut small craters, so the Moon is still shrinking.
    "naif-301": BodyActivity(
        volcanism=Volcanism(
            kind=SILICATE,
            status="extinct",
            status_sources=("braden_2014",),
            youngest_activity_years=Measurement(1.0e8, "braden_2014", upper_limit=True),
            note="young_age_disputed",
        ),
        tectonics=Tectonics(
            style="contractional_lid",
            status="probable",
            sources=("watters_2019",),
            note="global_contraction",
        ),
    ),
    # Mars. Olympus Mons hasn't erupted in tens of millions of years, but a
    # pyroxene-rich deposit around Cerberus Fossae dates to 53 ka — now,
    # geologically — and InSight found the same fissure system the planet's
    # most seismically active. Neither is an eruption, hence `suspected`
    # rather than Venus's `probable`.
    "naif-499": BodyActivity(
        volcanism=Volcanism(
            kind=SILICATE,
            status="suspected",
            status_sources=("horvath_2021",),
            youngest_activity_years=Measurement(
                5.3e4, "horvath_2021", range=(5.3e4, 2.1e5)
            ),
            note="cerberus_fossae",
        ),
        tectonics=Tectonics(
            style="stagnant_lid",
            status="probable",
            sources=("giardini_2020",),
            note="marsquakes",
        ),
    ),
    # Io. Not a matter of interpretation: 343 thermal sources mapped through
    # mid-2023, radiating 57.7 TW of the 105 TW leaving the body. The 47 TW
    # gap — Earth's entire heat flow — isn't accounted for by any resolved
    # volcano: either many sources below resolution, or heat conducting out
    # through the plains.
    #
    # Power and flux are Veeder's measurement, the same numbers `tidal.py`
    # carries: observed loss stands for production. Neither carries the
    # ±12 TW quoted elsewhere — that's Davies's restatement, not Veeder's.
    "naif-501": BodyActivity(
        volcanism=Volcanism(
            kind=SILICATE,
            status="active",
            status_sources=("davies_2024",),
            known_centres=Measurement(343.0, "davies_2024", as_of="through mid-2023"),
            endogenic_power_w=Measurement(1.05e14, "veeder_1994"),
            heat_flux_w_per_m2=Measurement(2.5, "veeder_1994"),
            note="unresolved_heat",
        ),
    ),
    # Europa. Ridges, bands and chaos say the shell moves; whether anything
    # erupts through it is thirty years unresolved. Hubble UV emission in
    # 2012, a reinterpreted 1997 Galileo magnetometer perturbation, one night
    # of water vapour out of seventeen searched — nothing repeats.
    "naif-502": BodyActivity(
        volcanism=Volcanism(
            kind=CRYO,
            status="suspected",
            status_sources=("paganini_2019",),
            note="intermittent_plumes",
        ),
        tectonics=Tectonics(
            style="ice_shell_tectonics",
            status="probable",
            sources=("nimmo_2025",),
            note="chaos_and_bands",
        ),
    ),
    # Ganymede. Grooved terrain covering two-thirds of it is extensional
    # tectonics, old — from a pulse of tidal heating around 2 Ga as the
    # Laplace resonance assembled. Nothing since.
    "naif-503": BodyActivity(
        volcanism=Volcanism(
            kind=CRYO,
            status="extinct",
            status_sources=("nimmo_2025",),
            youngest_activity_years=Measurement(2.0e9, "nimmo_2025"),
        ),
        tectonics=Tectonics(
            style="ice_shell_tectonics",
            status="extinct",
            sources=("nimmo_2025",),
            note="grooved_terrain",
        ),
    ),
    # Enceladus. 101 jets located along the four tiger stripes by a 6.5-year
    # imaging survey, throwing 200 kg/s of water vapour into Saturn's E ring
    # from a body 500 km across — the only place a subsurface ocean is being
    # sampled in flight.
    "naif-602": BodyActivity(
        volcanism=Volcanism(
            kind=CRYO,
            status="active",
            status_sources=("porco_2014",),
            plumes=Measurement(101.0, "porco_2014", as_of="Cassini ISS, 6.5 yr survey"),
            plume_mass_kg_per_s=Measurement(200.0, "hansen_2011", range=(170.0, 230.0)),
            endogenic_power_w=Measurement(
                1.58e10, "howett_2011", range=(1.27e10, 1.89e10)
            ),
        ),
        tectonics=Tectonics(
            style="ice_shell_tectonics",
            status="active",
            sources=("porco_2014",),
            note="tiger_stripes",
        ),
    ),
    # Titan. Sotra Patera with Doom and Erebor Montes is the best cryovolcanic
    # candidate on Titan — a depression beside two peaks with flows, seen in
    # radar and infrared together — and the only one that survived
    # re-examination; earlier candidates turned out to be something else, and
    # no model explains the plumbing.
    "naif-606": BodyActivity(
        volcanism=Volcanism(
            kind=CRYO,
            status="suspected",
            status_sources=("lopes_2013",),
            note="candidate_only",
        ),
    ),
    # Triton. Four plumes caught by Voyager 2, dark columns rising 8 km and
    # shearing to trail 100+ km downwind. Driven from inside, or by sunlight
    # warming nitrogen ice under a transparent layer (a solid-state
    # greenhouse, not volcanism) — still open. Either way the surface is
    # ~10 Myr old, so something is resurfacing it.
    "naif-801": BodyActivity(
        volcanism=Volcanism(
            kind=CRYO,
            status="active",
            status_sources=("soderblom_1990",),
            plumes=Measurement(4.0, "soderblom_1990", as_of="Voyager 2, 1989"),
            surface_age_years=Measurement(1.0e7, "nimmo_2025"),
            note="plume_drive_uncertain",
        ),
        tectonics=Tectonics(
            style="ice_shell_tectonics",
            status="probable",
            sources=("nimmo_2025",),
            note="cantaloupe_terrain",
        ),
    ),
    # Charon. Vulcan Planitia is cryovolcanic material that flooded the whole
    # southern hemisphere; its bounding faults record the ocean underneath
    # freezing and expanding. All early, while Charon was still spinning down
    # towards the double-synchronous state it's in now.
    "naif-901": BodyActivity(
        volcanism=Volcanism(
            kind=CRYO,
            status="extinct",
            status_sources=("nimmo_2025",),
        ),
        tectonics=Tectonics(
            style="ice_shell_tectonics",
            status="extinct",
            sources=("nimmo_2025",),
            note="ocean_freezing",
        ),
    ),
    # Pluto. Wright Mons (4-5 km) and Piccard Mons (7 km) sit in hummocky
    # terrain with no impact craters at all — read as overlapping cryovolcanic
    # flows, not two volcanoes. Wright's main rise alone is 2.4×10⁴ km³, about
    # Mauna Loa's volume. What powers it on a body that should have frozen
    # through is unresolved.
    "naif-999": BodyActivity(
        volcanism=Volcanism(
            kind=CRYO,
            status="dormant",
            status_sources=("singer_2022",),
            youngest_activity_years=Measurement(
                1.5e9, "singer_2022", range=(1.0e9, 2.0e9), upper_limit=True
            ),
            note="energy_source_unexplained",
        ),
    ),
    # Ceres. 22 domes shaped like Ahuna Mons but progressively flatter with
    # age — cryovolcanic mountains, mostly ice, relaxing under their own
    # weight. Fitting the flattening gives 10,000 m³/yr (10⁻⁵ km³), a
    # hundred-millionth of Earth's output and still not zero.
    "naif-2000001": BodyActivity(
        volcanism=Volcanism(
            kind=CRYO,
            status="probable",
            status_sources=("sori_2018",),
            erupted_volume_km3_per_year=Measurement(1.0e-5, "sori_2018"),
            known_centres=Measurement(22.0, "sori_2018", as_of="Dawn survey"),
            note="relaxing_domes",
        ),
    ),
    # Vesta. The oldest volcanic record anywhere: the eucrites are basalt from
    # Vesta's surface, crystallised within the first few million years of the
    # solar system. A magma ocean, a crust, then nothing for 4.5 billion years.
    "spkid-20000004": BodyActivity(
        volcanism=Volcanism(
            kind=SILICATE,
            status="extinct",
            status_sources=("mcsween_2013",),
            youngest_activity_years=Measurement(4.5e9, "mcsween_2013"),
            note="basaltic_achondrites",
        ),
    ),
}
