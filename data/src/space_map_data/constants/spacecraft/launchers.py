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

Curves come from three places. NASA's SLS Mission Planner's Guide tabulates its
own and Saturn V's was traced off a chart, so those points are written out
here. The rest are the digitised NASA Launch Services Program curves the
launch-performance downloader fetches, named by dataset id — a hundred points
per vehicle belongs in a file, not a module. Three well-known rockets below
carry no curve at all, because nobody has published a single point on theirs.
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

# Figure IV-7 of the Saturn V Payload Planner's Guide, "payload vs velocity
# capability", read off the 90° azimuth curve — due east from the Cape, which
# is both the standard ascent and the one the guide's own summary quotes when
# it says the vehicle throws about 98,000 lb to escape.
#
# The figure plots payload against V∞ rather than C3, and the guide's legend
# leader arrows cross the curves over the middle of the range. So it is read at
# twenty-one clean columns and a rocket-equation curve fitted through them
# fills the gap; every reading lands inside 3% of the fit, and the fit's free
# parameters come out at 16.2 t of inert mass and an Isp of 430 s, which are
# the S-IVB with its instrument unit and the J-2's own 421 s. A curve traced
# off a scanned 1965 chart reproducing the stage that flew it is the check that
# the trace is real.
#
# Conservative twice over: this is the 1965 vehicle rather than the uprated one
# that flew from Apollo 8 on, and the curve stops at the last clean reading
# rather than at the vehicle's true ceiling near C3 = 138.
_SATURN_V_POINTS = (
    (-2.0, 45520.0),
    (0.0, 44180.0),
    (5.0, 40980.0),
    (10.0, 38010.0),
    (20.0, 32680.0),
    (30.0, 28020.0),
    (40.0, 23940.0),
    (50.0, 20350.0),
    (60.0, 17160.0),
    (70.0, 14330.0),
    (80.0, 11810.0),
    (90.0, 9550.0),
    (100.0, 7510.0),
    (110.0, 5680.0),
    (120.0, 4020.0),
)

# The one curve here that was rebuilt rather than read. SpaceX's documents
# publish no escape performance for Falcon 9, but the website advertises
# "payload to Mars: 4,020 kg" — one point past escape, which is all the
# rocket-equation model needs. Anchor a stage there (taken as C3 = 10, with
# effective Isp and inert mass fitted from the Falcon Heavy expendable curve —
# the second stage is the same hardware) and it reproduces the site's own GTO
# figure to 1.4%: the three advertised numbers are one curve, and this is it.
#
# Two honest limits. The points stop at C3 = 45 because rebuilding a sibling's
# known curve the same way (Atlas V 401 → 551, shared Centaur) holds to 5% out
# to there and falls apart past it. And the whole curve is on SpaceX's
# advertised accounting: for Falcon Heavy that accounting sits about a third
# above the NASA-certified curve at Mars energies — Europa Clipper's 6,065 kg
# at C3 = 41.7 hugs the certified curve, not the website's — so against the
# girija_2023 vehicles this curve reads optimistic, and says so in its source.
_FALCON_9_POINTS = (
    (-2.0, 5720.0),
    (0.0, 5410.0),
    (5.0, 4680.0),
    (10.0, 4020.0),
    (15.0, 3410.0),
    (20.0, 2850.0),
    (25.0, 2340.0),
    (30.0, 1860.0),
    (35.0, 1430.0),
    (40.0, 1020.0),
    (45.0, 650.0),
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
    # Apollo's rocket, and the only one here whose curve had to be read off a
    # chart rather than a table. At trans-lunar injection it gives 45,400 kg
    # against the 45,700 kg Apollo 11 actually left orbit with, which is the
    # closest thing to a flight check any curve in this file has.
    Spacecraft(
        id="saturn-v",
        qid="Q54363",
        kind="launcher",
        propulsion="chemical",
        status="retired",
        departs_from=frozenset({"surface"}),
        c3_curve=C3Curve(
            source="saturn_v_planners_guide_1965", points=_SATURN_V_POINTS
        ),
        group_slug="lv-saturn",
    ),
    # Fully expended, which is the configuration the website's figures are
    # for. The curve is the rebuilt one — see _FALCON_9_POINTS.
    Spacecraft(
        id="falcon-9-expendable",
        qid="Q249091",
        kind="launcher",
        variant=("expendable",),
        propulsion="chemical",
        status="active",
        departs_from=frozenset({"surface"}),
        c3_curve=C3Curve(
            source="spacex_vehicle_pages_2026",
            points=_FALCON_9_POINTS,
            truncated=True,
        ),
        group_slug="lv-falcon",
    ),
    # No curve below this line, and the reason is the same for both: each
    # publishes payload to LEO and to GTO and nothing above them.
    #
    # Those two are points on this curve — a 185 km circular orbit is C3 = -61
    # and a standard GTO is C3 = -16 — but they are the wrong two. Fitting the
    # stage to them and extrapolating overshoots the digitised curves of the
    # vehicles that do publish escape performance by 9% at C3 = 0 and by up to
    # 90% at C3 = 40, always high, because a headline to LEO is a different
    # ascent flown for a different customer. Anchor the same fit on a point
    # that is already past escape and it reproduces those curves to a few
    # percent — which is how Falcon 9 above got its curve, and neither of
    # these two has ever published a number past escape anywhere. Until one
    # appears the export drops them: every route would answer "no published
    # figure", and the entries stay here so the number has somewhere to land.
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
