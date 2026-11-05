"""Tests of the links between MSC and WDS components of one letter."""

from unittest.mock import MagicMock

import pyarrow as pa
import pyarrow.compute as pc
import pytest

from space_map_data.download.providers.stars import wds
from space_map_data.extrasolar.systems.assemble import Assembler, Systems
from space_map_data.extrasolar.systems.build import build
from space_map_data.extrasolar.systems.msc import msc_nodes
from space_map_data.extrasolar.systems.nodes import (
    MSC,
    MSC_ID,
    WDS,
    WDS_ID,
    NodeList,
)
from space_map_data.extrasolar.systems.pairs import el_badry_pairs
from space_map_data.extrasolar.systems.prepare import (
    Inputs,
    _add_links,
    letter_links,
    separations_agree,
)
from space_map_data.extrasolar.systems.reduce import Interior, Reduced
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


class TestAddLinks:
    def test_a_link_keeps_the_order_of_a_rank(self):
        """In a rank, the star that more ids reach comes first (59 Aur)."""
        nodes = NodeList(MSC)
        nodes.add("1", -1, "A", [(*WDS_ID, "x")])
        found = {MSC: [[(900, 2), (100, 2)]]}
        _add_links([nodes.table()], found, {(*WDS_ID, "x"): (500, 3)})
        assert found[MSC] == [[(900, 2), (100, 2), (500, 3)]]


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


class TestEntryInAPoint:
    """An entry beside a point, whose interior from another source holds the
    same star, is that star. The sources name it by no shared id."""

    def test_a_pair_of_another_letter(self):
        """HD 144981: the WDS's EF at 0.9″ is the MSC's AB at 0.875″."""
        w = "16093-1927"
        resolver = FakeResolver(
            {("hip", "2007", "1"): 28138137, ("gaia", "dr3", "1"): 28138137},
            [fact(28138137, 242.337, -19.45731, 8.0251, parallax=6.70625)],
        )
        msc = msc_nodes(
            [msc_comp(w, "A", HIP=1), msc_comp(w, "B", Vmag=14.0)],
            [
                msc_pair(
                    w,
                    "A",
                    "B",
                    "*",
                    Type="v",
                    P=830.0,
                    Punit="y",
                    Sep=0.875,
                    Sunit='"',
                ),
                msc_pair(w, "Aa", "Ab", "A", Type="v", Sep=0.088, Sunit='"'),
            ],
            [],
        )
        catalogue = wds_catalogue(
            {w: [wds_pair("E", "F", 0.9, notes="V")]},
            {(w, "E"): wds_component(1, 242.337, -19.45719)},
        )
        systems = build(Inputs(msc=msc, wds=catalogue), resolver)
        assert systems.counts["entries that a point of the system holds"] == 1
        assert systems.points.filter(pc.equal(systems.points["key"], 28138137))[
            "stars"
        ].to_pylist() == [3]

    def test_a_pair_on_an_orbit_at_another_separation(self):
        """FG Aqr: the MSC has Bb at 0.89″, the WDS at 0.4″, under another id."""
        msc_id, wds_id = "22173-0848", "22173-0847"
        resolver = FakeResolver(
            {
                ("hip", "2007", "1"): 21535932,
                ("hip", "2007", "2"): 1095277756,
                ("gaia", "dr3", "1"): 21535932,
                ("gaia", "dr3", "2"): 1095277756,
            },
            [
                fact(21535932, 334.32697, -8.80470, 12.08639, parallax=90.489288),
                fact(1095277756, 334.32568, -8.80649, 12.90117, parallax=89.734001),
            ],
        )
        msc = msc_nodes(
            [msc_comp(msc_id, "A", HIP=1), msc_comp(msc_id, "B", HIP=2)],
            [
                msc_pair(msc_id, "A", "B", "*", Sep=7.905, Sunit='"'),
                msc_pair(
                    msc_id,
                    "Ba",
                    "Bb",
                    "B",
                    Type="V",
                    P=66.0,
                    Punit="y",
                    Sep=0.89,
                    Sunit='"',
                ),
            ],
            [],
        )
        catalogue = wds_catalogue(
            {
                wds_id: [
                    wds_pair("A", "B", 7.9, notes="T"),
                    wds_pair("Ba", "Bb", 0.4, notes="OT"),
                ]
            },
            {
                (wds_id, "A"): wds_component(1, 334.32900, -8.80342),
                (wds_id, "Ba"): wds_component(2, 334.32796, -8.80519),
            },
        )
        systems = build(Inputs(msc=msc, wds=catalogue), resolver)
        roots = systems.nodes.filter(pc.equal(systems.nodes["parent"], 0))
        assert roots["stars"].to_pylist() == [3]
        assert systems.counts["entries that a point of the system holds"] == 1

    @pytest.mark.parametrize("swapped", [False, True])
    def test_a_lone_pair_of_el_badry(self, swapped):
        """WDS 03112+0710 has B inside A's point at 1.4″. El-Badry names it at
        1.54″ by a Gaia id with no object, so the pair read as a third star.
        Only El-Badry's second star holds the separation."""
        w, first, second = "03112+0710", 7505953565990656, 7505957861693696
        catalogue = wds_catalogue(
            {w: [wds_pair("A", "B", 1.4, notes="", mag1=8.3, mag2=13.2)]},
            {
                (w, "A"): wds_component(first, 47.792684, 7.173952),
                (w, "B"): wds_component(second, 47.792279, 7.173801),
            },
        )
        pair = el_badry_pairs(
            pa.table(
                {
                    "source_id1": [second if swapped else first],
                    "source_id2": [first if swapped else second],
                    "ra1": [47.79268427],
                    "dec1": [7.17395164],
                    "ra2": [47.79227923],
                    "dec2": [7.1738012],
                    "parallax1": [6.956691],
                    "parallax2": [7.269293],
                    "phot_g_mean_mag1": [7.75809],
                    "phot_g_mean_mag2": [12.055403],
                    "sep_arcsec": [1.54477],
                    "R_chance_align": [5.555e-07],
                    "binary_type": ["MS??"],
                }
            )
        )
        resolver = FakeResolver(
            {("gaia", "dr3", str(first)): 16790869},
            [fact(16790869, 47.792684, 7.173952, 7.75809, parallax=6.956691)],
        )
        systems = build(Inputs(wds=catalogue, el_badry=pair), resolver)
        assert systems.nodes["stars"].to_pylist() == [2]
        assert systems.nodes["point"].to_pylist() == [True]
        assert systems.counts["entries that a point of the system holds"] == 1

    @staticmethod
    def in_primary(entry: dict, *stars: dict, source: str = MSC) -> bool:
        rows = {0: entry, **dict(enumerate(stars, 1))}
        inside = [(at, None) for at in range(1, len(rows))]
        assembler = MagicMock(chosen={7: Interior(7, source, 0, "1", inside)})
        assembler._row.side_effect = rows.__getitem__
        return Assembler._in_primary(assembler, 0, 7)

    @staticmethod
    def row(separation: float | None, source: str = WDS, **values) -> dict:
        base = {"source": source, "period": None, "known": None}
        return base | {"separation": separation} | values

    def test_the_separation_decides(self):
        star = self.row(0.875, MSC)
        assert self.in_primary(self.row(0.9), self.row(None, MSC), star)
        assert not self.in_primary(self.row(5.0), star)

    def test_the_interior_of_its_own_source_is_another_star(self):
        assert not self.in_primary(self.row(0.9), self.row(0.875), source=WDS)

    def test_an_entry_with_a_period_stays_for_its_orbit(self):
        """95 Cet: the MSC's B has an orbit, SIMBAD's B inside the point none."""
        entry = self.row(1.174, MSC, period=142082.25)
        assert not self.in_primary(entry, self.row(1.215, "simbad"), source="simbad")

    def test_an_orbit_of_the_entry_alone_stays(self):
        """HD 129260: ORB6 names the WDS row, and SIMBAD's B inside has no orbit."""
        entry = self.row(0.7, known=["visual", "visual orbit"])
        star = self.row(0.771, "simbad", known=["catalogue"])
        assert not self.in_primary(entry, star, source="simbad")

    def test_a_catalogue_gap_is_no_separation(self):
        assert not self.in_primary(self.row(-1.0), self.row(0.875, MSC))
        assert not self.in_primary(self.row(0.9), self.row(-1.0, MSC))


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
