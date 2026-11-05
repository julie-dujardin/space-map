"""Tests for the kinds of a group object with a point of its own."""

import math
from collections import Counter

import pyarrow as pa

from space_map_data.extrasolar.systems import assemble
from space_map_data.extrasolar.systems.groups import (
    COMBINED,
    GROUP_LEAVES,
    GROUP_OBJECT,
    PRIMARY,
    group_kind,
)
from space_map_data.extrasolar.systems.nodes import NODES, SIMBAD
from space_map_data.extrasolar.systems.reduce import Reduced, TreeReducer
from space_map_data.extrasolar.systems.report import report_lines
from space_map_data.extrasolar.systems.resolve import FACTS, Facts
from tests.extrasolar.systems_fakes import fact

OWN, A, B = 100, 101, 102
FAR = 116 / 3600


def facts(*rows: dict) -> Facts:
    return Facts(pa.Table.from_pylist(list(rows), schema=FACTS))


def reduce_group(own: dict, a: dict, b: dict) -> Reduced:
    """SIMBAD's pair AB, whose own point is `own`, with the stars A and B."""
    base = dict.fromkeys(NODES.names)
    rows = [("AB", -1, None, None), ("A", 0, None, a["mag"]), ("B", 0, 0.6, b["mag"])]
    table = pa.Table.from_pylist(
        [
            base
            | {
                "source": SIMBAD,
                "system": "76600",
                "node": at,
                "label": label,
                "parent": parent,
                "separation": separation,
                "g_mag": mag,
            }
            for at, (label, parent, separation, mag) in enumerate(rows)
        ],
        schema=NODES,
    )
    out = Reduced()
    candidates = [[(OWN, 4)], [(A, 2)], [(B, 2)]]
    TreeReducer(table, 0, candidates, facts(own, a, b), 0, out).run()
    return out


def group_events(out: Reduced) -> list[tuple[str, str]]:
    return [
        (kind.removeprefix(f"{GROUP_OBJECT}: "), text)
        for kind, _, text in out.events
        if kind.startswith(GROUP_OBJECT)
    ]


class TestGroupKind:
    """The kind of the point of HIP 111293 beside BD+53 2911 A and B, and of
    other points beside their members."""

    a = fact(A, 10.0, 10.0 + FAR, 9.92, "gaia-dr3-named")
    b = fact(B, 10.0, 10.0 + FAR + 0.6 / 3600, 9.96, "gaia-dr3-named")

    def test_combined_light(self):
        """Hipparcos 1997 puts HIP 111293 116″ from the stars. Its light is
        theirs: 9.19 mag together."""
        own = fact(OWN, 10.0, 10.0, 9.22, "hipparcos-1997")
        ((kind, text),) = group_events(reduce_group(own, self.a, self.b))
        assert kind == COMBINED
        assert text == (
            f"{SIMBAD} 76600 AB: {OWN} is a point of its own beside [{A}, {B}];"
            " hipparcos-1997 9.22 mag, its members 9.19 mag together"
        )

    def test_a_brighter_point_is_the_primary(self):
        """The point holds more light than its members: it is a star of its own."""
        own = fact(OWN, 10.0, 10.0, 7.5, "hipparcos-2007", parallax=5.0)
        out = reduce_group(own, self.a, self.b)
        assert [kind for kind, _ in group_events(out)] == [PRIMARY]
        assert out.counts[f"{SIMBAD}: {GROUP_OBJECT}: {PRIMARY}"] == 1

    def test_a_gaia_point_is_the_primary(self):
        """A Gaia source is one star, even when its magnitude fits the members."""
        own = fact(OWN, 10.0, 10.0, 9.19, "gaia-dr3", parallax=5.0)
        assert [
            kind for kind, _ in group_events(reduce_group(own, self.a, self.b))
        ] == [PRIMARY]

    def test_background_members(self):
        """MSC 03494-4421 A at ϖ 11.1 mas beside two faint stars at 1.3 and 1.8.
        The veto takes B from its primary A first. The point and A are at two
        distances, so the point leaves."""
        own = fact(OWN, 10.0, 10.0, 8.92, parallax=11.13)
        a = fact(A, 10.0, 10.0 + 162 / 3600, 18.06, parallax=1.29)
        b = fact(B, 10.0, 10.0 + 165 / 3600, 19.37, parallax=1.76)
        out = reduce_group(own, a, b)
        assert [(kind, text) for kind, _, text in out.events] == [
            (
                "parallaxes disagree",
                (
                    f"{SIMBAD} 76600 B: 102 1.760 ± 0.018 mas, primary A 101 1.290"
                    " ± 0.013 mas, physical"
                ),
            ),
            (
                GROUP_LEAVES,
                (
                    f"{SIMBAD} 76600 AB: {OWN}; parallax 11.13 ± 0.11 mas,"
                    " 101 1.29 ± 0.01 mas"
                ),
            ),
        ]
        assert not out.groups

    def test_background_members_that_agree(self):
        """Two faint stars at one distance stay a pair, and the point leaves."""
        own = fact(OWN, 10.0, 10.0, 8.92, parallax=11.13)
        a = fact(A, 10.0, 10.0 + 162 / 3600, 18.06, parallax=1.29)
        b = fact(B, 10.0, 10.0 + 165 / 3600, 19.37, parallax=1.30)
        out = reduce_group(own, a, b)
        assert [group.keys for group in out.groups] == [frozenset({A, B})]
        assert [(kind, text) for kind, _, text in out.events] == [
            (
                GROUP_LEAVES,
                (
                    f"{SIMBAD} 76600 AB: {OWN}; parallax 11.13 ± 0.11 mas,"
                    " 101 1.29 ± 0.01 mas, 102 1.30 ± 0.01 mas"
                ),
            )
        ]

    def test_a_point_that_holds_each_member(self):
        """A and B are SIMBAD components inside the Gaia point of AB."""
        own = fact(OWN, 10.0, 10.0, 9.5, parallax=5.0)
        a = fact(A, 10.0, 10.0 + 0.1 / 3600, 10.0, "simbad")
        b = fact(B, 10.0, 10.0 - 0.1 / 3600, 10.5, "simbad")
        out = reduce_group(own, a, b)
        assert {(item.key, item.into) for item in out.absorbed} == {(A, OWN), (B, OWN)}
        ((kind, text),) = group_events(out)
        assert kind == PRIMARY
        assert text.endswith(
            f"beside [{A}, {B}]; the point holds the light of each member"
        )

    def test_parallaxes_within_their_errors_agree(self):
        own = fact(OWN, 10.0, 10.0, 8.87, parallax=5.56)
        a = fact(A, 10.0, 10.0 + 19.7 / 3600, 10.66, parallax=5.54)
        kind, evidence = group_kind(facts(own).get(OWN), [facts(a).get(A)])
        assert kind == PRIMARY
        assert evidence == "gaia-dr3 8.87 mag, its members 10.66 mag together"

    def test_a_member_with_no_magnitude(self):
        own = fact(OWN, 10.0, 10.0, 9.22, "hipparcos-1997")
        a = fact(A, 10.0, 10.0, math.nan, "simbad")
        assert group_kind(facts(own).get(OWN), [facts(a).get(A)]) == (
            PRIMARY,
            "a member has no magnitude",
        )

    def test_the_report_counts_each_kind(self):
        own = fact(OWN, 10.0, 10.0, 9.22, "hipparcos-1997")
        out = reduce_group(own, self.a, self.b)
        events = pa.Table.from_pylist(
            [{"kind": k, "source": s, "text": t} for k, s, t in out.events],
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
        systems = assemble.Systems(*empty, events, counts=Counter())
        lines = report_lines(systems)
        assert f"{GROUP_OBJECT}: 1 ({PRIMARY} 0, {COMBINED} 1)" in lines
        assert any(line.startswith(f"  {GROUP_OBJECT}: {COMBINED}: ") for line in lines)
