"""Tests for the star-system builder on small synthetic systems."""

import os
import subprocess
import sys
from collections import Counter
from dataclasses import fields
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc

from space_map_data.extrasolar.systems.assemble import Systems
from space_map_data.extrasolar.systems.build import build
from space_map_data.extrasolar.systems.msc import msc_nodes
from space_map_data.extrasolar.systems.nodes import (
    EL_BADRY,
    GAIA_ORBITS,
    MSC,
    PLANETS,
    SIMBAD,
    SIMBAD_TYPE,
    WDS,
)
from space_map_data.extrasolar.systems.pairs import el_badry_pairs, orbit_pairs
from space_map_data.extrasolar.systems.planets import PLANETS_INPUT
from space_map_data.extrasolar.systems.prepare import Inputs
from space_map_data.extrasolar.systems.report import report_lines, tree_lines
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


def shape(systems: Systems, key: int):
    """The tree that holds `key`: (class, stars, members), with a point as
    its key, an entry as "entry", and a point that holds several stars as
    ("point", key, stars)."""
    points = systems.points.filter(pc.equal(systems.points["key"], key))
    assert points.num_rows == 1, f"{key} is in no system"
    root = points["root"][0].as_py()
    nodes = {row["node"]: row for row in systems.nodes.to_pylist()}
    members: dict[int, list[dict]] = {}
    for row in systems.members.to_pylist():
        members.setdefault(row["node"], []).append(row)

    def describe(node: int):
        row = nodes[node]
        if row["point"]:
            return ("point", row["key"], row["stars"])
        inner = []
        for member in members.get(node, []):
            if member["kind"] == "entry":
                inner.append("entry")
            elif member["member"]:
                inner.append(describe(member["member"]))
            else:
                inner.append(member["key"])
        return (row["class"], row["stars"], sorted(inner, key=_order))

    return describe(root)


def _order(member) -> tuple[int, str]:
    """Points first, then systems, then entries."""
    kind = 0 if isinstance(member, int) else 1 if isinstance(member, tuple) else 2
    return kind, str(member)


def node_of(systems: Systems, key: int, inner_keys: set[int]) -> dict:
    """The resolved node whose points are `inner_keys`."""
    for row in systems.nodes.to_pylist():
        if row["point"]:
            continue
        mine = systems.points.filter(pc.equal(systems.points["parent"], row["node"]))
        keys = set(mine["key"].to_pylist())
        if keys == inner_keys:
            return row
    raise AssertionError(f"no node of {inner_keys}")


def el_badry(rows: list[tuple[int, int, float, float, float]]) -> pa.Table:
    """Pairs of (source_id1, source_id2, separation, g1, g2)."""
    return el_badry_pairs(
        pa.table(
            {
                "source_id1": [r[0] for r in rows],
                "source_id2": [r[1] for r in rows],
                "ra1": [0.0] * len(rows),
                "dec1": [0.0] * len(rows),
                "ra2": [0.0] * len(rows),
                "dec2": [0.0] * len(rows),
                "parallax1": [20.0] * len(rows),
                "parallax2": [20.0] * len(rows),
                "phot_g_mean_mag1": [r[3] for r in rows],
                "phot_g_mean_mag2": [r[4] for r in rows],
                "sep_arcsec": [r[2] for r in rows],
                "R_chance_align": [1e-6] * len(rows),
                "binary_type": ["MSMS"] * len(rows),
            }
        )
    )


def planets(rows: list[dict]) -> pa.Table:
    base = dict.fromkeys(PLANETS_INPUT.names)
    return pa.Table.from_pylist([base | row for row in rows], schema=PLANETS_INPUT)


class TestAlphaCentauri:
    """MSC gives AB,C with A,B under AB; SIMBAD gives the pair AB."""

    def systems(self) -> Systems:
        comp = [
            msc_comp("14396-6050", "A", HIP=71683, HD=128620),
            msc_comp("14396-6050", "B", HIP=71681, HD=128621),
            msc_comp("14396-6050", "C", HIP=70890),
        ]
        pairs = [
            msc_pair("14396-6050", "AB", "C", "*", Sep=131.0, Sunit="'"),
            msc_pair(
                "14396-6050", "A", "B", "AB", Sep=17.5, Sunit='"', P=79.92, Punit="y"
            ),
        ]
        index = simbad_index(
            [
                simbad_object(1, "* alf Cen", 219.9, -60.83, otype="SB*"),
                simbad_object(2, "* alf Cen A", 219.902, -60.834, v=0.01, hip="71683"),
                simbad_object(3, "* alf Cen B", 219.896, -60.8375, v=1.33, hip="71681"),
            ],
            [(1, 2), (1, 3)],
        )
        resolver = FakeResolver(
            {
                ("hip", "2007", "71683"): 10,
                ("hip", "2007", "71681"): 11,
                ("hip", "2007", "70890"): 12,
                ("simbad", "oid", "2"): 10,
                ("simbad", "oid", "3"): 11,
            },
            [
                fact(10, 219.902, -60.834, -0.1, "hipparcos-2007", parallax=742.0),
                fact(11, 219.896, -60.8375, 1.2, "hipparcos-2007", parallax=742.0),
                fact(12, 217.43, -62.68, 8.98, parallax=768.0),
            ],
        )
        inputs = Inputs(
            msc=msc_nodes(comp, pairs, []),
            simbad=read_simbad(index.stars),
            simbad_index=index,
        )
        return build(inputs, resolver)

    def test_shape(self):
        systems = self.systems()
        assert shape(systems, 12) == (
            "multiple star",
            3,
            [12, ("binary star", 2, [10, 11])],
        )

    def test_pair_values_and_sources(self):
        systems = self.systems()
        pair = node_of(systems, 10, {10, 11})
        assert pair["sources"] == [MSC, SIMBAD]
        ids = {(i["catalogue"], i["catalogue_id"]) for i in pair["catalogue_ids"]}
        assert ("msc", "14396-6050 AB") in ids and ("simbad", "1") in ids
        assert pair["primary"] == 10
        members = systems.members.filter(
            pc.equal(systems.members["node"], pair["node"])
        )
        rows = {row["key"]: row for row in members.to_pylist()}
        assert rows[10]["letter"] == "A" and rows[11]["letter"] == "B"
        assert rows[11]["separation"] == 17.5
        assert rows[11]["period"] == 79.92 * 365.25
        names = systems.names.filter(pc.equal(systems.names["node"], pair["node"]))
        assert names["name"].to_pylist()[0] == "Alpha Centauri"

    def test_report(self):
        systems = self.systems()
        lines = report_lines(systems, [("α Cen", 10)])
        assert "Systems" in lines
        assert any("multiple star, 3 stars, resolved" in line for line in lines)
        assert not any(line.startswith("class changes") for line in lines)
        assert tree_lines(systems, 99) == ["99: in no system"]

    def test_report_takes_the_class_changes(self):
        systems = self.systems()
        classes = Counter({"star → binary star": 2})
        lines = report_lines(systems, classes=classes)
        at = lines.index("class changes:")
        assert lines[at + 1] == "  star → binary star: 2"


class TestCastor:
    """WDS gives A and B one Gaia id; HIP 36850 is the light of both."""

    def systems(self) -> Systems:
        w = "07346+3153"
        comp = [
            msc_comp(w, "A", HIP=36850, HD=60179, Id="HR_2891"),
            msc_comp(w, "B", HD=60178, Id="HR_2890"),
            msc_comp(w, "C", Id="V*_YY_Gem, BD+32_1582"),
        ]
        pairs = [
            msc_pair(w, "AB", "C", "*", Sep=70.5, Sunit='"'),
            msc_pair(w, "A", "B", "AB", Sep=6.722, Sunit='"'),
            msc_pair(w, "Aa", "Ab", "A", Sep=8.0, Sunit="m", P=9.213, Punit="d"),
            msc_pair(w, "Ba", "Bb", "B", Sep=3.445, Sunit="m", P=2.928, Punit="d"),
            msc_pair(w, "Cab", "Cc", "C", Sep=1.022, Sunit='"'),
            msc_pair(w, "Ca", "Cb", "Cab", Sep=1.203, Sunit="m", P=0.814, Punit="d"),
        ]
        index = simbad_index(
            [
                simbad_object(
                    20, "* alf Gem", 113.6500, 31.8886, otype="**", hip="36850"
                ),
                simbad_object(
                    21,
                    "* alf Gem A",
                    113.6500,
                    31.8886,
                    v=1.9,
                    hd="60179",
                    identifiers=("HR 2891",),
                ),
                simbad_object(
                    22,
                    "* alf Gem B",
                    113.6504,
                    31.8885,
                    v=3.0,
                    gaia="892",
                    hd="60178",
                    identifiers=("HR 2890",),
                ),
                simbad_object(
                    23,
                    "V* YY Gem",
                    113.656,
                    31.8695,
                    otype="EB*",
                    v=9.3,
                    gaia="893",
                    identifiers=("V* YY Gem",),
                ),
            ],
            [(20, 21), (20, 22)],
        )
        X, Y, Z = 100, 101, 102
        resolver = FakeResolver(
            {
                ("hip", "2007", "36850"): X,
                ("hd", "1949", "60179"): X,
                ("hd", "1949", "60178"): X,
                ("gaia", "dr3", "892"): X,
                ("simbad", "oid", "22"): X,
                ("simbad", "oid", "21"): Y,
                ("gaia", "dr3", "893"): Z,
                ("simbad", "oid", "23"): Z,
            },
            [
                fact(X, 113.6504, 31.8885, 2.92, parallax=66.0),
                fact(Y, 113.6500, 31.8886, 1.9, "simbad"),
                fact(Z, 113.656, 31.8695, 8.3, parallax=66.3),
            ],
        )
        components = {
            (w, "A"): wds_component(892, 113.6494, 31.8883),
            (w, "Aa"): wds_component(892, 113.6494, 31.8883),
            (w, "B"): wds_component(892, 113.6504, 31.8885),
            (w, "Ba"): wds_component(892, 113.6504, 31.8885),
            (w, "C"): wds_component(893, 113.656, 31.8695),
        }
        catalogue = wds_catalogue(
            {
                w: [
                    wds_pair("Aa", "Ab", 0.0),
                    wds_pair("A", "B", 5.4, notes="NO V", mag1=1.93, mag2=2.97),
                    wds_pair("A", "C", 69.6, notes="NO V", mag1=1.93, mag2=9.83),
                    wds_pair("B", "C", 73.8, notes="NV", mag1=2.97, mag2=9.83),
                    wds_pair("Ba", "Bb", 0.0),
                ]
            },
            components,
        )
        inputs = Inputs(
            msc=msc_nodes(comp, pairs, []),
            simbad=read_simbad(index.stars),
            simbad_index=index,
            wds=catalogue,
        )
        return build(inputs, resolver)

    def test_shape(self):
        systems = self.systems()
        assert shape(systems, 100) == (
            "multiple star",
            7,
            [
                ("multiple star", 4, [("point", 100, 2), ("point", 101, 2)]),
                ("point", 102, 3),
            ],
        )

    def test_the_shared_gaia_id_is_a_cross_match_error(self):
        systems = self.systems()
        events = systems.events.filter(
            pc.equal(systems.events["kind"], "cross-match error")
        )
        assert events.num_rows >= 1
        assert "stays with B" in events["text"][0].as_py()

    def test_sources_agree_on_ab(self):
        systems = self.systems()
        pair = node_of(systems, 100, {100, 101})
        assert pair["sources"] == [MSC, SIMBAD, WDS]

    def test_interiors_come_from_the_msc(self):
        systems = self.systems()
        nodes = systems.nodes.filter(systems.nodes["point"])
        assert dict(zip(nodes["key"].to_pylist(), nodes["evidence"].to_pylist())) == {
            100: MSC,
            101: MSC,
            102: MSC,
        }
        point = nodes.filter(pc.equal(nodes["key"], 102))["node"][0].as_py()
        entries = systems.members.filter(pc.equal(systems.members["node"], point))
        assert sorted(entries["letter"].to_pylist()) == ["Ca", "Cb", "Cc"]
        inner = dict(zip(entries["letter"].to_pylist(), entries["inner"].to_pylist()))
        assert inner == {"Ca": "Cab", "Cb": "Cab", "Cc": None}

    def test_castor_a_takes_the_system_distance(self):
        systems = self.systems()
        rows = systems.distances.to_pylist()
        assert [(r["key"], r["donor"]) for r in rows] == [(101, 100)]
        assert rows[0]["distance"] == 1000 / 66.0


class TestProcyon:
    """Procyon's composite type includes Procyon B, its own point."""

    def test_composite_moves_to_the_system(self):
        w = "07393+0514"
        resolver = FakeResolver(
            {("gaia", "dr3", "5"): 111},
            [
                fact(
                    110,
                    114.825,
                    5.225,
                    0.4,
                    "hipparcos-2007",
                    parallax=284.6,
                    spectral_type="F5IV-V+DQZ",
                ),
                fact(111, 114.8262, 5.2242, 10.7, "simbad", spectral_type="DQZ"),
            ],
            positions={f"{w} A": 110},
        )
        catalogue = wds_catalogue(
            {w: [wds_pair("A", "B", 4.3, notes="NO", mag1=0.37, mag2=10.7)]},
            {
                (w, "A"): wds_component(None, 114.825, 5.225),
                (w, "B"): wds_component(5, 114.8262, 5.2242),
            },
        )
        systems = build(Inputs(wds=catalogue), resolver)
        root = systems.nodes.filter(pc.equal(systems.nodes["parent"], 0)).to_pylist()
        assert root[0]["spectral_type"] == "F5IV-V+DQZ"
        points = {row["key"]: row for row in systems.points.to_pylist()}
        assert points[110]["spectral_type_moved"] is True
        assert points[110]["spectral_type"] is None
        assert points[111]["spectral_type"] == "DQZ"
        # Procyon B has no distance: it takes Procyon A's.
        assert systems.distances["key"].to_pylist() == [111]

    def test_an_unmatched_entry_that_is_a_point(self):
        """WDS B finds no object; the MSC has it as a point."""
        w = "07393+0514"
        resolver = FakeResolver(
            {("hip", "2007", "1"): 120, ("hd", "1949", "2"): 121},
            [
                fact(120, 114.825, 5.225, 0.4, "hipparcos-2007", parallax=284.6),
                fact(121, 114.8262, 5.2242, 10.7, "simbad"),
            ],
            positions={f"{w} A": 120},
        )
        catalogue = wds_catalogue(
            {w: [wds_pair("A", "B", 4.3, notes="NO", mag1=0.37, mag2=10.7)]},
            {(w, "A"): wds_component(None, 114.825, 5.225)},
        )
        comp = [msc_comp(w, "A", HIP=1), msc_comp(w, "C", HD=2)]
        systems = build(
            Inputs(
                msc=msc_nodes(comp, [msc_pair(w, "A", "C", "*")], []),
                wds=catalogue,
            ),
            resolver,
        )
        assert shape(systems, 120) == ("binary star", 2, [120, 121])
        assert systems.counts["entries that are a point of the system"] == 1


class TestEpsilonLyrae:
    """El-Badry has AB and CD; the MSC adds AB+CD."""

    def resolver(self) -> FakeResolver:
        return FakeResolver(
            {
                ("hip", "2007", "91919"): 30,
                ("hd", "1949", "173583"): 31,
                ("hip", "2007", "91926"): 32,
                ("hd", "1949", "173608"): 33,
                ("gaia", "dr3", "1"): 30,
                ("gaia", "dr3", "2"): 31,
                ("gaia", "dr3", "3"): 32,
                ("gaia", "dr3", "4"): 33,
            },
            [
                fact(30, 281.0848, 39.6701, 5.0, parallax=20.7),
                fact(31, 281.0846, 39.6708, 6.0, parallax=20.5),
                fact(32, 281.0949, 39.6127, 5.2, parallax=20.3),
                fact(33, 281.0957, 39.6128, 5.4, parallax=20.5),
            ],
        )

    def test_el_badry_alone(self):
        systems = build(
            Inputs(el_badry=el_badry([(1, 2, 2.28, 5.0, 6.0), (3, 4, 2.38, 5.2, 5.4)])),
            self.resolver(),
        )
        assert shape(systems, 30) == ("binary star", 2, [30, 31])
        assert shape(systems, 32) == ("binary star", 2, [32, 33])

    def test_msc_adds_the_level(self):
        w = "18443+3940"
        comp = [
            msc_comp(w, "A", HIP=91919),
            msc_comp(w, "B", HD=173583),
            msc_comp(w, "C", HIP=91926),
            msc_comp(w, "D", HD=173608),
        ]
        pairs = [
            msc_pair(w, "AB", "CD", "*", Sep=207.9, Sunit='"'),
            msc_pair(w, "A", "B", "AB"),
            msc_pair(w, "C", "D", "CD"),
            msc_pair(w, "Ca", "Cb", "X"),
        ]
        systems = build(
            Inputs(
                msc=msc_nodes(comp, pairs, []),
                el_badry=el_badry([(1, 2, 2.28, 5.0, 6.0), (3, 4, 2.38, 5.2, 5.4)]),
            ),
            self.resolver(),
        )
        assert shape(systems, 30) == (
            "multiple star",
            4,
            [("binary star", 2, [30, 31]), ("binary star", 2, [32, 33])],
        )
        assert node_of(systems, 30, {30, 31})["sources"] == [MSC, EL_BADRY]
        root = systems.nodes.filter(pc.equal(systems.nodes["parent"], 0))
        assert root["sources"].to_pylist() == [[MSC]]


class TestElBadry:
    """Pairs alone, a pair with an unstored star, and a pair that MSC lists."""

    def test_unstored_companion_is_an_entry(self):
        resolver = FakeResolver(
            {("gaia", "dr3", "1"): 40}, [fact(40, 10.0, 10.0, 9.0, parallax=10.0)]
        )
        systems = build(Inputs(el_badry=el_badry([(1, 2, 15.0, 9.0, 14.0)])), resolver)
        assert shape(systems, 40) == ("binary star", 2, [40, "entry"])
        entry = systems.members.filter(pc.equal(systems.members["kind"], "entry"))
        assert entry["g_mag"].to_pylist() == [14.0]
        assert entry["separation"].to_pylist() == [15.0]

    def test_duplicate_of_an_msc_pair_is_one_node(self):
        comp = [msc_comp("1", "A", HIP=1), msc_comp("1", "B", HIP=2)]
        resolver = FakeResolver(
            {
                ("hip", "2007", "1"): 50,
                ("hip", "2007", "2"): 51,
                ("gaia", "dr3", "11"): 50,
                ("gaia", "dr3", "12"): 51,
            },
            [
                fact(50, 10.0, 10.0, 7.0, parallax=10.0),
                fact(51, 10.001, 10.0, 8.0, parallax=10.0),
            ],
        )
        systems = build(
            Inputs(
                msc=msc_nodes(comp, [msc_pair("1", "A", "B", "*")], []),
                el_badry=el_badry([(11, 12, 3.6, 7.0, 8.0)]),
            ),
            resolver,
        )
        assert systems.nodes.num_rows == 1
        row = systems.nodes.to_pylist()[0]
        assert row["sources"] == [MSC, EL_BADRY]
        kinds = {i["catalogue"] for i in row["catalogue_ids"]}
        assert kinds == {"msc", "el-badry"}

    def test_a_crossing_pair_is_a_conflict(self):
        """MSC says AB; El-Badry pairs B with a third star C."""
        comp = [msc_comp("1", "A", HIP=1), msc_comp("1", "B", HIP=2)]
        resolver = FakeResolver(
            {
                ("hip", "2007", "1"): 60,
                ("hip", "2007", "2"): 61,
                ("gaia", "dr3", "12"): 61,
                ("gaia", "dr3", "13"): 62,
            },
            [
                fact(60, 10.0, 10.0, 7.0, parallax=10.0),
                fact(61, 10.001, 10.0, 8.0, parallax=10.0),
                fact(62, 10.01, 10.0, 9.0, parallax=10.0),
            ],
        )
        systems = build(
            Inputs(
                msc=msc_nodes(comp, [msc_pair("1", "A", "B", "*")], []),
                el_badry=el_badry([(12, 13, 30.0, 8.0, 9.0)]),
            ),
            resolver,
        )
        assert shape(systems, 60) == ("binary star", 2, [60, 61])
        conflicts = systems.events.filter(pc.equal(systems.events["kind"], "conflict"))
        assert conflicts.num_rows == 1
        assert "crosses msc 1" in conflicts["text"][0].as_py()
        assert 62 not in systems.points["key"].to_pylist()


class TestGaiaOrbits:
    """An orbit holds two stars unless its companion is a planet."""

    def resolver(self) -> FakeResolver:
        return FakeResolver(
            {}, [fact(k, 10.0 + k, 0.0, 9.0, parallax=10.0) for k in (70, 71, 72)]
        )

    def orbits(self) -> pa.Table:
        return orbit_pairs(
            pa.table(
                {
                    "key": [70, 71, 72],
                    "nss_solution_type": ["Orbital", "SB1", "SB1"],
                    "period": [500.0, 10.0, 20.0],
                    "eccentricity": [0.1, 0.0, 0.2],
                    "m1": [1.0, 1.0, 1.0],
                    "m2": [0.005, 0.5, 0.4],
                }
            )
        )

    def test_planets_are_no_members(self):
        systems = build(
            Inputs(
                orbits=self.orbits(),
                planets=planets([{"host": 72, "number": 1, "period": 20.5}]),
            ),
            self.resolver(),
        )
        points = systems.nodes.filter(systems.nodes["point"])
        assert points["key"].to_pylist() == [71]
        assert points["evidence"].to_pylist() == [GAIA_ORBITS]
        assert points["class"].to_pylist() == ["binary star"]
        counts = systems.counts
        assert counts[f"{GAIA_ORBITS}: companions under 13 MJ"] == 1
        assert counts[f"{GAIA_ORBITS}: companions that are listed planets"] == 1
        entries = systems.members.filter(pc.equal(systems.members["kind"], "entry"))
        assert entries["period"].to_pylist() == [None, 10.0]
        assert entries["known"].to_pylist() == [None, ["spectroscopic orbit"]]


class TestSiriusTrap:
    """Sirius is SB* because of Sirius B, which is its own point."""

    def inputs(self, with_pair: bool) -> tuple[Inputs, FakeResolver]:
        w = "06451-1643"
        index = simbad_index(
            [simbad_object(40, "* alf CMa", 101.287, -16.716, otype="SB*", v=-1.46)]
        )
        resolver = FakeResolver(
            {("simbad", "oid", "40"): 80, ("gaia", "dr3", "2947"): 81},
            [
                fact(
                    80,
                    101.2872,
                    -16.7161,
                    -1.4,
                    "hipparcos-2007",
                    parallax=379.0,
                ),
                fact(81, 101.2899, -16.7145, 8.5, parallax=374.5),
            ],
            positions={f"{w} A": 80},
        )
        catalogue = None
        if with_pair:
            catalogue = wds_catalogue(
                {w: [wds_pair("A", "B", 11.1, mag1=-1.47, mag2=8.44)]},
                {
                    (w, "A"): wds_component(None, 101.287, -16.716),
                    (w, "B"): wds_component(2947, 101.290, -16.7145),
                },
            )
        return Inputs(simbad_index=index, wds=catalogue), resolver

    def test_sirius_stays_a_star(self):
        inputs, resolver = self.inputs(with_pair=True)
        systems = build(inputs, resolver)
        assert resolver.matched == ["06451-1643 A"]
        assert shape(systems, 80) == ("binary star", 2, [80, 81])
        stars = dict(
            zip(systems.points["key"].to_pylist(), systems.points["stars"].to_pylist())
        )
        assert stars == {80: 1, 81: 1}
        assert systems.counts[f"{SIMBAD_TYPE}: SB* explained by a companion"] == 1

    def test_alone_it_would_hold_two(self):
        inputs, resolver = self.inputs(with_pair=False)
        systems = build(inputs, resolver)
        point = systems.nodes.filter(systems.nodes["point"]).to_pylist()
        assert [(p["key"], p["stars"], p["evidence"]) for p in point] == [
            (80, 2, SIMBAD_TYPE)
        ]


class TestPlanets:
    """A brown dwarf that is a planet leaves the tree; a circumbinary host."""

    def test_brown_dwarf_planet_wins(self):
        comp = [
            msc_comp("1", "A", HIP=1),
            msc_comp("1", "B", HIP=2),
            msc_comp("1", "C", HIP=3),
        ]
        pairs = [msc_pair("1", "AB", "C", "*"), msc_pair("1", "A", "B", "AB")]
        resolver = FakeResolver(
            {
                ("hip", "2007", "1"): 90,
                ("hip", "2007", "2"): 91,
                ("hip", "2007", "3"): 92,
                ("simbad", "oid", "7"): 92,
            },
            [fact(k, 10.0, 0.0, 9.0, parallax=10.0) for k in (90, 91, 92)],
        )
        systems = build(
            Inputs(
                msc=msc_nodes(comp, pairs, []),
                planets=planets(
                    [
                        {
                            "host": 90,
                            "number": 1,
                            "designation": "X b",
                            "class": "brown dwarf",
                            "star_ids": [
                                {
                                    "catalogue": "simbad",
                                    "release": "oid",
                                    "catalogue_id": "7",
                                }
                            ],
                        }
                    ]
                ),
            ),
            resolver,
        )
        assert shape(systems, 90) == ("binary star", 2, [90, 91])
        assert systems.overlaps["key"].to_pylist() == [92]
        assert systems.overlaps["designation"].to_pylist() == ["X b"]

    def test_circumbinary_host_is_the_pair(self):
        comp = [msc_comp("1", "A", HIP=1), msc_comp("1", "B", HIP=2)]
        resolver = FakeResolver(
            {("hip", "2007", "1"): 95, ("hip", "2007", "2"): 96},
            [fact(k, 10.0, 0.0, 9.0, parallax=10.0) for k in (95, 96)],
        )
        systems = build(
            Inputs(
                msc=msc_nodes(comp, [msc_pair("1", "A", "B", "*")], []),
                planets=planets(
                    [
                        {
                            "host": 95,
                            "number": 1,
                            "designation": "AB b",
                            "binary_type": "P-type",
                        }
                    ]
                ),
            ),
            resolver,
        )
        host = systems.hosts.to_pylist()
        root = systems.nodes.filter(pc.equal(systems.nodes["parent"], 0))
        assert host == [
            {
                "host": 95,
                "number": 1,
                "designation": "AB b",
                "node": root["node"][0].as_py(),
                "key": 0,
            }
        ]

    def test_circumbinary_host_alone_holds_the_pair(self):
        resolver = FakeResolver({}, [fact(97, 10.0, 0.0, 9.0, parallax=10.0)])
        systems = build(
            Inputs(
                planets=planets(
                    [
                        {
                            "host": 97,
                            "number": 1,
                            "designation": "X AB b",
                            "binary_type": "P-type",
                        }
                    ]
                )
            ),
            resolver,
        )
        point = systems.nodes.to_pylist()
        assert [(p["key"], p["stars"], p["evidence"]) for p in point] == [
            (97, 2, PLANETS)
        ]
        assert systems.hosts["key"].to_pylist() == [97]


def joined_groups() -> Systems:
    """A WDS system whose group label AB joins the pairs A,D and B,E."""
    w = "01000+0100"
    letters = "ABCDE"
    catalogue = wds_catalogue(
        {
            w: [
                wds_pair("A", "D", 1.0, notes="V"),
                wds_pair("B", "E", 2.0, notes="V"),
                wds_pair("AB", "C", 50.0, notes="V"),
            ]
        },
        {
            (w, x): wds_component(900 + at, 15.0 + at / 3600, 1.0)
            for at, x in enumerate(letters)
        },
    )
    resolver = FakeResolver(
        {("gaia", "dr3", str(900 + at)): 90 + at for at in range(len(letters))},
        [
            fact(90 + at, 15.0 + at / 3600, 1.0, 9.0 + at, parallax=10.0)
            for at in range(len(letters))
        ],
    )
    return build(Inputs(wds=catalogue), resolver)


def joined_groups_text() -> str:
    systems = joined_groups()
    return repr(
        [
            sorted(value.items()) if isinstance(value, Counter) else value.to_pylist()
            for value in (getattr(systems, f.name) for f in fields(Systems))
        ]
    )


class TestHashSeed:
    """The tables do not depend on the hash seed of strings."""

    def test_two_seeds_give_the_same_tables(self):
        code = (
            "from tests.extrasolar.test_systems_build import joined_groups_text;"
            " print(joined_groups_text())"
        )
        texts = [
            subprocess.run(
                [sys.executable, "-c", code],
                cwd=Path(__file__).parents[2],
                env=os.environ | {"PYTHONHASHSEED": seed},
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            for seed in ("1", "3")
        ]
        assert texts[0] and texts[0] == texts[1]

    def test_the_first_letter_is_the_primary(self):
        systems = joined_groups()
        nodes = systems.nodes.filter(pc.equal(systems.nodes["label"], "ABDE"))
        assert nodes["primary"].to_pylist() == [90]
        members = systems.members.filter(
            pc.equal(systems.members["node"], nodes["node"][0])
        )
        assert members["letter"].to_pylist() == ["AD", "BE"]
