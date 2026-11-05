"""Real cases of the rules of a bound system. Each class names its rule, and each
fixture holds the values of the registry and the catalogues."""

import math

import pyarrow.compute as pc

from space_map_data.extrasolar import sky
from space_map_data.extrasolar.systems.build import build
from space_map_data.extrasolar.systems.groups import GROUP_LEAVES
from space_map_data.extrasolar.systems.msc import msc_nodes
from space_map_data.extrasolar.systems.nodes import MSC_ID, SIMBAD, VISUAL_ORBIT
from space_map_data.extrasolar.systems.parallax import (
    MOTION,
    WIDE,
    excess,
    projected,
    unbound,
)
from space_map_data.extrasolar.systems.prepare import (
    Inputs,
    match_rows,
    place_guard,
)
from space_map_data.extrasolar.systems.reduce import (
    UNBOUND,
    WRONG_OBJECT,
    Reduced,
)
from space_map_data.extrasolar.systems.simbad import read_simbad
from tests.extrasolar.systems_fakes import (
    FakeResolver,
    fact,
    msc_comp,
    msc_pair,
    simbad_index,
    simbad_object,
    wds_catalogue,
    wds_component,
    wds_pair,
)
from tests.extrasolar.test_systems_bound import facts, kinds, one, reduced


def real(
    key: int,
    place: tuple[float, float],
    mag: float,
    parallax: tuple[float, float],
    motion: tuple[float, float, float, float],
    distance: float | None = None,
) -> dict:
    """A star of the registry: its parallax and motion with their errors."""
    return fact(
        key,
        *place,
        mag,
        "gaia-dr3",
        parallax[0],
        distance,
        parallax_error=parallax[1],
        pmra=motion[0],
        pmdec=motion[1],
        pmra_error=motion[2],
        pmdec_error=motion[3],
    )


class Test47Tuc:
    """`read_simbad` takes star-type nodes: SIMBAD links 3,612 members to NGC 104,
    and the site read that as a system of 41 stars."""

    def test_a_cluster_is_no_system(self):
        index = simbad_index(
            [
                simbad_object(3280200, "NGC 104", 6.022329, -72.081444, otype="GlC"),
                simbad_object(3279889, "Cl* NGC 104 R 21", 5.780614, -72.008171),
                simbad_object(
                    3279529, "Cl* NGC 104 SAW V7", 6.335727, -72.111105, otype="LP*"
                ),
            ],
            [(3280200, 3279889), (3280200, 3279529)],
        )
        resolver = FakeResolver(
            {("simbad", "oid", "3279889"): 25307627, ("simbad", "oid", "3279529"): 1},
            [
                real(
                    25307627,
                    (5.780614, -72.008171),
                    10.608248,
                    (0.197544, 0.011832),
                    (4.702803, -2.658804, 0.013022, 0.014894),
                ),
                real(
                    1,
                    (6.335727, -72.111105),
                    10.850767,
                    (0.202762, 0.014406),
                    (5.533483, -2.146732, 0.015031, 0.018459),
                ),
            ],
        )
        table = read_simbad(index.stars)
        systems = build(Inputs(simbad=table, simbad_index=index), resolver)
        assert not table.num_rows
        assert not systems.nodes.num_rows

    def test_a_cluster_under_a_star_is_no_node(self):
        index = simbad_index(
            [
                simbad_object(1, "HD 1", 10.0, 10.0),
                simbad_object(2, "NGC 1", 10.0, 10.1, otype="GlC"),
                simbad_object(3, "HD 3", 10.0, 10.2),
            ],
            [(1, 2), (1, 3)],
        )
        assert read_simbad(index.stars)["label"].to_pylist() == ["HD 1", "HD 3"]


class TestTonantzintla2:
    """`_own` and the width: SIMBAD resolved open cluster Ton 2 to the sdB star
    Tonantzintla 2 (2025A&A...703A.267G), 150° away, so its members hang below a
    star-type parent."""

    SDB = real(
        555228920,
        (114.518945, 26.412436),
        14.568084,
        (0.848013, 0.044918),
        (-1.520373, -9.319988, 0.046755, 0.039997),
        1179.22673,
    )
    MEMBER_1 = real(
        3248847218,
        (264.001404, -38.587539),
        14.69269,
        (0.059213, 0.048386),
        (-6.022476, -0.690769, 0.066199, 0.047349),
        7343.574707,
    )
    MEMBER_2 = real(
        2711976305,
        (264.059213, -38.576983),
        14.939872,
        (0.070269, 0.039059),
        (-5.8426, -0.744019, 0.049024, 0.038084),
        7343.574707,
    )

    def test_no_system_stays(self):
        rows = [
            ("GALEX J073804.5+262444", -1, None, None, None),
            ("2MASS J17360034-3835151", 0, None, None, None),
            ("2MASS J17361421-3834371", 0, 167.06, None, None),
        ]
        out = reduced(
            rows,
            [
                [(self.SDB["key"], 2)],
                [(self.MEMBER_1["key"], 2)],
                [(self.MEMBER_2["key"], 2)],
            ],
            [self.SDB, self.MEMBER_1, self.MEMBER_2],
            source=SIMBAD,
        )
        assert not out.groups
        assert GROUP_LEAVES in kinds(out)
        assert f"{UNBOUND}: {WIDE}" in kinds(out)


class Test11Ari:
    """`place_guard`: Aa of WDS 02068+2542 lists a Gaia id 5° off, far from the id
    and from its row, so 11 Ari lost its own place to a star at 860 pc."""

    W = "02068+2542"
    ARIETIS = real(
        16969009,
        (31.705235, 25.704498),
        5.998091,
        (3.953423, 0.047739),
        (18.23184, -13.091672, 0.059497, 0.043505),
    )
    B = real(
        553839921,
        (31.705064, 25.704959),
        10.186767,
        (4.053556, 0.044594),
        (19.696218, -11.774127, 0.059513, 0.036742),
    )
    OFF = real(
        16948555,
        (31.894938, 20.651345),
        13.081279,
        (1.163487, 0.016909),
        (10.275043, 2.686537, 0.024015, 0.017297),
    )

    def test_the_star_5_degrees_off_leaves(self):
        catalogue = wds_catalogue(
            {
                self.W: [
                    wds_pair("A", "B", 1.8, notes="", mag1=6.0, mag2=11.5),
                    wds_pair("Aa", "Ab", 0.1, notes="", mag1=13.7, mag2=13.7),
                ]
            },
            {
                (self.W, "A"): wds_component(105439557331202560, 31.705083, 25.704583),
                (self.W, "Aa"): wds_component(94195126792018688, 31.705083, 25.704583),
                (self.W, "B"): wds_component(105439553036130000, 31.704917, 25.705056),
            },
        )
        resolver = FakeResolver(
            {
                ("gaia", "dr3", "105439557331202560"): self.ARIETIS["key"],
                ("gaia", "dr3", "94195126792018688"): self.OFF["key"],
                ("gaia", "dr3", "105439553036130000"): self.B["key"],
            },
            [self.ARIETIS, self.B, self.OFF],
        )
        systems = build(Inputs(wds=catalogue), resolver)
        keys = systems.points["key"].to_pylist()
        assert sorted(keys) == [self.ARIETIS["key"], self.B["key"]]
        assert systems.counts["wds: id off its WDS id"] == 1


class TestSigma2398:
    """`wrong_object`: the MSC's B of Σ 2398 is Gliese 752 B, VB 10, at 3.5 pc from
    the true pair on the sky's far side. Its row's place fits VB 10, so the guard
    keeps it. The width refutes it, and the row stays an entry: the star is real,
    its object is not."""

    A = real(
        20696921,
        (280.683071, 59.638358),
        7.854393,
        (283.840118, 0.021993),
        (-1311.679077, 1792.324585, 0.027101, 0.026312),
    )
    VB_10 = real(
        1635199447,
        (289.237374, 5.144373),
        14.303288,
        (168.953705, 0.066833),
        (-598.761292, -1366.063477, 0.071686, 0.064969),
    )

    def test_vb_10_leaves_and_the_row_stays(self):
        rows = [
            ("A,B", -1, None, None, None),
            ("A", 0, None, None, None),
            ("B", 0, 13.88, [VISUAL_ORBIT], None),
        ]
        out = reduced(
            rows,
            [[], [(self.A["key"], 2)], [(self.VB_10["key"], 1)]],
            [self.A, self.VB_10],
        )
        assert kinds(out) == [f"{UNBOUND}: {WIDE}", WRONG_OBJECT]
        assert [group.keys for group in out.groups] == [frozenset({self.A["key"]})]
        assert [member.kind for member in out.groups[0].members] == ["point", "entry"]

    def test_a_veto_leaves_the_row_too(self):
        """With no orbit the parallaxes refute VB 10 before the width does."""
        rows = [
            ("A,B", -1, None, None, None),
            ("A", 0, None, None, None),
            ("B", 0, 13.88, None, None),
        ]
        out = reduced(
            rows,
            [[], [(self.A["key"], 2)], [(self.VB_10["key"], 1)]],
            [self.A, self.VB_10],
        )
        assert kinds(out) == ["parallaxes disagree", WRONG_OBJECT]
        assert [group.keys for group in out.groups] == [frozenset({self.A["key"]})]
        assert [member.kind for member in out.groups[0].members] == ["point", "entry"]


class TestFarMembers:
    """`place_guard`: a member far from the WDS id stays when its separation sits
    on a node above it, or when its row's place fits it. The id alone lost them."""

    @staticmethod
    def guarded(msc, keys: dict[str, int], points: list[dict]) -> list[list]:
        labels = msc["label"].to_pylist()
        found: list[list] = [
            [(keys[label], 2)] if label in keys else [] for label in labels
        ]
        place_guard(msc, found, facts(*points), Reduced())
        return found

    def test_capella_h(self):
        w = "05167+4600"
        msc = msc_nodes(
            [
                msc_comp(w, "A", RAdeg=79.172087, DEdeg=45.999027, HIP=24608),
                msc_comp(
                    w,
                    "H",
                    RAdeg=79.349427,
                    DEdeg=45.839702,
                    PMRA=88.4,
                    PMDE=-428.9,
                ),
                msc_comp(
                    w,
                    "L",
                    RAdeg=79.349802,
                    DEdeg=45.838695,
                    PMRA=54.0,
                    PMDE=-416.9,
                ),
            ],
            [
                msc_pair(w, "AB", "HL", "*", Type="Cmpr", Sep=723.0, Sunit='"'),
                msc_pair(w, "H", "L", "HL", Type="V", Sep=3.461, Sunit='"'),
            ],
            [],
        )
        points = [
            fact(17162496, 79.349991, 45.837796, 9.315714, pmra=88.4, pmdec=-428.9),
            fact(1627775232, 79.350146, 45.836842, 11.64075, pmra=54.0, pmdec=-416.9),
        ]
        keys = {"H": 17162496, "L": 1627775232}
        labels = msc["label"].to_pylist()
        found = self.guarded(msc, keys, points)
        assert found[labels.index("H")] == [(17162496, 2)]
        assert found[labels.index("L")] == [(1627775232, 2)]

    def test_au_mic(self):
        """AT Mic is 1.3° from the id of AU Mic, and 78′ wide on BC's node."""
        w = "20452-3120"
        msc = msc_nodes(
            [
                msc_comp(w, "A", RAdeg=311.289719, DEdeg=-31.340899, HIP=102409),
                msc_comp(
                    w,
                    "B",
                    RAdeg=310.463168,
                    DEdeg=-32.436175,
                    PMRA=296.9,
                    PMDE=-301.4,
                ),
                msc_comp(
                    w,
                    "C",
                    RAdeg=310.463034,
                    DEdeg=-32.435183,
                    PMRA=246.9,
                    PMDE=-417.2,
                ),
            ],
            [
                msc_pair(w, "A", "BC", "*", Sep=78.13, Sunit="'"),
                msc_pair(w, "B", "C", "BC", Type="V", Sep=2.537, Sunit='"'),
            ],
            [],
        )
        points = [
            fact(29132586, 310.464334, -32.437037, 9.575837, pmra=246.9, pmdec=-417.2),
            fact(566003498, 310.464731, -32.437515, 9.605488, pmra=296.9, pmdec=-301.4),
        ]
        keys = {"B": 566003498, "C": 29132586}
        labels = msc["label"].to_pylist()
        found = self.guarded(msc, keys, points)
        assert found[labels.index("B")] == [(566003498, 2)]
        assert found[labels.index("C")] == [(29132586, 2)]


class TestCapellaL:
    """`match_rows` takes the MSC's epoch: at J2000 Capella L is 7.2″ from where
    Gaia sees it at J2016, past the 1.5″ of the match."""

    def test_the_row_moves_to_the_epoch_of_the_match(self):
        w = "05167+4600"
        msc = msc_nodes(
            [
                msc_comp(w, "A", HIP=24608),
                msc_comp(
                    w,
                    "L",
                    RAdeg=79.349802,
                    DEdeg=45.838695,
                    PMRA=54.0,
                    PMDE=-416.9,
                ),
            ],
            [msc_pair(w, "A", "L", "*", Sep=723.0, Sunit='"')],
            [],
        )
        found: list[list] = [[] for _ in range(msc.num_rows)]
        rows = match_rows(msc, found, MSC_ID)
        row = rows.filter(pc.equal(rows["catalogue_id"], f"{w} L"))
        apart = sky.separation(
            row["match_ra"][0].as_py(),
            row["match_dec"][0].as_py(),
            79.350146,
            45.836842,
        )
        assert float(apart) < 0.1


class TestGammaCas:
    """MAX_PARSEC: 26 pairs at 1-2 pc pass the motion test. HD 5408 is 1.31 pc
    from Tiansi and stays. El-Badry's cut of 1 pc would lose it."""

    def test_a_pair_at_1_3_pc_stays(self):
        tiansi = one(
            fact(
                17553121,
                14.177451,
                60.716723,
                2.064583,
                "hipparcos-2007",
                5.94,
                parallax_error=0.12,
            )
        )
        hd_5408 = one(
            fact(
                17553037,
                14.195951,
                60.362819,
                5.967921,
                "hipparcos-2007",
                6.06,
                parallax_error=0.41,
            )
        )
        assert 1.0 < projected(tiansi, hd_5408) < 2.0
        assert unbound(tiansi, hd_5408) is None


class TestV592Per:
    """`_order`: 04445+3953 has groups AB and AB,C with one point, so they are one
    node here, and C, 11.2″ off with no star of its own, stayed out."""

    W = "04445+3953"

    def test_the_outer_entry_stays(self):
        msc = msc_nodes(
            [msc_comp(self.W, "A", HIP=22050), msc_comp(self.W, "C", Vmag=19.15)],
            [
                msc_pair(self.W, "AB", "C", "*", Sep=11.2, Sunit='"'),
                msc_pair(
                    self.W,
                    "A",
                    "B",
                    "AB",
                    Type="V",
                    P=200.0,
                    Punit="y",
                    Sep=0.272,
                    Sunit='"',
                ),
                msc_pair(
                    self.W,
                    "Aa",
                    "Ab",
                    "A",
                    Type="E",
                    P=0.716,
                    Punit="d",
                    Sep=0.114,
                    Sunit="m",
                ),
            ],
            [],
        )
        resolver = FakeResolver(
            {("hip", "2007", "22050"): 17146137},
            [fact(17146137, 71.13762, 39.875303, 8.244426, parallax=5.559949)],
        )
        systems = build(Inputs(msc=msc), resolver)
        entries = systems.members.filter(pc.equal(systems.members["kind"], "entry"))
        assert {"B", "C"} <= set(entries["label"].to_pylist())
        assert max(systems.nodes["stars"].to_pylist()) == 4


class TestBxTri:
    """`place_links`: 02208+3321 letters its stars one way in the MSC (Aa, Ab, B,
    C) and another in the WDS (Aa, Ab = MSC A, B; B = MSC C). By letter the MSC's
    B is the WDS's B, 66″ off. The places settle it."""

    W = "02208+3321"

    def test_each_star_stays(self):
        msc = msc_nodes(
            [
                msc_comp(self.W, "A", RAdeg=35.211878, DEdeg=33.346542, Vmag=13.37),
                msc_comp(self.W, "B", RAdeg=35.21171, DEdeg=33.346928, Vmag=14.43),
                msc_comp(self.W, "C", RAdeg=35.21505, DEdeg=33.327968, Vmag=16.87),
            ],
            [
                msc_pair(self.W, "AB", "C", "*", Sep=67.5, Sunit='"'),
                msc_pair(self.W, "A", "B", "AB", Sep=1.571, Sunit='"'),
                msc_pair(self.W, "Aa", "Ab", "A", Type="E", Sep=0.101, Sunit="m"),
            ],
            [],
        )
        catalogue = wds_catalogue(
            {
                self.W: [
                    wds_pair("Aa", "Ab", 1.5, notes="T", mag1=13.5, mag2=14.7),
                    wds_pair("A", "B", 67.5, notes="", mag1=13.3, mag2=16.5),
                ]
            },
            {
                (self.W, "Aa"): wds_component(1, 35.21192, 33.34658),
                (self.W, "Ab"): wds_component(2, 35.21171, 33.34697),
                (self.W, "B"): wds_component(3, 35.21508, 33.32803),
            },
        )
        resolver = FakeResolver(
            {
                ("gaia", "dr3", "1"): 17368886,
                ("gaia", "dr3", "2"): 554239798,
                ("gaia", "dr3", "3"): 1091110710,
            },
            [
                real(
                    17368886,
                    (35.21266, 33.346025),
                    12.516331,
                    (18.989563, 0.025871),
                    (144.250259, -111.209656, 0.027649, 0.026909),
                ),
                real(
                    554239798,
                    (35.212467, 33.346394),
                    14.426201,
                    (18.836576, 0.073633),
                    (142.286957, -120.111748, 0.072819, 0.071156),
                ),
                real(
                    1091110710,
                    (35.215812, 33.327461),
                    15.257886,
                    (18.874432, 0.035956),
                    (143.052765, -113.742767, 0.037861, 0.037491),
                ),
            ],
        )
        systems = build(Inputs(msc=msc, wds=catalogue), resolver)
        points = systems.points.to_pylist()
        assert {point["key"] for point in points} == {
            17368886,
            554239798,
            1091110710,
        }
        assert len({point["root"] for point in points}) == 1
        assert systems.counts["msc: members by place"] == 3


class TestKoi4418:
    """The motion test stops at 4″, where Gaia's motions are not reliable. KOI 4418
    A and B are 1.5″ apart and move 10.6 mas/yr apart, 235 km/s at A's distance."""

    A = one(
        real(
            8610444126,
            (293.014869, 38.01239),
            16.001797,
            (0.214701, 0.035167),
            (-1.878666, -7.107979, 0.036549, 0.038948),
        )
    )
    B = one(
        real(
            25790313310,
            (293.014939, 38.012025),
            18.292343,
            (0.460464, 0.137007),
            (2.996529, 2.342256, 0.180521, 0.13422),
        )
    )

    def test_no_motion_refutes_a_close_pair(self):
        assert math.isnan(excess(self.A, self.B))
        assert unbound(self.A, self.B) is None

    def test_the_same_motions_refute_a_wider_pair(self):
        wider = self.B._replace(dec=self.B.dec + 6 / 3600)
        assert unbound(self.A, wider) == MOTION


class TestAlmach:
    """`excess` reads no Hipparcos motion against a Gaia motion over MAX_RUWE. γ²
    And is a close multiple at RUWE 6.5, so it reads 10.5 km/s from γ¹ And."""

    A = one(
        fact(
            17407007,
            30.975056,
            42.32951,
            1.602585,
            "hipparcos-2007",
            8.3,
            parallax_error=1.04,
            pmra=42.32,
            pmdec=-49.3,
            pmra_error=0.92,
            pmdec_error=0.81,
        )
    )
    BC = one(
        real(
            554277919,
            (30.978259, 42.330699),
            4.862768,
            (12.07239, 0.955431),
            (16.644728, -47.745937, 0.929646, 0.9014),
        )
    )

    def test_a_star_that_gaia_cannot_fit_stays(self):
        assert unbound(self.A, self.BC._replace(ruwe=6.54985)) is None

    def test_the_same_motions_refute_a_star_that_gaia_fits(self):
        assert unbound(self.A, self.BC._replace(ruwe=1.0)) == MOTION
