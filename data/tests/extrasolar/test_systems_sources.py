"""Tests for the tree sources of the star systems: WDS and MSC."""

import pytest

from space_map_data.extrasolar.systems import wds as wds_source
from space_map_data.extrasolar.systems.msc import msc_nodes
from space_map_data.extrasolar.systems.nodes import (
    DUBIOUS,
    MSC_ID,
    PROPER_MOTION,
    UNVERIFIED,
    VISUAL_ORBIT,
)
from tests.extrasolar.systems_fakes import (
    msc_comp,
    msc_pair,
    wds_catalogue,
    wds_component,
    wds_pair,
)


def _tree(table) -> dict[str, list[str]]:
    """The labels of the children of each label."""
    labels = table["label"].to_pylist()
    found: dict[str, list[str]] = {}
    for label, parent in zip(labels, table["parent"].to_pylist()):
        key = labels[parent] if parent >= 0 else "-"
        found.setdefault(key, []).append(label)
    return found


class TestWdsLetters:
    """The pair names of the WDS and the tree that they imply."""

    @pytest.mark.parametrize(
        ("text", "pair"),
        [
            (None, ("A", "B")),
            ("AB", ("A", "B")),
            ("AC", ("A", "C")),
            ("Aa,Ab", ("Aa", "Ab")),
            ("AB,C", ("AB", "C")),
            ("AB,CD", ("AB", "CD")),
            ("Aa1,2", ("Aa1", "Aa2")),
            ("Ba,b", ("Ba", "Bb")),
            ("ABC", None),
        ],
    )
    def test_split(self, text, pair):
        assert wds_source.split_components(text) == pair

    def test_top_letters(self):
        assert wds_source.top_letters("AB") == {"A", "B"}
        assert wds_source.top_letters("Aa") == {"A"}
        assert wds_source.top_letters("C") == {"C"}

    def test_evidence_codes(self):
        assert wds_source.evidence("NO", (None, None), (None, None))[0] is None
        assert VISUAL_ORBIT in wds_source.evidence("NO", (None, None), (None, None))[1]
        assert wds_source.evidence("NU", (None, None), (None, None))[0] == "optical"
        assert wds_source.evidence("NUV", (None, None), (None, None))[0] == DUBIOUS
        assert wds_source.evidence(" X", (None, None), (None, None))[0] == DUBIOUS
        assert wds_source.evidence("N", (None, None), (None, None))[0] == UNVERIFIED

    def test_common_motion_is_physical(self):
        found, known = wds_source.evidence("N", (11, 61), (6, 52))
        assert found is None and PROPER_MOTION in known
        assert wds_source.evidence("N", (11, 61), (-7, -4))[0] == UNVERIFIED
        # A slow primary says nothing.
        assert wds_source.evidence("N", (3, 2), (3, 2))[0] == UNVERIFIED

    def test_wide_pair_nests(self):
        """AB at 5″ and AC at 70″: C orbits the pair AB."""
        catalogue = wds_catalogue(
            {"1": [wds_pair("A", "B", 5.0), wds_pair("A", "C", 70.0)]}
        )
        tree = _tree(catalogue.nodes())
        assert tree["-"] == ["ABC"]
        assert sorted(tree["ABC"]) == ["AB", "C"]
        assert tree["AB"] == ["A", "B"]

    def test_close_separations_are_flat(self):
        """AB at 5″ and AC at 8″: one group of three."""
        catalogue = wds_catalogue(
            {"1": [wds_pair("A", "B", 5.0), wds_pair("A", "C", 8.0)]}
        )
        tree = _tree(catalogue.nodes())
        assert tree["-"] == ["ABC"]
        assert tree["ABC"] == ["A", "B", "C"]

    def test_subcomponents_and_groups(self):
        """Aa,Ab inside A; AB,CD at the root."""
        catalogue = wds_catalogue(
            {
                "1": [
                    wds_pair("Aa", "Ab", 0.1),
                    wds_pair("A", "B", 2.1),
                    wds_pair("C", "D", 2.4),
                    wds_pair("AB", "CD", 209.0),
                ]
            }
        )
        tree = _tree(catalogue.nodes())
        assert tree["-"] == ["ABCD"]
        assert tree["ABCD"] == ["AB", "CD"]
        assert tree["AB"] == ["A", "B"]
        assert tree["A"] == ["Aa", "Ab"]

    def test_group_label_that_holds_the_primary(self):
        """AB, then A,BC: C joins the pair AB, with no loop."""
        catalogue = wds_catalogue(
            {"1": [wds_pair("A", "B", 1.0), wds_pair("A", "BC", 9.0)]}
        )
        tree = _tree(catalogue.nodes())
        assert tree["-"] == ["ABC"]
        assert sorted(tree["ABC"]) == ["AB", "C"]

    def test_physical_pairs_make_the_levels(self):
        """An unverified AI at 150″ comes after the physical AB,CD at 209″."""
        catalogue = wds_catalogue(
            {
                "1": [
                    wds_pair("A", "B", 2.1),
                    wds_pair("C", "D", 2.4),
                    wds_pair("A", "I", 150.0, notes="N"),
                    wds_pair("AB", "CD", 209.0, notes="NZ"),
                ]
            }
        )
        tree = _tree(catalogue.nodes())
        assert tree["-"] == ["ABCDI"]
        assert tree["ABCDI"] == ["AB", "CD", "I"]

    def test_msc_refutes_a_pair(self):
        catalogue = wds_catalogue(
            {"1": [wds_pair("C", "D", 2.4), wds_pair("Ca", "Cb", 0.1)]}
        )
        tree = _tree(catalogue.nodes(frozenset({("1", "Ca", "Cb")})))
        assert "C" not in tree
        assert catalogue.counts["pairs that the MSC refutes, left out"] == 1

    def test_repeated_gaia_id_stays_on_each_letter(self):
        """Castor A and B read one DR3 id: the builder decides."""
        components = {
            ("1", "A"): wds_component(892),
            ("1", "B"): wds_component(892),
        }
        nodes = wds_catalogue({"1": [wds_pair("A", "B", 5.4)]}, components).nodes()
        ids = [
            [i["catalogue_id"] for i in row or [] if i["catalogue"] == "gaia"]
            for row in nodes["ids"].to_pylist()
        ]
        labels = nodes["label"].to_pylist()
        assert ids[labels.index("A")] == ["892"]
        assert ids[labels.index("B")] == ["892"]

    def test_unverified_pairs_carry_their_evidence(self):
        catalogue = wds_catalogue(
            {"1": [wds_pair("A", "B", 5.0), wds_pair("A", "C", 60.0, notes="N")]}
        )
        nodes = catalogue.nodes()
        evidence = dict(zip(nodes["label"].to_pylist(), nodes["evidence"].to_pylist()))
        assert evidence["C"] == UNVERIFIED
        assert evidence["B"] is None


class TestMsc:
    """The MSC tree: parents, refuted pairs and trapezia."""

    def test_hierarchy(self):
        comp = [
            msc_comp("1", "A", HIP=71683, HD=128620, Id="HR_5459, *alp1_Cen"),
            msc_comp("1", "B", HIP=71681),
            msc_comp("1", "C", HIP=70890, Id="V*_V645_Cen, Proxima"),
        ]
        pairs = [
            msc_pair("1", "AB", "C", "*", Sep=131.0, Sunit="'", P=772.7, Punit="k"),
            msc_pair(
                "1",
                "A",
                "B",
                "AB",
                Sep=17.5,
                Sunit='"',
                P=79.92,
                Punit="y",
                Type="S2,V",
            ),
        ]
        nodes = msc_nodes(comp, pairs, [])
        tree = _tree(nodes)
        assert tree["-"] == ["AB,C"]
        assert tree["AB,C"] == ["AB", "C"]
        assert tree["AB"] == ["A", "B"]
        rows = {row["label"]: row for row in nodes.to_pylist()}
        assert rows["C"]["separation"] == pytest.approx(131.0 * 60)
        assert rows["B"]["period"] == pytest.approx(79.92 * 365.25)
        assert rows["B"]["known"] == ["spectroscopic orbit", "visual orbit"]
        ids = {(i["catalogue"], i["catalogue_id"]) for i in rows["A"]["ids"]}
        assert ("hr", "5459") in ids and ("hip", "71683") in ids
        assert (MSC_ID[0], "1 A") in ids
        gcvs = {i["catalogue_id"] for i in rows["C"]["ids"] if i["catalogue"] == "gcvs"}
        assert gcvs == {"V* V645 Cen"}

    def test_refuted_and_optical_pairs_are_left_out(self):
        pairs = [
            msc_pair("1", "AB", "CD", "*"),
            msc_pair("1", "A", "B", "AB"),
            msc_pair("1", "C", "D", "CD"),
            msc_pair("1", "Ca", "Cb", "X"),
            msc_pair("1", "Da", "Db", "D", Type="Xmp"),
        ]
        tree = _tree(msc_nodes([], pairs, []))
        assert "C" not in tree and "D" not in tree
        assert tree["CD"] == ["C", "D"]

    def test_trapezium_is_flat(self):
        pairs = [
            msc_pair("1", "A", "C", "t", Sep=6.8, Sunit='"'),
            msc_pair("1", "A", "B", "t", Sep=3.5, Sunit='"'),
        ]
        nodes = msc_nodes([], pairs, [])
        tree = _tree(nodes)
        assert tree["-"] == ["t"]
        assert tree["t"] == ["A", "C", "B"]
        assert nodes["flat"].to_pylist()[0] is True

    def test_zero_is_unknown(self):
        comp = [msc_comp("1", "A", HIP=0, HD=0, Vmag=0.0)]
        pairs = [msc_pair("1", "A", "B", "*", Sep=0.0, Sunit='"', P=0.0, Punit="y")]
        rows = {row["label"]: row for row in msc_nodes(comp, pairs, []).to_pylist()}
        assert rows["A"]["v_mag"] is None
        assert rows["B"]["separation"] is None and rows["B"]["period"] is None
        assert all(i["catalogue"] == "msc" for i in rows["A"]["ids"])

    def test_true_zeros_stay(self):
        comp = [
            msc_comp("1", "A", PMRA=0.0, PMDE=-15.5),
            msc_comp("1", "B", PMRA=0.0, PMDE=0.0),
        ]
        pairs = [msc_pair("1", "A", "B", "*", PA=0.0)]
        orbits = [{"WDS": "1", "System": "A,B", "e": 0.0, "a": 0.0}]
        rows = {row["label"]: row for row in msc_nodes(comp, pairs, orbits).to_pylist()}
        assert rows["B"]["eccentricity"] == 0.0
        assert rows["B"]["semi_major_axis"] is None
        assert (rows["A"]["pmra"], rows["A"]["pmdec"]) == (0.0, -15.5)
        assert (rows["B"]["pmra"], rows["B"]["pmdec"]) == (None, None)
        assert rows["B"]["position_angle"] is None
