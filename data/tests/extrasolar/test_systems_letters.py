"""Tests of the links between MSC and WDS components of one letter."""

import pyarrow.compute as pc
import pytest

from space_map_data.download.providers.stars import wds
from space_map_data.extrasolar.systems.assemble import Systems
from space_map_data.extrasolar.systems.build import build
from space_map_data.extrasolar.systems.msc import msc_nodes
from space_map_data.extrasolar.systems.nodes import MSC, MSC_ID, WDS, WDS_ID
from space_map_data.extrasolar.systems.prepare import (
    Inputs,
    letter_links,
    separations_agree,
)
from space_map_data.extrasolar.systems.reduce import Reduced
from space_map_data.extrasolar.systems.resolve import LETTER
from space_map_data.extrasolar.systems.wds import WdsCatalogue
from tests.download.test_star_system_downloads import COMPONENTS, PAIRS
from tests.extrasolar.systems_fakes import (
    FakeResolver,
    fact,
    msc_comp,
    msc_pair,
    wds_catalogue,
    wds_component,
    wds_pair,
)

W = "03082+4057"
REFUTED = f"{WDS}: letter links that the separations refute"
NOT_TESTED = f"{WDS}: letter links with no separation to test"
PROPER_MOTION = ["common proper motion"]
ORBIT = ["visual orbit"]


class TestFirstMeasure:
    """The WDS reader keeps the first measure of a pair beside the last."""

    def test_reads_it(self, tmp_path):
        (tmp_path / wds.PAIRS_FILE).write_text(PAIRS)
        for name in (wds.GAIA_FILE, wds.COMPONENTS_FILE):
            (tmp_path / name).write_text(COMPONENTS)
        ab, ac = WdsCatalogue.read(tmp_path).pairs["14396-6050"]
        assert (ab["first_separation"], ab["separation"]) == (20.5, 8.1)
        # A measure past the width of the field is no measure.
        assert ac["first_separation"] is None

    def test_a_first_measure_past_the_field_is_no_measure(self, tmp_path):
        """The last measure is one, so the pair stays."""
        pairs = PAIRS.replace("  20.5   8.1", " 999.9   8.1")
        (tmp_path / wds.PAIRS_FILE).write_text(pairs)
        for name in (wds.GAIA_FILE, wds.COMPONENTS_FILE):
            (tmp_path / name).write_text(COMPONENTS)
        ab, _ = WdsCatalogue.read(tmp_path).pairs["14396-6050"]
        assert (ab["first_separation"], ab["separation"]) == (None, 8.1)


class TestSeparationsAgree:
    """The MSC separation against the first and last measures of the WDS."""

    @pytest.mark.parametrize(
        ("separation", "measures", "known"),
        [
            (9.3, (None, 9.3), PROPER_MOTION),
            (14.0, (None, 9.4), PROPER_MOTION),
            # 22419+2126 B: the MSC gives the orbit's semi-major axis.
            (3.78, (1.2, 1.4), ORBIT),
            # 11221-2447 B: the pair closed from 1.0″ to 0.1″.
            (1.056, (1.0, 0.1), ORBIT),
            # A pair that the MSC knows by proper motion can still move.
            (1.743, (1.8, 0.1), PROPER_MOTION),
            (0.337, (0.2, 0.2), None),
        ],
    )
    def test_the_same_star(self, separation, measures, known):
        assert separations_agree(separation, measures, known) is True

    @pytest.mark.parametrize(
        ("separation", "measures", "known"),
        [
            # Algol B.
            (0.104, (58.8, 59.4), ORBIT),
            # A component measured once in each direction of a swap.
            (6.84, (1.3, 1.3), PROPER_MOTION),
            (1.35, (6.8, 6.7), PROPER_MOTION),
            (15.0, (None, 9.4), PROPER_MOTION),
            (6.0, (None, 1.0), ORBIT),
            (0.15, (None, 1.0), ORBIT),
        ],
    )
    def test_two_stars(self, separation, measures, known):
        assert separations_agree(separation, measures, known) is False

    @pytest.mark.parametrize(
        ("separation", "measures"),
        [
            (None, (1.0, 1.0)),
            (1.0, (None, None)),
            # The WDS writes -1 for no measure, and 0 for a pair under 0.05″.
            (1.0, (-1.0, -1.0)),
            (1.0, (0.0, 0.0)),
        ],
    )
    def test_no_separation(self, separation, measures):
        assert separations_agree(separation, measures, ORBIT) is None


class TestLetterLinks:
    """Each side lends its best candidate, under one test for both sides."""

    def links(
        self,
        msc_sep: float | None,
        wds_sep: float,
        first: float | None = None,
        kind: str = "V",
    ) -> tuple[dict, Reduced]:
        comp = [msc_comp(W, "A"), msc_comp(W, "B")]
        values = {"Sep": msc_sep, "Sunit": '"'} if msc_sep else {}
        msc = msc_nodes(comp, [msc_pair(W, "A", "B", "*", Type=kind, **values)], [])
        wds = wds_catalogue(
            {W: [wds_pair("A", "B", wds_sep, first_separation=first)]}
        ).nodes()
        found: dict[str, list[list[tuple[int, int]]]] = {
            MSC: [[] for _ in range(msc.num_rows)],
            WDS: [[] for _ in range(wds.num_rows)],
        }
        # The objects of B in each source.
        found[MSC][msc["label"].to_pylist().index("B")] = [(5, 2)]
        found[WDS][wds["label"].to_pylist().index("B")] = [(6, 2)]
        reduced = Reduced()
        return letter_links(msc, wds, found, reduced), reduced

    def test_agreement_links_both_ways(self):
        links, reduced = self.links(1.2, 1.0)
        assert links == {
            (*WDS_ID, f"{W} B"): (5, LETTER),
            (*MSC_ID, f"{W} B"): (6, LETTER),
        }
        assert reduced.counts[REFUTED] == 0
        assert reduced.counts[NOT_TESTED] == 0

    def test_disagreement_links_neither_way(self):
        links, reduced = self.links(0.104, 59.4, first=58.8)
        assert links == {}
        assert reduced.counts[REFUTED] == 1
        assert reduced.events == [
            ("letters of two stars", WDS, f'{W} B: MSC 0.104", WDS 58.8" to 59.4"')
        ]

    def test_the_first_measure_counts(self):
        links, reduced = self.links(1.056, 0.1, first=1.0)
        assert len(links) == 2
        assert reduced.counts[REFUTED] == 0

    def test_a_pair_with_no_motion_has_a_smaller_tolerance(self):
        assert len(self.links(2.0, 1.0, kind="Cmp")[0]) == 0
        assert len(self.links(2.0, 1.0, kind="V")[0]) == 2

    @pytest.mark.parametrize(("msc_sep", "wds_sep"), [(None, 1.0), (1.0, -1.0)])
    def test_no_separation_links_on_the_letter(self, msc_sep, wds_sep):
        links, reduced = self.links(msc_sep, wds_sep)
        assert len(links) == 2
        assert reduced.counts[NOT_TESTED] == 1


class TestTwoStarsOfOneLetter:
    """The MSC's B lies inside the point of A. The WDS's B has no object either,
    so no candidate asks for the test of their separations."""

    def systems(self, msc_sep: float, wds_sep: float) -> Systems:
        resolver = FakeResolver(
            {
                ("hip", "2007", "1"): 90,
                ("gaia", "dr3", "1"): 90,
                ("gaia", "dr3", "2"): 91,
            },
            [
                fact(90, 47.04, 40.96, 2.1, parallax=35.0),
                fact(91, 47.05, 40.97, 8.0, parallax=35.0),
            ],
        )
        msc = msc_nodes(
            [msc_comp(W, "A", HIP=1), msc_comp(W, "B")],
            [msc_pair(W, "A", "B", "*", Type="V", Sep=msc_sep, Sunit='"')],
            [],
        )
        catalogue = wds_catalogue(
            {W: [wds_pair("A", "B", wds_sep), wds_pair("A", "C", 40.0)]},
            {
                (W, "A"): wds_component(1, 47.04, 40.96),
                (W, "C"): wds_component(2, 47.05, 40.97),
            },
        )
        return build(Inputs(msc=msc, wds=catalogue), resolver)

    def test_the_far_star_stays(self):
        systems = self.systems(0.2, 30.0)
        assert systems.two_stars == {f"{W} B"}
        assert systems.counts[REFUTED] == 1
        assert systems.counts["entries that a point of the system holds"] == 0
        entries = systems.members.filter(pc.equal(systems.members["source"], WDS))
        assert "B" in entries["letter"].to_pylist()

    def test_separations_that_agree_are_one_star(self):
        systems = self.systems(0.3, 1.0)
        assert not systems.two_stars
        assert systems.counts["entries that a point of the system holds"] == 1


class TestAlgol:
    """The WDS's B is a field star at 600 pc. The MSC's B is the 680-day star,
    with no object of its own, beside the point of A that holds Aa and Ab."""

    def systems(self, wds_sep: float, kind: str = "V") -> Systems:
        resolver = FakeResolver(
            {("hip", "2007", "14576"): 500, ("gaia", "dr3", "7"): 501},
            [
                fact(500, 47.04, 40.96, 2.1, "hipparcos-2007", parallax=35.0),
                fact(501, 47.05, 40.97, 13.3, parallax=1.66),
            ],
        )
        msc = msc_nodes(
            [msc_comp(W, "A", HIP=14576), msc_comp(W, "B", Vmag=4.7)],
            [
                msc_pair(
                    W,
                    "A",
                    "B",
                    "*",
                    Type=kind,
                    P=680.0,
                    Punit="d",
                    Sep=0.104,
                    Sunit='"',
                ),
                msc_pair(
                    W, "Aa", "Ab", "A", Type="E", P=2.87, Punit="d", Sep=2.3, Sunit="m"
                ),
            ],
            [],
        )
        catalogue = wds_catalogue(
            {W: [wds_pair("A", "B", wds_sep, notes="", mag1=2.1, mag2=12.7)]},
            {
                (W, "A"): wds_component(None, 47.04, 40.96),
                (W, "B"): wds_component(7, 47.05, 40.97),
            },
        )
        return build(Inputs(msc=msc, wds=catalogue), resolver)

    def test_the_field_star_leaves(self):
        systems = self.systems(59.4)
        points = systems.points.filter(pc.equal(systems.points["key"], 501))
        assert points.num_rows == 0

    def test_the_msc_star_stays_beside_the_inner_pair(self):
        systems = self.systems(59.4)
        points = systems.points.filter(pc.equal(systems.points["key"], 500))
        root = systems.nodes.filter(pc.equal(systems.nodes["node"], points["root"][0]))
        assert root["point"].to_pylist() == [False]
        assert root["stars"].to_pylist() == [3]
        members = systems.members.filter(
            pc.equal(systems.members["node"], root["node"][0])
        )
        assert members["letter"].to_pylist() == ["A", "B"]
        assert members["kind"].to_pylist() == ["system", "entry"]

    def test_with_no_visual_orbit_the_point_holds_it(self):
        systems = self.systems(59.4, kind="s")
        root = systems.nodes.filter(pc.equal(systems.nodes["key"], 500))
        assert root["stars"].to_pylist() == [3]
        assert root["root"].to_pylist() == root["node"].to_pylist()

    def test_an_orbit_with_no_period_makes_no_level(self):
        """The WDS notes an orbit but gives no period."""
        catalogue = wds_catalogue(
            {
                W: [
                    wds_pair("Aa1", "Aa2", 0.1),
                    wds_pair("Aa", "Ab", 0.1, notes="O"),
                ]
            },
            {(W, "Aa"): wds_component(9, 47.04, 40.96)},
        )
        resolver = FakeResolver(
            {("gaia", "dr3", "9"): 600}, [fact(600, 47.04, 40.96, 2.1, parallax=35.0)]
        )
        systems = build(Inputs(wds=catalogue), resolver)
        root = systems.nodes.filter(pc.equal(systems.nodes["key"], 600))
        assert root["stars"].to_pylist() == [3]
        assert root["root"].to_pylist() == root["node"].to_pylist()

    def test_a_component_at_the_same_separation_keeps_the_link(self):
        """The letter link, not the parallax, decides the star. An orbit pair
        passes the veto, so a real link keeps the object in the tree."""
        systems = self.systems(0.1)
        assert systems.counts[REFUTED] == 0
        assert 501 in systems.points["key"].to_pylist()
