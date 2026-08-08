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
therefore incomplete in ways that show: Rosetta's masses are known and its
specific impulse is not, so it has no derivable Δv, and saying so is the point.
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
    # Masses known, engine not. Rosetta spent 1,670 kg getting to a comet by
    # way of three Earth flybys and one of Mars, and the catalogue can say
    # how much it spent without being able to say how fast it went.
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
        object_ids=("probe-88698880",),
    ),
    Spacecraft(
        id="europa-clipper",
        qid="Q15637513",
        kind="probe",
        propulsion="chemical",
        status="active",
        departs_from=frozenset({"orbit"}),
        power="solar",
        dry_mass_kg=Measured(3241, "gcat_satcat"),
        propellant_mass_kg=Measured(2750, "gcat_satcat"),
        object_ids=("probe-119541760",),
    ),
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
        qid="Q48496",
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
    # descent, ascent and attitude control. No Isp is cited for the descent
    # engine in either source, so the Δv that took two people to the surface
    # and back is not derivable here.
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
        crew=Measured(2, "apollo_11_press_kit"),
        capabilities=frozenset({"landing"}),
        capability_source="apollo_11_press_kit",
    ),
    # --- crewed ------------------------------------------------------------
    # 12,250 lb of command module and 51,243 lb of service module. The service
    # module's dry mass is in neither cited document, so the propellant load
    # cannot be separated out and the SPS Δv is not derivable — the one figure
    # this entry most wants. Entry speed is Apollo 11's own return: 36,194 ft/s
    # off the free-return trajectory, which is what a lunar-return heat shield
    # has to be built for and is well short of a Mars return.
    Spacecraft(
        id="apollo-csm",
        qid="Q680027",
        kind="crewed",
        propulsion="chemical",
        status="retired",
        departs_from=frozenset({"orbit"}),
        power="battery",
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
