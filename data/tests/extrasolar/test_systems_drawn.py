"""The pairs that the orbit sources reach, the orbits that they draw, and the
stars that the nodes hold."""

from collections import Counter

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pytest

from space_map_data.extrasolar import frame
from space_map_data.extrasolar.exoplanets.catalogues import OEC
from space_map_data.extrasolar.exoplanets.table import default_node
from space_map_data.extrasolar.systems import assemble, drawn, elements, orbits
from space_map_data.extrasolar.systems.assemble import Systems
from space_map_data.extrasolar.systems.nodes import GAIA_ORBITS
from space_map_data.extrasolar.systems.prepare import Inputs
from tests.extrasolar.systems_fakes import (
    ALPHA_CEN_DISTANCE,
    KEPLER_16,
    KEPLER_16_GAIA,
    FakeResolver,
    catalogue_orbits,
)


def _systems(
    nodes: list[dict], members: list[dict], orbit_keys: tuple[int, ...] = ()
) -> Systems:
    empty = [
        schema.empty_table()
        for schema in (
            assemble.POINTS,
            assemble.ABSORBED,
            assemble.DISTANCES,
            assemble.HOSTS,
            assemble.OVERLAPS,
            assemble.NAMES,
            assemble.EVENTS,
        )
    ]
    return Systems(
        pa.Table.from_pylist(nodes, schema=assemble.NODES),
        pa.Table.from_pylist(members, schema=assemble.MEMBERS),
        *empty,
        Counter(),
        np.array(orbit_keys, np.int64),
    )


def _ids(*items: tuple[str, str, str]) -> list[dict]:
    return [dict(zip(("catalogue", "release", "catalogue_id"), i)) for i in items]


def alpha_cen(first: str = "A", second: str = "B") -> Systems:
    """α Cen AB: a resolved pair of two points, members in this order."""
    keys = {"A": 11, "B": 12}
    return _systems(
        [
            {
                "node": 1,
                "key": 0,
                "ra": 219.87,
                "dec": -60.83,
                "distance": ALPHA_CEN_DISTANCE,
                "root": 1,
                "depth": 0,
            }
        ],
        [
            {
                "node": 1,
                "kind": assemble.STAR,
                "key": keys[letter],
                "letter": letter,
                "label": letter,
                "source": "msc",
                "ids": _ids(("msc", "id", f"14396-6050 {letter}")),
            }
            for letter in (first, second)
        ],
    )


def kepler_16() -> Systems:
    """Kepler-16: a point that holds both stars, with its Gaia orbit."""
    return _systems(
        [
            {
                "node": 1,
                "key": 20,
                "point": True,
                "ra": 289.076,
                "dec": 51.757,
                "distance": 75.3,
                "root": 1,
                "depth": 0,
            }
        ],
        [
            {
                "node": 1,
                "kind": assemble.ENTRY,
                "letter": label,
                "label": label,
                "source": "planet-catalogues",
                "mass": mass,
                "ids": _ids((OEC, "systems", f"{label} {suffix}".strip())),
            }
            for label, suffix, mass in (
                ("Kepler-16", "A", 0.69),
                ("Kepler-16 B", "", 0.2025),
            )
        ],
        orbit_keys=(20,),
    )


@pytest.fixture
def alpha_cen_orbits(tmp_path) -> pa.Table:
    return catalogue_orbits(tmp_path)


class TestPairs:
    """The orbit that each pair draws."""

    def test_alpha_cen(self, alpha_cen_orbits):
        found = drawn.draw(
            alpha_cen(), Inputs(catalogue_orbits=alpha_cen_orbits), FakeResolver({}, [])
        )
        (row,) = found.orbits.to_pylist()
        assert row["period_source"] == row["node_source"] == "msc"
        assert row["semi_major_axis"] == pytest.approx(17.66 * ALPHA_CEN_DISTANCE)
        assert row["semi_major_axis_arcsec"] == 17.66
        assert (row["node"], row["arg_periastron"]) == (204.75, 232.30)
        # The spectroscopic ω agrees, so the listed node is the ascending one.
        assert row["node_ascending"]
        assert found.counts["nodes kept by an orbit with a fixed ω"] == 1
        assert row["barycentre"] == pytest.approx(4.61 / (4.61 + 5.45))
        assert row["mass_ratio_source"] == "msc"
        assert row["assumed"] == [] and row["phase"] == elements.PERIASTRON
        assert {"source": "msc", "reference": "VB6_Pbx2016 RHD_1AB Gr.2"} in row[
            "references"
        ]

    def test_a_pair_by_its_letters(self, alpha_cen_orbits):
        """Members with no WDS or MSC id, named "Rigil Kentaurus B" and
        "Alpha Centauri A": the node's WDS id and their letters find them."""
        systems = _systems(
            [
                {
                    "node": 1,
                    "key": 0,
                    "ra": 219.87,
                    "dec": -60.83,
                    "distance": ALPHA_CEN_DISTANCE,
                    "catalogue_ids": _ids(("wds", "id", "14396-6050")),
                }
            ],
            [
                {
                    "node": 1,
                    "kind": assemble.STAR,
                    "key": key,
                    "letter": label,
                    "label": label,
                    "source": "planet-catalogues",
                }
                for key, label in ((12, "Rigil Kentaurus B"), (11, "Alpha Centauri A"))
            ],
        )
        found = drawn.draw(
            systems, Inputs(catalogue_orbits=alpha_cen_orbits), FakeResolver({}, [])
        )
        (row,) = found.orbits.to_pylist()
        assert found.counts["msc: orbits on a pair by its letters"] == 3
        assert found.counts["orb6: orbits on a pair by its letters"] == 1
        # B is the first member, so the orbit is A's about B.
        assert row["arg_periastron"] == pytest.approx((232.30 + 180) % 360)

    def test_an_orb6_orbit_with_no_components(self, alpha_cen_orbits):
        """ORB6 gives no components for the only pair of a system: A and B."""
        orb6_rows = alpha_cen_orbits.filter(
            pc.equal(alpha_cen_orbits["source"], orbits.ORB6)
        ).to_pylist()
        row = next(r for r in orb6_rows if r["pair"] == "AB")
        row |= {"pair": None, "primary": None, "secondary": None}
        table = pa.Table.from_pylist([row], schema=orbits.ORBITS)
        found = drawn.draw(
            alpha_cen(), Inputs(catalogue_orbits=table), FakeResolver({}, [])
        )
        assert found.counts["orb6: orbits on a pair"] == 1
        assert found.orbits.num_rows == 1

    def test_members_in_the_other_order(self, alpha_cen_orbits):
        """B first: the orbit turns round, A about B."""
        found = drawn.draw(
            alpha_cen("B", "A"),
            Inputs(catalogue_orbits=alpha_cen_orbits),
            FakeResolver({}, []),
        )
        (row,) = found.orbits.to_pylist()
        assert row["arg_periastron"] == pytest.approx((232.30 + 180) % 360)
        assert row["barycentre"] == pytest.approx(5.45 / (4.61 + 5.45))

    def test_kepler_16(self):
        literature, stars = orbits.read_literature()
        elements_table = pa.Table.from_pylist([KEPLER_16_GAIA])
        found = drawn.draw(
            kepler_16(),
            Inputs(
                catalogue_orbits=literature,
                catalogue_stars=stars,
                orbit_elements=elements_table,
            ),
            FakeResolver({KEPLER_16: 20}, []),
        )
        (row,) = found.orbits.to_pylist()
        for name in ("period", "semi_major_axis", "eccentricity", "inclination"):
            assert row[f"{name}_source"] == orbits.LITERATURE
        # No paper gives a node: Kepler-16 takes its Gaia orbit's.
        assert row["node_source"] == GAIA_ORBITS and row["node_ascending"]
        assert row["node"] == pytest.approx(8.2, abs=0.1)
        assert row["mass_ratio_source"] == orbits.LITERATURE
        assert row["barycentre"] == pytest.approx(0.20255 / (0.6897 + 0.20255))
        assert row["references"][0] == {
            "source": orbits.LITERATURE,
            "reference": "doyle_2011",
        }
        a, b = found.held.to_pylist()
        assert (a["letter"], b["letter"]) == ("A", "B")
        assert (a["mass"], a["radius"], a["teff"]) == pytest.approx(
            (0.6897, 0.6489, 4450)
        )
        assert a["mass_source"] == a["radius_source"] == orbits.LITERATURE
        assert b["teff"] is None and b["radius"] == pytest.approx(0.22623)
        assert a["references"] == [
            {"source": orbits.LITERATURE, "reference": "doyle_2011"}
        ]

    def test_a_pair_with_no_node_takes_the_planets_node(self, alpha_cen_orbits):
        literature, stars = orbits.read_literature()
        found = drawn.draw(
            kepler_16(),
            Inputs(catalogue_orbits=literature, catalogue_stars=stars),
            FakeResolver({KEPLER_16: 20}, []),
        )
        (row,) = found.orbits.to_pylist()
        assert row["node"] is None and "node" in row["assumed"]
        assert found.counts["pairs drawn with an assumed node"] == 1
        root = 123
        node = drawn.assumed_node(root)
        assert node == default_node(root)
        scene = drawn.scene(row, node)
        assert scene["node"] == node and scene["centre"] == drawn.BARYCENTRE
        direction = frame.direction(row["ra"], row["dec"])
        expected = frame.ecliptic_angles(
            direction, row["inclination"], node, row["arg_periastron"]
        )
        assert (scene["i"], scene["om"], scene["w"]) == pytest.approx(expected)
        assert scene["n"] == pytest.approx(360 / row["period"])
        assert scene["periastron_time"] == pytest.approx(
            row["epoch"] - row["mean_anomaly"] * row["period"] / 360
        )

    def test_a_spectroscopic_orbit_is_not_drawn(self):
        orbit = KEPLER_16_GAIA | {"nss_solution_type": "SB1", "arg_periastron": 10.0}
        found = drawn.draw(
            kepler_16(),
            Inputs(orbit_elements=pa.Table.from_pylist([orbit])),
            FakeResolver({}, []),
        )
        assert found.orbits.num_rows == 0
        assert found.counts["pairs with orbits and no inclination"] == 1

    def test_no_mass_ratio_keeps_the_primary_at_the_centre(self):
        orbit = KEPLER_16_GAIA | {"m1": None, "m2": None}
        found = drawn.draw(
            kepler_16(),
            Inputs(orbit_elements=pa.Table.from_pylist([orbit])),
            FakeResolver({}, []),
        )
        # With no masses Gaia gives no a.
        assert found.orbits.num_rows == 0
        assert found.counts["pairs with orbits and no semi-major axis"] == 1


class TestHeldStars:
    """An entry with a value of its own is a held star."""

    def test_a_letter_or_a_value(self):
        systems = _systems(
            [{"node": 1, "key": 30, "point": True, "ra": 1.0, "dec": 2.0}],
            [
                {"node": 1, "kind": assemble.ENTRY, "source": "gaia-dr3-orbits"},
                {
                    "node": 1,
                    "kind": assemble.ENTRY,
                    "source": "gaia-dr3-orbits",
                    "mass": 0.5,
                },
                {"node": 1, "kind": assemble.ENTRY, "letter": "B", "label": "B"},
                {"node": 1, "kind": assemble.ENTRY, "letter": "B", "label": "B"},
            ],
        )
        found = drawn.draw(systems, Inputs(), FakeResolver({}, []))
        held = found.held.to_pylist()
        assert [(h["member"], h["tag"], h["letter"]) for h in held] == [
            (1, "#2", None),
            (2, "B", "B"),
            (3, "B #4", "B"),
        ]
        assert held[0]["mass_source"] == "gaia-dr3-orbits"
        assert found.counts["entries with no value of their own"] == 1
