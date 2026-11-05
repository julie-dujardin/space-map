"""Tests for the rules that keep a system to bound stars."""

import math
from collections import Counter
from collections.abc import Sequence

import pyarrow as pa
import pytest

from space_map_data.extrasolar.systems import assemble
from space_map_data.extrasolar.systems.build import build
from space_map_data.extrasolar.systems.distance import DISTANCES
from space_map_data.extrasolar.systems.groups import GROUP_LEAVES
from space_map_data.extrasolar.systems.msc import msc_nodes
from space_map_data.extrasolar.systems.nodes import (
    EL_BADRY,
    GAIA_DR3,
    MSC,
    MSC_ID,
    NODES,
    PLANETS,
    SIMBAD,
    UNVERIFIED,
    VISUAL,
    VISUAL_ORBIT,
    WDS,
    WDS_ID,
)
from space_map_data.extrasolar.systems.pairs import el_badry_pairs
from space_map_data.extrasolar.systems.parallax import (
    IN_CLUSTER,
    MAX_CLUSTER_AU,
    MOTION,
    WIDE,
    excess,
    one_cluster,
    projected,
    unbound,
    wrong_object,
)
from space_map_data.extrasolar.systems.prepare import (
    ID_OFF,
    Inputs,
    cluster_keys,
    cluster_pairs,
    id_place,
    letter_links,
    place_guard,
    place_links,
)
from space_map_data.extrasolar.systems.reduce import (
    ENTRY,
    PLANET_ROW,
    UNBOUND,
    WRONG_OBJECT,
    Reduced,
    TreeReducer,
)
from space_map_data.extrasolar.systems.report import report_lines
from space_map_data.extrasolar.systems.resolve import (
    FACTS,
    HIPPARCOS_ASTROMETRY,
    LETTER,
    Facts,
)
from space_map_data.extrasolar.systems.simbad import (
    NON_STELLAR,
    non_stellar_parents,
    read_simbad,
)
from tests.extrasolar.conftest import offset
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

A, B, C, D = 101, 102, 103, 104
# 1 pc at 100 pc, in arcsec.
PARSEC = 2062.65
# 10,000 AU at 100 pc, in arcsec.
CLUSTER_CUT = 100.0


def star(
    key: int,
    arcsec: float,
    mag: float = 9.0,
    astrometry: str = "gaia-dr3",
    parallax: float | None = 10.0,
    **values,
) -> dict:
    """A star at 100 pc, `arcsec` east of (10, 0)."""
    motion = {"pmra": 5.0, "pmdec": 5.0, "pmra_error": 0.01, "pmdec_error": 0.01}
    place = offset(10.0, 0.0, arcsec, 90.0)
    return fact(key, *place, mag, astrometry, parallax, **(motion | values))


def facts(*rows: dict) -> Facts:
    return Facts(pa.Table.from_pylist(list(rows), schema=FACTS))


def one(row: dict):
    found = facts(row).get(row["key"])
    assert found is not None
    return found


# Hipparcos 2007, and Gaia DR3 3322963321574168064.
BETELGEUSE = fact(
    22821649,
    88.793062,
    7.407114,
    -0.137637,
    "hipparcos-2007",
    6.55,
    parallax_error=0.83,
    pmra=27.54,
    pmdec=11.30,
    pmra_error=1.03,
    pmdec_error=0.65,
)
BETELGEUSE_D = fact(
    559692563,
    88.787908,
    7.426378,
    13.048707,
    "gaia-dr3",
    3.183362,
    parallax_error=0.016219,
    ruwe=1.026116,
    pmra=7.731902,
    pmdec=-37.707024,
    pmra_error=0.018341,
    pmdec_error=0.01381,
)
# Gaia DR3.
HD_2057 = fact(
    17491282,
    6.288326,
    48.047481,
    7.412349,
    "gaia-dr3",
    20.620485,
    parallax_error=0.477382,
    ruwe=18.40777,
    pmra=278.815948,
    pmdec=17.66227,
    pmra_error=0.4147,
    pmdec_error=0.307279,
)
HD_2057_D = fact(
    8070554962,
    6.282687,
    48.046725,
    16.302095,
    "gaia-dr3",
    18.48851,
    parallax_error=0.057195,
    ruwe=1.081386,
    pmra=280.285706,
    pmdec=0.083786,
    pmra_error=0.058742,
    pmdec_error=0.043258,
)
HD_2057_C = fact(
    554362183,
    6.267015,
    47.987683,
    14.897724,
    "gaia-dr3",
    1.287876,
    parallax_error=0.025131,
    ruwe=0.988779,
    pmra=-9.191151,
    pmdec=-9.527093,
    pmra_error=0.021202,
    pmdec_error=0.018089,
)


def reduced(
    rows: Sequence[tuple],
    candidates: list[list[tuple[int, int]]],
    points: list[dict],
    dropped: frozenset[int] = frozenset(),
    source: str = WDS,
    clusters: dict[int, frozenset[str]] | None = None,
) -> Reduced:
    """`rows` are (label, parent, separation, known, evidence) of system "1"."""
    base = dict.fromkeys(NODES.names)
    table = pa.Table.from_pylist(
        [
            base
            | {
                "source": source,
                "system": "1",
                "node": at,
                "label": label,
                "parent": parent,
                "separation": separation,
                "known": known,
                "evidence": evidence,
            }
            for at, (label, parent, separation, known, evidence) in enumerate(rows)
        ],
        schema=NODES,
    )
    out = Reduced()
    TreeReducer(
        table,
        0,
        candidates,
        facts(*points),
        0,
        out,
        dropped=dropped,
        clusters=clusters,
    ).run()
    return out


def pair(second: dict, separation: float | None = None, known=None) -> Reduced:
    """A at 0″ and the member `second` as B."""
    rows = [
        ("AB", -1, None, None, None),
        ("A", 0, None, None, None),
        ("B", 0, separation, known or [VISUAL], None),
    ]
    return reduced(rows, [[], [(A, 2)], [(B, 2)]], [star(A, 0.0), second])


def kinds(out: Reduced) -> list[str]:
    return [kind for kind, _, _ in out.events]


class TestUnbound:
    """The width of a pair and the motion left over beside an orbit."""

    def test_the_width(self):
        assert unbound(one(star(A, 0.0)), one(star(B, 1.9 * PARSEC))) is None
        assert unbound(one(star(A, 0.0)), one(star(B, 2.1 * PARSEC))) == WIDE

    def test_the_brighter_star_gives_the_distance(self):
        near = star(A, 0.0, mag=5.0)
        far = star(B, PARSEC, mag=9.0, distance=1000.0)
        assert projected(one(near), one(far)) == pytest.approx(1.0)

    def test_no_distance_gives_no_width(self):
        first = star(A, 0.0, parallax=None, distance=None)
        second = star(B, 3 * PARSEC, parallax=None, distance=None)
        assert math.isnan(projected(one(first), one(second)))
        assert unbound(one(first), one(second)) is None

    def test_the_excess_is_past_an_orbit_and_three_sigma(self):
        first = star(A, 0.0, pmra=0.0, pmdec=0.0, pmra_error=0.1, pmdec_error=0.1)
        second = star(B, 100.0, pmra=30.0, pmdec=0.0, pmra_error=0.1, pmdec_error=0.1)
        orbit = 0.44 * 10**1.5 / 10
        expected = 4.74047 * (30.0 - orbit - 3 * math.sqrt(0.02)) * 0.1
        assert excess(one(first), one(second)) == pytest.approx(expected)

    def test_the_motion(self):
        second = star(B, 100.0, pmra=30.0)
        assert unbound(one(star(A, 0.0)), one(second)) == MOTION
        assert unbound(one(star(A, 0.0)), one(second), moving=False) is None

    def test_a_close_pair_has_no_motion_test(self):
        """Gaia's motions are not reliable under 4″ (KOI 4418)."""
        assert unbound(one(star(A, 0.0)), one(star(B, 3.9, pmra=30.0))) is None
        assert unbound(one(star(A, 0.0)), one(star(B, 4.1, pmra=30.0))) == MOTION

    def test_a_hipparcos_motion_counts(self):
        second = star(
            B, 100.0, pmra=30.0, astrometry=min(HIPPARCOS_ASTROMETRY), parallax_error=1
        )
        assert unbound(one(star(A, 0.0)), one(second)) == MOTION

    def test_a_hipparcos_star_with_no_measured_parallax_has_no_motion(self):
        """Garnet Star, 0.55 ± 0.20 mas: no distance turns its motion into km/s."""
        second = star(
            B, 100.0, pmra=30.0, astrometry=min(HIPPARCOS_ASTROMETRY), parallax_error=3
        )
        assert math.isnan(excess(one(star(A, 0.0)), one(second)))

    def test_another_position_has_no_motion(self):
        second = star(B, 100.0, pmra=30.0, astrometry="simbad")
        assert math.isnan(excess(one(star(A, 0.0)), one(second)))


class TestWrongObject:
    """Whether a pair's points fit the catalogue's separation."""

    def test_far_from_the_listed_separation(self):
        assert wrong_object(one(star(A, 0.0)), one(star(B, 100.0)), 10.0)

    def test_a_share_alone_is_no_wrong_object(self):
        assert not wrong_object(one(star(A, 0.0)), one(star(B, 6.0)), 1.0)

    def test_a_small_ratio_is_no_wrong_object(self):
        assert not wrong_object(one(star(A, 0.0)), one(star(B, 140.0)), 100.0)

    @pytest.mark.parametrize("listed", [None, 0.0, 999.9])
    def test_no_measure_says_nothing(self, listed):
        assert not wrong_object(one(star(A, 0.0)), one(star(B, 9000.0)), listed)


class TestBoundMembers:
    """Each member against its primary."""

    def test_a_wide_member_leaves(self):
        out = pair(star(B, 3 * PARSEC), 3 * PARSEC)
        assert not out.groups
        assert kinds(out) == [f"{UNBOUND}: {WIDE}"]
        assert out.counts[f"{WDS}: physical members {WIDE}"] == 1

    def test_a_moving_member_leaves(self):
        out = pair(star(B, 100.0, pmra=30.0), 100.0)
        assert not out.groups
        assert kinds(out) == [f"{UNBOUND}: {MOTION}"]

    def test_an_orbit_explains_the_motion(self):
        out = pair(star(B, 100.0, pmra=30.0), 100.0, [VISUAL, VISUAL_ORBIT])
        assert [group.keys for group in out.groups] == [frozenset({A, B})]

    def test_an_orbit_does_not_explain_the_width(self):
        out = pair(star(B, 3 * PARSEC), 3 * PARSEC, [VISUAL, VISUAL_ORBIT])
        assert not out.groups

    def test_a_point_that_holds_several_stars_meets_the_motion_test(self):
        """WDS 05552+0724 D, at 72″ from Betelgeuse's Aa, Ab: 53 mas/yr apart."""
        rows = [
            ("AD", -1, None, None, None),
            ("A", 0, None, None, None),
            ("Aa", 1, None, None, None),
            ("Ab", 1, 0.1, [VISUAL], None),
            ("D", 0, 71.7, [VISUAL], None),
        ]
        candidates = [
            [],
            [],
            [(BETELGEUSE["key"], 2)],
            [],
            [(BETELGEUSE_D["key"], 2)],
        ]
        out = reduced(rows, candidates, [BETELGEUSE, BETELGEUSE_D])
        assert not out.groups
        assert kinds(out) == [f"{UNBOUND}: {MOTION}"]
        assert [interior.key for interior in out.interiors] == [BETELGEUSE["key"]]

    def test_a_chance_star_leaves_a_ruined_primary(self):
        """WDS 00251+4803: A has RUWE 18.4, D is its real companion, and C, the
        most precise of the three, a field star at 1.29 mas."""
        rows = [
            ("ACD", -1, None, None, None),
            ("A", 0, None, None, None),
            ("D", 0, 13.8, [VISUAL], None),
            ("C", 0, 121.0, [VISUAL], None),
        ]
        candidates = [
            [],
            [(HD_2057["key"], 2)],
            [(HD_2057_D["key"], 2)],
            [(HD_2057_C["key"], 2)],
        ]
        out = reduced(rows, candidates, [HD_2057, HD_2057_D, HD_2057_C])
        assert [group.keys for group in out.groups] == [
            frozenset({HD_2057["key"], HD_2057_D["key"]})
        ]
        assert kinds(out) == ["parallaxes disagree"]

    def test_a_wrong_object_stays_an_entry(self):
        """The catalogue lists a star at 5″, and the id reaches a star 3 pc
        away: the star is real, its object is not."""
        out = pair(star(B, 3 * PARSEC), 5.0)
        assert kinds(out) == [f"{UNBOUND}: {WIDE}", WRONG_OBJECT]
        ((group,),) = [[g for g in out.groups if g.keys == frozenset({A})]]
        assert [member.kind for member in group.members] == ["point", ENTRY]

    def test_a_separation_alone_refutes_nothing(self):
        """WDS 17200-0555: the listed separation is far off, and the stars
        move together."""
        out = pair(star(B, 300.0), 5.0)
        assert [group.keys for group in out.groups] == [frozenset({A, B})]
        assert not kinds(out)


TRIPLE = (
    ("ABC", -1, None, None, None),
    ("A", 0, None, None, None),
    ("B", 0, 100.0, [VISUAL], None),
    ("C", 0, 200.0, [VISUAL], None),
)
PAIR = TRIPLE[:3]


class TestMainStar:
    """Each member against the main star, which its primary can hide."""

    def test_an_objectless_primary_tests_nothing(self):
        """WDS ABCDEF has no object for A. B stands for it, or nothing
        tests the others."""
        out = reduced(
            TRIPLE,
            [[], [], [(A, 2)], [(B, 2)]],
            [star(A, 0.0), star(B, 200.0, parallax=2.0, distance=500.0)],
        )
        assert kinds(out) == ["parallaxes disagree"]
        assert frozenset({A, B}) not in [group.keys for group in out.groups]

    def test_a_wide_member_of_an_objectless_primary(self):
        out = reduced(
            TRIPLE,
            [[], [], [(A, 2)], [(B, 2)]],
            [star(A, 0.0), star(B, 3 * PARSEC)],
        )
        assert kinds(out) == [f"{UNBOUND}: {WIDE}"]

    def test_the_stand_in_is_not_measured_from_the_primary(self):
        """C is listed 200″ from A, which has no object. That says nothing of
        its place beside B, so a refuted C leaves and stays no entry."""
        rows = [*TRIPLE[:3], ("C", 0, 1.0, [VISUAL], None)]
        out = reduced(
            rows,
            [[], [], [(A, 2)], [(B, 2)]],
            [star(A, 0.0), star(B, 3 * PARSEC)],
        )
        assert WRONG_OBJECT not in kinds(out)

    def test_the_first_point_that_stays_stands_in(self):
        """B is unverified and nothing tests it, so it leaves. C stays and
        stands for A, and D is tested against it."""
        rows = [
            *TRIPLE[:2],
            ("B", 0, 100.0, [VISUAL], UNVERIFIED),
            ("C", 0, 200.0, [VISUAL], None),
            ("D", 0, 300.0, [VISUAL], None),
        ]
        out = reduced(
            rows,
            [[], [], [(B, 2)], [(C, 2)], [(D, 2)]],
            [star(B, 0.0), star(C, 1.0), star(D, 3 * PARSEC)],
        )
        assert kinds(out) == [f"{UNBOUND}: {WIDE}"]
        assert out.counts[f"{WDS}: {UNVERIFIED} members left for agreement"] == 1
        assert [group.keys for group in out.groups] == [frozenset({C})]

    def test_a_chain_of_pairs_ends_at_the_width(self):
        """B is 1.5 pc from A and C 1.5 pc past B. Each link holds, and C is
        3 pc from A, so the pair BC leaves as the system that it is."""
        rows = [
            ("ABC", -1, None, None, None),
            ("A", 0, None, None, None),
            ("BC", 0, 1.5 * PARSEC, [VISUAL], None),
            ("B", 2, None, None, None),
            ("C", 2, 1.5 * PARSEC, [VISUAL], None),
        ]
        out = reduced(
            rows,
            [[], [(A, 2)], [], [(B, 2)], [(C, 2)]],
            [star(A, 0.0), star(B, 1.5 * PARSEC), star(C, 3 * PARSEC)],
        )
        assert [group.keys for group in out.groups] == [frozenset({B, C})]
        assert kinds(out) == [f"{UNBOUND}: {WIDE}"]
        assert out.events[0][2].startswith(f"{WDS} 1 BC: {C} from {A}: 3.00 pc")


def real(
    key: int,
    place: tuple[float, float],
    mag: float,
    parallax: tuple[float, float],
    motion: tuple[float, float] = (math.nan, math.nan),
    errors: tuple[float, float] = (math.nan, math.nan),
    astrometry: str = "gaia-dr3",
    **values,
) -> dict:
    """A star with its values in the registry."""
    return fact(
        key,
        *place,
        mag,
        astrometry,
        parallax[0],
        parallax_error=parallax[1],
        pmra=motion[0],
        pmdec=motion[1],
        pmra_error=errors[0],
        pmdec_error=errors[1],
        **values,
    )


# Pleiades, 179.7″ and about 24,500 AU apart, WDS.
HD_23924 = real(
    A,
    (57.4206, 23.34137),
    8.09433,
    (7.31591, 0.04082),
    (18.73308, -45.13350),
    (0.04072, 0.03817),
)
HD_23912 = real(
    B,
    (57.38645, 23.3802),
    9.03487,
    (7.23128, 0.02089),
    (20.34647, -44.30134),
    (0.02362, 0.01580),
)
# Hyades, 163″ and about 7,500 AU apart, WDS.
HG_7_142 = real(
    A,
    (64.05523, 18.88436),
    11.20327,
    (21.82751, 0.02053),
    (120.62003, -32.14845),
    (0.02102, 0.01564),
)
HG_7_141 = real(
    B,
    (64.01546, 18.85908),
    12.99346,
    (20.81803, 0.01893),
    (112.99088, -28.06928),
    (0.01837, 0.01336),
)
# Hyades, about 16,000 AU apart. κ¹ Tauri holds a close pair.
KAPPA1_TAU = real(
    A,
    (66.34285, 22.29367),
    4.16724,
    (20.91185, 0.15706),
    (104.35453, -44.43582),
    (0.18281, 0.11904),
)
KAPPA2_TAU = real(
    B,
    (66.35477, 22.19979),
    5.22473,
    (22.01774, 0.12882),
    (112.37063, -46.63900),
    (0.17783, 0.10386),
)
# The beta_Tuc_Group of Hunt & Reffert, a moving group, about 29,000 AU apart.
BETA1_TUC = real(
    A,
    (7.88694, -62.95846),
    4.32993,
    (22.83841, 0.08612),
    (84.01118, -54.85047),
    (0.08996, 0.08935),
)
BETA3_TUC = real(
    B,
    (8.18379, -63.03172),
    5.05502,
    (21.67942, 0.0683),
    (86.54079, -50.11537),
    (0.06799, 0.06921),
)
# In no cluster, about 10,600 AU apart.
ALPHA_CEN_A = real(
    A,
    (219.92041, -60.83515),
    0.0,
    (754.81, 4.11),
    astrometry="hipparcos-2007",
    distance=1.3459,
)
PROXIMA = real(
    B,
    (217.39232, -62.67608),
    8.98475,
    (768.06659, 0.04987),
    (-3781.74121, 769.46503),
    (0.03139, 0.05052),
    distance=1.30197,
)
# No cluster lists Alcyone, whose astrometry is Hipparcos's. 24 Tauri is 182″ off.
ALCYONE = real(
    A,
    (56.871101, 24.105242),
    2.89613,
    (8.09, 0.42),
    astrometry="hipparcos-2007",
)
TAU_24 = real(B, (56.83776, 24.116067), 6.29883, (7.1999, 0.05976))
PLEIADES = frozenset({"Melotte_22"})
TWO = {A: PLEIADES, B: PLEIADES}


def wide_pair(
    first: dict,
    second: dict,
    clusters: dict[int, frozenset[str]],
    separation: float | None = None,
    known=None,
) -> Reduced:
    rows = [
        ("AB", -1, None, None, None),
        ("A", 0, None, None, None),
        ("B", 0, separation, known or [VISUAL], None),
    ]
    return reduced(
        rows,
        [[], [(first["key"], 2)], [(second["key"], 2)]],
        [first, second],
        clusters=clusters,
    )


class TestClusterRule:
    """Two members of one star cluster over MAX_CLUSTER_AU are neighbours."""

    def test_the_cut(self):
        first, near = one(star(A, 0.0)), one(star(B, 0.99 * CLUSTER_CUT))
        far = one(star(B, 1.01 * CLUSTER_CUT))
        assert unbound(first, near, cluster=True) is None
        assert unbound(first, far, cluster=True) == IN_CLUSTER
        assert MAX_CLUSTER_AU == 10_000.0

    def test_width_alone_refutes_nothing(self):
        first, far = one(star(A, 0.0)), one(star(B, 1.01 * CLUSTER_CUT))
        assert unbound(first, far) is None

    def test_a_star_in_two_clusters(self):
        clusters = {
            A: frozenset({"Stock_2", "NGC_869"}),
            B: frozenset({"NGC_869"}),
        }
        found = one_cluster(clusters, one(star(A, 0.0)), one(star(B, 1.0)))
        assert found == {"NGC_869"}

    def test_neighbours_leave(self):
        out = wide_pair(HD_23924, HD_23912, TWO, 179.7)
        assert not out.groups
        assert kinds(out) == [f"{UNBOUND}: {IN_CLUSTER}"]
        assert out.counts[f"{WDS}: physical members {IN_CLUSTER}"] == 1
        assert "Melotte_22" in out.events[0][2]

    def test_a_pair_under_the_cut_stays(self):
        out = wide_pair(HG_7_142, HG_7_141, TWO, 163.1)
        assert [group.keys for group in out.groups] == [frozenset({A, B})]
        assert not kinds(out)

    def test_an_orbit_pair_stays(self):
        second = star(B, 1.5 * CLUSTER_CUT)
        out = wide_pair(star(A, 0.0), second, TWO, 150.0, [VISUAL, VISUAL_ORBIT])
        assert [group.keys for group in out.groups] == [frozenset({A, B})]

    def test_a_moving_group_stays(self):
        """`cluster_members` lists no moving group."""
        out = wide_pair(BETA1_TUC, BETA3_TUC, {}, 240.8)
        assert [group.keys for group in out.groups] == [frozenset({A, B})]

    def test_a_field_pair_stays(self):
        out = wide_pair(ALPHA_CEN_A, PROXIMA, {}, 7850.0)
        assert [group.keys for group in out.groups] == [frozenset({A, B})]

    def test_a_star_that_no_cluster_lists_stays(self):
        out = wide_pair(ALCYONE, TAU_24, {B: PLEIADES}, 182.0)
        assert [group.keys for group in out.groups] == [frozenset({A, B})]

    def test_two_clusters_are_no_crowd(self):
        out = wide_pair(
            HD_23924, HD_23912, {A: PLEIADES, B: frozenset({"NGC_1"})}, 179.7
        )
        assert [group.keys for group in out.groups] == [frozenset({A, B})]

    def test_a_point_with_two_members_leaves(self):
        rows = [
            ("ABC", -1, None, None, None),
            ("AB", 0, None, None, None),
            ("A", 1, None, None, None),
            ("B", 1, 0.1, [VISUAL], None),
            ("C", 0, 339.4, [VISUAL], None),
        ]
        out = reduced(
            rows,
            [[], [], [(A, 2)], [(A, 2)], [(B, 2)]],
            [KAPPA1_TAU, KAPPA2_TAU],
            clusters=TWO,
        )
        assert not out.groups
        assert [len(interior.entries) for interior in out.interiors] == [2]
        assert kinds(out) == [f"{UNBOUND}: {IN_CLUSTER}"]

    def test_a_wrong_object_stays_an_entry(self):
        out = wide_pair(HD_23924, HD_23912, TWO, 5.0)
        assert kinds(out) == [f"{UNBOUND}: {IN_CLUSTER}", WRONG_OBJECT]
        ((group,),) = [[g for g in out.groups if g.keys == frozenset({A})]]
        assert [member.kind for member in group.members] == ["point", ENTRY]

    def test_a_group_leaves_by_any_of_its_points(self):
        """B is near A and C is not, and the pair BC keeps its own system."""
        rows = [
            ("ABC", -1, None, None, None),
            ("A", 0, None, None, None),
            ("BC", 0, 50.0, [VISUAL], None),
            ("B", 2, None, None, None),
            ("C", 2, 100.0, [VISUAL], None),
        ]
        out = reduced(
            rows,
            [[], [(A, 2)], [], [(B, 2)], [(C, 2)]],
            [star(A, 0.0), star(B, 50.0), star(C, 1.5 * CLUSTER_CUT)],
            clusters={A: PLEIADES, B: PLEIADES, C: PLEIADES},
        )
        assert [group.keys for group in out.groups] == [frozenset({B, C})]
        assert kinds(out) == [f"{UNBOUND}: {IN_CLUSTER}"]

    def test_a_group_point_leaves(self):
        out = reduced(
            PAIR,
            [[(C, 2)], [(A, 2)], [(B, 2)]],
            [star(A, 0.0), star(B, 1.0), star(C, 1.5 * CLUSTER_CUT)],
            clusters={A: PLEIADES, C: PLEIADES},
        )
        assert [group.keys for group in out.groups] == [frozenset({A, B})]
        assert kinds(out) == [GROUP_LEAVES]


def el_badry_row(first: dict, second: dict) -> pa.Table:
    """The El-Badry pair of two stars, whose ids are their keys."""
    return el_badry_pairs(
        pa.table(
            {
                "source_id1": [first["key"]],
                "source_id2": [second["key"]],
                "ra1": [first["ra"]],
                "dec1": [first["dec"]],
                "ra2": [second["ra"]],
                "dec2": [second["dec"]],
                "parallax1": [first["parallax"]],
                "parallax2": [second["parallax"]],
                "phot_g_mean_mag1": [first["mag"]],
                "phot_g_mean_mag2": [second["mag"]],
                "sep_arcsec": [179.7],
                "R_chance_align": [0.03],
                "binary_type": ["MSMS"],
            }
        )
    )


def gaia_resolver(*rows: dict) -> FakeResolver:
    ids = {(*GAIA_DR3, str(row["key"])): row["key"] for row in rows}
    return FakeResolver(ids, list(rows))


def members_of(*keys: int, cluster: str = "Melotte_22") -> pa.Table:
    return pa.table(
        {
            "source_id": pa.array(keys, pa.int64()),
            "cluster": [cluster] * len(keys),
        }
    )


class TestClusterKeys:
    """The members of the star clusters become objects."""

    def test_only_objects_of_the_systems(self):
        resolver = gaia_resolver(HD_23924, HD_23912)
        known = Facts(resolver.facts(pa.array([A]).to_numpy()))
        assert cluster_keys(members_of(A, B, 7), resolver, known) == {A: PLEIADES}

    def test_a_star_in_two_clusters(self):
        resolver = gaia_resolver(HD_23924)
        known = Facts(resolver.facts(pa.array([A]).to_numpy()))
        two = pa.concat_tables([members_of(A), members_of(A, cluster="NGC_1")])
        assert cluster_keys(two, resolver, known) == {
            A: frozenset({"Melotte_22", "NGC_1"})
        }

    def test_no_table(self):
        resolver = gaia_resolver(HD_23924)
        assert cluster_keys(None, resolver, facts(HD_23924)) == {}


class TestClusterPairs:
    """El-Badry's evidence is a shared motion, which every member has."""

    def test_neighbours_are_no_system(self):
        resolver = gaia_resolver(HD_23924, HD_23912)
        systems = build(
            Inputs(
                el_badry=el_badry_row(HD_23924, HD_23912), clusters=members_of(A, B)
            ),
            resolver,
        )
        assert not systems.points.num_rows
        assert systems.counts[f"{EL_BADRY}: pairs {IN_CLUSTER}"] == 1
        events = systems.events.to_pylist()
        assert [row["kind"] for row in events] == [f"{UNBOUND}: {IN_CLUSTER}"]

    def test_the_pair_stays_outside_a_cluster(self):
        resolver = gaia_resolver(HD_23924, HD_23912)
        systems = build(
            Inputs(el_badry=el_badry_row(HD_23924, HD_23912), clusters=members_of(A)),
            resolver,
        )
        assert set(systems.points["key"].to_pylist()) == {A, B}

    def test_a_pair_under_the_cut_stays(self):
        resolver = gaia_resolver(HG_7_142, HG_7_141)
        systems = build(
            Inputs(
                el_badry=el_badry_row(HG_7_142, HG_7_141), clusters=members_of(A, B)
            ),
            resolver,
        )
        assert set(systems.points["key"].to_pylist()) == {A, B}

    def test_a_tree_and_el_badry_agree(self):
        """A pair that a tree loses does not come back through El-Badry."""
        wds = wds_catalogue(
            {"03495+2320": [wds_pair("A", "B", 179.7, notes="V")]},
            {
                ("03495+2320", "A"): wds_component(source_id=A, ra=57.4206, dec=23.34),
                ("03495+2320", "B"): wds_component(source_id=B, ra=57.3864, dec=23.38),
            },
        )
        resolver = gaia_resolver(HD_23924, HD_23912)
        systems = build(
            Inputs(
                wds=wds,
                el_badry=el_badry_row(HD_23924, HD_23912),
                clusters=members_of(A, B),
            ),
            resolver,
        )
        assert not systems.points.num_rows

    def test_cluster_pairs(self):
        row = el_badry_row(KAPPA1_TAU, KAPPA2_TAU)
        keys = (pa.array([A]).to_numpy(), pa.array([B]).to_numpy())
        known = facts(KAPPA1_TAU, KAPPA2_TAU)
        assert cluster_pairs(known, row, keys, TWO).tolist() == [True]


class TestGroupPoint:
    """A group's own point that is not bound to its main star."""

    def test_a_wide_point_leaves(self):
        out = reduced(
            PAIR,
            [[(C, 2)], [(A, 2)], [(B, 2)]],
            [star(A, 0.0), star(B, 1.0), star(C, 3 * PARSEC)],
        )
        assert [group.keys for group in out.groups] == [frozenset({A, B})]
        assert kinds(out) == [GROUP_LEAVES]

    def test_a_near_point_stays(self):
        out = reduced(
            PAIR,
            [[(C, 2)], [(A, 2)], [(B, 2)]],
            [star(A, 0.0), star(B, 1.0), star(C, 200.0)],
        )
        assert [group.keys for group in out.groups] == [frozenset({A, B, C})]
        assert GROUP_LEAVES not in kinds(out)


class TestPlanetRow:
    """A component whose objects all left the trees is a planet: Ross 458 c
    is MSC C, COCONUTS-2 b is WDS B. It is no star of its system."""

    def test_a_flat_tree(self):
        rows = [
            ("AB", -1, None, None, None),
            ("A", 0, None, None, None),
            ("B", 0, 100.0, [VISUAL], None),
        ]
        out = reduced(
            rows,
            [[], [(A, 2)], [(B, 2)]],
            [star(A, 0.0), star(B, 100.0)],
            dropped=frozenset({B}),
        )
        assert not out.groups
        assert not out.interiors
        assert out.events == [(PLANET_ROW, WDS, f"{WDS} 1 B")]
        assert out.counts[f"{WDS}: {PLANET_ROW}"] == 1

    def test_a_row_of_the_planet_catalogues_is_a_star(self):
        """HD 106906 B is the star that the planet catalogues list. Its id
        reaches SIMBAD's HD 106906B, which is the planet, so it stays an entry."""
        rows = [
            ("AB", -1, None, None, None),
            ("A", 0, None, None, None),
            ("B", 0, None, None, None),
        ]
        out = reduced(
            rows,
            [[], [(A, 2)], [(B, 2)]],
            [star(A, 0.0), star(B, 7.1)],
            dropped=frozenset({B}),
            source=PLANETS,
        )
        assert PLANET_ROW not in kinds(out)
        assert [len(interior.entries) for interior in out.interiors] == [2]

    def test_another_object_keeps_the_row(self):
        rows = [
            ("AB", -1, None, None, None),
            ("A", 0, None, None, None),
            ("B", 0, 100.0, [VISUAL], None),
        ]
        out = reduced(
            rows,
            [[], [(A, 2)], [(B, 2), (C, 4)]],
            [star(A, 0.0), star(B, 100.0), star(C, 100.0)],
            dropped=frozenset({B}),
        )
        assert [group.keys for group in out.groups] == [frozenset({A, C})]


class TestSimbadHierarchy:
    """`h_link` also links a cluster to its members (47 Tuc)."""

    objects = (
        simbad_object(1, "NGC 104", 6.0, -72.0, otype="GlC"),
        simbad_object(2, "Cl* NGC 104 A", 6.0, -72.0),
        simbad_object(3, "Cl* NGC 104 B", 6.1, -72.0),
        simbad_object(4, "Cl* NGC 104 Ba", 6.1, -72.0),
    )
    links = ((1, 2), (1, 3), (3, 4))

    def test_a_cluster_is_no_node(self):
        table = read_simbad(simbad_index(list(self.objects), self.links).stars)
        assert table["label"].to_pylist() == ["Cl* NGC 104 B", "Cl* NGC 104 Ba"]
        assert table["parent"].to_pylist() == [-1, 0]

    def test_it_is_logged(self):
        stars = simbad_index(list(self.objects), self.links).stars
        assert non_stellar_parents(stars) == ["NGC 104 (GlC): 2 children"]

    def test_the_build_reports_it(self):
        index = simbad_index(list(self.objects), self.links)
        systems = build(
            Inputs(simbad=read_simbad(index.stars), simbad_index=index),
            FakeResolver({}, []),
        )
        assert systems.counts[f"{SIMBAD}: {NON_STELLAR}"] == 1
        assert systems.events["kind"].to_pylist().count(NON_STELLAR) == 1


class TestPlaceGuard:
    """A candidate is wrong only when it is far from its WDS id and from the
    place of its row. 06530+3852 is RA 103.25, Dec +38.87."""

    w = "06530+3852"

    def guarded(self, *points: dict, ra=None, dec=None, parent_sep=None) -> Reduced:
        base = dict.fromkeys(NODES.names)
        table = pa.Table.from_pylist(
            [
                base
                | {
                    "source": MSC,
                    "system": self.w,
                    "node": 0,
                    "label": "AB",
                    "parent": -1,
                    "separation": parent_sep,
                },
                base
                | {
                    "source": MSC,
                    "system": self.w,
                    "node": 1,
                    "label": "B",
                    "parent": 0,
                    "ra": ra,
                    "dec": dec,
                },
            ],
            schema=NODES,
        )
        self.found: list[list[tuple[int, int]]] = [
            [],
            [(point["key"], 2) for point in points],
        ]
        out = Reduced()
        place_guard(table, self.found, facts(*points), out)
        return out

    def test_the_place_of_an_id(self):
        assert id_place(self.w) == (103.25, pytest.approx(38 + 52 / 60))
        assert id_place("01234-0506") == (pytest.approx(20.85), -(5 + 6 / 60))
        assert id_place("76600") is None

    def test_a_wrong_id_leaves(self):
        out = self.guarded(fact(A, 104.288, 47.589, 9.0))
        assert self.found[1] == []
        assert out.counts[f"{MSC}: {ID_OFF}"] == 1
        assert out.events == [(ID_OFF, MSC, f"{self.w} B: {A} is 31517″ off")]

    def test_a_near_star_stays(self):
        out = self.guarded(fact(A, 103.3, 38.9, 9.0))
        assert self.found[1] == [(A, 2)]
        assert not out.events

    def test_the_row_place_saves_a_far_star(self):
        """AU Mic and Capella H are far from the WDS id that they follow."""
        out = self.guarded(fact(A, 104.288, 47.589, 9.0), ra=104.28, dec=47.59)
        assert self.found[1] == [(A, 2)]
        assert not out.events

    def test_a_rough_row_place_does_not_refute(self):
        """WDS row places can be rough (09186+2944 A): the id still holds."""
        self.guarded(fact(A, 103.3, 38.9, 9.0), ra=110.0, dec=30.0)
        assert self.found[1] == [(A, 2)]

    def test_a_wide_separation_above_saves_a_far_star(self):
        self.guarded(fact(A, 103.25, 40.0, 9.0), parent_sep=7000.0)
        assert self.found[1] == [(A, 2)]

    def test_a_fast_star_has_moved(self):
        """A star of 4″/yr moves 64″ from J2000 to the catalogue epoch."""
        out = self.guarded(
            fact(A, 104.288, 47.589, 9.0, pmra=4000.0, pmdec=0.0),
            ra=104.288,
            dec=47.589 + 100 / 3600,
        )
        assert self.found[1] == [(A, 2)]
        assert not out.events

    def test_a_label_that_is_no_wds_id(self):
        out = self.guarded(fact(A, 200.0, 40.0, 9.0))
        assert out.events
        self.w = "76600"
        assert not self.guarded(fact(A, 200.0, 40.0, 9.0)).events


class TestPlaceLinks:
    """MSC and WDS letter one star differently (MSC C is WDS B). Their places
    agree, so the object of the WDS row reaches the MSC row."""

    w = "01234+0506"
    place = (20.0, 5.0 + 10 / 3600)

    def tables(
        self, b: tuple[float, float], c: tuple[float, float] = (20.0, 5.1)
    ) -> tuple[pa.Table, pa.Table]:
        msc = msc_nodes(
            [
                msc_comp(self.w, "A"),
                msc_comp(self.w, "C", RAdeg=self.place[0], DEdeg=self.place[1]),
            ],
            [msc_pair(self.w, "A", "C", "*")],
            [],
        )
        wds = wds_catalogue(
            {self.w: [wds_pair("A", "B", 10.0), wds_pair("A", "C", 30.0)]},
            {
                (self.w, "A"): wds_component(None, 20.0, 5.0),
                (self.w, "B"): wds_component(None, *b),
                (self.w, "C"): wds_component(None, *c),
            },
        ).nodes()
        return msc, wds

    def found(
        self, msc: pa.Table, wds: pa.Table
    ) -> dict[str, list[list[tuple[int, int]]]]:
        keys = {"A": 1, "B": 2, "C": 3}
        return {
            MSC: [[] for _ in range(msc.num_rows)],
            WDS: [
                [(keys[label], 2)] if label in keys else []
                for label in wds["label"].to_pylist()
            ],
        }

    def test_a_place_links_other_letters(self):
        msc, wds = self.tables(self.place)
        out = Reduced()
        links, placed = place_links(msc, wds, self.found(msc, wds), out)
        assert links == {(*MSC_ID, f"{self.w} C"): (2, LETTER)}
        assert placed == frozenset({msc["label"].to_pylist().index("C")})
        assert out.counts[f"{MSC}: members by place"] == 1

    def test_too_far_is_no_link(self):
        msc, wds = self.tables(offset(*self.place, 2.0, 90.0))
        links, placed = place_links(msc, wds, self.found(msc, wds), Reduced())
        assert not links
        assert not placed

    def test_the_next_star_limits_the_reach(self):
        """The nearest star is 0.9″ off, and the next 1″: either can be it."""
        msc, wds = self.tables(
            offset(*self.place, 0.9, 180.0), offset(*self.place, 1.0, 0.0)
        )
        links, _ = place_links(msc, wds, self.found(msc, wds), Reduced())
        assert not links

    def test_a_place_rules_out_the_letter_link(self):
        msc, wds = self.tables(self.place)
        found = self.found(msc, wds)
        out = Reduced()
        _, placed = place_links(msc, wds, found, out)
        letters = letter_links(msc, wds, found, out, placed)
        assert (*WDS_ID, f"{self.w} C") not in letters
        assert not out.two_stars


class TestMscMatch:
    """An MSC component with no id goes to a match by position, at J2000."""

    w = "01234+0506"

    def test_it_takes_the_matched_star(self):
        msc = msc_nodes(
            [
                msc_comp(self.w, "A", HIP=1, RAdeg=20.0, DEdeg=5.0),
                msc_comp(self.w, "B", RAdeg=20.0, DEdeg=5.0 + 10 / 3600),
            ],
            [msc_pair(self.w, "A", "B", "*", Sep=10.0, Sunit='"')],
            [],
        )
        assert set(msc["epoch"].to_pylist()) == {2000.0}
        resolver = FakeResolver(
            {("hip", "2007", "1"): A},
            [
                fact(A, 20.0, 5.0, 9.0, parallax=10.0),
                fact(B, 20.0, 5.0 + 10 / 3600, 9.5, parallax=10.0),
            ],
            {f"{self.w} B": B},
        )
        systems = build(Inputs(msc=msc), resolver)
        assert resolver.matched == [f"{self.w} B"]
        assert systems.counts[f"{MSC}: members matched by position"] == 1
        keys = systems.points["key"].to_pylist()
        assert sorted(keys) == [A, B]


class TestNestedEntries:
    """WDS 04445+3953: AB and AB,C hold one point, so they are one node. The
    entries of both stay."""

    w = "04445+3953"

    def test_the_outer_entry_stays(self):
        catalogue = wds_catalogue(
            {
                self.w: [
                    wds_pair("A", "B", 30.0, notes="N O", mag1=7.0, mag2=9.0),
                    wds_pair("AB", "C", 90.0, notes="N O", mag1=7.0, mag2=10.0),
                ]
            },
            {(self.w, "A"): wds_component(1)},
        )
        systems = build(
            Inputs(wds=catalogue),
            FakeResolver(
                {("gaia", "dr3", "1"): A},
                [fact(A, 71.0, 39.9, 7.0, parallax=10.0)],
            ),
        )
        root = systems.nodes.to_pylist()[0]
        assert (root["stars"], root["class"]) == (3, "multiple star")
        labels = [
            row["label"] for row in systems.members.to_pylist() if row["kind"] == ENTRY
        ]
        assert sorted(labels) == ["B", "C"]


class TestReport:
    """The report counts each class of split and gives examples."""

    def test_the_splits(self):
        rows = [
            (f"{UNBOUND}: {WIDE}", WDS, "wide"),
            (f"{UNBOUND}: {WIDE}", WDS, "wide too"),
            (f"{UNBOUND}: {MOTION}", WDS, "moving"),
            (f"{UNBOUND}: {IN_CLUSTER}", WDS, "neighbours"),
            (ID_OFF, MSC, "off"),
            (GROUP_LEAVES, SIMBAD, "point"),
            (NON_STELLAR, SIMBAD, "cluster"),
            (WRONG_OBJECT, WDS, "object"),
            (PLANET_ROW, WDS, "planet"),
        ]
        events = pa.Table.from_pylist(
            [{"kind": k, "source": s, "text": t} for k, s, t in rows],
            schema=assemble.EVENTS,
        )
        tables = (
            assemble.NODES,
            assemble.MEMBERS,
            assemble.POINTS,
            assemble.ABSORBED,
            DISTANCES,
            assemble.HOSTS,
            assemble.OVERLAPS,
            assemble.NAMES,
        )
        empty = [schema.empty_table() for schema in tables]
        lines = report_lines(assemble.Systems(*empty, events, counts=Counter()))
        at = lines.index("splits:")
        assert sorted(lines[at + 1 : at + 9]) == sorted(
            [
                f"  {UNBOUND}: {WIDE}: 2",
                f"  {UNBOUND}: {MOTION}: 1",
                f"  {UNBOUND}: {IN_CLUSTER}: 1",
                f"  {WRONG_OBJECT}: 1",
                f"  {ID_OFF}: 1",
                f"  {GROUP_LEAVES}: 1",
                f"  {NON_STELLAR}: 1",
                f"  {PLANET_ROW}: 1",
            ]
        )
        assert f"  {UNBOUND}: {WIDE}: wide too" in lines
        assert f"  {NON_STELLAR}: cluster" in lines
