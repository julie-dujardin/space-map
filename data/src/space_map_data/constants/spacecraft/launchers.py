"""Launch vehicles, described by the only thing a departure needs from them:
how much mass they can throw at a given escape energy.

One entry per *configuration*, not per rocket. A Falcon Heavy that recovers
its boosters delivers less than half the payload of one that does not at every
energy above about C3 = 20, and a Star-48 kick stage does not scale a curve so
much as replace its top end. Treating those as one vehicle with a footnote
would make the selector lie in exactly the cases that matter.

Every entry here departs from a pad and nowhere else, and says so per entry
rather than inheriting it from `kind` — a default that quiet would be exactly
where a vehicle that also flies off the Moon would hide.

Curves come from two places. NASA's SLS Mission Planner's Guide tabulates its
own, so those points are written out here. The rest are the digitised NASA
Launch Services Program curves the launch-performance downloader fetches, named
by dataset id — a hundred points per vehicle belongs in a file, not a module.
Everything else on this page publishes payload to LEO and to GTO and refers
escape questions to the manufacturer, which is why several well-known rockets
below carry no curve at all rather than an invented one.
"""

from space_map_data.constants.spacecraft.specs import C3Curve, Cost, Spacecraft

# SLS Mission Planner's Guide Table 4-1, "Useful PSM to Earth Escape", read off
# the tonnes column. Block 1B is published as a band because its development
# path was not settled; the lower edge is taken, so the catalogue never claims
# more than the document guarantees. The negative energies are trans-lunar
# injections — a C3 of -0.99 is TLI, and the curve is defined there because
# not every departure leaves Earth behind.
_SLS_BLOCK_1_POINTS = (
    (-0.99, 27200.0),
    (0.0, 26600.0),
    (10.0, 21800.0),
    (20.0, 17900.0),
    (30.0, 14800.0),
    (40.0, 12300.0),
    (50.0, 10200.0),
    (60.0, 8400.0),
    (70.0, 6900.0),
    (80.0, 5600.0),
    (90.0, 4500.0),
    (100.0, 3600.0),
    (110.0, 2700.0),
    (120.0, 2000.0),
    (130.0, 1400.0),
    (140.0, 800.0),
)

_SLS_BLOCK_1B_POINTS = (
    (-20.0, 50600.0),
    (-10.0, 43300.0),
    (-0.99, 37600.0),
    (0.0, 37000.0),
    (10.0, 31600.0),
    (20.0, 26800.0),
    (30.0, 22500.0),
    (40.0, 18700.0),
    (50.0, 15300.0),
    (60.0, 12300.0),
    (70.0, 9600.0),
    (80.0, 7200.0),
    (90.0, 5100.0),
    (100.0, 3200.0),
    (110.0, 1400.0),
)


LAUNCHERS: tuple[Spacecraft, ...] = (
    # The workhorse of two decades of planetary missions, in its bare
    # configuration: no solid boosters, four-metre fairing. New Horizons flew
    # the five-solid version of the same rocket with a third stage on top.
    Spacecraft(
        id="atlas-v-401",
        qid="Q20803939",
        kind="launcher",
        propulsion="chemical",
        status="active",
        departs_from=frozenset({"surface"}),
        c3_curve=C3Curve(source="girija_2023", dataset="atlas-v401"),
        # What NASA paid to fly Lucy, launch service plus the mission-related
        # costs the award covers. Not a list price — nobody publishes one.
        cost=Cost(148.3, 2019, "launch_service", "nasa_lsp_lucy_2019"),
        group_slug="lv-atlas",
    ),
    Spacecraft(
        id="atlas-v-551",
        qid="Q16352007",
        kind="launcher",
        propulsion="chemical",
        status="active",
        departs_from=frozenset({"surface"}),
        c3_curve=C3Curve(source="girija_2023", dataset="atlas-v551"),
        cost=Cost(150.0, 2023, "launch_service", "girija_2023"),
        group_slug="lv-atlas",
    ),
    # The same rocket with a solid third stage. It buys nothing below about
    # C3 = 40 and roughly doubles the payload above 80 — which is the only
    # reason New Horizons reached Pluto in nine years.
    Spacecraft(
        id="atlas-v-551-star-48",
        qid="Q16352007",
        kind="launcher",
        variant=("star-48",),
        propulsion="chemical",
        status="active",
        departs_from=frozenset({"surface"}),
        c3_curve=C3Curve(source="girija_2023", dataset="atlas-v551-star-48"),
        group_slug="lv-atlas",
    ),
    Spacecraft(
        id="delta-iv-heavy",
        qid="Q249492",
        kind="launcher",
        propulsion="chemical",
        status="retired",
        departs_from=frozenset({"surface"}),
        c3_curve=C3Curve(source="girija_2023", dataset="delta-iv-heavy"),
        group_slug="lv-delta",
    ),
    Spacecraft(
        id="delta-iv-heavy-star-48",
        qid="Q249492",
        kind="launcher",
        variant=("star-48",),
        propulsion="chemical",
        status="retired",
        departs_from=frozenset({"surface"}),
        c3_curve=C3Curve(source="girija_2023", dataset="delta-iv-heavy-star-48"),
        group_slug="lv-delta",
    ),
    # Fully expended: no landing legs, no boost-back, nothing recovered. This
    # is the configuration Europa Clipper flew and the one the price below
    # bought.
    Spacecraft(
        id="falcon-heavy-expendable",
        qid="Q1093627",
        kind="launcher",
        variant=("expendable",),
        propulsion="chemical",
        status="active",
        departs_from=frozenset({"surface"}),
        c3_curve=C3Curve(source="girija_2023", dataset="falcon-heavy-expendable"),
        cost=Cost(178.0, 2021, "launch_service", "nasa_lsp_clipper_2021"),
        group_slug="lv-falcon",
    ),
    Spacecraft(
        id="falcon-heavy-expendable-star-48",
        qid="Q1093627",
        kind="launcher",
        variant=("expendable", "star-48"),
        propulsion="chemical",
        status="active",
        departs_from=frozenset({"surface"}),
        c3_curve=C3Curve(
            source="girija_2023", dataset="falcon-heavy-expendable-star-48"
        ),
        group_slug="lv-falcon",
    ),
    # Boosters recovered. The curve ends at C3 = 64 rather than 100: the
    # propellant held back to fly three cores home is propellant the payload
    # does not get, and past that energy the vehicle simply stops.
    Spacecraft(
        id="falcon-heavy-reusable",
        qid="Q1093627",
        kind="launcher",
        variant=("reusable",),
        propulsion="chemical",
        status="active",
        departs_from=frozenset({"surface"}),
        c3_curve=C3Curve(source="girija_2023", dataset="falcon-heavy-reusable"),
        group_slug="lv-falcon",
    ),
    # Six solid boosters, the heaviest Vulcan. The digitised curve reads
    # 7,578 kg at C3 = 20 against the 7,600 kg ULA's own user's guide states,
    # which is the check that the whole digitised set is trustworthy.
    Spacecraft(
        id="vulcan-vc6",
        qid="Q19816744",
        kind="launcher",
        propulsion="chemical",
        status="active",
        departs_from=frozenset({"surface"}),
        c3_curve=C3Curve(
            source="girija_2023",
            dataset="vulcan-vc6",
            cross_check="ula_vulcan_2023",
        ),
        cost=Cost(150.0, 2023, "launch_service", "girija_2023"),
        group_slug="lv-vulcan",
    ),
    Spacecraft(
        id="vulcan-vc6-star-48",
        qid="Q19816744",
        kind="launcher",
        variant=("star-48",),
        propulsion="chemical",
        status="active",
        departs_from=frozenset({"surface"}),
        c3_curve=C3Curve(source="girija_2023", dataset="vulcan-vc6-star-48"),
        group_slug="lv-vulcan",
    ),
    # The cost is the production cost of one expended SLS. The flight it flies
    # on costs $4.1B once Orion and the ground systems are counted, which is a
    # different number about a different thing.
    Spacecraft(
        id="sls-block-1",
        qid="Q109943270",
        kind="launcher",
        propulsion="chemical",
        status="active",
        departs_from=frozenset({"surface"}),
        c3_curve=C3Curve(source="sls_mpg_2018", points=_SLS_BLOCK_1_POINTS),
        cost=Cost(2200.0, 2021, "unit", "nasa_oig_2021"),
        group_slug="lv-sls",
    ),
    Spacecraft(
        id="sls-block-1b",
        qid="Q109943307",
        kind="launcher",
        propulsion="chemical",
        # Cancelled in 2026. The curve stays: what the Mission Planner's Guide
        # published is still what was published, and a vehicle that was going
        # to be able to do this is a more useful thing to say than silence.
        status="cancelled",
        departs_from=frozenset({"surface"}),
        c3_curve=C3Curve(source="sls_mpg_2018", points=_SLS_BLOCK_1B_POINTS),
        group_slug="lv-sls",
    ),
    # No curve below this line. Each of these publishes payload to LEO and to
    # GTO and answers escape questions privately, so the catalogue says it does
    # not know rather than interpolating one from a mass-to-Mars headline.
    Spacecraft(
        id="falcon-9",
        qid="Q249091",
        kind="launcher",
        propulsion="chemical",
        status="active",
        departs_from=frozenset({"surface"}),
        group_slug="lv-falcon",
    ),
    Spacecraft(
        id="saturn-v",
        qid="Q54363",
        kind="launcher",
        propulsion="chemical",
        status="retired",
        departs_from=frozenset({"surface"}),
        group_slug="lv-saturn",
    ),
    Spacecraft(
        id="new-glenn",
        qid="Q26869616",
        kind="launcher",
        propulsion="chemical",
        status="active",
        departs_from=frozenset({"surface"}),
        group_slug="lv-new-glenn",
    ),
    Spacecraft(
        id="long-march-5",
        qid="Q787531",
        kind="launcher",
        propulsion="chemical",
        status="active",
        departs_from=frozenset({"surface"}),
        group_slug="lv-long-march",
    ),
)
