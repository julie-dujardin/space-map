"""Tests for the star-system builder on small synthetic systems."""

import os
import subprocess
import sys
from collections import Counter
from dataclasses import fields, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pytest

from space_map_data.extrasolar.exoplanets.catalogues import EU
from space_map_data.extrasolar.exoplanets.simbad import Simbad
from space_map_data.extrasolar.ids import encode
from space_map_data.extrasolar.registry import Registry
from space_map_data.extrasolar.systems.assemble import Assembler, Systems, _Node
from space_map_data.extrasolar.systems.build import build
from space_map_data.extrasolar.systems.drawn import draw
from space_map_data.extrasolar.systems.msc import msc_nodes
from space_map_data.extrasolar.systems.nodes import (
    DUBIOUS,
    EL_BADRY,
    GAIA_ORBITS,
    MSC,
    NODES,
    PLANETS,
    SIMBAD,
    SIMBAD_TYPE,
    UNVERIFIED,
    VISUAL,
    VISUAL_ORBIT,
    WDS,
)
from space_map_data.extrasolar.systems.pairs import PAIRS, el_badry_pairs, orbit_pairs
from space_map_data.extrasolar.systems.planets import PLANETS_INPUT, planet_star_ids
from space_map_data.extrasolar.systems.prepare import (
    APART,
    ID_OFF,
    LEAVES,
    MEMBER,
    OTHER_STAR,
    Inputs,
    vetoed_pairs,
)
from space_map_data.extrasolar.systems.reduce import (
    ENTRY,
    GROUP,
    POINT,
    Group,
    Interior,
    Member,
    Reduced,
    TreeReducer,
)
from space_map_data.extrasolar.systems.registry import (
    RegistryResolver,
    _point_hosts,
    registry_orbits,
)
from space_map_data.extrasolar.systems.report import report_lines, tree_lines
from space_map_data.extrasolar.systems.resolve import FACTS, MATCH, Facts
from space_map_data.extrasolar.systems.simbad import read_simbad
from space_map_data.extrasolar.systems.wds import WDS_MATCHER, WdsCatalogue
from space_map_data.extrasolar.tables import SYSTEM_STAR, SYSTEM_TABLE
from tests.extrasolar.conftest import offset
from tests.extrasolar.systems_fakes import (
    KEPLER_16_GAIA,
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

    def systems(self, wds: WdsCatalogue | None = None) -> Systems:
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
            wds=wds,
        )
        return build(inputs, resolver)

    def test_shape(self):
        systems = self.systems()
        assert shape(systems, 12) == (
            "multiple star",
            3,
            [12, ("binary star", 2, [10, 11])],
        )

    def test_a_wds_with_no_nodes(self):
        systems = self.systems(wds_catalogue({}))
        assert shape(systems, 12) == shape(self.systems(), 12)
        assert not any(name.startswith(f"{WDS}:") for name in systems.counts)

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

    def test_a_star_with_no_parallax_takes_the_distance_of_its_node(self):
        """No star gives Castor B a place of its own, as in the registry."""
        systems = self.systems()
        rows = {r["key"]: r["distance"] for r in systems.distances.to_pylist()}
        assert rows.keys() == {100, 101, 102}
        node = systems.nodes.filter(pc.equal(systems.nodes["key"], 101))
        assert rows[101] == pytest.approx(node["distance"][0].as_py())
        assert np.isfinite(rows[101])


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
        # Procyon B has no distance: it takes the system's, Procyon A's vote.
        rows = dict(
            zip(
                systems.distances["key"].to_pylist(),
                systems.distances["distance"].to_pylist(),
            )
        )
        assert rows[111] == pytest.approx(1000 / 284.6)

    def test_an_unmatched_entry_that_is_a_point(self):
        """WDS B finds no object; the MSC has it as a point. The orbit moved B
        from 4.3″ to 5.2″ since the WDS measure, and the magnitudes agree."""
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


SIMBAD_STAR = {"catalogue": "simbad", "release": "oid", "catalogue_id": "7"}
STAR_ID = ("simbad", "oid", "7")


def record(host: int, class_: str = "brown dwarf", **values) -> dict:
    """A planet record that is the star of `STAR_ID`."""
    return {
        "host": host,
        "number": 1,
        "designation": "X b",
        "class": class_,
        "star_ids": [SIMBAD_STAR],
    } | values


def on_a_circle(key: int, separation: float, angle: float = 90.0, **values) -> dict:
    """The facts of a star `separation` arcsec from (10, 0), towards `angle`."""
    ra, dec = offset(10.0, 0.0, separation, angle)
    return fact(key, ra, dec, 9.0, **values)


class TestBrownDwarfs:
    """A brown dwarf record stays on its host, and its star in its system."""

    def wds(self, *pairs: dict) -> WdsCatalogue:
        components = {("1", "A"): wds_component(1, 10.0, 0.0)}
        for pair in pairs:
            components["1", pair["secondary"]] = wds_component(None, 9.0, 3.0)
        return wds_catalogue({"1": list(pairs)}, components)

    def test_it_stays_in_its_tree(self):
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
                STAR_ID: 92,
            },
            [fact(k, 10.0, 0.0, 9.0, parallax=10.0) for k in (90, 91, 92)],
        )
        systems = build(
            Inputs(msc=msc_nodes(comp, pairs, []), planets=planets([record(90)])),
            resolver,
        )
        assert shape(systems, 90)[:2] == ("multiple star", 3)
        assert systems.overlaps["outcome"].to_pylist() == [MEMBER]
        assert systems.overlaps["key"].to_pylist() == [92]
        assert systems.overlaps["record"].to_pylist() == [0]

    def test_it_takes_the_component_at_its_place(self):
        """The match reaches no star that SIMBAD lists with no magnitude. A
        WDS companion has no proper motion, so its row gives its place from
        its primary."""
        resolver = FakeResolver(
            {("gaia", "dr3", "1"): 90, STAR_ID: 92},
            [fact(90, 10.0, 0.0, 9.0, parallax=10.0), on_a_circle(92, 2.9)],
        )
        pair = wds_pair("A", "B", 2.9, mag1=9.0, mag2=19.0, position_angle=90.0)
        systems = build(
            Inputs(wds=self.wds(pair), planets=planets([record(90)])), resolver
        )
        assert shape(systems, 90) == ("binary star", 2, [90, 92])
        star = systems.members.filter(pc.equal(systems.members["key"], 92))
        assert star["letter"].to_pylist() == ["B"]
        assert star["v_mag"].to_pylist() == [19.0]
        counts = systems.counts
        assert counts[f"{PLANETS}: brown dwarfs that take a component"] == 1

    def test_a_star_at_its_hosts_position_takes_a_near_component(self):
        """SIMBAD can give a companion the position of its primary."""
        resolver = FakeResolver(
            {("gaia", "dr3", "1"): 90, STAR_ID: 92},
            [fact(90, 10.0, 0.0, 9.0, parallax=10.0), fact(92, 10.0, 0.0, 19.0)],
        )
        pair = wds_pair("A", "B", 2.9, mag1=9.0, mag2=19.0, position_angle=90.0)
        systems = build(
            Inputs(wds=self.wds(pair), planets=planets([record(90)])), resolver
        )
        assert shape(systems, 90) == ("binary star", 2, [90, 92])

    def test_two_records_of_one_star_take_one_component(self):
        """HD 97334 B and C: one point holds the pair."""
        resolver = FakeResolver(
            {("gaia", "dr3", "1"): 90, STAR_ID: 92},
            [fact(90, 10.0, 0.0, 9.0, parallax=10.0), on_a_circle(92, 2.9)],
        )
        pairs = [
            wds_pair("A", "B", 2.9, mag1=9.0, mag2=19.0, position_angle=90.0),
            wds_pair("A", "C", 3.5, mag1=9.0, mag2=19.0, position_angle=90.0),
        ]
        systems = build(
            Inputs(
                wds=self.wds(*pairs),
                planets=planets([record(90), record(90, number=2)]),
            ),
            resolver,
        )
        assert shape(systems, 90) == ("multiple star", 3, [90, 92, "entry"])
        counts = systems.counts
        assert counts[f"{PLANETS}: brown dwarfs that take a component"] == 1

    def test_a_component_elsewhere_is_another_star(self):
        resolver = FakeResolver(
            {("gaia", "dr3", "1"): 90, STAR_ID: 92},
            [fact(90, 10.0, 0.0, 9.0, parallax=10.0), on_a_circle(92, 52.0)],
        )
        pair = wds_pair("A", "B", 2.9, mag1=9.0, mag2=19.0, position_angle=90.0)
        systems = build(
            Inputs(wds=self.wds(pair), planets=planets([record(90)])), resolver
        )
        assert shape(systems, 90) == ("multiple star", 3, [90, 92, "entry"])

    def test_it_takes_the_pair_it_holds(self):
        """GJ 1001: the point of B holds Ba and Bb, which the MSC lists."""
        comp = [msc_comp("1", "A", HIP=1)]
        pairs = [
            msc_pair("1", "A", "B", "*", Sep=18.3, Sunit='"', PA=90.0),
            msc_pair("1", "Ba", "Bb", "B", Sep=0.087, Sunit='"'),
        ]
        resolver = FakeResolver(
            {("hip", "2007", "1"): 90, STAR_ID: 92},
            [fact(90, 10.0, 0.0, 9.0, parallax=10.0), on_a_circle(92, 18.3)],
        )
        systems = build(
            Inputs(msc=msc_nodes(comp, pairs, []), planets=planets([record(90)])),
            resolver,
        )
        assert shape(systems, 90) == ("multiple star", 3, [90, ("point", 92, 2)])

    def test_a_row_measured_from_another_star_is_not_it(self):
        """C lies 0.1″ from B, not from the host."""
        comp = [msc_comp("1", "A", HIP=1)]
        pairs = [
            msc_pair("1", "A", "BC", "*", Sep=30.0, Sunit='"', PA=90.0),
            msc_pair("1", "B", "C", "BC", Sep=0.1, Sunit='"'),
        ]
        resolver = FakeResolver(
            {("hip", "2007", "1"): 90, STAR_ID: 92},
            [fact(90, 10.0, 0.0, 9.0, parallax=10.0), on_a_circle(92, 1.0)],
        )
        systems = build(
            Inputs(msc=msc_nodes(comp, pairs, []), planets=planets([record(90)])),
            resolver,
        )
        assert systems.counts[f"{PLANETS}: brown dwarfs that take a component"] == 0

    def test_the_host_goes_down_beside_its_brown_dwarf(self):
        """HD 33632: the MSC puts the host on A, with Aa and Ab under it."""
        comp = [msc_comp("1", "A", HIP=1)]
        pairs = [msc_pair("1", "Aa", "Ab", "A", Sep=0.9, Sunit='"', PA=90.0)]
        pairs.append(msc_pair("1", "A", "B", "*", Sep=30.0, Sunit='"', PA=10.0))
        comp.append(msc_comp("1", "B", HIP=2))
        resolver = FakeResolver(
            {("hip", "2007", "1"): 90, ("hip", "2007", "2"): 91, STAR_ID: 92},
            [
                fact(90, 10.0, 0.0, 9.0, parallax=10.0),
                on_a_circle(91, 30.0, 10.0, parallax=10.0),
                on_a_circle(92, 0.9),
            ],
        )
        systems = build(
            Inputs(msc=msc_nodes(comp, pairs, []), planets=planets([record(90)])),
            resolver,
        )
        assert shape(systems, 90) == (
            "multiple star",
            3,
            [91, ("binary star", 2, [90, 92])],
        )

    def test_it_joins_at_the_top_of_the_tree_of_its_host(self):
        """No tree places it, so it is a member of the system as a whole."""
        comp = [msc_comp("1", "A", HIP=1), msc_comp("1", "B", HIP=2)]
        pairs = [msc_pair("1", "A", "B", "*", Sep=5.0, Sunit='"')]
        resolver = FakeResolver(
            {("hip", "2007", "1"): 90, ("hip", "2007", "2"): 91, STAR_ID: 92},
            [
                fact(90, 10.0, 0.0, 9.0, parallax=10.0),
                on_a_circle(91, 5.0, 0.0, parallax=10.0),
                on_a_circle(92, 200.0),
            ],
        )
        systems = build(
            Inputs(msc=msc_nodes(comp, pairs, []), planets=planets([record(90)])),
            resolver,
        )
        assert shape(systems, 90) == ("multiple star", 3, [90, 91, 92])
        star = systems.members.filter(pc.equal(systems.members["key"], 92))
        assert star["source"].to_pylist() == [None]
        assert systems.counts[f"{PLANETS}: brown dwarfs that join by their record"] == 1

    def test_a_host_in_no_tree_makes_a_system_with_it(self):
        resolver = FakeResolver(
            {("gaia", "dr3", "1"): 90, STAR_ID: 92},
            [fact(90, 10.0, 0.0, 9.0), on_a_circle(92, 3.5)],
        )
        systems = build(Inputs(planets=planets([record(90)])), resolver)
        assert shape(systems, 90) == ("binary star", 2, [90, 92])
        root = systems.nodes.filter(pc.equal(systems.nodes["parent"], 0))
        assert root["primary"].to_pylist() == [90]
        assert root["sources"].to_pylist() == [[PLANETS]]

    def test_the_host_stays_the_primary(self):
        """A SIMBAD row with a child lists its own point after it."""
        index = simbad_index(
            [
                simbad_object(6, "HD 1", 10.0, 0.0, v=7.0),
                simbad_object(7, "HD 1B", 10.0, 0.0),
            ],
            [(6, 7)],
        )
        resolver = FakeResolver(
            {("simbad", "oid", "6"): 90, STAR_ID: 92},
            [fact(90, 10.0, 0.0, 7.0, parallax=10.0), fact(92, 10.0, 0.0, 19.0)],
        )
        systems = build(
            Inputs(
                simbad=read_simbad(index.stars),
                simbad_index=index,
                planets=planets([record(90)]),
            ),
            resolver,
        )
        root = systems.nodes.filter(pc.equal(systems.nodes["parent"], 0))
        assert root["primary"].to_pylist() == [90]

    def test_a_pair_of_el_badry_stays_inside_the_new_system(self):
        """A set of the host and the star alone would cross the pair."""
        ids = {("gaia", "dr3", "1"): 90, ("gaia", "dr3", "2"): 91, STAR_ID: 92}
        resolver = FakeResolver(
            ids,
            [
                fact(90, 10.0, 0.0, 9.0, parallax=10.0),
                on_a_circle(91, 8.0, 0.0, parallax=10.0),
                on_a_circle(92, 3.5),
            ],
        )
        systems = build(
            Inputs(
                el_badry=el_badry([(1, 2, 8.0, 9.0, 12.0)]),
                planets=planets([record(90)]),
            ),
            resolver,
        )
        assert shape(systems, 90) == (
            "multiple star",
            3,
            [92, ("binary star", 2, [90, 91])],
        )

    def test_two_records_of_each_other_make_one_system(self):
        """2MASS J1450-7841: each is listed as the other's planet."""
        ids = [
            {"catalogue": EU, "release": "catalog", "catalogue_id": name}
            for name in ("X A", "X B")
        ]
        resolver = FakeResolver(
            {(EU, "catalog", "X A"): 90, (EU, "catalog", "X B"): 91},
            [fact(90, 10.0, 0.0, 9.0), on_a_circle(91, 5.0)],
        )
        systems = build(
            Inputs(
                planets=planets(
                    [
                        record(90, designation="X B", star_ids=[ids[1]]),
                        record(91, designation="X A", star_ids=[ids[0]]),
                    ]
                )
            ),
            resolver,
        )
        assert shape(systems, 90) == ("binary star", 2, [90, 91])
        assert systems.overlaps["outcome"].to_pylist() == [MEMBER, MEMBER]
        root = systems.nodes.filter(pc.equal(systems.nodes["parent"], 0))
        assert root["primary"].to_pylist() == [90]

    def test_parallaxes_that_disagree_show_a_wrong_id(self):
        """LHS 5166 b: SIMBAD's Gaia id leads 93° away. The star stays as it
        is, in its own system."""
        ids = {("gaia", "dr3", "1"): 90, STAR_ID: 92, ("hip", "2007", "3"): 92}
        ids[("hip", "2007", "4")] = 93
        comp = [msc_comp("1", "A", HIP=3), msc_comp("1", "B", HIP=4)]
        pairs = [msc_pair("1", "A", "B", "*", Sep=5.0, Sunit='"')]
        resolver = FakeResolver(
            ids,
            [
                fact(90, 10.0, 0.0, 9.0, parallax=50.0),
                fact(92, 100.0, 40.0, 9.0, parallax=6.0),
                fact(93, 100.0, 40.0, 9.0, parallax=6.0),
            ],
        )
        systems = build(
            Inputs(msc=msc_nodes(comp, pairs, []), planets=planets([record(90)])),
            resolver,
        )
        assert systems.overlaps["outcome"].to_pylist() == [APART]
        assert shape(systems, 92) == ("binary star", 2, [92, 93])
        assert 90 not in systems.points["key"].to_pylist()
        assert systems.counts[f"{PLANETS}: brown dwarfs at another distance"] == 1

    def test_a_star_in_another_system_stays_there(self):
        comp = [
            msc_comp("1", "A", HIP=1),
            msc_comp("1", "B", HIP=2),
            msc_comp("2", "A", HIP=3),
            msc_comp("2", "B", HIP=4),
        ]
        pairs = [
            msc_pair("1", "A", "B", "*", Sep=5.0, Sunit='"'),
            msc_pair("2", "A", "B", "*", Sep=5.0, Sunit='"'),
        ]
        ids = {("hip", "2007", str(n)): 89 + n for n in (1, 2, 3, 4)}
        resolver = FakeResolver(
            ids | {STAR_ID: 92},
            [
                fact(90, 10.0, 0.0, 9.0, parallax=10.0),
                on_a_circle(91, 5.0, 0.0, parallax=10.0),
                on_a_circle(92, 100.0, parallax=10.0),
                on_a_circle(93, 105.0, parallax=10.0),
            ],
        )
        systems = build(
            Inputs(msc=msc_nodes(comp, pairs, []), planets=planets([record(90)])),
            resolver,
        )
        assert shape(systems, 90) == ("binary star", 2, [90, 91])
        assert shape(systems, 92) == ("binary star", 2, [92, 93])
        assert systems.counts[f"{PLANETS}: brown dwarfs in another system"] == 1

    def test_a_record_with_no_host_leaves_its_star_as_it_is(self):
        """The ingest gives a host that gets no ID the key 0. Such a record
        is not drawn, so its star is."""
        resolver = FakeResolver({STAR_ID: 92}, [on_a_circle(92, 3.5)])
        systems = build(Inputs(planets=planets([record(0)])), resolver)
        assert systems.overlaps.num_rows == 0

    def test_a_record_is_its_first_star(self):
        """Its ids reach two stars: the first in the order of its ids."""
        other = {"catalogue": "simbad", "release": "oid", "catalogue_id": "8"}
        resolver = FakeResolver(
            {("hip", "2007", "1"): 90, STAR_ID: 92, ("simbad", "oid", "8"): 93},
            [
                fact(90, 10.0, 0.0, 9.0, parallax=10.0),
                on_a_circle(92, 5.0),
                on_a_circle(93, 50.0),
            ],
        )
        found = record(90, star_ids=[other, SIMBAD_STAR])
        systems = build(Inputs(planets=planets([found])), resolver)
        assert systems.overlaps["key"].to_pylist() == [93]

    def test_a_star_inside_the_light_of_its_host_is_no_star_of_its_own(self):
        """A record links no star to its own host."""
        index = simbad_index(
            [
                simbad_object(6, "HD 1", 10.0, 0.0, v=7.0),
                simbad_object(5, "HD 1 B", 10.0, 0.0),
                simbad_object(7, "HD 1 C", 10.0, 0.0, v=9.0),
            ],
            [(5, 6), (5, 7)],
        )
        resolver = FakeResolver(
            {("simbad", "oid", "6"): 90, STAR_ID: 92},
            [
                fact(90, 10.0, 0.0, 7.0, parallax=10.0),
                fact(92, 10.0, 0.0, 9.0, "simbad"),
            ],
        )
        systems = build(
            Inputs(
                simbad=read_simbad(index.stars),
                simbad_index=index,
                planets=planets([record(90)]),
            ),
            resolver,
        )
        assert systems.absorbed["into"].to_pylist() == [90]
        assert systems.overlaps.num_rows == 0

    def test_the_star_of_its_own_name(self):
        """The name of a record reaches the star of that name in its
        catalogue."""
        assert planet_star_ids(Simbad(), [(EU, "X B")]) == [(EU, "catalog", "X B")]

    def letters(self, systems: Systems) -> dict[str, int]:
        members = systems.members
        return dict(zip(members["letter"].to_pylist(), members["key"].to_pylist()))

    def children_of_a(self, *pairs: dict) -> WdsCatalogue:
        """Aa and its pairs under A, whose Gaia id is 1."""
        components = {("1", "A"): wds_component(1, 10.0, 0.0)}
        for pair in pairs:
            components["1", pair["secondary"]] = wds_component(None, 9.0, 3.0)
        return wds_catalogue({"1": list(pairs)}, components)

    def test_the_host_goes_down_only_to_the_first_child(self):
        """Aa has its own object, so the host stays on A and Ac stays free."""
        pairs = [
            wds_pair("Aa", "Ab", 2.9, position_angle=90.0),
            wds_pair("Aa", "Ac", 40.0, position_angle=10.0),
        ]
        catalogue = self.children_of_a(*pairs)
        catalogue.components["1", "Aa"] = wds_component(5, 10.0, 0.0)
        resolver = FakeResolver(
            {("gaia", "dr3", "1"): 90, ("gaia", "dr3", "5"): 95, STAR_ID: 92},
            [
                fact(90, 10.0, 0.0, 9.0, parallax=10.0),
                on_a_circle(95, 1.0, 180.0, parallax=10.0),
                on_a_circle(92, 2.9),
            ],
        )
        systems = build(Inputs(wds=catalogue, planets=planets([record(90)])), resolver)
        letters = self.letters(systems)
        assert letters["Ab"] == 92
        assert not letters["Ac"]

    def test_a_second_brown_dwarf_takes_the_host_no_further(self):
        """The host goes down once."""
        pairs = [
            wds_pair("Aa", "Ab", 2.9, position_angle=90.0),
            wds_pair("Aa", "Ac", 20.0, position_angle=90.0),
            # Nearest the host's magnitude, so a link would hold.
            wds_pair("Aa", "Ad", 40.0, mag1=14.0, mag2=9.0, position_angle=90.0),
        ]
        resolver = FakeResolver(
            {
                ("gaia", "dr3", "1"): 90,
                STAR_ID: 92,
                ("simbad", "oid", "8"): 93,
            },
            [
                fact(90, 10.0, 0.0, 9.0, parallax=10.0),
                on_a_circle(92, 2.9),
                on_a_circle(93, 20.0),
            ],
        )
        second = {"catalogue": "simbad", "release": "oid", "catalogue_id": "8"}
        systems = build(
            Inputs(
                wds=self.children_of_a(*pairs),
                planets=planets([record(90), record(90, number=2, star_ids=[second])]),
            ),
            resolver,
        )
        letters = self.letters(systems)
        assert (letters["Aa"], letters["Ab"], letters["Ac"]) == (90, 92, 93)
        assert not letters["Ad"]

    @pytest.mark.parametrize("separation", [-1.0, 0.0])
    def test_a_row_with_no_measure_is_not_it(self, separation):
        """The WDS gives -1 for no measure and 0 for a pair too close to
        measure, and neither is a place."""
        resolver = FakeResolver(
            {("gaia", "dr3", "1"): 90, STAR_ID: 92},
            [fact(90, 10.0, 0.0, 9.0, parallax=10.0), on_a_circle(92, 5.0)],
        )
        pair = wds_pair("A", "B", separation, mag1=9.0, mag2=19.0)
        systems = build(
            Inputs(wds=self.wds(pair), planets=planets([record(90)])), resolver
        )
        assert systems.counts[f"{PLANETS}: brown dwarfs that take a component"] == 0

    def test_a_pair_of_el_badry_comes_with_a_star_that_joins(self):
        """A pair that the group crosses would leave its other star out."""
        comp = [msc_comp("1", "A", HIP=1), msc_comp("1", "B", HIP=2)]
        pairs = [msc_pair("1", "A", "B", "*", Sep=5.0, Sunit='"')]
        resolver = FakeResolver(
            {
                ("hip", "2007", "1"): 90,
                ("hip", "2007", "2"): 91,
                STAR_ID: 92,
                ("gaia", "dr3", "92"): 92,
                ("gaia", "dr3", "93"): 93,
            },
            [
                fact(90, 10.0, 0.0, 9.0, parallax=10.0),
                on_a_circle(91, 5.0, 0.0, parallax=10.0),
                on_a_circle(92, 200.0, parallax=10.0),
                on_a_circle(93, 205.0, parallax=10.0),
            ],
        )
        systems = build(
            Inputs(
                msc=msc_nodes(comp, pairs, []),
                el_badry=el_badry([(92, 93, 5.0, 19.0, 20.0)]),
                planets=planets([record(90)]),
            ),
            resolver,
        )
        assert shape(systems, 90) == (
            "multiple star",
            4,
            [90, 91, ("binary star", 2, [92, 93])],
        )

    def test_a_pair_of_el_badry_comes_with_a_host_that_joins(self):
        comp = [msc_comp("1", "A", HIP=1), msc_comp("1", "B", HIP=2)]
        pairs = [msc_pair("1", "A", "B", "*", Sep=5.0, Sunit='"')]
        resolver = FakeResolver(
            {
                ("hip", "2007", "1"): 92,
                ("hip", "2007", "2"): 93,
                STAR_ID: 92,
                ("gaia", "dr3", "90"): 90,
                ("gaia", "dr3", "91"): 91,
            },
            [
                fact(90, 10.0, 0.0, 9.0, parallax=10.0),
                on_a_circle(91, 8.0, 0.0, parallax=10.0),
                on_a_circle(92, 200.0, parallax=10.0),
                on_a_circle(93, 205.0, parallax=10.0),
            ],
        )
        systems = build(
            Inputs(
                msc=msc_nodes(comp, pairs, []),
                el_badry=el_badry([(90, 91, 8.0, 9.0, 12.0)]),
                planets=planets([record(90)]),
            ),
            resolver,
        )
        assert shape(systems, 92) == (
            "multiple star",
            4,
            [92, 93, ("binary star", 2, [90, 91])],
        )

    def test_two_records_of_each_other_are_two_stars(self):
        """One record calls B a planet of A, the other A a brown dwarf of B.
        Each star hosts a record, so both are stars."""
        ids = [
            {"catalogue": EU, "release": "catalog", "catalogue_id": name}
            for name in ("X A", "X B")
        ]
        resolver = FakeResolver(
            {(EU, "catalog", "X A"): 90, (EU, "catalog", "X B"): 92},
            [fact(90, 10.0, 0.0, 9.0), on_a_circle(92, 5.0)],
        )
        systems = build(
            Inputs(
                planets=planets(
                    [
                        record(
                            90,
                            "planet",
                            mass=5.0,
                            designation="X B",
                            star_ids=[ids[1]],
                        ),
                        record(92, designation="X A", star_ids=[ids[0]]),
                    ]
                )
            ),
            resolver,
        )
        assert shape(systems, 90)[:2] == ("binary star", 2)
        assert systems.overlaps["key"].to_pylist() == [90, 92]
        assert systems.overlaps["outcome"].to_pylist() == [MEMBER, MEMBER]

    def test_leaving_wins_over_a_membership(self):
        """Two records reach one star: a planet of one host, a brown dwarf of
        the other."""
        resolver = FakeResolver(
            {STAR_ID: 92},
            [fact(90, 10.0, 0.0, 9.0), fact(91, 12.0, 0.0, 9.0), on_a_circle(92, 5.0)],
        )
        systems = build(
            Inputs(planets=planets([record(90, "planet", mass=5.0), record(91)])),
            resolver,
        )
        assert systems.points.num_rows == 0
        assert systems.overlaps["outcome"].to_pylist() == [LEAVES, LEAVES]

    def primary(self, systems: Systems) -> list[int]:
        root = systems.nodes.filter(pc.equal(systems.nodes["parent"], 0))
        return root["primary"].to_pylist()

    def test_a_host_that_joins_its_brown_dwarf_is_the_primary(self):
        comp = [msc_comp("1", "A", HIP=1), msc_comp("1", "B", HIP=2)]
        pairs = [msc_pair("1", "A", "B", "*", Sep=5.0, Sunit='"')]
        resolver = FakeResolver(
            {("hip", "2007", "1"): 92, ("hip", "2007", "2"): 93, STAR_ID: 92},
            [
                fact(90, 10.0, 0.0, 9.0, parallax=10.0),
                on_a_circle(92, 3.5, parallax=10.0),
                on_a_circle(93, 8.0, parallax=10.0),
            ],
        )
        systems = build(
            Inputs(msc=msc_nodes(comp, pairs, []), planets=planets([record(90)])),
            resolver,
        )
        assert self.primary(systems) == [90]

    def test_a_host_is_the_primary_over_an_inner_pair_too(self):
        """The brown dwarf is the first star of a pair of the group."""
        comp = [msc_comp("1", name, HIP=at + 1) for at, name in enumerate("ABC")]
        pairs = [
            msc_pair("1", "AB", "C", "*", Sep=20.0, Sunit='"'),
            msc_pair("1", "A", "B", "AB", Sep=5.0, Sunit='"'),
        ]
        ids = {("hip", "2007", str(at + 1)): 92 + at for at in range(3)}
        resolver = FakeResolver(
            ids | {STAR_ID: 92},
            [
                fact(90, 10.0, 0.0, 9.0, parallax=10.0),
                on_a_circle(92, 3.5, parallax=10.0),
                on_a_circle(93, 8.0, parallax=10.0),
                on_a_circle(94, 20.0, parallax=10.0),
            ],
        )
        systems = build(
            Inputs(msc=msc_nodes(comp, pairs, []), planets=planets([record(90)])),
            resolver,
        )
        assert self.primary(systems) == [90]

    def test_a_close_type_throws_off_the_parallax(self):
        """A SIMBAD close pair on the host: no veto, as for the trees."""
        index = simbad_index([simbad_object(6, "HD 1", 10.0, 0.0, otype="SB*", v=9.0)])
        resolver = FakeResolver(
            {("simbad", "oid", "6"): 90, STAR_ID: 92},
            [
                fact(90, 10.0, 0.0, 9.0, parallax=50.0),
                on_a_circle(92, 3.5, parallax=6.0),
            ],
        )
        systems = build(
            Inputs(simbad_index=index, planets=planets([record(90)])), resolver
        )
        assert systems.overlaps["outcome"].to_pylist() == [MEMBER]

    def test_a_gaia_orbit_throws_off_the_parallax(self):
        orbits = orbit_pairs(
            pa.table(
                {
                    "key": [90],
                    "nss_solution_type": ["SB1"],
                    "period": [10.0],
                    "eccentricity": [0.0],
                    "m1": [1.0],
                    "m2": [0.5],
                }
            )
        )
        resolver = FakeResolver(
            {STAR_ID: 92},
            [
                fact(90, 10.0, 0.0, 9.0, parallax=50.0),
                on_a_circle(92, 3.5, parallax=6.0),
            ],
        )
        systems = build(Inputs(orbits=orbits, planets=planets([record(90)])), resolver)
        assert systems.overlaps["outcome"].to_pylist() == [MEMBER]


class TestDryRunMatch:
    """The dry run's match takes the kind of the rows of the ingest."""

    def matched(self, kind: str) -> list[int]:
        resolver = RegistryResolver(MagicMock(part_regions=lambda _: []))
        rows = pa.Table.from_pylist(
            [
                {
                    "catalogue_id": "1 B",
                    "mint": False,
                    "match_ra": 10.0,
                    "match_dec": 0.0,
                    "match_error": 1.0,
                }
            ],
            schema=MATCH,
        )
        candidates = pa.table(
            {
                "id": [92],
                "ra": [10.0],
                "dec": [0.0],
                "pos_error": [1.0],
                "size": pa.array([None], pa.float32()),
                "mag": pa.array([None], pa.float32()),
                "kind": [kind],
            }
        )
        return resolver._match(rows, candidates, WDS_MATCHER).tolist()

    def test_a_star(self):
        assert self.matched("star") == [92]

    def test_an_unseen_star_is_out_of_its_reach(self):
        assert self.matched("unseen star") == [0]


class TestPlanets:
    """A planet under the IAU's line leaves the tree; a circumbinary host."""

    def test_a_planet_that_is_a_star_leaves(self):
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
                planets=planets([record(90, "planet", mass=5.0)]),
            ),
            resolver,
        )
        assert shape(systems, 90) == ("binary star", 2, [90, 91])
        assert systems.overlaps["key"].to_pylist() == [92]
        assert systems.overlaps["designation"].to_pylist() == ["X b"]
        assert systems.overlaps["outcome"].to_pylist() == [LEAVES]

    def test_a_record_with_no_mass_is_its_star(self):
        """It is a planet only by default, so the star catalogue decides."""
        resolver = FakeResolver(
            {("hip", "2007", "1"): 90, ("simbad", "oid", "7"): 92},
            [fact(90, 10.0, 0.0, 9.0, parallax=10.0), on_a_circle(92, 5.0)],
        )
        systems = build(Inputs(planets=planets([record(90, "planet")])), resolver)
        assert systems.overlaps["outcome"].to_pylist() == [MEMBER]
        assert shape(systems, 90)[:2] == ("binary star", 2)

    def test_a_transiting_brown_dwarf_leaves(self):
        """Found through its host, it has no point of its own: the star that
        it reaches is a catalogue entry of the record."""
        resolver = FakeResolver(
            {("hip", "2007", "1"): 90, ("simbad", "oid", "7"): 92},
            [
                fact(90, 10.0, 0.0, 9.0, parallax=10.0),
                on_a_circle(92, 0.2, astrometry="simbad"),
            ],
        )
        found = record(90, mass=54.0, discovery_method="Transit")
        systems = build(Inputs(planets=planets([found])), resolver)
        assert systems.overlaps["outcome"].to_pylist() == [LEAVES]
        assert systems.points.num_rows == 0

    def test_a_planet_at_another_distance_reaches_another_star(self):
        resolver = FakeResolver(
            {("hip", "2007", "1"): 90, ("simbad", "oid", "7"): 92},
            [
                fact(90, 10.0, 0.0, 9.0, parallax=10.0),
                on_a_circle(92, 30.0, parallax=40.0),
            ],
        )
        found = record(90, "planet", mass=5.0, discovery_method="Imaging")
        systems = build(Inputs(planets=planets([found])), resolver)
        assert systems.overlaps["outcome"].to_pylist() == [APART]

    def test_a_star_that_hosts_a_record_is_a_star(self):
        """A planet record reaches a star that has a planet of its own."""
        resolver = FakeResolver(
            {("hip", "2007", "1"): 90, ("simbad", "oid", "7"): 92},
            [fact(90, 10.0, 0.0, 9.0, parallax=10.0), on_a_circle(92, 5.0)],
        )
        rows = [
            record(90, "planet", mass=5.0, discovery_method="Imaging"),
            record(92, "planet", mass=1.0, star_ids=None, designation="Y b"),
        ]
        systems = build(Inputs(planets=planets(rows)), resolver)
        assert systems.overlaps["outcome"].to_pylist() == [MEMBER]

    def test_a_transiting_planet_reaches_no_star_with_a_point(self):
        """A Gaia star that its record reaches is another star."""
        resolver = FakeResolver(
            {("hip", "2007", "1"): 90, ("simbad", "oid", "7"): 92},
            [
                fact(90, 10.0, 0.0, 9.0, parallax=10.0),
                on_a_circle(92, 90.0, astrometry="gaia-dr3", parallax=11.0),
            ],
        )
        found = record(90, "planet", mass=0.01, discovery_method="Transit")
        systems = build(Inputs(planets=planets([found])), resolver)
        assert systems.overlaps["outcome"].to_pylist() == [OTHER_STAR]

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
            sorted(value.items())
            if isinstance(value, Counter)
            else value.tolist()
            if isinstance(value, np.ndarray)
            else sorted(value)
            if isinstance(value, frozenset)
            else value.to_pylist()
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


def wds_tree(rows: list[tuple]) -> pa.Table:
    """A WDS node table of (label, parent, separation, V, evidence) rows."""
    base = dict.fromkeys(NODES.names)
    return pa.Table.from_pylist(
        [
            base
            | {
                "source": WDS,
                "system": "01000+1000",
                "node": at,
                "label": label,
                "parent": parent,
                "separation": separation,
                "v_mag": mag,
                "evidence": evidence,
            }
            for at, (label, parent, separation, mag, evidence) in enumerate(rows)
        ],
        schema=NODES,
    )


class TestCrossMatchError:
    """A and B of one WDS pair reach X, which they are too far apart to share.

    B holds Ba and the unverified pair Bb, which leaves the tree as a group of
    its own. B loses X, and Ba takes W.
    """

    def reduced(self) -> Reduced:
        table = wds_tree(
            [
                ("AB", -1, None, None, None),
                ("A", 0, None, 5.0, None),
                ("B", 0, 5.0, 8.0, None),
                ("Ba", 2, None, 8.0, None),
                ("Bb", 2, 3.0, 9.0, UNVERIFIED),
                ("Bb1", 4, None, 9.0, None),
                ("Bb2", 4, 2.0, 9.5, None),
            ]
        )
        X, W, Y, Z = 100, 101, 102, 103
        candidates = [[], [(X, 2)], [], [(X, 2), (W, 2)], [], [(Y, 2)], [(Z, 2)]]
        facts = Facts(
            pa.Table.from_pylist(
                [
                    fact(X, 10.0, 10.0, 5.1, parallax=10.0),
                    fact(W, 10.0, 10.0014, 8.1, parallax=10.0),
                    fact(Y, 10.0, 10.003, 9.0, parallax=10.0),
                    fact(Z, 10.0, 10.0031, 9.5, parallax=10.0),
                ],
                schema=FACTS,
            )
        )
        out = Reduced()
        TreeReducer(table, 0, candidates, facts, 0, out).run()
        return out

    def test_each_subtree_counts_once(self):
        out = self.reduced()
        members = {
            name: value
            for name, value in out.counts.items()
            if name.startswith(f"{WDS}: members ")
        }
        # The leaves A, Ba, Bb1 and Bb2.
        assert sum(members.values()) == 4
        assert out.counts[f"{WDS}: {UNVERIFIED} members left for agreement"] == 1
        assert out.counts[f"{WDS}: inner systems of members that left"] == 1
        assert out.counts[f"{WDS}: cross-match error"] == 1
        assert [kind for kind, _, _ in out.events] == ["cross-match error"]
        (tentative,) = out.tentative
        assert tentative.keys == frozenset({101, 102, 103})

    def test_no_duplicate_group(self):
        out = self.reduced()
        assert [(group.value, group.keys) for group in out.groups] == [
            (4, frozenset({102, 103})),
            (0, frozenset({100, 101})),
        ]

    def test_an_unverified_member_that_loses_its_object_leaves(self):
        """B is unverified and reaches X with A. X stays with A, and B has no
        other candidate: it has no point whose parallax could agree."""
        table = wds_tree(
            [
                ("AB", -1, None, None, None),
                ("A", 0, None, 5.0, None),
                ("B", 0, 1.1, 5.3, UNVERIFIED),
            ]
        )
        x = fact(100, 10.0, 10.0, 5.0, parallax=10.0, pmra=20.0, pmdec=-5.0)
        facts = Facts(pa.Table.from_pylist([x], schema=FACTS))
        out = Reduced()
        TreeReducer(table, 0, [[], [(100, 2)], [(100, 9)]], facts, 0, out).run()
        assert out.groups == [] and out.interiors == []
        assert [kind for kind, _, _ in out.events] == ["cross-match error"]
        assert out.counts[f"{WDS}: {UNVERIFIED} members left for agreement"] == 1
        assert f"{WDS}: unverified members kept by parallax" not in out.counts

    def test_the_id_of_a_keeper_that_leaves_goes_back(self):
        """A and B of AB reach X, and X's magnitude is nearer B's. B keeps X,
        so A has no object, and B is unverified and leaves. X goes back to A,
        and AB is a point of the system ABC."""
        table = wds_tree(
            [
                ("ABC", -1, None, None, None),
                ("AB", 0, None, None, None),
                ("A", 1, None, 5.0, None),
                ("B", 1, 1.1, 5.3, UNVERIFIED),
                ("C", 0, 20.0, 7.0, None),
            ]
        )
        x = fact(100, 10.0, 10.0, 5.3, parallax=10.0, pmra=20.0, pmdec=-5.0)
        q = fact(101, 10.0, 10.0 + 20 / 3600, 7.0, parallax=10.0, pmra=20.0, pmdec=-5.0)
        facts = Facts(pa.Table.from_pylist([x, q], schema=FACTS))
        out = Reduced()
        candidates = [[], [], [(100, 2)], [(100, 2)], [(101, 2)]]
        TreeReducer(table, 0, candidates, facts, 0, out).run()
        (group,) = out.groups
        assert group.keys == frozenset({100, 101})
        assert [(m.kind, m.key, m.value) for m in group.members] == [
            ("point", 100, 1),
            ("point", 101, 4),
        ]
        ((kind, _, text),) = out.events
        assert kind == "cross-match error"
        assert text.endswith("it stays with B; B leaves the tree, so it goes back to A")
        assert out.counts[f"{WDS}: shared ids back from a member that left"] == 1
        assert out.counts[f"{WDS}: {UNVERIFIED} members left for agreement"] == 1


class TestUnverifiedMembers:
    """An unverified member B of the pair AB stays only where two points agree."""

    def reduced(
        self,
        separation: float | None,
        facts: list[dict],
        b: int,
        evidence: str | None = UNVERIFIED,
        b_next: int = 0,
    ) -> Reduced:
        table = wds_tree(
            [
                ("AB", -1, None, None, None),
                ("A", 0, None, 5.0, None),
                ("B", 0, separation, 5.3, evidence),
            ]
        )
        out = Reduced()
        found = Facts(pa.Table.from_pylist(facts, schema=FACTS))
        b_candidates = ([(b, 2)] if b else []) + ([(b_next, 9)] if b_next else [])
        TreeReducer(table, 0, [[], [(100, 2)], b_candidates], found, 0, out).run()
        return out

    def test_two_points_that_agree(self):
        x = fact(100, 10.0, 10.0, 5.0, parallax=10.0, pmra=20.0, pmdec=-5.0)
        y = fact(101, 10.0, 10.0 + 20 / 3600, 5.3, parallax=10.1, pmra=20.5, pmdec=-5.0)
        out = self.reduced(20.0, [x, y], 101)
        (group,) = out.groups
        assert group.keys == frozenset({100, 101})
        assert out.counts[f"{WDS}: unverified members kept by parallax"] == 1

    def test_one_point_holds_both(self):
        """A and B are 0.3″ apart and reach X, which cannot split them. X holds
        both stars, as for a physical pair."""
        x = fact(100, 10.0, 10.0, 5.0, parallax=10.0, pmra=20.0, pmdec=-5.0)
        out = self.reduced(0.3, [x], 100)
        assert out.groups == [] and out.tentative == [] and out.events == []
        (interior,) = out.interiors
        assert interior.key == 100 and interior.entries == [(1, None), (2, None)]
        assert f"{WDS}: {UNVERIFIED} members on the primary's point" not in out.counts

    def test_no_object_inside_the_primary_point(self):
        """B reaches no object, and X cannot split it from A at 0.1″ (HD
        206136). X holds both stars."""
        x = fact(100, 10.0, 10.0, 5.0, parallax=10.0, pmra=20.0, pmdec=-5.0)
        out = self.reduced(0.1, [x], 0)
        assert out.groups == [] and out.tentative == []
        (interior,) = out.interiors
        assert interior.key == 100 and interior.entries == [(1, None), (2, None)]
        name = f"{WDS}: unverified members inside the primary's point"
        assert out.counts[name] == 1

    def test_an_interior_of_unverified_members(self):
        x = fact(100, 10.0, 10.0, 5.0, parallax=10.0, pmra=20.0, pmdec=-5.0)
        assert [i.unverified for i in self.reduced(0.1, [x], 0).interiors] == [True]
        assert [i.unverified for i in self.reduced(0.1, [x], 0, None).interiors] == [
            False
        ]

    def test_no_object_beside_the_primary_point(self):
        """X splits B from A at 1.1″, so B needs a point of its own."""
        x = fact(100, 10.0, 10.0, 5.0, parallax=10.0, pmra=20.0, pmdec=-5.0)
        out = self.reduced(1.1, [x], 0)
        assert out.groups == [] and out.interiors == []
        assert out.counts[f"{WDS}: {UNVERIFIED} members left for agreement"] == 1

    def test_one_point_with_no_separation(self):
        """With no separation, nothing says that X cannot split them."""
        x = fact(100, 10.0, 10.0, 5.0, parallax=10.0, pmra=20.0, pmdec=-5.0)
        out = self.reduced(None, [x], 100)
        assert out.groups == [] and out.interiors == []
        assert out.counts[f"{WDS}: {UNVERIFIED} members on the primary's point"] == 1

    def test_a_dubious_member_on_a_point_that_cannot_split_them(self):
        """X cannot split A and B at 0.3″, and B is dubious, so B leaves."""
        x = fact(100, 10.0, 10.0, 5.0, parallax=10.0, pmra=20.0, pmdec=-5.0)
        out = self.reduced(0.3, [x], 100, DUBIOUS)
        assert out.groups == [] and out.interiors == []
        assert out.tentative == [] and out.events == []
        assert out.counts[f"{WDS}: {DUBIOUS} members on the primary's point"] == 1

    def test_a_dubious_member_on_a_point_that_splits_them(self):
        """X splits A and B at 1.1″, so the shared id is a cross-match error.
        B is dubious and has no other object, so it leaves."""
        x = fact(100, 10.0, 10.0, 5.0, parallax=10.0, pmra=20.0, pmdec=-5.0)
        out = self.reduced(1.1, [x], 100, DUBIOUS)
        assert out.groups == [] and out.tentative == []
        assert [kind for kind, _, _ in out.events] == ["cross-match error"]
        assert out.counts[f"{WDS}: {DUBIOUS} members left for agreement"] == 1
        assert f"{WDS}: {DUBIOUS} members on the primary's point" not in out.counts

    def test_a_dubious_member_takes_its_next_candidate(self):
        """B's id reaches A's point X by error. B takes its own star Y and
        waits for another source to agree."""
        x = fact(100, 10.0, 10.0, 5.0, parallax=10.0, pmra=20.0, pmdec=-5.0)
        y = fact(
            101, 10.0, 10.0 + 1.1 / 3600, 5.3, parallax=10.0, pmra=20.0, pmdec=-5.0
        )
        out = self.reduced(1.1, [x, y], 100, DUBIOUS, b_next=101)
        assert out.groups == []
        assert [kind for kind, _, _ in out.events] == ["cross-match error"]
        (tentative,) = out.tentative
        assert tentative.keys == frozenset({100, 101})
        assert tentative.evidence == DUBIOUS
        assert out.counts[f"{WDS}: {DUBIOUS} members left for agreement"] == 1


class TestMergedPoint:
    """BCD is an unverified member of ABCD. Y holds B and C, its physical
    companion at 0.1″. D is 5″ away and an entry."""

    def interiors(self, c_evidence: str | None) -> list[Interior]:
        table = wds_tree(
            [
                ("ABCD", -1, None, None, None),
                ("A", 0, None, 5.0, None),
                ("BCD", 0, 20.0, None, UNVERIFIED),
                ("B", 2, None, 6.0, None),
                ("C", 2, 0.1, 6.5, c_evidence),
                ("D", 2, 5.0, 7.0, None),
            ]
        )
        rows = [
            fact(100, 10.0, 10.0, 5.0, parallax=10.0, pmra=20.0, pmdec=-5.0),
            fact(
                101, 10.0, 10.0 + 20 / 3600, 6.0, parallax=10.0, pmra=20.0, pmdec=-5.0
            ),
        ]
        facts = Facts(pa.Table.from_pylist(rows, schema=FACTS))
        out = Reduced()
        candidates = [[], [(100, 2)], [], [(101, 2)], [], []]
        TreeReducer(table, 0, candidates, facts, 0, out).run()
        return out.interiors

    def test_a_physical_companion(self):
        (interior,) = self.interiors(None)
        assert interior.key == 101 and len(interior.entries) == 2
        assert not interior.unverified

    def test_an_unverified_companion(self):
        (interior,) = self.interiors(UNVERIFIED)
        assert interior.unverified


class TestUnverifiedInsideAGroup:
    """B of ABC is unverified, has no object, and is 0.1″ from A. C is a
    point 30″ away. B is inside A's point."""

    def test_the_point_holds_b(self):
        table = wds_tree(
            [
                ("ABC", -1, None, None, None),
                ("A", 0, None, 5.0, None),
                ("B", 0, 0.1, 5.5, UNVERIFIED),
                ("C", 0, 30.0, 7.0, None),
            ]
        )
        rows = [
            fact(100, 10.0, 10.0, 5.0, parallax=10.0, pmra=20.0, pmdec=-5.0),
            fact(
                102, 10.0, 10.0 + 30 / 3600, 7.0, parallax=10.0, pmra=20.0, pmdec=-5.0
            ),
        ]
        facts = Facts(pa.Table.from_pylist(rows, schema=FACTS))
        out = Reduced()
        TreeReducer(table, 0, [[], [(100, 2)], [], [(102, 2)]], facts, 0, out).run()
        (group,) = out.groups
        assert [(m.kind, m.key) for m in group.members] == [
            ("point", 100),
            ("point", 102),
        ]
        (interior,) = out.interiors
        assert interior.key == 100 and [e[0] for e in interior.entries] == [1, 2]
        assert interior.unverified


class TestInteriorEvidence:
    """An interior is of unverified members when each star beside the main
    star is one."""

    def test_an_entry_leaves(self):
        item = Interior(100, WDS, 0, "x", [(1, None), (2, None), (3, None)])
        item = replace(item, unverified_rows=frozenset({3}))
        assert not item.unverified
        assert replace(item, entries=[(1, None), (3, None)]).unverified


class TestCommonProperMotion:
    """HD 106906 (C) and HD 106444 (A) move together at 1,000″. The motion
    alone does not make them a pair."""

    def systems(self, parallax: float, notes: str = "N") -> Systems:
        w = "12148-5547"
        components = {(w, "A"): wds_component(1), (w, "C"): wds_component(3)}
        pair = wds_pair("A", "C", 1000.0, notes=notes, pm1=(-38, -12), pm2=(-39, -13))
        resolver = FakeResolver(
            {("gaia", "dr3", "1"): 10, ("gaia", "dr3", "3"): 12},
            [
                fact(10, 183.7, -55.79, 7.0, parallax=8.735, pmra=-38.5, pmdec=-12.5),
                fact(
                    12,
                    183.7,
                    -55.79 + 1000 / 3600,
                    8.0,
                    parallax=parallax,
                    pmra=-38.5,
                    pmdec=-12.5,
                ),
            ],
        )
        return build(Inputs(wds=wds_catalogue({w: [pair]}, components)), resolver)

    def test_another_distance_is_no_pair(self):
        systems = self.systems(parallax=9.767)
        assert systems.points.num_rows == 0
        name = f"{WDS}: {UNVERIFIED} members that the parallaxes veto"
        assert systems.counts[name] == 1

    def test_the_same_distance_is_a_pair(self):
        systems = self.systems(parallax=8.8)
        assert shape(systems, 12) == ("binary star", 2, [10, 12])
        assert systems.counts[f"{WDS}: unverified members kept by parallax"] == 1


class TestParallaxVeto:
    """A physical member leaves when its parallax and its primary's clearly
    disagree, unless it is an orbit pair."""

    def reduced(
        self,
        parallax: float,
        known: list[str] | None = None,
        astrometry: str = "gaia-dr3",
    ) -> Reduced:
        table = wds_tree(
            [
                ("AB", -1, None, None, None),
                ("A", 0, None, 7.0, None),
                ("B", 0, 1000.0, 8.0, None),
            ]
        ).set_column(
            NODES.get_field_index("known"),
            "known",
            pa.array([None, None, known], pa.list_(pa.string())),
        )
        a = fact(100, 183.7, -55.79, 7.0, parallax=8.735, pmra=-38.5, pmdec=-12.5)
        b = fact(
            101,
            183.7,
            -55.79 + 1000 / 3600,
            8.0,
            astrometry=astrometry,
            parallax=parallax,
            pmra=-38.5,
            pmdec=-12.5,
        )
        facts = Facts(pa.Table.from_pylist([a, b], schema=FACTS))
        out = Reduced()
        candidates = [[], [(100, 2)], [(101, 2)]]
        TreeReducer(table, 0, candidates, facts, 0, out).run()
        return out

    def test_a_physical_member_leaves(self):
        out = self.reduced(9.767)
        assert out.groups == [] and out.tentative == []
        assert out.counts[f"{WDS}: physical members that the parallaxes veto"] == 1
        ((kind, source, text),) = out.events
        assert (kind, source) == ("parallaxes disagree", WDS)
        assert text.startswith(f"{WDS} 01000+1000 B: 101 9.767")

    def test_parallaxes_within_ten_percent(self):
        (group,) = self.reduced(9.5).groups
        assert group.keys == frozenset({100, 101})

    def test_an_orbit_pair_is_exempt(self):
        (group,) = self.reduced(9.767, known=[VISUAL, VISUAL_ORBIT]).groups
        assert group.keys == frozenset({100, 101})

    def test_only_own_astrometry(self):
        (group,) = self.reduced(9.767, astrometry="simbad").groups
        assert group.keys == frozenset({100, 101})

    def test_a_point_that_holds_several_stars_is_no_exemption(self):
        """B's point holds Ba and Bb, and leaves with them."""
        table = wds_tree(
            [
                ("AB", -1, None, None, None),
                ("A", 0, None, 7.0, None),
                ("B", 0, 1000.0, 8.0, None),
                ("Ba", 2, None, 8.0, None),
                ("Bb", 2, 0.1, 8.5, None),
            ]
        )
        a = fact(100, 183.7, -55.79, 7.0, parallax=8.735)
        b = fact(101, 183.7, -55.79 + 1000 / 3600, 8.0, parallax=9.767)
        facts = Facts(pa.Table.from_pylist([a, b], schema=FACTS))
        out = Reduced()
        candidates = [[], [(100, 2)], [], [(101, 2)], []]
        TreeReducer(table, 0, candidates, facts, 0, out).run()
        assert out.groups == []
        (interior,) = out.interiors
        assert interior.key == 101
        assert out.counts[f"{WDS}: physical members that the parallaxes veto"] == 1

    def test_el_badry_pairs(self):
        """The veto drops an El-Badry pair."""
        facts = Facts(
            pa.Table.from_pylist(
                [
                    fact(100, 183.7, -55.79, 7.0, parallax=8.735),
                    fact(101, 183.7, -55.79 + 1000 / 3600, 8.0, parallax=9.767),
                    fact(102, 183.7, -55.79 + 900 / 3600, 8.0, parallax=8.8),
                ],
                schema=FACTS,
            )
        )
        first = np.array([100, 100, 100, 0], np.int64)
        second = np.array([101, 102, 101, 101], np.int64)
        found = vetoed_pairs(facts, first, second)
        assert found.tolist() == [True, False, True, False]

    def test_el_badry_pairs_with_no_facts(self):
        found = vetoed_pairs(
            Facts(FACTS.empty_table()),
            np.array([0, 5], np.int64),
            np.array([0, 0], np.int64),
        )
        assert found.tolist() == [False, False]


class TestElBadryVeto:
    """El-Badry pairs 100 and 101, whose parallaxes clearly disagree."""

    def systems(self, otype: str | None = None, wds: bool = False) -> Systems:
        resolver = FakeResolver(
            {
                ("gaia", "dr3", "21"): 100,
                ("gaia", "dr3", "22"): 101,
                ("simbad", "oid", "40"): 100,
            },
            [
                fact(100, 183.7, -55.79, 7.0, parallax=8.735),
                fact(101, 183.7, -55.79 + 1000 / 3600, 8.0, parallax=9.767),
            ],
        )
        index = None
        if otype:
            index = simbad_index(
                [simbad_object(40, "HD 1", 183.7, -55.79, otype=otype, v=7.0)]
            )
        catalogue = None
        if wds:
            w = "12148-5547"
            catalogue = wds_catalogue(
                {w: [wds_pair("A", "B", 0.1, mag1=7.0, mag2=8.0)]},
                {(w, "A"): wds_component(21)},
            )
        inputs = Inputs(
            el_badry=el_badry([(21, 22, 1000.0, 7.0, 8.0)]),
            simbad_index=index,
            wds=catalogue,
        )
        return build(inputs, resolver)

    def test_the_veto_is_an_event(self):
        systems = self.systems()
        assert systems.counts[f"{EL_BADRY}: pairs that the parallaxes veto"] == 1
        events = systems.events.filter(
            pc.equal(systems.events["kind"], "parallaxes disagree")
        )
        assert events["source"].to_pylist() == [EL_BADRY]
        (text,) = events["text"].to_pylist()
        assert "100 8.735" in text and "101 9.767" in text

    def test_a_close_type_is_no_exemption(self):
        systems = self.systems(otype="EB*")
        assert systems.counts[f"{EL_BADRY}: pairs that the parallaxes veto"] == 1

    def test_a_point_with_an_interior_is_no_exemption(self):
        """WDS B is inside the point of A, so the point holds two stars."""
        systems = self.systems(wds=True)
        assert systems.counts[f"{EL_BADRY}: pairs that the parallaxes veto"] == 1


class TestGroupPrimary:
    """C is measured from the pair AB, so it is tested against A, the first
    point of AB."""

    def reduced(self, parallax: float, evidence: str | None) -> Reduced:
        table = wds_tree(
            [
                ("ABC", -1, None, None, None),
                ("AB", 0, None, None, None),
                ("A", 1, None, 5.0, None),
                ("B", 1, 5.0, 6.0, None),
                ("C", 0, 30.0, 7.0, evidence),
            ]
        )
        rows = [
            fact(100, 10.0, 10.0, 5.0, parallax=10.0, pmra=20.0, pmdec=-5.0),
            fact(101, 10.0, 10.0 + 5 / 3600, 6.0, parallax=10.0, pmra=20.0, pmdec=-5.0),
            fact(
                102,
                10.0,
                10.0 + 30 / 3600,
                7.0,
                parallax=parallax,
                pmra=20.0,
                pmdec=-5.0,
            ),
        ]
        facts = Facts(pa.Table.from_pylist(rows, schema=FACTS))
        out = Reduced()
        candidates = [[], [], [(100, 2)], [(101, 2)], [(102, 2)]]
        TreeReducer(table, 0, candidates, facts, 0, out).run()
        return out

    def test_an_unverified_member_that_agrees(self):
        out = self.reduced(10.05, UNVERIFIED)
        assert [group.keys for group in out.groups] == [
            frozenset({100, 101}),
            frozenset({100, 101, 102}),
        ]
        assert out.counts[f"{WDS}: unverified members of a group kept"] == 1

    def test_an_unverified_member_that_disagrees(self):
        out = self.reduced(10.5, UNVERIFIED)
        assert {group.keys for group in out.groups} == {frozenset({100, 101})}
        assert out.counts[f"{WDS}: {UNVERIFIED} members left for agreement"] == 1

    def test_the_veto(self):
        out = self.reduced(12.0, None)
        assert {group.keys for group in out.groups} == {frozenset({100, 101})}
        assert out.counts[f"{WDS}: physical members that the parallaxes veto"] == 1


class TestCrossedGroupOrder:
    """WDS 14565+5923 ABCD: AC holds A and C, and B is measured from A.
    SIMBAD's pair HD 132422 holds A and B, so it crosses AC, and AC leaves the
    tree. The points of AC join ABCD in the WDS order. A stays the primary for
    each order of the keys."""

    def systems(self, a: int, b: int, c: int) -> Systems:
        w = "14565+5923"
        catalogue = wds_catalogue(
            {
                w: [
                    wds_pair("A", "B", 2.9, notes="N W", mag1=8.26, mag2=10.32),
                    wds_pair("A", "C", 999.9, notes="NVW", mag1=8.26, mag2=7.42),
                    wds_pair("C", "D", 9999.999, notes="NVW", mag1=7.42, mag2=10.11),
                ]
            },
            {
                (w, "A"): wds_component(1),
                (w, "B"): wds_component(2),
                (w, "C"): wds_component(3, 226.073, 59.535),
            },
        )
        index = simbad_index(
            [
                simbad_object(10, "HD 132422", 224.123, 59.38, otype="**"),
                simbad_object(11, "HD 132422A", 224.123, 59.38, v=8.26, gaia="1"),
                simbad_object(12, "HD 132422B", 224.122, 59.379, v=10.32, gaia="2"),
            ],
            [(10, 11), (10, 12)],
        )
        resolver = FakeResolver(
            {
                ("gaia", "dr3", "1"): a,
                ("gaia", "dr3", "2"): b,
                ("gaia", "dr3", "3"): c,
                ("simbad", "oid", "11"): a,
                ("simbad", "oid", "12"): b,
            },
            [
                fact(key, ra, dec, mag, parallax=parallax, pmra=pmra, pmdec=pmdec)
                for key, ra, dec, mag, parallax, pmra, pmdec in (
                    (a, 224.123, 59.38, 8.15, 9.18, -13.06, -1.44),
                    (b, 224.123, 59.38 - 2.9 / 3600, 10.1, 9.18, -13.06, -1.44),
                    (c, 226.073, 59.535, 7.38, 9.09, -13.71, -0.12),
                )
            ],
        )
        inputs = Inputs(
            simbad=read_simbad(index.stars), simbad_index=index, wds=catalogue
        )
        return build(inputs, resolver)

    def test_a_is_the_primary(self):
        for a, b, c in ((19713758, 19713757, 19713532), (19713532, 19713533, 19713758)):
            systems = self.systems(a, b, c)
            assert shape(systems, c) == (
                "multiple star",
                4,
                [c, ("binary star", 2, sorted([a, b])), "entry"],
            )
            root = systems.nodes.filter(pc.equal(systems.nodes["label"], "ABCD"))
            assert root["primary"].to_pylist() == [a]
            members = systems.members.filter(
                pc.equal(systems.members["node"], root["node"][0])
            )
            assert members["kind"].to_pylist() == ["system", "star", "entry"]
            assert members["key"].to_pylist()[1] == c


class TestOneWrongId:
    """One id of an MSC component reaches a wrong star through SIMBAD. Far
    from its WDS id it is no candidate. Near it, the star that more of the ids
    reach wins. Each holds for each order of the keys."""

    def systems(
        self, comp: dict, objects: list, ids: dict, rows: list[dict]
    ) -> Systems:
        w = comp["WDS"]
        inputs = Inputs(
            msc=msc_nodes(
                [comp, msc_comp(w, "B")],
                [msc_pair(w, "A", "B", "*", Sep=22.0, Sunit='"')],
                [],
            ),
            simbad_index=simbad_index(objects),
        )
        return build(inputs, FakeResolver(ids, rows))

    def events(self, systems: Systems, kind: str = ID_OFF) -> list[str]:
        events = systems.events.filter(pc.equal(systems.events["kind"], kind))
        return events["text"].to_pylist()

    def test_59_aur(self):
        """MSC gives 59 Aur the GCVS name of QX Aur, a Mira 9° away."""
        w = "06530+3852"
        comp = msc_comp(
            w, "A", HIP=33041, HD=50018, Id="ADS_5534A. HR_2539, 59_Aur, V*_QX_Aur"
        )
        objects = [
            simbad_object(
                918209,
                "* 59 Aur",
                103.256,
                38.869,
                v=6.14,
                hip="33041",
                hd="50018",
                identifiers=("HR 2539",),
            ),
            simbad_object(
                397430,
                "V* QX Aur",
                104.288,
                47.589,
                otype="Mi*",
                identifiers=("V* QX Aur",),
            ),
        ]
        for right, wrong in ((18494922, 18557114), (18557114, 18494922)):
            ids = {
                ("hip", "2007", "33041"): right,
                ("hd", "1949", "50018"): right,
                ("simbad", "oid", "918209"): right,
                ("simbad", "oid", "397430"): wrong,
            }
            rows = [
                fact(right, 103.256, 38.869, 6.0),
                fact(wrong, 104.288, 47.589, 9.0),
            ]
            systems = self.systems(comp, objects, ids, rows)
            assert shape(systems, right) == ("binary star", 2, [right, "entry"])
            assert self.events(systems) == [f"{w} A: {wrong} is 31517″ off"]
            assert not self.events(systems, "ids reach two objects")

    def test_a_wrong_star_near_the_id(self):
        """59 Aur with QX Aur moved 1′ off, too near for the guard."""
        w = "06530+3852"
        comp = msc_comp(
            w, "A", HIP=33041, HD=50018, Id="ADS_5534A. HR_2539, 59_Aur, V*_QX_Aur"
        )
        place = (103.256 + 1 / 60, 38.869)
        objects = [
            simbad_object(
                918209,
                "* 59 Aur",
                103.256,
                38.869,
                v=6.14,
                hip="33041",
                hd="50018",
                identifiers=("HR 2539",),
            ),
            simbad_object(
                397430,
                "V* QX Aur",
                *place,
                otype="Mi*",
                identifiers=("V* QX Aur",),
            ),
        ]
        for right, wrong in ((18494922, 18557114), (18557114, 18494922)):
            ids = {
                ("hip", "2007", "33041"): right,
                ("hd", "1949", "50018"): right,
                ("simbad", "oid", "918209"): right,
                ("simbad", "oid", "397430"): wrong,
            }
            rows = [fact(right, 103.256, 38.869, 6.0), fact(wrong, *place, 9.0)]
            systems = self.systems(comp, objects, ids, rows)
            assert shape(systems, right) == ("binary star", 2, [right, "entry"])
            assert self.events(systems, "ids reach two objects") == [
                f"msc {w} A: {right} (by SIMBAD, 3 ids) over {wrong} (by SIMBAD, 1 id)"
            ]

    def test_37_com(self):
        """MSC gives 37 Com HIP 62462, which is G 149-9, 4° away."""
        w = "13003+3047"
        comp = msc_comp(
            w,
            "A",
            HIP=62462,
            HD=112989,
            Id="BD+31_2434, ADS_8731, HR_4924, *37_Com, LU_Com",
        )
        objects = [
            simbad_object(
                1,
                "* 37 Com",
                195.069,
                30.785,
                v=4.9,
                hip="63462",
                hd="112989",
                identifiers=("HR 4924",),
            ),
            simbad_object(2, "G 149-9", 192.010, 27.762, v=12.0, hip="62462"),
        ]
        for right, wrong in ((19441586, 23983862), (23983862, 19441586)):
            ids = {
                ("hip", "2007", "62462"): wrong,
                ("hd", "1949", "112989"): right,
                ("simbad", "oid", "1"): right,
                ("simbad", "oid", "2"): wrong,
            }
            rows = [
                fact(right, 195.069, 30.785, 4.7),
                fact(wrong, 192.01, 27.762, 11.8),
            ]
            systems = self.systems(comp, objects, ids, rows)
            assert shape(systems, right) == ("binary star", 2, [right, "entry"])
            assert self.events(systems) == [f"{w} A: {wrong} is 14522″ off"]
            assert not self.events(systems, "ids reach two objects")


class TestInnerSystemStays:
    """B holds Ba and Bb on one point. B is unverified and leaves AB, and its
    point keeps both stars (HD 104576 Aa, Ab)."""

    def test_the_point_keeps_its_stars(self):
        w = "12027-1043"
        resolver = FakeResolver(
            {("gaia", "dr3", "1"): 10, ("gaia", "dr3", "2"): 11},
            [
                fact(10, 180.7, -10.72, 7.0, parallax=10.0, pmra=20.0, pmdec=-5.0),
                fact(
                    11,
                    180.7,
                    -10.72 + 40 / 3600,
                    7.5,
                    parallax=10.0,
                    pmra=-40.0,
                    pmdec=30.0,
                ),
            ],
        )
        catalogue = wds_catalogue(
            {
                w: [
                    wds_pair("A", "B", 40.0, notes="N", mag1=7.0, mag2=7.5),
                    wds_pair("Ba", "Bb", 0.1, notes="O", mag1=7.6, mag2=8.5),
                ]
            },
            {(w, "A"): wds_component(1), (w, "Ba"): wds_component(2)},
        )
        systems = build(Inputs(wds=catalogue), resolver)
        assert shape(systems, 11) == ("point", 11, 2)
        assert systems.counts[f"{WDS}: inner systems of members that left"] == 1
        assert systems.counts[f"{WDS}: {UNVERIFIED} members left for agreement"] == 1


class TestUnverifiedInterior:
    """WDS B is unverified and inside the point of A at 0.1″. An orbit or a
    close type of that point is better evidence, and its interior wins."""

    w = "06451-1643"

    def inputs(self, otype: str | None, orbit: bool) -> tuple[Inputs, FakeResolver]:
        resolver = FakeResolver(
            {("gaia", "dr3", "1"): 80, ("simbad", "oid", "40"): 80},
            [fact(80, 101.287, -16.716, 7.0, parallax=10.0)],
        )
        catalogue = wds_catalogue(
            {self.w: [wds_pair("A", "B", 0.1, notes="N", mag1=7.0, mag2=8.0)]},
            {(self.w, "A"): wds_component(1)},
        )
        index = None
        if otype:
            index = simbad_index(
                [simbad_object(40, "HD 1", 101.287, -16.716, otype=otype, v=7.0)]
            )
        orbits = None
        if orbit:
            orbits = orbit_pairs(
                pa.table(
                    {
                        "key": [80],
                        "nss_solution_type": ["SB1"],
                        "period": [10.0],
                        "eccentricity": [0.0],
                        "m1": [1.0],
                        "m2": [0.5],
                    }
                )
            )
        return Inputs(wds=catalogue, simbad_index=index, orbits=orbits), resolver

    def point(self, otype: str | None, orbit: bool) -> tuple[Systems, list[tuple]]:
        systems = build(*self.inputs(otype, orbit))
        points = systems.nodes.filter(systems.nodes["point"]).to_pylist()
        return systems, [(p["key"], p["stars"], p["evidence"]) for p in points]

    def test_the_wds_interior_alone(self):
        assert self.point(None, False)[1] == [(80, 2, WDS)]

    def test_a_gaia_orbit_wins(self):
        systems, points = self.point(None, True)
        assert points == [(80, 2, GAIA_ORBITS)]
        name = f"{WDS}: interiors of unverified members that give way"
        assert systems.counts[name] == 1

    def test_the_orbit_of_a_planet_reaches_no_pair(self):
        """The Gaia orbit is that of a listed planet: the WDS interior holds
        the pair, and the orbit is not the pair's."""
        inputs, resolver = self.inputs(None, True)
        planet = {"host": 80, "number": 1, "designation": "HD 1 b", "period": 10.2}
        systems = build(replace(inputs, planets=planets([planet])), resolver)
        points = systems.nodes.filter(systems.nodes["point"]).to_pylist()
        assert [(p["key"], p["evidence"]) for p in points] == [(80, WDS)]
        assert systems.orbit_keys.tolist() == [0]
        orbit = KEPLER_16_GAIA | {"nss_solution_type": "SB1", "period": 10.0}
        elements = pa.Table.from_pylist([orbit])
        found = draw(systems, replace(inputs, orbit_elements=elements), resolver)
        assert f"{GAIA_ORBITS}: orbits on a pair" not in found.counts

    def test_a_close_type_wins(self):
        systems, points = self.point("EB*", False)
        assert points == [(80, 2, SIMBAD_TYPE)]
        name = f"{WDS}: interiors of unverified members that give way"
        assert systems.counts[name] == 1

    def test_a_circumbinary_planet_wins(self):
        inputs, resolver = self.inputs(None, False)
        host = {"host": 80, "number": 1, "designation": "X b", "binary_type": "P-type"}
        systems = build(replace(inputs, planets=planets([host])), resolver)
        points = systems.nodes.filter(systems.nodes["point"]).to_pylist()
        assert [(p["key"], p["stars"], p["evidence"]) for p in points] == [
            (80, 2, PLANETS)
        ]


class TestRegistryInputs:
    def test_no_gaia_orbits(self, tmp_path):
        orbits, elements = registry_orbits(Registry(tmp_path))
        assert orbits.num_rows == 0 and orbits.schema == PAIRS
        assert elements.num_rows == 0


class TestComponentOnItsPairsPoint:
    """A WDS component never takes the object of another node of its WDS
    system. η CrB: Gaia sees A and B as one point, A's Gaia id reaches it, and
    B's position lands on it too."""

    W = "15232+3017"

    def build(self, separation: float, mag: float) -> tuple[Systems, FakeResolver]:
        resolver = FakeResolver(
            {("gaia", "dr3", "1"): 130},
            [fact(130, 230.8, 30.29, mag, parallax=56.0)],
            positions={f"{self.W} B": 130},
        )
        ra, dec = offset(230.8, 30.29, separation, 0.0)
        catalogue = wds_catalogue(
            {self.W: [wds_pair("A", "B", separation, mag1=5.6, mag2=5.9)]},
            {
                (self.W, "A"): wds_component(1, 230.8, 30.29),
                (self.W, "B"): wds_component(None, ra, dec),
            },
        )
        return build(Inputs(wds=catalogue), resolver), resolver

    def test_the_point_holds_the_pair(self):
        systems, resolver = self.build(0.3, 5.0)
        assert resolver.matched == [f"{self.W} B"]
        assert resolver.excluded == [[130]]
        assert shape(systems, 130) == ("point", 130, 2)
        assert systems.counts[f"{WDS}: members by position"] == 0
        assert systems.counts[f"{WDS}: members with no object"] == 1

    def test_the_point_keeps_the_letter_of_its_own_id(self):
        """Gaia should split A and B. B's magnitude is nearer the point's, so
        B took the point when its position reached it."""
        systems, _ = self.build(1.1, 5.95)
        assert shape(systems, 130) == ("binary star", 2, [130, "entry"])
        letters = {
            (m["kind"], m["key"]): m["letter"] for m in systems.members.to_pylist()
        }
        assert letters == {("star", 130): "A", ("entry", 0): "B"}
        assert "cross-match error" not in systems.events["kind"].to_pylist()

    def test_a_far_component_keeps_its_match(self):
        """WDS 15591+5148: A has no Gaia id, and the Gaia id of B, 79″ away,
        names the star at A's position. A still matches it."""
        w = "15591+5148"
        b = offset(239.77, 51.80, 79.2, 270.0)
        resolver = FakeResolver(
            {("gaia", "dr3", "2"): 140},
            [fact(140, 239.77, 51.80, 14.2, parallax=60.0)],
            positions={f"{w} A": 140},
        )
        catalogue = wds_catalogue(
            {w: [wds_pair("A", "B", 79.2, notes="V", mag1=14.6, mag2=14.9)]},
            {
                (w, "A"): wds_component(None, 239.77, 51.80),
                (w, "B"): wds_component(2, *b),
            },
        )
        systems = build(Inputs(wds=catalogue), resolver)
        assert resolver.excluded == [None]
        letters = {
            (m["kind"], m["key"]): m["letter"] for m in systems.members.to_pylist()
        }
        assert letters == {("star", 140): "A", ("entry", 0): "B"}


class TestOneStarOfTwoSources:
    """The WDS puts B inside the point of A, and the MSC puts it beside the
    point. Both give it the WDS component id 03513+2621 B, so the system
    lists it once."""

    W = "03513+2621"

    def systems(self, letter: str = "B", with_c: bool = True) -> Systems:
        w = self.W
        c = offset(57.8, 26.35, 30.0, 45.0)
        resolver = FakeResolver(
            {
                ("hip", "2007", "1"): 700,
                ("gaia", "dr3", "11"): 700,
                ("hip", "2007", "2"): 701,
            },
            [
                fact(700, 57.8, 26.35, 9.0, parallax=10.0),
                fact(701, *c, 10.0, parallax=10.0),
            ],
        )
        comp = [msc_comp(w, "A", HIP=1), msc_comp(w, letter, Vmag=11.0)]
        pairs = [msc_pair(w, "A", letter, "*", Type="V", Sep=1.0, Sunit='"')]
        if with_c:
            comp.append(msc_comp(w, "C", HIP=2))
            pairs = [
                msc_pair(w, "AB", "C", "*", Sep=30.0, Sunit='"'),
                msc_pair(w, "A", letter, "AB", Type="V", Sep=1.0, Sunit='"'),
            ]
        catalogue = wds_catalogue(
            {w: [wds_pair("A", "B", 0.25, notes="V", mag1=9.0, mag2=11.0)]},
            {(w, "A"): wds_component(11, 57.8, 26.35)},
        )
        inputs = Inputs(msc=msc_nodes(comp, pairs, []), wds=catalogue)
        return build(inputs, resolver)

    def test_the_entry_beside_the_point_leaves(self):
        systems = self.systems()
        assert shape(systems, 701) == ("multiple star", 3, [701, ("point", 700, 2)])
        assert systems.counts["entries that a point of the system holds"] == 1
        events = systems.events.filter(
            pc.equal(systems.events["kind"], "entry is in a point")
        )
        assert events["text"].to_pylist() == [f"msc {self.W} B is in 700"]

    def test_a_root_left_with_one_point_is_that_point(self):
        systems = self.systems(with_c=False)
        assert shape(systems, 700) == ("point", 700, 2)
        assert systems.counts["systems that are one point once entries leave"] == 1

    def test_another_letter_is_another_star(self):
        systems = self.systems("D")
        assert shape(systems, 701) == (
            "multiple star",
            4,
            [701, ("multiple star", 3, [("point", 700, 2), "entry"])],
        )
        assert "entries that a point of the system holds" not in systems.counts


class TestOneMemberNode:
    """A node that holds one member is that member, with all its fields. No
    tree gives a node one entry and no point, so `_known_entries` leaves
    only the entry here."""

    def test_the_member_keeps_its_inner_label(self, monkeypatch):
        assembler = object.__new__(Assembler)
        prepared = SimpleNamespace(origin=np.array([0, 1]))
        monkeypatch.setattr(assembler, "p", prepared, raising=False)
        assembler.groups = [
            Group(
                MSC,
                0,
                "1",
                0,
                frozenset({7, 8}),
                [Member(POINT, key=8, value=1), Member(GROUP, group=1, value=2)],
            ),
            Group(
                MSC,
                0,
                "1",
                2,
                frozenset({7}),
                [Member(POINT, key=7, value=3), Member(ENTRY, value=4, inner="Ca")],
            ),
        ]
        child = _Node(frozenset({7}), [1])
        root = _Node(frozenset({7, 8}), [0], children=[child])
        child.parent = root

        def entries_only(node: _Node, members: list, listed: dict) -> list:
            return [m for m in members if m[0] == ENTRY] if node is child else members

        monkeypatch.setattr(assembler, "_known_entries", entries_only)
        assembler._order(root, {})
        assert (ENTRY, 0, None, 4, "Ca") in root.members


class TestEntryIsAPoint:
    """An entry and a point of one system at the same separation from the
    same primary are one star: the entry leaves."""

    def test_a_wds_entry_is_a_simbad_point(self):
        """NAME Oph 11: WDS B finds no object, because its V is 2 mag fainter
        than the G of SIMBAD's B. The position angles agree."""
        w = "16224-2405"
        b = offset(245.6, -24.08, 1.95, 178.0)
        index = simbad_index(
            [
                simbad_object(1, "NAME Oph 11", 245.6, -24.08, otype="**"),
                simbad_object(2, "NAME Oph 11A", 245.6, -24.08, v=21.1),
                simbad_object(3, "NAME Oph 11B", *b, v=22.0),
            ],
            [(1, 2), (1, 3)],
        )
        resolver = FakeResolver(
            {
                ("simbad", "oid", "2"): 200,
                ("simbad", "oid", "3"): 201,
                ("gaia", "dr3", "11"): 200,
            },
            [fact(200, 245.6, -24.08, 20.0), fact(201, *b, 20.24)],
        )
        pair = wds_pair(
            "A", "B", 1.9, notes="V", mag1=21.1, mag2=22.3, position_angle=178.0
        )
        catalogue = wds_catalogue(
            {w: [pair]}, {(w, "A"): wds_component(11, 245.6, -24.08)}
        )
        inputs = Inputs(
            simbad=read_simbad(index.stars), simbad_index=index, wds=catalogue
        )
        systems = build(inputs, resolver)
        assert shape(systems, 200) == ("binary star", 2, [200, 201])
        assert systems.counts["entries that are a point of the system"] == 1

    def interior(
        self,
        b: tuple[float, float],
        position_angle: float,
        mag: float = 13.52,
        inner: bool = True,
        orbits: pa.Table | None = None,
    ) -> Systems:
        """HD 141176: the MSC puts B inside the point of A, with Aa and Ab when
        `inner`, and El-Badry pairs A with a star at `b`."""
        w = "15468+2505"
        comp = [msc_comp(w, "A", HIP=1), msc_comp(w, "B", Vmag=13.77)]
        pairs = [msc_pair(w, "A", "B", "*", Sep=1.707, Sunit='"', PA=position_angle)]
        if inner:
            pairs.append(
                msc_pair(w, "Aa", "Ab", "A", Sep=0.738, Sunit="m", P=3, Punit="d")
            )
        resolver = FakeResolver(
            {
                ("hip", "2007", "1"): 300,
                ("gaia", "dr3", "21"): 300,
                ("gaia", "dr3", "22"): 301,
            },
            [
                fact(300, 236.7, 25.08, 8.24, parallax=20.0),
                fact(301, *b, mag, parallax=20.0),
            ],
        )
        inputs = Inputs(
            msc=msc_nodes(comp, pairs, []),
            el_badry=el_badry([(21, 22, 1.707, 8.24, mag)]),
            orbits=orbits,
        )
        return build(inputs, resolver)

    def test_an_entry_inside_a_point(self):
        systems = self.interior(offset(236.7, 25.08, 1.707, 256.5), 256.5)
        assert shape(systems, 301) == ("multiple star", 3, [301, ("point", 300, 2)])
        assert systems.counts["entries that are a point of the system"] == 1

    def test_a_close_triple_keeps_its_third_star(self):
        """The El-Badry star is at the separation of B, at another angle, and
        0.8 mag fainter. Gaia gives both positions, so the angle decides."""
        systems = self.interior(offset(236.7, 25.08, 1.707, 140.0), 256.5, 14.6)
        assert shape(systems, 301) == ("multiple star", 4, [301, ("point", 300, 3)])
        assert "entries that are a point of the system" not in systems.counts

    def test_the_point_takes_its_next_interior(self):
        """The MSC gives point 300 the stars A and B, and B is the El-Badry
        star. So the point takes its Gaia orbit."""
        orbits = orbit_pairs(
            pa.table(
                {
                    "key": [300],
                    "nss_solution_type": ["SB1"],
                    "period": [10.0],
                    "eccentricity": [0.1],
                    "m1": [1.0],
                    "m2": [0.5],
                }
            )
        )
        b = offset(236.7, 25.08, 1.707, 256.5)
        systems = self.interior(b, 256.5, inner=False, orbits=orbits)
        assert shape(systems, 301) == ("multiple star", 3, [301, ("point", 300, 2)])
        point = systems.nodes.filter(pc.equal(systems.nodes["key"], 300))
        assert point["evidence"].to_pylist() == [GAIA_ORBITS]
        assert systems.counts["interiors of one star once an entry leaves"] == 1

    def test_a_component_of_the_same_catalogue_is_another_star(self):
        """The WDS lists B, which finds no object, and C, a point at the same
        place."""
        w = "06000+3000"
        c = offset(90.0, 30.0, 2.05, 92.0)
        resolver = FakeResolver(
            {("gaia", "dr3", "1"): 600, ("gaia", "dr3", "2"): 601},
            [
                fact(600, 90.0, 30.0, 9.0, parallax=10.0),
                fact(601, *c, 11.0, parallax=10.0),
            ],
        )
        catalogue = wds_catalogue(
            {
                w: [
                    wds_pair(
                        "A",
                        "B",
                        2.0,
                        notes="V",
                        mag1=9.0,
                        mag2=11.0,
                        position_angle=90.0,
                    ),
                    wds_pair(
                        "A",
                        "C",
                        2.05,
                        notes="V",
                        mag1=9.0,
                        mag2=11.0,
                        position_angle=92.0,
                    ),
                ]
            },
            {(w, "A"): wds_component(1, 90.0, 30.0), (w, "C"): wds_component(2, *c)},
        )
        systems = build(Inputs(wds=catalogue), resolver)
        assert shape(systems, 600) == ("multiple star", 3, [600, 601, "entry"])

    def test_a_pair_the_wrong_way_round(self):
        """The WDS gives A the Gaia id of SIMBAD's B, so its B, inside that
        point, is at the opposite angle of SIMBAD's A. The point then holds
        one star."""
        w = "01345+3440"
        a = offset(23.6, 34.67, 0.412, 123.0)
        index = simbad_index(
            [
                simbad_object(1, "BD+33 257", 23.6, 34.67, otype="**"),
                simbad_object(2, "BD+33 257A", *a, v=10.2),
                simbad_object(3, "BD+33 257B", 23.6, 34.67, v=10.4),
            ],
            [(1, 2), (1, 3)],
        )
        resolver = FakeResolver(
            {
                ("simbad", "oid", "2"): 701,
                ("simbad", "oid", "3"): 700,
                ("gaia", "dr3", "41"): 700,
            },
            [fact(700, 23.6, 34.67, 10.24), fact(701, *a, 10.11)],
        )
        pair = wds_pair(
            "A", "B", 0.4, notes="NO", mag1=10.46, mag2=10.68, position_angle=300.0
        )
        catalogue = wds_catalogue(
            {w: [pair]}, {(w, "A"): wds_component(41, 23.6, 34.67)}
        )
        inputs = Inputs(
            simbad=read_simbad(index.stars), simbad_index=index, wds=catalogue
        )
        systems = build(inputs, resolver)
        assert shape(systems, 700) == ("binary star", 2, [700, 701])
        assert systems.counts["interiors of one star once an entry leaves"] == 1
        assert systems.counts[f"points holding several stars, by {WDS}"] == 0

    def orbiting(
        self,
        others: dict[int, tuple[float, float]],
        separation: float = 4.3,
        apart: float = 4.3,
    ) -> Systems:
        """WDS B finds no object. Its last measure is at `separation` and 200°,
        and the MSC lists A and the stars `others` (key → J2016 angle, G) at
        `apart`."""
        w = "08000+1000"
        points = {
            k: offset(120.0, 10.0, apart, angle) for k, (angle, _) in others.items()
        }
        resolver = FakeResolver(
            {("hip", "2007", "1"): 900} | {("hd", "1949", str(k)): k for k in others},
            [fact(900, 120.0, 10.0, 8.0, parallax=50.0)]
            + [fact(k, *points[k], g, parallax=50.0) for k, (_, g) in others.items()],
            positions={f"{w} A": 900},
        )
        pair = wds_pair(
            "A", "B", separation, notes="NO", mag1=8.0, mag2=10.7, position_angle=200.0
        )
        catalogue = wds_catalogue(
            {w: [pair]}, {(w, "A"): wds_component(None, 120.0, 10.0)}
        )
        letters = dict(zip(others, "CD"))
        comp = [msc_comp(w, "A", HIP=1)]
        comp += [msc_comp(w, letters[k], HD=k) for k in others]
        pairs = [msc_pair(w, "A", letters[k], "*") for k in others]
        return build(Inputs(msc=msc_nodes(comp, pairs, []), wds=catalogue), resolver)

    def test_an_orbit_turns_the_angle(self):
        """Gaia sees B at 108°: the pair turned since the WDS measure. B is the
        only point at that separation, and the magnitudes agree."""
        systems = self.orbiting({901: (108.0, 10.7)})
        assert shape(systems, 900) == ("binary star", 2, [900, 901])
        assert systems.counts["entries that are a point of the system"] == 1

    def test_the_slack_scales_with_the_separation(self):
        """22248+2233 B: the WDS gives 1.315″, and Gaia sees it at 2.438″."""
        systems = self.orbiting({901: (108.0, 10.7)}, 1.315, 2.438)
        assert systems.counts["entries that are a point of the system"] == 1

    def test_a_close_pair_is_no_wide_point(self):
        """V1018 Cas Ab is 0.00005″ from Aa. A star 1.6″ away is another star."""
        systems = self.orbiting({901: (108.0, 10.7)}, 0.00005, 1.64)
        assert "entries that are a point of the system" not in systems.counts

    def test_two_points_at_the_separation(self):
        """Two Gaia points at B's separation, at other angles: the angle stays
        the guard, so B stays an entry."""
        systems = self.orbiting({901: (108.0, 10.7), 902: (300.0, 10.8)})
        assert shape(systems, 900)[:2] == ("multiple star", 4)
        assert "entries that are a point of the system" not in systems.counts

    def test_the_best_point_wins(self):
        """WDS B is at 2″ and 90°. SIMBAD's C is at 2″ and 270°, which the
        angle turned by 180° also fits. B's own point at 90° fits better."""
        w = "09000+2000"
        b, c = offset(135.0, 20.0, 2.0, 90.0), offset(135.0, 20.0, 2.0, 270.0)
        resolver = FakeResolver(
            {
                ("hip", "2007", "1"): 800,
                ("hd", "1949", "2"): 801,
                ("hd", "1949", "3"): 802,
            },
            [
                fact(800, 135.0, 20.0, 9.0, parallax=10.0),
                fact(801, *c, 11.0, "simbad"),
                fact(802, *b, 11.0, parallax=10.0),
            ],
            positions={f"{w} A": 800},
        )
        pair = wds_pair(
            "A", "B", 2.0, notes="NO", mag1=9.0, mag2=11.0, position_angle=90.0
        )
        catalogue = wds_catalogue(
            {w: [pair]}, {(w, "A"): wds_component(None, 135.0, 20.0)}
        )
        comp = [msc_comp(w, "A", HIP=1), msc_comp(w, "C", HD=2), msc_comp(w, "D", HD=3)]
        pairs = [msc_pair(w, "A", "C", "*"), msc_pair(w, "A", "D", "*")]
        systems = build(Inputs(msc=msc_nodes(comp, pairs, []), wds=catalogue), resolver)
        assert shape(systems, 800)[:2] == ("multiple star", 3)
        texts = systems.events.filter(
            pc.equal(systems.events["kind"], "entry is a point")
        )
        assert [t.split(" is ")[-1] for t in texts["text"].to_pylist()] == ["802"]


class TestDryRunHosts:
    """The dry run reads a planet's host as the ingest does: a point."""

    def test_a_held_star_stands_for_its_point(self) -> None:
        held, point = encode(7, SYSTEM_TABLE, 42), encode(7, 1, 42)
        other_held = encode(8, SYSTEM_TABLE, 42)
        system = pa.table(
            {
                "id": pa.array([held, other_held], pa.int64()),
                "parent": pa.array([point, None], pa.int64()),
                "star": pa.array([{"radius": 1.0}, None], SYSTEM_STAR),
            }
        )
        registry = MagicMock(read_table=lambda *_: system)
        hosts = np.array([held, point, other_held], np.int64)
        found = _point_hosts(registry, hosts)
        assert found.tolist() == [point, point, other_held]
