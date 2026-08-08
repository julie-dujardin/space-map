"""Spacecraft: what flies once a launcher has let go of it.

Every entry states the rocket equation's inputs rather than a Δv, so the panel
can show its working. Two conventions make those inputs comparable:

* `propellant_mass_kg` is the load spent through the engine whose Isp is
  quoted, and nothing else. An ion craft carrying hydrazine for attitude
  control counts that hydrazine as dry mass — spending it at 3,100 s when it
  burns at 230 would inflate Dawn's Δv by two kilometres a second.
* Masses are the flight article at launch. Where a mission flew twice with the
  same design, the entry describes the design and links both spacecraft.

A figure with no source is not written down. Several entries below are
therefore incomplete in ways that show: nobody publishes an Isp for the Draco
thruster, so Crew Dragon has masses and no derivable Δv, and saying so is the
point.

Where an engine is not named by its mission, it is identified by what the
mission does publish — thrust and propellants — and the identification is
stated next to the number rather than buried in it.
"""

from space_map_data.constants.spacecraft.specs import Cost, Measured, Spacecraft

SPACECRAFT: tuple[Spacecraft, ...] = (
    # --- outer-planet probes ---------------------------------------------
    # Voyager's 104 kg of hydrazine is the whole reason both spacecraft are
    # still pointed at Earth fifty years on: the trajectory was bought by
    # Jupiter and Saturn, and the propellant only ever had to hold the
    # attitude. GCAT pairs the airframe with an MR-104; the difference between
    # that and the MR-103 thrusters is 12 s of Isp and 16 m/s of the answer.
    Spacecraft(
        id="voyager-1",
        qid="Q48469",
        kind="probe",
        propulsion="chemical",
        status="active",
        departs_from=frozenset({"orbit"}),
        power="rtg",
        dry_mass_kg=Measured(716, "gcat_satcat"),
        propellant_mass_kg=Measured(104, "gcat_satcat"),
        isp_s=Measured(239.0, "gcat_engines"),
        object_ids=("probe-49065984", "probe-49000448"),
    ),
    # Three fifths of Cassini's launch mass was propellant, which is what
    # arriving at Saturn rather than flying past it costs. GCAT lists the main
    # engines as R-4D-12 and tabulates the R-4D-11's performance; the family's
    # Isp is what the number below is.
    Spacecraft(
        id="cassini",
        qid="Q2941291",
        kind="probe",
        propulsion="chemical",
        status="retired",
        departs_from=frozenset({"orbit"}),
        power="rtg",
        dry_mass_kg=Measured(2125, "gcat_satcat"),
        propellant_mass_kg=Measured(3129, "gcat_satcat"),
        isp_s=Measured(315.5, "gcat_engines"),
        thrust_n=Measured(490.0, "gcat_engines"),
        object_ids=("probe-88592384",),
    ),
    Spacecraft(
        id="juno",
        qid="Q48546",
        kind="probe",
        propulsion="chemical",
        status="active",
        departs_from=frozenset({"orbit"}),
        # The furthest solar-powered spacecraft ever flown, and the reason it
        # needed three panels nine metres long.
        power="solar",
        dry_mass_kg=Measured(1593, "gcat_satcat"),
        propellant_mass_kg=Measured(2032, "gcat_satcat"),
        isp_s=Measured(318.0, "gcat_engines"),
        thrust_n=Measured(670.0, "gcat_engines"),
        object_ids=("probe-107159552",),
    ),
    # 77 kg of hydrazine on a 478 kg spacecraft: New Horizons was thrown at
    # Pluto and never slowed down. The whole Δv below is course correction.
    Spacecraft(
        id="new-horizons",
        qid="Q48461",
        kind="probe",
        propulsion="chemical",
        status="active",
        departs_from=frozenset({"orbit"}),
        power="rtg",
        dry_mass_kg=Measured(401, "gcat_satcat"),
        propellant_mass_kg=Measured(77, "gcat_satcat"),
        isp_s=Measured(227.0, "gcat_engines"),
        object_ids=("probe-104804352",),
    ),
    # The counter-example to every impulsive assumption in the solver. Dawn
    # carried more Δv than any spacecraft ever flown and could only spend it
    # at 92 millinewtons — five years of thrusting to orbit two asteroids in
    # turn. Dry mass here is the 747 kg airframe plus its 46 kg of attitude
    # hydrazine, because the Δv below is the xenon's alone.
    Spacecraft(
        id="dawn",
        qid="Q48558",
        kind="probe",
        propulsion="electric",
        status="retired",
        departs_from=frozenset({"orbit"}),
        power="solar",
        dry_mass_kg=Measured(793, "gcat_satcat"),
        propellant_mass_kg=Measured(425, "rayman_2006_dawn"),
        isp_s=Measured(3100.0, "rayman_2006_dawn"),
        thrust_n=Measured(0.092, "rayman_2006_dawn"),
        object_ids=("probe-101912576",),
    ),
    # Hall thrusters rather than gridded ions: half the specific impulse, more
    # thrust per kilowatt, and the first of either flown beyond the Moon.
    Spacecraft(
        id="psyche",
        qid="Q21079313",
        kind="probe",
        propulsion="electric",
        status="active",
        departs_from=frozenset({"orbit"}),
        power="solar",
        dry_mass_kg=Measured(1662, "nasa_psyche_spacecraft"),
        propellant_mass_kg=Measured(1085, "nasa_psyche_spacecraft"),
        isp_s=Measured(1820.0, "snyder_2019_psyche_ep"),
        thrust_n=Measured(0.24, "nasa_psyche_spacecraft"),
        object_ids=("probe-118050816",),
    ),
    # Rosetta had no main engine: 1,670 kg went out through twenty-four 10 N
    # thrusters over eleven years, three Earth flybys and one of Mars. The
    # manufacturer's flight-heritage list is what names the mission, and 292 s
    # reproduces the 2.3 km/s ESA budgeted for the trip.
    Spacecraft(
        id="rosetta",
        qid="Q48572",
        kind="probe",
        propulsion="chemical",
        status="retired",
        departs_from=frozenset({"orbit"}),
        power="solar",
        dry_mass_kg=Measured(1295, "gcat_satcat"),
        propellant_mass_kg=Measured(1670, "gcat_satcat"),
        isp_s=Measured(292.0, "ariane_10n_thruster"),
        object_ids=("probe-88698880",),
    ),
    # Dry mass is the flight system overview's 5,892 kg at launch less the
    # 2,750 kg of propellant the same paper says the tanks hold and were
    # filled to "nearly".
    #
    # The engine is the one inference in the catalogue. No Clipper document
    # names a thruster model — the paper gets as far as twenty-four at 27.5 N
    # burning MMH/MON-3, in modules built at Goddard — and exactly one
    # catalogue thruster is 27.5 N on those propellants. Its quoted figure is
    # a *minimum* Isp, so the Δv below is a floor twice over.
    Spacecraft(
        id="europa-clipper",
        qid="Q15637513",
        kind="probe",
        propulsion="chemical",
        status="active",
        departs_from=frozenset({"orbit"}),
        power="solar",
        dry_mass_kg=Measured(3142, "srinivasan_2025_clipper"),
        propellant_mass_kg=Measured(2750, "srinivasan_2025_clipper"),
        isp_s=Measured(297.0, "moog_biprop_thrusters"),
        object_ids=("probe-119541760",),
    ),
    # Twelve MR-111C thrusters, per the manufacturer, which is the same family
    # New Horizons flies and the same reason both entries take their specific
    # impulse from the engine catalogue rather than the mission.
    Spacecraft(
        id="parker-solar-probe",
        qid="Q899091",
        kind="probe",
        propulsion="chemical",
        status="active",
        departs_from=frozenset({"orbit"}),
        power="solar",
        dry_mass_kg=Measured(605, "gcat_satcat"),
        propellant_mass_kg=Measured(80, "gcat_satcat"),
        isp_s=Measured(229.0, "gcat_engines"),
        object_ids=("probe-110309376",),
    ),
    # Over half its launch mass was propellant, spent on six flybys and an
    # orbit insertion — Mercury is the hardest place in the inner system to
    # stop at, and this is what stopping costs.
    Spacecraft(
        id="messenger",
        qid="Q182539",
        kind="probe",
        propulsion="chemical",
        status="retired",
        departs_from=frozenset({"orbit"}),
        power="solar",
        dry_mass_kg=Measured(513, "gcat_satcat"),
        propellant_mass_kg=Measured(595, "gcat_satcat"),
        isp_s=Measured(318.0, "gcat_engines"),
        thrust_n=Measured(670.0, "gcat_engines"),
        object_ids=("probe-89325568",),
    ),
    # --- landers -----------------------------------------------------------
    # The rover is 899 kg of the 3,839 kg that hit the atmosphere; the rest is
    # heat shield, parachute and sky crane, and none of it arrives. A lander
    # entry is about what survives, so the mass below is the rover.
    #
    # It departs from nowhere. A rover is cargo — the trip it can be offered
    # against is the one that delivers it, not one it flies.
    Spacecraft(
        id="curiosity",
        # The rover, not the mission that delivered it — Q48496 is the Mars
        # Science Laboratory, and the mass below is Curiosity's own.
        qid="Q48485",
        kind="lander",
        propulsion="chemical",
        status="active",
        departs_from=frozenset(),
        power="rtg",
        dry_mass_kg=Measured(899, "gcat_satcat"),
        capabilities=frozenset({"entry", "landing"}),
        capability_source="gcat_satcat",
        object_ids=("probe-100265984",),
    ),
    Spacecraft(
        id="perseverance",
        qid="Q87749354",
        kind="lander",
        propulsion="chemical",
        status="active",
        departs_from=frozenset(),
        power="rtg",
        dry_mass_kg=Measured(1025, "gcat_satcat"),
        capabilities=frozenset({"entry", "landing"}),
        capability_source="gcat_satcat",
        object_ids=("probe-113246208",),
    ),
    # The only crewed lander ever flown, and the press kit breaks it down to
    # the pound: 9,287 lb of structure against 23,918 lb of propellant across
    # descent, ascent and attitude control. Three quarters of that load went
    # through the descent engine, so its specific impulse is the one quoted —
    # the ascent engine's is within a second of it.
    #
    # Understated more than the usual ideal-Δv caveat, because the LM threw
    # away the descent stage halfway: one stage carrying the whole load is
    # about a kilometre a second short of what the two actually managed.
    #
    # The only craft in the catalogue to have flown both departures: descent
    # stage down from lunar orbit, ascent stage up off the surface.
    Spacecraft(
        id="apollo-lm",
        qid="Q208382",
        kind="lander",
        propulsion="chemical",
        status="retired",
        departs_from=frozenset({"surface", "orbit"}),
        power="battery",
        dry_mass_kg=Measured(4213, "apollo_11_press_kit"),
        propellant_mass_kg=Measured(10848, "apollo_11_press_kit"),
        isp_s=Measured(305.0, "nasa_ter_dps_1973"),
        crew=Measured(2, "apollo_11_press_kit"),
        capabilities=frozenset({"landing"}),
        capability_source="apollo_11_press_kit",
    ),
    # --- crewed ------------------------------------------------------------
    # 12,250 lb of command module and 51,243 lb of service module, so 28,800 kg
    # off the pad. No Apollo document states the service module's dry mass; the
    # mission report states the other side of the same subtraction, the SPS
    # load gauged before lift-off at 15,712 lb of fuel and 25,091 lb of
    # oxidizer. Dry mass below is the launch weight less that 40,803 lb.
    #
    # 3.2 km/s is the capsule flying alone and reads high against the ~2.8 that
    # gets quoted, which is the stack with a lunar module bolted to the front.
    #
    # Entry speed is Apollo 11's own return: 36,194 ft/s off the free-return
    # trajectory, which is what a lunar-return heat shield has to be built for
    # and is well short of a Mars return.
    Spacecraft(
        id="apollo-csm",
        qid="Q680027",
        kind="crewed",
        propulsion="chemical",
        status="retired",
        departs_from=frozenset({"orbit"}),
        power="battery",
        dry_mass_kg=Measured(10292, "apollo_11_press_kit"),
        propellant_mass_kg=Measured(18508, "apollo_11_mission_report"),
        isp_s=Measured(314.0, "gcat_engines"),
        thrust_n=Measured(91190.0, "apollo_11_press_kit"),
        crew=Measured(3, "apollo_11_press_kit"),
        max_entry_speed_kms=Measured(11.03, "apollo_11_press_kit"),
        capabilities=frozenset({"entry", "crew_return"}),
        capability_source="apollo_11_press_kit",
        group_slug="const-apollo",
    ),
    # Dry mass is the Artemis I post-TLI mass less the usable propellant, both
    # from the reference guide's own numbers table. The main engine is a flown
    # Shuttle OMS engine, which is where its specific impulse comes from.
    Spacecraft(
        id="orion",
        qid="Q211727",
        kind="crewed",
        propulsion="chemical",
        status="active",
        departs_from=frozenset({"orbit"}),
        power="solar",
        dry_mass_kg=Measured(15422, "nasa_orion_reference_2022"),
        propellant_mass_kg=Measured(8618, "nasa_orion_reference_2022"),
        isp_s=Measured(316.0, "gcat_engines"),
        thrust_n=Measured(26600.0, "gcat_engines"),
        crew=Measured(4, "nasa_orion_reference_2022"),
        endurance_days=Measured(21, "nasa_orion_reference_2022"),
        max_entry_speed_kms=Measured(11.18, "nasa_orion_reference_2022"),
        capabilities=frozenset({"entry", "crew_return"}),
        capability_source="nasa_orion_reference_2022",
        # The capsule and its European service module, priced separately by
        # the OIG because ESA supplies the second under a barter agreement.
        cost=Cost(1300.0, 2021, "unit", "nasa_oig_2021"),
    ),
    # Both masses published, no specific impulse anywhere: SpaceX has never
    # stated one for the Draco, and the engine catalogues that carry its thrust
    # leave the column empty. So no Δv, on a capsule that has flown people
    # dozens of times.
    Spacecraft(
        id="crew-dragon",
        qid="Q105095031",
        kind="crewed",
        propulsion="chemical",
        status="active",
        departs_from=frozenset({"orbit"}),
        power="solar",
        dry_mass_kg=Measured(9500, "gcat_satcat"),
        propellant_mass_kg=Measured(1255, "gcat_satcat"),
        capabilities=frozenset({"entry", "crew_return"}),
        capability_source="gcat_satcat",
        group_slug="const-crew-dragon",
    ),
    # Masses are Columbia's on STS-1. An orbiter's whole Δv is two engines and
    # about 300 m/s of it — everything else about where it went was decided
    # before the solid boosters let go.
    Spacecraft(
        id="space-shuttle-orbiter",
        qid="Q1064394",
        kind="crewed",
        propulsion="chemical",
        status="retired",
        departs_from=frozenset({"orbit"}),
        power="battery",
        dry_mass_kg=Measured(83869, "gcat_satcat"),
        propellant_mass_kg=Measured(5870, "gcat_satcat"),
        isp_s=Measured(316.0, "gcat_engines"),
        # Per engine; the orbiter carries two.
        thrust_n=Measured(27000.0, "gcat_engines"),
        capabilities=frozenset({"entry", "crew_return"}),
        capability_source="gcat_satcat",
    ),
    # Included with no performance figures at all, deliberately. Every mass
    # and specific impulse in circulation for Starship traces to a slide or a
    # remark rather than to a document, and the vehicle has not flown the
    # configuration those figures describe.
    #
    # The departures are the exception to that silence, because they are a
    # statement about the airframe rather than a number: it lands on its
    # engines and lifts off again, which is the whole design. Leaving Earth it
    # still needs a booster under it; leaving the Moon it does not.
    Spacecraft(
        id="starship",
        qid="Q62833385",
        kind="crewed",
        propulsion="chemical",
        status="concept",
        departs_from=frozenset({"surface", "orbit"}),
    ),
)
