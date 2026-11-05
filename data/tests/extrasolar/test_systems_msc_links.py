"""Tests for the links that reach the stars of the MSC."""

from collections.abc import Sequence
from typing import ClassVar
from unittest.mock import MagicMock

import numpy as np
import pyarrow as pa
import pytest

from space_map_data.extrasolar.match import Pairs
from space_map_data.extrasolar.systems.build import build
from space_map_data.extrasolar.systems.msc import (
    MSC_MATCHER,
    MSC_POSITION_ERROR,
    msc_nodes,
)
from space_map_data.extrasolar.systems.nodes import MSC, MSC_ID, WDS, WDS_ID
from space_map_data.extrasolar.systems.parallax import (
    MAX_RUWE,
    disagree,
    unbound,
    veto_error,
)
from space_map_data.extrasolar.systems.prepare import (
    WDS_POSITION_ERROR,
    Inputs,
    letter_links,
    match_rows,
    vetoed_pairs,
)
from space_map_data.extrasolar.systems.reduce import Reduced
from space_map_data.extrasolar.systems.registry import RegistryResolver, point_facts
from space_map_data.extrasolar.systems.resolve import FACTS, MATCH, Fact, Facts
from space_map_data.extrasolar.systems.wds import COMPONENT_KIND, WDS_MATCHER
from space_map_data.extrasolar.tables import POINT_SOURCE
from tests.extrasolar.conftest import offset
from tests.extrasolar.systems_fakes import (
    FakeResolver,
    fact,
    msc_comp,
    msc_pair,
    wds_catalogue,
    wds_component,
    wds_pair,
)

A, B, C, D = 201, 202, 203, 204


def rows_of(table: pa.Table) -> dict[str, dict]:
    return {row["label"]: row for row in table.to_pylist()}


def hip_ids(row: dict) -> list[str]:
    return [i["catalogue_id"] for i in row["ids"] if i["catalogue"] == "hip"]


def facts(*rows: dict) -> Facts:
    return Facts(pa.Table.from_pylist(list(rows), schema=FACTS))


def one(row: dict) -> Fact:
    found = facts(row).get(row["key"])
    assert found is not None
    return found


class TestLetterHolders:
    """Comp A holds the light of Aa and Ab, and a tree can have no node A."""

    def test_sw_lyn(self):
        """MSC 08077+4148: Aab,Ac and Aa,Ab, with the only row on comp A."""
        w = "08077+4148"
        comp = msc_comp(
            w,
            "A",
            RAdeg=121.923215,
            DEdeg=41.800483,
            PMRA=-17.5,
            PMDE=-36.6,
            plx=3.06,
            HIP=39771,
            HD=67008,
            Vmag=9.66,
            Gmag=9.5,
        )
        pairs = [msc_pair(w, "Aab", "Ac", "*"), msc_pair(w, "Aa", "Ab", "Aab")]
        rows = rows_of(msc_nodes([comp], pairs, []))
        root = rows["Aab,Ac"]
        assert (root["ra"], root["dec"]) == (121.923215, 41.800483)
        assert hip_ids(root) == ["39771"]
        assert root["pmra"] == pytest.approx(-17.5)
        assert root["v_mag"] == pytest.approx(9.66)
        assert all(rows[label]["ra"] is None for label in ("Aab", "Aa", "Ab", "Ac"))

    def test_a_node_of_other_letters_holds_no_row(self):
        """MSC 00406-4831: AC holds Aa, Ab and C, so comp A goes on Aab."""
        w = "00406-4831"
        pairs = [
            msc_pair(w, "AC", "B", "*"),
            msc_pair(w, "Aab", "C", "AC"),
            msc_pair(w, "Aa", "Ab", "Aab"),
        ]
        comp = msc_comp(
            w,
            "A",
            HIP=3186,
            RAdeg=10.138618,
            DEdeg=-48.509046,
            PMRA=211.6,
            PMDE=53.2,
            plx=16.62,
            Vmag=11.07,
            Gmag=10.6,
        )
        rows = rows_of(msc_nodes([comp], pairs, []))
        assert hip_ids(rows["Aab"]) == ["3186"]
        assert hip_ids(rows["AC"]) == []

    def test_a_lone_label_takes_its_letter(self):
        w = "01000+0100"
        comp = msc_comp(w, "A", HIP=1, RAdeg=15.0, DEdeg=1.0)
        rows = rows_of(msc_nodes([comp], [msc_pair(w, "Aa", "B", "*")], []))
        assert hip_ids(rows["Aa"]) == ["1"]

    def test_a_row_of_its_own_wins(self):
        w = "01000+0100"
        comp = [msc_comp(w, "A", HIP=1), msc_comp(w, "Aa", HIP=2)]
        pairs = [
            msc_pair(w, "Aa", "B", "*"),
            msc_pair(w, "Aa1", "Aa2", "Aa"),
        ]
        rows = rows_of(msc_nodes(comp, pairs, []))
        assert hip_ids(rows["Aa"]) == ["2"]

    def test_a_star_of_a_refuted_pair_stays_off(self):
        """MSC 00094-2759: C is only in a pair that the MSC refutes."""
        w = "00094-2759"
        pairs = [
            msc_pair(w, "A", "B", "*", Type="V", Sep=1.5, Sunit='"'),
            msc_pair(w, "AB", "C", "X", Type="Xhpm", Sep=75.7, Sunit='"'),
        ]
        comp = msc_comp(w, "C", RAdeg=2.316973, DEdeg=-27.997361, Gmag=18.3)
        rows = rows_of(msc_nodes([comp], pairs, []))
        assert "C" not in rows
        assert all(row["ra"] is None for row in rows.values())

    def test_a_loop_ends(self):
        w = "01000+0100"
        pairs = [msc_pair(w, "Aa", "Ab", "Ab"), msc_pair(w, "Ab", "Aa", "Aa")]
        assert msc_nodes([msc_comp(w, "A")], pairs, []) is not None


class TestGroupsInTheMatch:
    """The MSC's place sits on a group when its stars are unresolved."""

    w = "08077+4148"
    place: ClassVar = {"RAdeg": 121.923215, "DEdeg": 41.800483}

    def sent(self, comp: list[dict], held: dict[str, int]) -> list[str]:
        pairs = [
            msc_pair(self.w, "Aab", "Ac", "*"),
            msc_pair(self.w, "Aa", "Ab", "Aab"),
        ]
        table = msc_nodes(comp, pairs, [])
        labels = table["label"].to_pylist()
        found = [[(held[x], 4)] if x in held else [] for x in labels]
        rows = match_rows(table, found, MSC_ID, groups=True)
        return [text.split(" ")[1] for text in rows["catalogue_id"].to_pylist()]

    def test_a_group_of_unplaced_stars_goes(self):
        assert self.sent([msc_comp(self.w, "A", **self.place)], {}) == ["Aab,Ac"]

    def test_a_group_goes_beside_a_companion_with_a_star(self):
        comp = [msc_comp(self.w, "A", **self.place)]
        assert self.sent(comp, {"Ac": A}) == ["Aab,Ac"]

    def test_a_group_never_takes_the_star_of_a_node_near_it(self):
        comp = [
            msc_comp(self.w, "A", **self.place),
            msc_comp(self.w, "Ac", HIP=9, **self.place),
        ]
        pairs = [
            msc_pair(self.w, "Aab", "Ac", "*"),
            msc_pair(self.w, "Aa", "Ab", "Aab"),
        ]
        table = msc_nodes(comp, pairs, [])
        found = [[(A, 4)] if x == "Ac" else [] for x in table["label"].to_pylist()]
        rows = match_rows(table, found, MSC_ID, groups=True)
        assert rows["match_exclude"].to_pylist() == [[A]]

    def test_the_wds_sends_leaves_only(self):
        table = msc_nodes(
            [msc_comp(self.w, "A", **self.place)],
            [msc_pair(self.w, "Aa", "Ab", "*")],
            [],
        )
        found: list[list[tuple[int, int]]] = [[] for _ in range(table.num_rows)]
        assert match_rows(table, found, WDS_ID).num_rows == 0

    def test_sw_lyn_is_one_point_of_three_stars(self):
        """A row that only comp A places, on a star that no id reaches."""
        comp = msc_comp(self.w, "A", Vmag=9.66, Gmag=9.5, **self.place)
        pairs = [
            msc_pair(self.w, "Aab", "Ac", "*", Type="E*", P=2120.0, Punit="d"),
            msc_pair(self.w, "Aa", "Ab", "Aab", Type="E,S2", P=0.644, Punit="d"),
        ]
        resolver = FakeResolver(
            {},
            [fact(A, 121.923215, 41.800483, 9.5, parallax=3.06)],
            {f"{self.w} Aab,Ac": A},
        )
        systems = build(Inputs(msc=msc_nodes([comp], pairs, [])), resolver)
        points = systems.points.to_pylist()
        assert [row["key"] for row in points] == [A]
        assert points[0]["stars"] == 3

    def test_a_companion_keeps_the_star_of_its_group_beside_it(self):
        """A group's star that is not its member's is the primary."""
        comp = [
            msc_comp(self.w, "A", Vmag=9.66, Gmag=9.5, **self.place),
            msc_comp(
                self.w,
                "Ac",
                HIP=9,
                RAdeg=121.923215,
                DEdeg=41.800483 + 5 / 3600,
                Gmag=12.0,
            ),
        ]
        pairs = [msc_pair(self.w, "Aab", "Ac", "*", Type="V")]
        pairs.append(msc_pair(self.w, "Aa", "Ab", "Aab", Type="E,S2"))
        resolver = FakeResolver(
            {("hip", "2007", "9"): B},
            [
                fact(A, 121.923215, 41.800483, 9.5, parallax=3.06),
                fact(B, 121.923215, 41.800483 + 5 / 3600, 12.0, parallax=3.06),
            ],
            {f"{self.w} Aab,Ac": A},
        )
        systems = build(Inputs(msc=msc_nodes(comp, pairs, [])), resolver)
        assert sorted(systems.points["key"].to_pylist()) == [A, B]


class TestMatchBeforeLetters:
    """A place beats a letter. MSC 09281-6420 B and C are 3.991″ apart, 213″
    from A, so B gives no separation that could refute WDS B, a star 10.7″
    from A at another distance."""

    w = "09281-6420"
    a = (142.020984, -64.337207)
    b = (142.020956, -64.278078)
    c = (142.021115, -64.276972)
    wrong = (142.022167, -64.340639)

    def inputs(self, separation: float | None = None) -> Inputs:
        comp = [
            msc_comp(self.w, "A", HIP=46428, RAdeg=142.022027, DEdeg=-64.337671),
            msc_comp(
                self.w,
                "B",
                RAdeg=142.021997,
                DEdeg=-64.278545,
                PMRA=-101.7,
                PMDE=105.1,
                plx=12.79,
                Vmag=13.44,
                Gmag=12.75,
            ),
            msc_comp(
                self.w,
                "C",
                RAdeg=142.022136,
                DEdeg=-64.277433,
                PMRA=-99.7,
                PMDE=103.8,
                plx=12.75,
                Vmag=16.28,
                Gmag=15.06,
            ),
        ]
        pairs = [
            msc_pair(self.w, "A", "BC", "*", Sep=212.865, Sunit='"'),
            msc_pair(self.w, "B", "C", "BC", Sep=3.991, Sunit='"'),
        ]
        if separation is not None:
            pairs = [msc_pair(self.w, "A", "B", "*", Sep=separation, Sunit='"')]
        wds = wds_catalogue(
            {self.w: [wds_pair("A", "B", 10.7)]},
            {
                (self.w, "A"): wds_component(None, 142.022042, -64.337667),
                (self.w, "B"): wds_component(D, *self.wrong),
            },
        )
        return Inputs(msc=msc_nodes(comp, pairs, []), wds=wds)

    def resolver(self, matched: dict[str, int]) -> FakeResolver:
        return FakeResolver(
            {("hip", "2007", "46428"): A, ("gaia", "dr3", str(D)): D},
            [
                fact(A, *self.a, 8.888, parallax=12.787),
                fact(B, *self.b, 12.755, parallax=12.788),
                fact(C, *self.c, 15.062, parallax=12.75),
                fact(D, *self.wrong, 13.0, parallax=2.54),
            ],
            matched,
        )

    def test_the_star_at_its_place_wins(self):
        resolver = self.resolver({f"{self.w} B": B, f"{self.w} C": C})
        systems = build(self.inputs(), resolver)
        assert systems.counts[f"{MSC}: members matched by position"] == 2
        assert sorted(systems.points["key"].to_pylist()) == [A, B, C]

    def test_it_goes_to_the_match_before_it_has_a_letter(self):
        resolver = self.resolver({})
        build(self.inputs(), resolver)
        assert f"{self.w} B" in resolver.matched

    def test_with_no_star_at_its_place_the_letter_stands(self):
        """A fast star with no motion in the MSC is off its place at J2016."""
        resolver = self.resolver({})
        systems = build(self.inputs(), resolver)
        assert systems.counts[f"{MSC}: members by letter"] == 1

    def test_a_matched_row_lends_no_star(self):
        inputs = self.inputs()
        assert inputs.msc is not None and inputs.wds is not None
        msc, wds = inputs.msc, inputs.wds.nodes()
        labels = msc["label"].to_pylist()
        found = {
            MSC: [[(B, 9)] if x == "B" else [] for x in labels],
            WDS: [[] for _ in range(wds.num_rows)],
        }
        links = letter_links(msc, wds, found, Reduced(), frozenset({labels.index("B")}))
        assert not links

    def test_a_matched_row_still_shows_two_stars(self):
        """Separations that disagree say so, whatever the row is linked to."""
        inputs = self.inputs(separation=212.865)
        assert inputs.msc is not None and inputs.wds is not None
        msc, wds = inputs.msc, inputs.wds.nodes()
        labels = msc["label"].to_pylist()
        found = {
            MSC: [[(B, 9)] if x == "B" else [] for x in labels],
            WDS: [[] for _ in range(wds.num_rows)],
        }
        out = Reduced()
        letter_links(msc, wds, found, out, frozenset({labels.index("B")}))
        assert f"{self.w} B" in out.two_stars

    def test_a_star_at_its_place_beats_a_wds_star_near_it(self):
        """MSC 00169+2004: WDS B has no id, so WDS A's star is the nearest one
        that a place link can lend to MSC B, 0.8″ off. B's own star is at its
        place to 1 mas."""
        w = "00169+2004"
        comp = [
            msc_comp(w, "A", RAdeg=4.236478, DEdeg=20.065396, PMRA=238.9, PMDE=17.7),
            msc_comp(w, "B", RAdeg=4.236818, DEdeg=20.065264, PMRA=231.6, PMDE=28.4),
        ]
        pairs = [msc_pair(w, "A", "B", "*", Sep=1.08, Sunit='"')]
        gaia = 1
        wds = wds_catalogue(
            {w: [wds_pair("A", "B", 1.1)]},
            {
                (w, "A"): wds_component(gaia, 4.236583, 20.065306),
                (w, "B"): wds_component(None, 4.236875, 20.065222),
            },
        )
        resolver = FakeResolver(
            {("gaia", "dr3", str(gaia)): A},
            [
                fact(A, 4.237609, 20.065475, 13.183, parallax=29.31),
                fact(B, 4.237914, 20.06539, 13.261, parallax=29.139),
            ],
            {f"{w} A": A, f"{w} B": B},
        )
        systems = build(Inputs(msc=msc_nodes(comp, pairs, []), wds=wds), resolver)
        assert sorted(systems.points["key"].to_pylist()) == [A, B]
        assert systems.counts[f"{MSC}: members by place"] == 0
        assert not systems.counts[f"{MSC}: cross-match error"]

    def test_a_star_of_a_row_with_an_id_stays(self):
        """α Cen A lies 32″ from where its MSC place and motion put it at
        J2016, as it moves on its orbit too. Its HIP number holds."""
        w = "14396-6050"
        comp = [
            msc_comp(
                w,
                "A",
                HIP=71683,
                RAdeg=219.920411,
                DEdeg=-60.835136,
                PMRA=-3678.0,
                PMDE=482.0,
            ),
            msc_comp(
                w,
                "B",
                HIP=71681,
                RAdeg=219.896096,
                DEdeg=-60.837528,
                PMRA=-3614.4,
                PMDE=803.0,
            ),
        ]
        pairs = [msc_pair(w, "A", "B", "*", Type="S2,V", Sep=17.515, Sunit='"')]
        resolver = FakeResolver(
            {("hip", "2007", "71683"): A, ("hip", "2007", "71681"): B},
            [
                fact(A, 219.868508, -60.831879, -0.172, "hipparcos-2007", 754.81),
                fact(B, 219.863136, -60.83395, 1.112, "hipparcos-2007", 796.92),
            ],
        )
        systems = build(Inputs(msc=msc_nodes(comp, pairs, [])), resolver)
        assert resolver.matched == []
        assert sorted(systems.points["key"].to_pylist()) == [A, B]


class TestMscError:
    """MSC places are Gaia places, so a neighbour 4.6″ off is not the star."""

    def test_the_rows_carry_their_error(self):
        w = "19168+4052"
        comp = msc_comp(w, "A", RAdeg=289.202752, DEdeg=40.867442, Gmag=16.44)
        table = msc_nodes([comp], [msc_pair(w, "Aa", "Ab", "*")], [])
        found: list[list[tuple[int, int]]] = [[] for _ in range(table.num_rows)]
        rows = match_rows(table, found, MSC_ID, groups=True)
        assert rows["match_error"].to_pylist() == [pytest.approx(MSC_POSITION_ERROR)]

    @staticmethod
    def score(matcher, error: float, apart: float, mags=(16.44, 15.54)) -> float:
        pairs = Pairs(
            separation=np.array([apart]),
            row_error=np.array([error]),
            row_size=np.array([np.nan]),
            row_mag=np.array([mags[0]]),
            row_kind=pa.array([COMPONENT_KIND]),
            key_error=np.array([1e-5]),
            key_size=np.array([np.nan]),
            key_mag=np.array([mags[1]]),
            key_kind=pa.array([COMPONENT_KIND]),
        )
        return float(matcher.score(pairs)[0])

    def test_the_neighbour_of_19168_4052(self):
        """The WDS error reaches it, 4.6″ off and 0.9 mag out."""
        assert np.isfinite(self.score(WDS_MATCHER, WDS_POSITION_ERROR, 4.6))
        assert np.isnan(self.score(MSC_MATCHER, MSC_POSITION_ERROR, 4.6))

    @pytest.mark.parametrize(("apart", "found"), [(1.49, True), (1.51, False)])
    def test_the_limit_is_five_sigma(self, apart, found):
        score = self.score(MSC_MATCHER, MSC_POSITION_ERROR, apart)
        assert np.isfinite(score) == found

    def test_the_dry_run_takes_the_matcher_of_the_kind(self):
        rows = pa.Table.from_pylist(
            [
                {
                    "catalogue_id": "19168+4052 Aa,Ab",
                    "mint": False,
                    "match_ra": 289.202752,
                    "match_dec": 40.867442,
                    "match_mag": 16.44,
                    "match_error": MSC_POSITION_ERROR,
                }
            ],
            schema=MATCH,
        )
        place = offset(289.202752, 40.867442, 2.0, 90.0)
        candidates = pa.table(
            {
                "id": [92],
                "ra": [place[0]],
                "dec": [place[1]],
                "pos_error": pa.array([1e-5], pa.float32()),
                "size": pa.array([None], pa.float32()),
                "mag": pa.array([16.3], pa.float32()),
                "kind": [COMPONENT_KIND],
            }
        )
        registry = MagicMock(part_regions=lambda _: [])
        registry.positions = lambda _: candidates
        resolver = RegistryResolver(registry)
        assert resolver.match(rows, MSC_ID).tolist() == [0]
        assert resolver.match(rows, WDS_ID).tolist() == [92]


def gaia_star(
    key: int,
    parallax: float,
    error: float,
    ruwe: float | None,
    arcsec: float = 0.0,
) -> dict:
    """A star `arcsec` from a fixed place: the veto reads only how far apart."""
    place = offset(204.27, -36.51, arcsec, 90.0)
    return fact(
        key,
        *place,
        10.0,
        "gaia-dr3",
        parallax,
        parallax_error=error,
        ruwe=ruwe,
        pmra=0.0,
        pmdec=0.0,
        pmra_error=0.01,
        pmdec_error=0.01,
    )


class TestRuinedParallax:
    """Real pairs. Over RUWE 1.4 a solution does not fit its star, and the veto
    reads its error scaled by that RUWE."""

    def test_13371_3631(self):
        a = one(gaia_star(A, 9.793, 0.371, 9.167))
        b = one(gaia_star(B, 13.662, 0.033, 1.316, 0.992))
        c = one(gaia_star(C, 13.356, 0.157, 1.083, 8.838))
        assert not disagree(a, b)
        assert not disagree(a, c)

    def test_11498_4637(self):
        a = one(gaia_star(A, 7.218, 0.367, 18.027))
        b = one(gaia_star(B, 9.095, 0.033, 1.217, 9.115))
        assert not disagree(a, b)

    def test_the_same_pair_with_a_good_solution_is_vetoed(self):
        a = one(gaia_star(A, 9.793, 0.371, MAX_RUWE))
        b = one(gaia_star(B, 13.662, 0.033, 1.316, 0.992))
        assert disagree(a, b)

    def test_a_ruined_star_that_is_far_stays_vetoed(self):
        """WDS 21199-2000 B: Gaia RVs -23.7 and 59.0 km/s."""
        a = one(gaia_star(A, 0.903, 0.020, 1.158))
        b = one(gaia_star(B, 2.746, 0.067, 3.652, 3.869))
        assert disagree(a, b)

    def test_no_ruwe_is_read_as_it_stands(self):
        a = one(gaia_star(A, 9.793, 0.371, None))
        b = one(gaia_star(B, 13.662, 0.033, None, 0.992))
        assert disagree(a, b)

    def test_veto_error(self):
        found = veto_error(np.array([0.1, 0.1, 0.1]), np.array([1.4, 3.0, np.nan]))
        assert found == pytest.approx([0.1, 0.3, 0.1])

    def test_el_badry_pairs_read_the_same_error(self):
        table = facts(
            gaia_star(A, 9.793, 0.371, 9.167),
            gaia_star(B, 13.662, 0.033, 1.316, 0.992),
            gaia_star(C, 9.793, 0.371, 1.0),
            gaia_star(D, 13.662, 0.033, 1.0, 0.992),
        )
        first, second = np.array([A, C]), np.array([B, D])
        found = vetoed_pairs(table, first, second, frozenset())
        assert found.tolist() == [False, True]

    def test_a_ruined_parallax_keeps_its_sky_place(self):
        """The bound test reads no parallax error: 3 pc is 3 pc."""
        a = one(gaia_star(A, 10.0, 0.1, 9.0))
        b = one(gaia_star(B, 10.0, 0.01, 1.0, 6200.0))
        assert unbound(a, b, moving=False) is not None

    def test_it_keeps_a_physical_member(self):
        """MSC 11498+4637: A, B and C all stay."""
        w = "11498+4637"
        comp = [
            msc_comp(w, "A", RAdeg=177.439437, DEdeg=46.620152, Gmag=11.28),
            msc_comp(w, "B", RAdeg=177.436118, DEdeg=46.621219, Gmag=15.02),
            msc_comp(w, "C", RAdeg=177.4334, DEdeg=46.627747, Gmag=16.21),
        ]
        pairs = [
            msc_pair(w, "AB", "C", "*", Type="Cmhp", Sep=31.3, Sunit='"'),
            msc_pair(w, "A", "B", "AB", Type="Cmhp", Sep=9.11, Sunit='"'),
        ]

        def star(key: int, ra: float, dec: float, values: Sequence[float]) -> dict:
            return fact(
                key,
                ra,
                dec,
                values[0],
                parallax=values[1],
                parallax_error=values[2],
                ruwe=values[3],
                pmra=-50.0,
                pmdec=-16.0,
                pmra_error=0.05,
                pmdec_error=0.05,
            )

        resolver = FakeResolver(
            {},
            [
                star(A, 177.439437, 46.620152, (11.28, 7.218, 0.367, 18.027)),
                star(B, 177.436118, 46.621219, (15.02, 9.095, 0.033, 1.217)),
                star(C, 177.4334, 46.627747, (16.21, 9.123, 0.053, 1.029)),
            ],
            {f"{w} A": A, f"{w} B": B, f"{w} C": C},
        )
        systems = build(Inputs(msc=msc_nodes(comp, pairs, [])), resolver)
        assert sorted(systems.points["key"].to_pylist()) == [A, B, C]

    def test_ruwe_is_of_the_gaia_solution_only(self):
        """A Hipparcos parallax owes nothing to Gaia's fit of the star."""
        positions = pa.table(
            {
                "key": pa.array([A, B], pa.int64()),
                "ra": [1.0, 2.0],
                "dec": [1.0, 2.0],
                "pmra": pa.array([0.0, 0.0], pa.float32()),
                "pmdec": pa.array([0.0, 0.0], pa.float32()),
                "mag": pa.array([9.0, 9.0], pa.float32()),
            }
        )
        point = pa.Table.from_pylist(
            [
                {"id": A, "astrometry_source": "gaia-dr3", "ruwe": 2.0},
                {"id": B, "astrometry_source": "hipparcos-2007", "ruwe": 2.0},
            ],
            schema=POINT_SOURCE.schema,
        )
        meta = pa.table(
            {
                "id": pa.array([A, B], pa.int64()),
                "name": pa.array([None, None], pa.string()),
                "name_source": pa.array([None, None], pa.string()),
            }
        )
        found = point_facts(positions, point, meta)
        assert found["ruwe"].to_pylist() == [2.0, None]
