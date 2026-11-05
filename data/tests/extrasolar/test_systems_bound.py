"""Tests for the rules that keep a system to bound stars."""

import math
from collections import Counter
from collections.abc import Sequence

import pyarrow as pa
import pytest

from space_map_data.extrasolar.systems import assemble
from space_map_data.extrasolar.systems.build import build
from space_map_data.extrasolar.systems.groups import GROUP_LEAVES
from space_map_data.extrasolar.systems.msc import msc_nodes
from space_map_data.extrasolar.systems.nodes import (
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
from space_map_data.extrasolar.systems.parallax import (
    MOTION,
    WIDE,
    excess,
    projected,
    unbound,
    wrong_object,
)
from space_map_data.extrasolar.systems.prepare import (
    ID_OFF,
    Inputs,
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


def reduced(
    rows: Sequence[tuple],
    candidates: list[list[tuple[int, int]]],
    points: list[dict],
    close: frozenset[int] = frozenset(),
    dropped: frozenset[int] = frozenset(),
    source: str = WDS,
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
        table, 0, candidates, facts(*points), 0, out, dropped=dropped, close=close
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

    def test_only_gaia_motions_count(self):
        second = star(B, 100.0, pmra=30.0, astrometry=min(HIPPARCOS_ASTROMETRY))
        assert unbound(one(star(A, 0.0)), one(second)) is None


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

    def test_a_point_that_holds_several_has_no_motion_test(self):
        rows = [
            ("AB", -1, None, None, None),
            ("A", 0, None, None, None),
            ("B", 0, 100.0, [VISUAL], None),
        ]
        out = reduced(
            rows,
            [[], [(A, 2)], [(B, 2)]],
            [star(A, 0.0), star(B, 100.0, pmra=30.0)],
            close=frozenset({B}),
        )
        assert [group.keys for group in out.groups] == [frozenset({A, B})]

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
            assemble.DISTANCES,
            assemble.HOSTS,
            assemble.OVERLAPS,
            assemble.NAMES,
        )
        empty = [schema.empty_table() for schema in tables]
        lines = report_lines(assemble.Systems(*empty, events, counts=Counter()))
        at = lines.index("splits:")
        assert sorted(lines[at + 1 : at + 8]) == sorted(
            [
                f"  {UNBOUND}: {WIDE}: 2",
                f"  {UNBOUND}: {MOTION}: 1",
                f"  {WRONG_OBJECT}: 1",
                f"  {ID_OFF}: 1",
                f"  {GROUP_LEAVES}: 1",
                f"  {NON_STELLAR}: 1",
                f"  {PLANET_ROW}: 1",
            ]
        )
        assert f"  {UNBOUND}: {WIDE}: wide too" in lines
        assert f"  {NON_STELLAR}: cluster" in lines
