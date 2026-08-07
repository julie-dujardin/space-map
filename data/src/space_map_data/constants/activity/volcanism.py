"""Volcanism and tectonics, body by body.

The interesting column here is `status`, not any of the numbers. Whether Venus
is erupting *right now* rests on two surface changes in Magellan's radar and
nothing else; whether the Moon erupted within the last hundred million years
turns on seventy small mounds whose crater counts may be measuring roughness
rather than age. Collapsing that into "active/inactive"
would throw away what the last twenty years of work actually established, so
the vocabulary keeps five rungs and each body's comment says which rung its
evidence reaches and why.

Cryovolcanism is the same word for a different machine — brine and ammonia
where Earth has basalt — and it is given the same fields because the
observables are the same: vents, plumes, a resurfacing rate, an age for the
youngest thing anyone can date.

Counts of active vents are snapshots of surveys and carry `as_of`. Nobody has
counted the volcanoes of any world; they have counted what an instrument
resolved on the days it looked.
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
    # Mercury. Effusive volcanism built the northern smooth plains and then
    # stopped: crater counts put the end of widespread eruption at about
    # 3.5 Ga, the planet having cooled and contracted enough that magma could
    # no longer reach the surface through a lithosphere in compression. The
    # tectonics outlived the volcanism and are the reason — up to 7 km of
    # radial shrinkage taken up in thrust faults, and small scarps crisp enough
    # to be less than 50 Myr old, which makes Mercury the only one-plate planet
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
    # an eruption. The whole direct case is one vent on Maat Mons that went
    # from 2.2 km² and near-circular to 4.0 km² and irregular between two
    # Magellan passes eight months apart in 1991 — and Herrick & Hensley found
    # exactly that one change while examining ~1.5% of the planet's surface,
    # which they read as Venus being less active than Io but not a small
    # fraction of Earth. Radar backscatter changes at Sif Mons and Niobe
    # Planitia are the second, independent detection.
    #
    # The eruption *count* is not a measurement of Venus at all — it is Earth's
    # 1980-2021 record scaled by mass and area — while the erupted volume is,
    # being derived from the cratering record and from atmospheric chemistry;
    # hence one is flagged modelled and the other is not. The surface age is
    # the counterweight: 250 Ma to 1 Ga depending on the crater model, so
    # whatever is happening now, the planet was resurfaced wholesale once and
    # has been mostly quiet since.
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
        # `mobile_lid` records the deformation that is actually mapped —
        # coronae, rifts, the localised trenches — and not a settled regime,
        # because there isn't one. The competing reading has Venus in the
        # quiescent stagnant-lid half of an episodic cycle, which fits the same
        # crater statistics; a third has equilibrium resurfacing under a weak,
        # intrusion-riddled crust. The note is what the panel should say.
        tectonics=Tectonics(
            style="mobile_lid",
            status="probable",
            sources=("gulcher_2020", "gillmann_2024"),
            note="regime_debated",
        ),
    ),
    # Earth. Both counts are the Smithsonian's catalogue rather than physical
    # constants, so each carries the version it was read at, and both are
    # rederived from the downloaded eruption record by `download/providers/
    # gvp.py` and checked against it by the constants test — 1,196 Holocene
    # volcanoes and 79.2 eruptions in an average year over 2010-2024. The 47 TW
    # is the whole planet's heat loss, of which volcanism carries only a
    # fraction — most of it conducts out through the sea floor.
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
        # The only body in this file whose surface is destroyed as fast as it
        # is made.
        tectonics=Tectonics(
            style="plate_tectonics",
            status="active",
            sources=("bird_2003",),
        ),
    ),
    # Moon. Mare volcanism ended around 1 Ga on the usual reading, but seventy
    # irregular mare patches on the nearside have crater counts implying
    # eruptions within the last 100 Myr — contested, since the same
    # morphologies can be made by ancient magmatic foam that never developed a
    # crater-retaining surface. Recorded as extinct with the young date as an
    # upper limit rather than a claim. The thrust scarps are firmer: shallow
    # moonquakes recorded by Apollo cluster near faults young enough to cut
    # small craters, so the Moon is still shrinking.
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
    # Mars. Olympus Mons is the largest volcano in the system and has not
    # erupted in tens of millions of years, but a dark, pyroxene-rich deposit
    # spread symmetrically around a segment of Cerberus Fossae dates to 53 ka
    # — geologically now. InSight then found the same fissure system to be the
    # most seismically active place on the planet. Neither observation is an
    # eruption, which is why this is `suspected` and Venus is `probable`.
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
    # Io. Not a matter of interpretation anywhere: 343 distinct thermal sources
    # in the global map through mid-2023, radiating 57.7 TW between them, out
    # of 105 TW leaving the body. The 47 TW difference — the size of Earth's
    # entire heat flow — is not accounted for by any resolved volcano, which is
    # the standing puzzle: either a great many sources below the resolution
    # limit, or heat conducting out through the plains.
    #
    # The power and the flux are one measurement of Veeder's, and are the same
    # numbers `tidal.py` carries: on Io the observed loss is taken as the
    # production. Neither carries the ±12 TW quoted in later work, which is
    # Davies's restatement rather than an uncertainty Veeder attached.
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
    # erupts through it is thirty years unresolved. Hubble saw ultraviolet
    # emission over the south pole in 2012, Galileo's magnetometer data
    # reinterpreted in 2018 showed a plume-shaped perturbation on a 1997 pass,
    # and a ground-based search found water vapour on one night out of
    # seventeen. Nothing repeats, which is the problem.
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
    # Ganymede. The grooved terrain that covers two-thirds of it is extensional
    # tectonics, and it is old — associated with a pulse of tidal heating
    # around 2 Ga as the Laplace resonance assembled. Nothing since.
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
    # Enceladus. 101 distinct jets located along the four tiger stripes by a
    # 6.5-year imaging survey,
    # throwing 200 kg of water vapour a second into Saturn's E ring, from a
    # body 500 km across. The plume is the only place in the solar system where
    # a subsurface ocean is being sampled in flight.
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
    # candidate anywhere on Titan — a depression beside two peaks with flows
    # running from them, in radar and infrared together. It is also the only
    # one that survived re-examination; several earlier candidates turned out
    # to be something else, and no model explains how the plumbing would work.
    "naif-606": BodyActivity(
        volcanism=Volcanism(
            kind=CRYO,
            status="suspected",
            status_sources=("lopes_2013",),
            note="candidate_only",
        ),
    ),
    # Triton. Four plumes caught in the act by Voyager 2, dark columns rising
    # 8 km and then shearing over to trail more than 100 km downwind. Whether
    # they are driven from inside or by sunlight warming nitrogen ice under a
    # transparent surface layer is still open — the second is a solid-state
    # greenhouse, not volcanism — but either way the surface is about 10 Myr
    # old, so something is resurfacing it.
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
    # Charon. Vulcan Planitia is a plain of cryovolcanic material that flooded
    # the whole southern hemisphere, and the fault system that bounds it
    # records the ocean underneath freezing and expanding. All of it happened
    # early, while Charon was still spinning down towards the double-
    # synchronous state it is in now.
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
    # Pluto. Wright Mons and Piccard Mons are 4-5 km and 7 km high, and the
    # ground around them is a hummocky terrain with no impact craters at all —
    # read as many overlapping cryovolcanic flows rather than as two volcanoes.
    # 2.4×10⁴ km³ in the main rise of Wright alone, about the volume of Mauna
    # Loa. What powers it on a body that should have frozen through is the
    # unresolved part.
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
    # Ceres. Twenty-two domes of the same shape as Ahuna Mons but progressively
    # flatter with age — cryovolcanic mountains relaxing under their own weight
    # because they are mostly ice. Fitting the flattening to the population
    # gives an average extrusion rate of 10,000 m³ a year, which is 10⁻⁵ km³:
    # a hundred-millionth of Earth's volcanic output, and still not zero.
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
    # Vesta's surface, and they crystallised within the first few million years
    # of the solar system. A magma ocean, a crust, and then nothing for 4.5
    # billion years.
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
