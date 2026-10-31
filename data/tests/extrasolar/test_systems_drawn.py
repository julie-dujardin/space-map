"""The pairs that the orbit sources reach, the orbits that they draw, and the
stars that the nodes hold."""

from collections import Counter
from collections.abc import Iterable
from types import SimpleNamespace
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pytest

from space_map_data.extrasolar import frame
from space_map_data.extrasolar.exoplanets.catalogues import OEC
from space_map_data.extrasolar.exoplanets.table import default_node
from space_map_data.extrasolar.systems import assemble, drawn, elements, orbits
from space_map_data.extrasolar.systems.assemble import Systems
from space_map_data.extrasolar.systems.ingest import (
    _held_rows,
    _node_names,
    held_names,
)
from space_map_data.extrasolar.systems.nodes import GAIA_ORBITS
from space_map_data.extrasolar.systems.prepare import LEAVES, MEMBER, Inputs
from space_map_data.extrasolar.tables import CROSS_ID
from tests.download.orbit_catalogue_files import MSC_LINES
from tests.extrasolar.systems_fakes import (
    ALPHA_CEN_DISTANCE,
    KEPLER_16,
    KEPLER_16_GAIA,
    FakeResolver,
    catalogue_orbits,
    msc_orbit_rows,
    msc_pair,
)


def _systems(
    nodes: list[dict],
    members: list[dict],
    orbit_keys: tuple[int, ...] = (),
    points: Iterable[dict] = (),
    names: Iterable[dict] = (),
) -> Systems:
    return Systems(
        pa.Table.from_pylist(
            [{"root": node["node"]} | node for node in nodes], schema=assemble.NODES
        ),
        pa.Table.from_pylist(members, schema=assemble.MEMBERS),
        pa.Table.from_pylist(list(points), schema=assemble.POINTS),
        assemble.ABSORBED.empty_table(),
        assemble.DISTANCES.empty_table(),
        assemble.HOSTS.empty_table(),
        assemble.OVERLAPS.empty_table(),
        pa.Table.from_pylist(list(names), schema=assemble.NAMES),
        assemble.EVENTS.empty_table(),
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


def kepler_16(order: str = "AB") -> Systems:
    """Kepler-16: a point that holds both stars, A first unless `order` is
    "BA", with its Gaia orbit."""
    stars = {
        "A": ("Kepler-16", "A", 0.69),
        "B": ("Kepler-16 B", "", 0.2025),
    }
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
            for label, suffix, mass in (stars[letter] for letter in order)
        ],
        orbit_keys=(20,),
    )


def gaia_pair(masses: tuple[float | None, float | None]) -> Systems:
    """A point that holds two stars that only its Gaia orbit gives."""
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
            {"node": 1, "kind": assemble.ENTRY, "source": GAIA_ORBITS, "mass": mass}
            for mass in masses
        ],
        orbit_keys=(20,),
    )


def msc_masses(*rows: tuple[str, str, float, str, float, str]) -> pa.Table:
    """COMPONENTS of α Cen's pairs in the MSC's sys.tsv."""
    return orbits.msc_masses(
        [
            msc_pair(
                "14396-6050",
                primary,
                secondary,
                "*",
                Mass1=m1,
                MCode1=c1,
                Mass2=m2,
                MCode2=c2,
            )
            for primary, secondary, m1, c1, m2, c2 in rows
        ]
    )


ALPHA_CEN_MASSES = ("A", "B", 1.10, "v", 0.88, "v")


@pytest.fixture
def alpha_cen_orbits(tmp_path) -> pa.Table:
    return catalogue_orbits(tmp_path)


@pytest.fixture
def orb6_only(alpha_cen_orbits) -> pa.Table:
    """α Cen AB's ORB6 orbit, which gives no mass ratio."""
    return alpha_cen_orbits.filter(pc.equal(alpha_cen_orbits["source"], orbits.ORB6))


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

    def test_an_assumed_omega_settles_no_node(self, tmp_path, orb6_only):
        """A circular orbit of α Cen AB with no ω, made up from its SB9 row,
        beside its ORB6 orbit, whose node can be either node."""
        circular = msc_orbit_rows(
            tmp_path,
            "14396-6050|A,B     |  29188.0996|35319.1992| 0.000|  0.0000|  0.00|"
            "  0.00|  0.00|  4.61|  5.45|  -22.44|B|d|SB9_815 2002A&A...386..280P   ",
        )
        found = drawn.draw(
            alpha_cen(),
            Inputs(catalogue_orbits=pa.concat_tables([circular, orb6_only])),
            FakeResolver({}, []),
        )
        (row,) = found.orbits.to_pylist()
        assert row["node_source"] == orbits.ORB6
        assert row["node"] == pytest.approx(205.073) and not row["node_ascending"]
        assert "nodes turned by an orbit with a fixed ω" not in found.counts

    def test_a_node_with_an_assumed_omega_stays_either_node(self, tmp_path):
        """α Cen AB's visual orbit, made circular with no ω, beside its SB9
        orbits, whose ω is fixed."""
        sb9 = [
            line
            for line in MSC_LINES
            if line.startswith("14396-6050|A,B") and "SB9" in line
        ]
        table = msc_orbit_rows(
            tmp_path,
            "14396-6050|A,B     |     79.9100| 1955.6600| 0.000| 17.6600|204.75|"
            "  0.00| 79.32|  0.00|  0.00|    0.00| |y|VB6_Pbx2016 RHD_1AB Gr.2      ",
            *sb9,
        )
        found = drawn.draw(
            alpha_cen(), Inputs(catalogue_orbits=table), FakeResolver({}, [])
        )
        (row,) = found.orbits.to_pylist()
        assert row["node"] == 204.75 and not row["node_ascending"]
        assert "nodes turned by an orbit with a fixed ω" not in found.counts

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

    def test_the_paper_goes_to_the_members_by_their_letters(self):
        """Kepler-16 with B first: Doyle et al.'s orbit of B about A turns
        round, and A's values go to A."""
        literature, stars = orbits.read_literature()
        found = drawn.draw(
            kepler_16("BA"),
            Inputs(catalogue_orbits=literature, catalogue_stars=stars),
            FakeResolver({KEPLER_16: 20}, []),
        )
        (row,) = found.orbits.to_pylist()
        # The paper's 263.464° is A's ω: B's about A is 83.464°, A's about B
        # 263.464°.
        assert row["arg_periastron"] == pytest.approx(263.464)
        assert row["barycentre"] == pytest.approx(0.6897 / (0.6897 + 0.20255))
        b, a = found.held.to_pylist()
        assert (b["letter"], b["mass"]) == ("B", pytest.approx(0.20255))
        assert (a["letter"], a["mass"]) == ("A", pytest.approx(0.6897))
        assert found.counts["literature: orbits turned by the letters"] == 1

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


class TestMassRatio:
    """The MSC's masses of a pair give its mass ratio when no other source
    does."""

    def test_the_msc_masses_last(self, orb6_only):
        stars = msc_masses(ALPHA_CEN_MASSES)
        found = drawn.draw(
            alpha_cen(),
            Inputs(catalogue_orbits=orb6_only, catalogue_stars=stars),
            FakeResolver({}, []),
        )
        (row,) = found.orbits.to_pylist()
        assert row["barycentre"] == pytest.approx(0.88 / (1.10 + 0.88))
        assert row["mass_ratio_source"] == "msc"
        assert found.counts["msc: masses on a pair"] == 1
        assert found.counts["pairs drawn, mass ratio from msc masses"] == 1
        assert found.counts["pairs drawn, MSC mass codes v/v"] == 1

    def test_members_in_the_other_order(self, orb6_only):
        stars = msc_masses(ALPHA_CEN_MASSES)
        found = drawn.draw(
            alpha_cen("B", "A"),
            Inputs(catalogue_orbits=orb6_only, catalogue_stars=stars),
            FakeResolver({}, []),
        )
        (row,) = found.orbits.to_pylist()
        assert row["barycentre"] == pytest.approx(1.10 / (1.10 + 0.88))

    def test_the_k1_and_k2_of_the_msc_come_first(self, alpha_cen_orbits):
        stars = msc_masses(ALPHA_CEN_MASSES)
        found = drawn.draw(
            alpha_cen(),
            Inputs(catalogue_orbits=alpha_cen_orbits, catalogue_stars=stars),
            FakeResolver({}, []),
        )
        (row,) = found.orbits.to_pylist()
        assert row["barycentre"] == pytest.approx(4.61 / (4.61 + 5.45))
        assert found.counts["pairs drawn, mass ratio from msc velocities"] == 1

    def test_the_msc_masses_give_no_semi_major_axis(self, orb6_only):
        """Kepler's third law takes the masses of the papers, Gaia and OEC."""
        no_axis = orb6_only.set_column(
            orb6_only.schema.get_field_index("semi_major_axis"),
            "semi_major_axis",
            pa.nulls(orb6_only.num_rows, pa.float64()),
        )
        found = drawn.draw(
            alpha_cen(),
            Inputs(
                catalogue_orbits=no_axis, catalogue_stars=msc_masses(ALPHA_CEN_MASSES)
            ),
            FakeResolver({}, []),
        )
        assert found.orbits.num_rows == 0
        assert found.counts["pairs with orbits and no semi-major axis"] == 1

    def test_a_minimum_mass_keeps_the_primary_at_the_centre(self, orb6_only):
        stars = msc_masses(("A", "B", 1.10, "v", 0.30, "m"))
        found = drawn.draw(
            alpha_cen(),
            Inputs(catalogue_orbits=orb6_only, catalogue_stars=stars),
            FakeResolver({}, []),
        )
        (row,) = found.orbits.to_pylist()
        assert row["barycentre"] is None
        assert "msc: masses on a pair" not in found.counts

    def test_masses_of_no_pair(self, orb6_only):
        stars = msc_masses(("Ba", "Bb", 0.5, "v", 0.4, "v"))
        found = drawn.draw(
            alpha_cen(),
            Inputs(catalogue_orbits=orb6_only, catalogue_stars=stars),
            FakeResolver({}, []),
        )
        (row,) = found.orbits.to_pylist()
        assert row["barycentre"] is None
        assert found.counts["msc: masses of pairs in no tree"] == 1


def _entry(**values) -> dict:
    return {"node": 1, "kind": assemble.ENTRY} | values


def _held(
    members: list[dict], drawn_pairs: tuple[int, ...] = ()
) -> tuple[pa.Table, Counter]:
    systems = _systems(
        [{"node": 1, "key": 30, "point": True, "ra": 1.0, "dec": 2.0}], members
    )
    drawer = drawn.Drawer(systems, Inputs(), FakeResolver({}, []))
    return drawer.held(drawn_pairs), drawer.counts


class TestHeldStars:
    """An entry that a source names and that we know more of, or a member of a
    drawn pair, is a held star."""

    def test_a_name_or_a_letter_with_a_value(self):
        held, counts = _held(
            [
                _entry(source=GAIA_ORBITS),
                _entry(source=GAIA_ORBITS, mass=0.5),
                _entry(source="wds", letter="B", label="B", spectral_type="L4"),
                _entry(source="wds", letter="B", label="B", mass=0.2),
                _entry(source="simbad", label="HD 27028A"),
                _entry(
                    source="planet-catalogues",
                    letter="PSR B1620-26",
                    label="PSR B1620-26",
                ),
            ]
        )
        rows = held.to_pylist()
        assert [(h["member"], h["tag"], h["letter"], h["own_name"]) for h in rows] == [
            (2, "B", "B", None),
            (3, "B", None, None),
            (4, "HD 27028A", "A", "HD 27028A"),
            (5, "PSR B1620-26", None, "PSR B1620-26"),
        ]
        assert not any(h["pair_letter"] for h in rows)
        # The Gaia masses of an entry give it no ID.
        assert counts["entries that no source names, in no drawn pair"] == 2
        assert (
            counts["entries that no source names, in no drawn pair, with values"] == 1
        )
        assert counts["held stars that a source names"] == 4

    def test_a_letter_alone_stays_an_entry(self):
        """A magnitude or a separation earns no ID."""
        held, counts = _held(
            [
                _entry(source="wds", letter="B", label="B", v_mag=9.0, separation=2.0),
                _entry(source="msc", letter="C", label="C"),
            ]
        )
        assert held.num_rows == 0
        assert counts["entries that are only a letter, of wds"] == 1
        assert counts["entries that are only a letter, of msc"] == 1

    def test_a_label_that_gives_no_name_is_a_letter_alone(self):
        held, _ = _held([_entry(source="simbad", label="Gaia DR3 3794264514053115648")])
        assert held.num_rows == 0

    def test_a_drawn_pair_needs_no_value(self):
        """We draw it, so it has an ID."""
        held, _ = _held(
            [
                _entry(source="wds", letter="A", label="A"),
                _entry(source="wds", letter="B", label="B"),
            ],
            (1,),
        )
        assert held["letter"].to_pylist() == ["A", "B"]

    def test_tags_that_stay_the_same_in_each_ingest(self):
        """The stars of a Gaia orbit by their sides, in either order. Nothing
        names an El-Badry entry: it has no tag."""
        members = [
            _entry(source=GAIA_ORBITS, mass=0.5, known=["spectroscopic orbit"]),
            _entry(source=GAIA_ORBITS, mass=0.7),
        ]
        held, _ = _held(members, (1,))
        assert held["tag"].to_pylist() == ["secondary", "primary"]
        held, counts = _held([_entry(source="el-badry-2021")] * 2, (1,))
        assert held["tag"].to_pylist() == [None, None]
        assert counts["held stars that nothing of their own names"] == 2

    def test_a_simbad_name(self):
        held, _ = _held([_entry(source="simbad", letter="A", label="* phi And A")])
        assert held["own_name"].to_pylist() == ["Phi Andromedae A"]

    def test_the_letters_of_the_wds_and_the_msc_as_they_stand(self):
        held, _ = _held(
            [
                _entry(source="msc", letter="Aab", label="Aab", mass=1.0),
                _entry(source="wds", letter="S17", label="S17", mass=0.5),
            ]
        )
        assert held["letter"].to_pylist() == ["Aab", "S17"]

    def test_a_drawn_pair_the_heavier_star_is_a(self):
        members = [
            _entry(source=GAIA_ORBITS, mass=0.5),
            _entry(source=GAIA_ORBITS, mass=0.7),
        ]
        assert _held(members)[0].num_rows == 0
        held, counts = _held(members, (1,))
        assert held["letter"].to_pylist() == ["B", "A"]
        assert held["pair_letter"].to_pylist() == [True, True]
        assert counts["held stars that no source names, of drawn pairs"] == 2
        assert counts["held stars of drawn pairs"] == 2
        assert counts["held stars with a letter of their pair"] == 2

    def test_with_no_masses_the_first_member_is_a(self):
        held, _ = _held([_entry(source=GAIA_ORBITS), _entry(source=GAIA_ORBITS)], (1,))
        assert held["letter"].to_pylist() == ["A", "B"]

    def test_the_letter_that_the_other_member_leaves(self):
        """A planet catalogue names the primary as the system, and gives B a
        letter."""
        held, _ = _held(
            [
                _entry(
                    source="planet-catalogues",
                    letter="K2-136",
                    label="K2-136",
                    mass=0.1,
                ),
                _entry(
                    source="planet-catalogues",
                    letter="K2-136 B",
                    label="K2-136 B",
                    mass=0.7,
                ),
            ]
        )
        rows = held.to_pylist()
        assert [(h["letter"], h["pair_letter"], h["own_name"]) for h in rows] == [
            ("A", True, "K2-136"),
            ("B", False, "K2-136 B"),
        ]

    def test_a_star_beside_an_entry(self):
        held, _ = _held(
            [
                {
                    "node": 1,
                    "kind": assemble.STAR,
                    "key": 40,
                    "letter": "A",
                    "label": "A",
                },
                _entry(source=GAIA_ORBITS, mass=2.0),
            ],
            (1,),
        )
        assert held.to_pylist()[0]["letter"] == "B"

    def test_the_stars_of_a_drawn_gaia_orbit(self):
        elements_table = pa.Table.from_pylist([KEPLER_16_GAIA])
        found = drawn.draw(
            gaia_pair((0.67, 0.19)),
            Inputs(orbit_elements=elements_table),
            FakeResolver({}, []),
        )
        assert found.orbits.num_rows == 1
        assert found.held["letter"].to_pylist() == ["A", "B"]

    def test_a_gaia_orbit_that_is_not_drawn_holds_no_star(self):
        orbit = KEPLER_16_GAIA | {"nss_solution_type": "SB1", "arg_periastron": 10.0}
        found = drawn.draw(
            gaia_pair((0.67, 0.19)),
            Inputs(orbit_elements=pa.Table.from_pylist([orbit])),
            FakeResolver({}, []),
        )
        assert found.orbits.num_rows == 0 and found.held.num_rows == 0


class TestHeldMagnitudes:
    """The magnitudes of a held star's member go on its values, for the
    export."""

    def test_they_come_with_it(self):
        held, _ = _held(
            [_entry(letter="A", source="msc", mass=1.0, v_mag=7.0, g_mag=6.5)]
        )
        assert held["v_mag"].to_pylist() == [7.0]
        assert held["g_mag"].to_pylist() == [6.5]

    def test_they_earn_no_id(self):
        held, _ = _held([_entry(letter="A", source="wds", v_mag=7.0, g_mag=6.5)])
        assert held.num_rows == 0


def _system(*members: dict) -> tuple[drawn.Drawer, pa.Table]:
    """The Drawer and the held stars of root 1, with the node 2 inside it.
    Each member is a dict of `_entry`."""
    systems = _systems(
        [
            {"node": 1, "key": 0, "ra": 1.0, "dec": 2.0},
            {"node": 2, "key": 0, "root": 1, "parent": 1, "ra": 1.0, "dec": 2.0},
        ],
        list(members),
    )
    drawer = drawn.Drawer(systems, Inputs(), FakeResolver({}, []))
    return drawer, drawer.held(())


class TestOneLetter:
    """A letter stays with one member of a system."""

    B_MSC = _entry(source="msc", letter="B", label="B", spectral_type="M1")
    B_WDS = _entry(node=2, source="wds", letter="B", label="B", spectral_type="M2")

    def test_a_later_source_gives_it_up(self):
        _, held = _system(self.B_WDS, self.B_MSC)
        rows = {h["number"]: h["letter"] for h in held.to_pylist()}
        assert rows == {1: "B", 2: None}

    def test_the_claim_stays(self):
        """A claim reads the source's letter, so the ID stays."""
        _, held = _system(self.B_WDS, self.B_MSC)
        assert sorted(held["tag"].to_pylist()) == ["B", "B"]
        assert len(set(zip(held["number"].to_pylist(), held["tag"].to_pylist()))) == 2

    def test_two_systems_can_each_have_it(self):
        systems = _systems(
            [{"node": 1, "key": 0}, {"node": 2, "key": 0}],
            [self.B_MSC, self.B_WDS],
        )
        held = drawn.Drawer(systems, Inputs(), FakeResolver({}, [])).held(())
        assert held["letter"].to_pylist() == ["B", "B"]

    def test_a_star_goes_before_a_node(self):
        """The letter of a node is that of its main star. An MSC node gives
        it up to a WDS star, which has a name to lose."""
        node = _entry(kind=assemble.SYSTEM, source="msc", letter="A", label="A")
        star = _entry(node=2, source="wds", letter="A", label="A", mass=1.0)
        drawer, held = _system(node, star)
        assert held["letter"].to_pylist() == ["A"]
        assert drawer.repeated == {0}

    def test_a_point_gives_it_up_with_its_label(self):
        point = _entry(
            node=2, kind=assemble.STAR, key=5, source="wds", letter="B", label="B"
        )
        drawer, _ = _system(self.B_MSC, point)
        assert drawer.repeated == {1}
        members = drawn.without_letters(drawer.systems.members, drawer.repeated)
        assert members["letter"].to_pylist() == ["B", None]
        assert members["label"].to_pylist() == ["B", None]

    def test_a_label_that_is_a_name_stays(self):
        name = _entry(source="msc", letter="B", label="B", mass=1.0)
        other = _entry(node=2, source="simbad", letter="B", label="* ksi UMa B")
        drawer, held = _system(name, other)
        members = drawn.without_letters(drawer.systems.members, drawer.repeated)
        assert members["letter"].to_pylist() == ["B", None]
        assert members["label"].to_pylist() == ["B", "* ksi UMa B"]
        assert held["own_name"].to_pylist() == [None, "Xi Ursae Majoris B"]

    def test_inner_goes_with_it(self):
        star = self.B_WDS | {"inner": "Ba"}
        drawer, _ = _system(self.B_MSC, star)
        members = drawn.without_letters(drawer.systems.members, drawer.repeated)
        assert members["inner"].to_pylist() == [None, None]

    def test_a_star_of_a_pair_takes_a_letter_of_its_pair(self):
        """The first member of node 2 lost its letter. The other is B."""
        _, held = _system(
            self.B_MSC,
            self.B_WDS | {"mass": 1.0},
            _entry(node=2, source="wds", letter="Bb", label="Bb", mass=0.5),
        )
        rows = {(h["number"], h["tag"]): h for h in held.to_pylist()}
        star = rows[2, "B"]
        assert (star["letter"], star["pair_letter"]) == ("A", True)

    def test_a_pair_letter_is_no_source_letter(self):
        """A star keeps its letter when a pair letter gives another star B."""
        _, held = _system(
            _entry(source=GAIA_ORBITS),
            _entry(source=GAIA_ORBITS, known=["spectroscopic orbit"]),
            _entry(node=2, source="wds", letter="B", label="B", mass=1.0),
        )
        assert held.num_rows == 1
        assert held["letter"].to_pylist() == ["B"]

    def test_an_entry_with_no_id_keeps_it_or_gives_it_up_too(self):
        """A page lists the line of an entry, so a letter stays on one line."""
        letter = _entry(source="msc", letter="B", label="B")
        drawer, held = _system(letter, self.B_WDS)
        assert held["member"].to_pylist() == [1]
        assert held["letter"].to_pylist() == [None]
        assert drawer.repeated == {1}
        letter = _entry(node=2, source="wds", letter="B", label="B")
        drawer, held = _system(self.B_MSC, letter)
        assert held["letter"].to_pylist() == ["B"]
        assert drawer.repeated == {1}

    def test_counts_by_kind(self):
        drawer, _ = _system(self.B_MSC, self.B_WDS)
        assert drawer.counts["letters given up by entry members"] == 1


class TestPairCalledByItsFirstStar:
    """HD 130948: the MSC gives the orbit of A about BC as A,B."""

    ITEM: Any = SimpleNamespace(source="msc", flipped=lambda: "turned")

    def drawer(self) -> drawn.Drawer:
        w = "14503+2355"
        systems = _systems(
            [{"node": 1, "key": 0, "ra": 1.0, "dec": 2.0}],
            [
                _entry(letter="B", ids=_ids(("wds", "id", f"{w} B"))),
                _entry(letter="C", ids=_ids(("wds", "id", f"{w} C"))),
            ],
        )
        return drawn.Drawer(systems, Inputs(), FakeResolver({}, []))

    def test_the_orbit_of_a_about_it_stays_off(self):
        drawer = self.drawer()
        assert not drawer._on_component(self.ITEM, "14503+2355 B", "A")
        assert drawer.pairs[1].orbits == []

    def test_the_orbit_of_its_own_stars_goes_on(self):
        drawer = self.drawer()
        assert drawer._on_component(self.ITEM, "14503+2355 C", "B")
        assert drawer.pairs[1].orbits == [self.ITEM]

    def test_it_goes_on_the_pair_above(self):
        w = "14503+2355"
        systems = _systems(
            [
                {"node": 1, "key": 0, "ra": 1.0, "dec": 2.0},
                {"node": 2, "key": 0, "parent": 1, "root": 1, "ra": 1.0, "dec": 2.0},
            ],
            [
                {"node": 1, "kind": assemble.STAR, "key": 30, "letter": "A"},
                {"node": 1, "kind": assemble.SYSTEM, "member": 2},
                _entry(node=2, letter="B", ids=_ids(("wds", "id", f"{w} B"))),
                _entry(node=2, letter="C"),
            ],
        )
        drawer = drawn.Drawer(systems, Inputs(), FakeResolver({}, []))
        assert drawer._on_component(self.ITEM, f"{w} B", "A")
        assert drawer.pairs[1].orbits == [self.ITEM]
        assert drawer.pairs[2].orbits == []

    def test_a_primary_inside_the_other_member_goes_on(self):
        """An orbit of B about Ca reaches the pair of B and C, turned."""
        drawer = self.drawer()
        assert drawer._on_component(self.ITEM, "14503+2355 B", "Ca")
        assert drawer.pairs[1].orbits == ["turned"]

    def inner_pair(self, label: str, stars: pa.Table | None = None) -> drawn.Drawer:
        """(A, (B, `label`)), where `label` is a pair or a star's sub-pair."""
        w = "14503+2355"
        systems = _systems(
            [
                {"node": 1, "key": 0, "ra": 1.0, "dec": 2.0},
                {"node": 2, "key": 0, "parent": 1, "root": 1, "ra": 1.0, "dec": 2.0},
            ],
            [
                {"node": 1, "kind": assemble.STAR, "key": 30, "letter": "A"},
                {"node": 1, "kind": assemble.SYSTEM, "member": 2},
                _entry(node=2, letter="B", ids=_ids(("wds", "id", f"{w} B"))),
                {"node": 2, "kind": assemble.SYSTEM, "letter": label, "label": label},
            ],
        )
        return drawn.Drawer(
            systems, Inputs(catalogue_stars=stars), FakeResolver({}, [])
        )

    @pytest.mark.parametrize("label", ["CD", "BC", "Cab"])
    def test_a_sub_pair_beside_it_is_another_pair(self, label):
        """The label of a sub-pair is no single letter."""
        drawer = self.inner_pair(label)
        assert drawer._on_component(self.ITEM, "14503+2355 B", "A")
        assert drawer.pairs[1].orbits == [self.ITEM]
        assert drawer.pairs[2].orbits == []

    @pytest.mark.parametrize("label", ["CD", "BC", "Cab"])
    def test_its_masses_go_on_the_pair_above(self, label):
        stars = orbits.msc_masses(
            [
                msc_pair(
                    "14503+2355",
                    "A",
                    "B",
                    "*",
                    Mass1=1.1,
                    MCode1="v",
                    Mass2=0.8,
                    MCode2="v",
                )
            ]
        )
        drawer = self.inner_pair(label, stars)
        drawer.match_msc_masses()
        assert drawer.pairs[1].msc_masses == (pytest.approx(1.1), pytest.approx(0.8))
        assert drawer.pairs[2].msc_masses is None
        assert drawer.counts["msc: masses of a star that heads a pair"] == 1


class TestTwoStarsOfOneId:
    """The MSC's B at 0.2″ and the WDS's B at 30″ are two stars of one id."""

    W = "14396-6050"
    MASSES = ("A", "B", 1.10, "v", 0.88, "v")

    def item(self, source: str) -> Any:
        return SimpleNamespace(source=source, flipped=lambda: "turned")

    def systems(self, msc_first: bool, two_stars: Iterable[str] = ()) -> Systems:
        """The pair of each catalogue, `msc_first` for the MSC's as node 1."""
        top = {"node": 1, "key": 0, "ra": 1.0, "dec": 2.0}
        inner = {"node": 2, "key": 0, "parent": 1, "root": 1, "ra": 1.0, "dec": 2.0}

        def pair(node: int, catalogue: str) -> list[dict]:
            return [
                _entry(
                    node=node,
                    letter=letter,
                    label=letter,
                    source=catalogue,
                    ids=_ids((catalogue, "id", f"{self.W} {letter}")),
                )
                for letter in "AB"
            ]

        found = _systems(
            [top, inner],
            [
                *pair(1, "msc" if msc_first else "wds"),
                *pair(2, "wds" if msc_first else "msc"),
            ],
        )
        found.two_stars = frozenset(f"{self.W} {letter}" for letter in two_stars)
        return found

    def node_of(self, msc_first: bool, catalogue: str) -> int:
        return 1 if msc_first == (catalogue == "msc") else 2

    @pytest.mark.parametrize("msc_first", [True, False])
    @pytest.mark.parametrize(
        ("source", "catalogue"), [("msc", "msc"), ("orb6", "wds"), ("sbx", "wds")]
    )
    def test_an_orbit_takes_the_id_of_its_catalogue(self, msc_first, source, catalogue):
        systems = self.systems(msc_first, "B")
        drawer = drawn.Drawer(systems, Inputs(), FakeResolver({}, []))
        assert drawer._on_component(self.item(source), f"{self.W} B", "A")
        assert drawer.pairs[self.node_of(msc_first, catalogue)].orbits
        assert not drawer.pairs[
            self.node_of(msc_first, "msc" if catalogue == "wds" else "wds")
        ].orbits

    @pytest.mark.parametrize("msc_first", [True, False])
    def test_msc_masses_take_the_msc_id(self, msc_first):
        systems = self.systems(msc_first, "B")
        stars = msc_masses(self.MASSES)
        drawer = drawn.Drawer(
            systems, Inputs(catalogue_stars=stars), FakeResolver({}, [])
        )
        drawer.match_msc_masses()
        assert drawer.pairs[self.node_of(msc_first, "msc")].msc_masses
        assert not drawer.pairs[self.node_of(msc_first, "wds")].msc_masses

    def lone_msc_pair(self, two_stars: Iterable[str] = ()) -> drawn.Drawer:
        """The MSC's pair, and no WDS member: a member holds the ids of its
        tree source only."""
        systems = alpha_cen()
        systems.two_stars = frozenset(f"{self.W} {letter}" for letter in two_stars)
        return drawn.Drawer(systems, Inputs(), FakeResolver({}, []))

    def test_the_other_catalogue_reaches_a_member_of_one_star(self):
        drawer = self.lone_msc_pair()
        assert drawer._on_component(self.item("orb6"), f"{self.W} B", "A")
        assert drawer.pairs[1].orbits

    def test_the_other_catalogue_does_not_reach_a_second_star(self):
        drawer = self.lone_msc_pair("B")
        assert not drawer._on_component(self.item("orb6"), f"{self.W} B", "A")
        assert not drawer.pairs[1].orbits

    def test_letters_do_not_reach_a_second_star(self):
        drawer = self.lone_msc_pair("B")
        assert not drawer._on_letters(self.item("orb6"), self.W, "A", "B")
        assert not drawer.pairs[1].orbits

    def own_member_in_no_pair(self, two_stars: Iterable[str] = ()) -> drawn.Drawer:
        """The MSC's B in a node of three, the WDS's in a pair."""

        def members(node: int, catalogue: str, letters: str) -> list[dict]:
            return [
                _entry(
                    node=node,
                    letter=letter,
                    label=letter,
                    source=catalogue,
                    ids=_ids((catalogue, "id", f"{self.W} {letter}")),
                )
                for letter in letters
            ]

        systems = _systems(
            [
                {"node": 1, "key": 0, "ra": 1.0, "dec": 2.0},
                {"node": 2, "key": 0, "parent": 1, "root": 1, "ra": 1.0, "dec": 2.0},
            ],
            [*members(1, "msc", "ABC"), *members(2, "wds", "AB")],
        )
        systems.two_stars = frozenset(f"{self.W} {letter}" for letter in two_stars)
        return drawn.Drawer(systems, Inputs(), FakeResolver({}, []))

    @pytest.mark.parametrize("msc_first", [True, False])
    @pytest.mark.parametrize("source", ["msc", "orb6", "sbx"])
    def test_one_star_in_both_trees_takes_one_pair(self, msc_first, source):
        """Each source of one star's orbit goes on one pair, so it is drawn
        once."""
        systems = self.systems(msc_first)
        drawer = drawn.Drawer(systems, Inputs(), FakeResolver({}, []))
        assert drawer._on_component(self.item(source), f"{self.W} B", "A")
        assert drawer.pairs[self.node_of(msc_first, "msc")].orbits
        assert not drawer.pairs[self.node_of(msc_first, "wds")].orbits

    def test_one_star_in_both_trees_takes_its_pair(self):
        """The two ids name one star, so the orbit goes where it can."""
        drawer = self.own_member_in_no_pair()
        assert drawer._on_component(self.item("msc"), f"{self.W} B", "A")
        assert drawer.pairs[2].orbits

    def test_two_stars_keep_to_their_own_member(self):
        drawer = self.own_member_in_no_pair("B")
        assert drawer._on_component(self.item("msc"), f"{self.W} B", "A")
        assert not drawer.pairs[2].orbits
        assert drawer.counts["msc: orbits of a node that is no pair"] == 1


class TestHostPairs:
    """An orbit that names a host reaches the pair of the host and its brown
    dwarf, as it reached the point that held them."""

    def systems(
        self,
        *nodes: dict,
        outcome: str = MEMBER,
        period: float | None = None,
        orbit_keys: tuple[int, ...] = (),
    ) -> Systems:
        found = _systems(
            [{"node": 1, "key": 0}, *nodes],
            [
                {"node": 1, "kind": assemble.STAR, "key": 30},
                {"node": 1, "kind": assemble.STAR, "key": 40},
            ],
            orbit_keys,
        )
        found.overlaps = pa.Table.from_pylist(
            [{"key": 40, "host": 30, "outcome": outcome, "period": period}],
            schema=assemble.OVERLAPS,
        )
        return found

    def catalogue_orbit(self, period: float, record: float | None) -> list:
        """The periods on the pair after an SBX orbit of the host."""
        row = dict.fromkeys(orbits.ORBITS.names) | {
            "source": orbits.SBX,
            "system": "1",
            "period": period,
            "ids": _ids(("hip", "2007", "1")),
        }
        inputs = Inputs(
            catalogue_orbits=pa.Table.from_pylist([row], schema=orbits.ORBITS)
        )
        drawer = drawn.Drawer(
            self.systems(period=record),
            inputs,
            FakeResolver({("hip", "2007", "1"): 30}, []),
        )
        drawer.match_catalogues()
        return [item.period for item in drawer.pairs[1].orbits]

    def gaia_orbit(self, record: float | None) -> list:
        orbit = dict(KEPLER_16_GAIA)
        drawer = drawn.Drawer(
            self.systems(period=record, orbit_keys=(30,)),
            Inputs(orbit_elements=pa.Table.from_pylist([orbit])),
            FakeResolver({}, []),
        )
        drawer.match_gaia()
        return [item.period for item in drawer.pairs[1].orbits]

    def test_the_pair_of_the_host(self):
        drawer = drawn.Drawer(self.systems(), Inputs(), FakeResolver({}, []))
        assert drawer.point_node == {30: 1}

    def test_a_star_that_left_is_no_partner(self):
        systems = self.systems(outcome=LEAVES)
        assert drawn.Drawer(systems, Inputs(), FakeResolver({}, [])).point_node == {}

    def test_the_orbit_at_the_period_of_the_record(self):
        assert self.catalogue_orbit(1000.0, 1040.0) == [1000.0]

    def test_an_orbit_at_another_period_is_of_another_companion(self):
        """A 5-day orbit of the host is no orbit of a wide brown dwarf."""
        assert self.catalogue_orbit(5.0, 1000.0) == []

    def test_a_record_with_no_period_shows_no_orbit(self):
        assert self.catalogue_orbit(5.0, None) == []

    def test_a_gaia_orbit_at_the_period_of_the_record(self):
        period = KEPLER_16_GAIA["period"]
        assert self.gaia_orbit(period) == [pytest.approx(period)]

    def test_a_gaia_orbit_at_another_period(self):
        assert self.gaia_orbit(5000.0) == []


class TestHeldClaims:
    """A held star claims its node's anchor and its tag. One with no claim of
    its own has no row, as it would take a new ID in each ingest."""

    def test_rows(self):
        systems = _systems(
            [
                {"node": n, "key": k, "point": True, "ra": 1.0, "dec": 2.0}
                | {"root": n, "depth": 0, "primary": k}
                for n, k in ((1, 30), (2, 40))
            ],
            [_entry(), _entry(), _entry(), _entry(), _entry(node=2)],
        )
        columns = ("member", "number", "tag", "letter", "pair_letter")
        rows = [
            (0, 1, "A", "A", False),
            # Two stars B in one node.
            (1, 1, "B", "B", False),
            (2, 1, "B", "B", False),
            # Nothing of its own names it.
            (3, 1, None, "C", True),
            # Its node has nothing to claim.
            (4, 2, "A", "A", False),
        ]
        held = pa.Table.from_pylist(
            [dict(zip(columns, row)) for row in rows], schema=drawn.HELD_STARS
        )
        counts: Counter = Counter()
        part, labels = _held_rows(
            systems,
            held,
            {},
            np.array(["p30", "p40"], object),
            np.array(["gaia/dr3/30", None], object),
            lambda keys, name: pa.nulls(len(keys), pa.float32()),
            counts,
        )
        claim = ("star-system", "member", "gaia/dr3/30 A")
        assert part["claims"].to_pylist() == [[dict(zip(CROSS_ID.names, claim))]]
        assert part["mint"].to_pylist() == [True]
        assert labels.to_pylist() == ["p30 | A", None, None, None, None]
        assert counts["held stars whose claim another held star makes"] == 2
        assert counts["held stars with nothing to claim"] == 2


class TestHeldNames:
    """A held star's own name, else its root's name and its letter, else its
    pair's name and A or B."""

    def test_names(self):
        held_columns = ("number", "letter", "pair_letter", "own_name")
        systems = _systems(
            [
                # Castor, with B a point that holds Ba and Bb.
                {"node": 1, "key": 0, "root": 1},
                {"node": 2, "key": 50, "point": True, "root": 1},
                # A point of a Gaia pair inside Castor, and one of its own.
                {"node": 3, "key": 60, "point": True, "root": 1},
                {"node": 4, "key": 70, "point": True, "root": 4},
                # A point with no name.
                {"node": 5, "key": 80, "point": True, "root": 5},
            ],
            [],
            points=[
                {"key": 50, "name": "Alpha Geminorum B"},
                {"key": 60, "name": "HD 99"},
                {"key": 70, "name": "K2-136"},
                {"key": 80, "name": None},
            ],
        )
        rows = [
            (2, "Ba", False, None),
            (3, "A", True, None),
            (4, "A", True, "K2-136"),
            (4, "B", False, "K2-136 B"),
            (4, "C", False, "PSR B1620-26"),
            (5, "A", True, None),
        ]
        held = pa.Table.from_pylist(
            [dict(zip(held_columns, row)) for row in rows],
            schema=pa.schema([drawn.HELD_STARS.field(name) for name in held_columns]),
        )
        counts: Counter = Counter()
        assert held_names(systems, held, {1: "Castor"}, counts) == [
            "Castor Ba",
            "HD 99 A",
            "K2-136 A",
            "K2-136 B",
            "PSR B1620-26",
            None,
        ]
        assert counts == {
            "held stars named by their root and letter": 1,
            "held stars named by their pair and A or B": 2,
            "held stars named by their source": 2,
            "held stars with no name": 1,
        }

    def test_a_point_root_named_for_its_primary(self):
        """A point that is a root has the name of its primary; its stars
        take the name with no component letter."""
        held_columns = ("number", "letter", "pair_letter", "own_name")
        systems = _systems(
            [
                {"node": 1, "key": 10, "point": True, "root": 1},
                {"node": 2, "key": 20, "point": True, "root": 2},
                {"node": 3, "key": 30, "point": True, "root": 3},
                {"node": 4, "key": 40, "point": True, "root": 4},
                # A resolved root whose inner point is named for A.
                {"node": 5, "key": 0, "root": 5},
                {"node": 6, "key": 50, "point": True, "root": 5},
            ],
            [],
            points=[
                {"key": 10, "name": "HQ Tau A"},
                {"key": 20, "name": "HD 27160A"},
                {"key": 30, "name": "DMPP-3 A"},
                {"key": 40, "name": "Gaia DR3 123"},
                {"key": 50, "name": "HD 98 A"},
            ],
        )
        rows = [
            (1, "Aa", False, None),
            (1, "Ab", False, None),
            # SIMBAD names the point and its first star alike.
            (2, "A", False, "HD 27160A"),
            (2, "B", False, "HD 27160B"),
            (3, "A", True, None),
            (3, "B", True, None),
            (4, "A", True, None),
            (6, "A", True, None),
        ]
        held = pa.Table.from_pylist(
            [dict(zip(held_columns, row)) for row in rows],
            schema=pa.schema([drawn.HELD_STARS.field(name) for name in held_columns]),
        )
        assert held_names(systems, held, {5: "HD 98"}, Counter()) == [
            "HQ Tau Aa",
            "HQ Tau Ab",
            "HD 27160 A",
            "HD 27160B",
            "DMPP-3 A",
            "DMPP-3 B",
            "Gaia DR3 123 A",
            # An inner point is a component: its pair keeps the letter.
            "HD 98 A A",
        ]


class TestRootNames:
    """A root with no name of its own takes its primary's name with no
    component letter, as it is the whole system."""

    def test_names(self):
        def star(node: int, key: int) -> dict:
            return {"node": node, "kind": assemble.STAR, "key": key}

        def inner(node: int, member: int, key: int = 0) -> dict:
            return {"node": node, "kind": assemble.SYSTEM, "key": key, "member": member}

        systems = _systems(
            [
                # HD 284149: its primary is the point of A, which holds Aa, Ab.
                {"node": 1, "key": 0, "root": 1, "depth": 0},
                {"node": 2, "key": 10, "point": True, "root": 1, "depth": 1},
                # A root whose inner pair takes the name of its point.
                {"node": 3, "key": 0, "root": 3, "depth": 0},
                {"node": 4, "key": 0, "parent": 3, "root": 3, "depth": 1},
                # A root named by SIMBAD keeps its letter.
                {"node": 5, "key": 0, "root": 5, "depth": 0},
                # A letter that is part of no component name stays.
                {"node": 6, "key": 0, "root": 6, "depth": 0},
                # A letter with a number is a designation.
                {"node": 7, "key": 0, "root": 7, "depth": 0},
            ],
            [
                inner(1, 2, 10),
                {"node": 1, "kind": assemble.ENTRY, "letter": "B"},
                inner(3, 4),
                star(3, 40),
                star(4, 20),
                star(4, 30),
                star(5, 50),
                star(6, 60),
                star(6, 70),
                star(7, 80),
            ],
            points=[
                {"key": 10, "name": "HD 284149 A"},
                {"key": 20, "name": "HD 20837A"},
                {"key": 50, "name": "tet01 Ori D1"},
                {"key": 60, "name": "eps CrB"},
                {"key": 80, "name": "[GEO97] W7"},
            ],
            names=[
                {"node": 1, "rank": 1, "source": "wds", "name": "WDS J04066+2018"},
                {"node": 5, "rank": 1, "source": "simbad", "name": "Theta1 Orionis D"},
            ],
        )
        assert _node_names(systems) == {
            1: "HD 284149",
            3: "HD 20837",
            4: "HD 20837A",
            5: "Theta1 Orionis D",
            6: "eps CrB",
            7: "[GEO97] W7",
        }
