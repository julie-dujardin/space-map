"""The pairs that the orbit sources reach, the orbits that they draw, and the
stars that the nodes hold."""

from collections import Counter
from collections.abc import Iterable

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pytest

from space_map_data.extrasolar import frame
from space_map_data.extrasolar.exoplanets.catalogues import OEC
from space_map_data.extrasolar.exoplanets.table import default_node
from space_map_data.extrasolar.systems import assemble, drawn, elements, orbits
from space_map_data.extrasolar.systems.assemble import Systems
from space_map_data.extrasolar.systems.ingest import _node_names, held_names
from space_map_data.extrasolar.systems.nodes import GAIA_ORBITS
from space_map_data.extrasolar.systems.prepare import Inputs
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
    empty = [
        schema.empty_table()
        for schema in (
            assemble.ABSORBED,
            assemble.DISTANCES,
            assemble.HOSTS,
            assemble.OVERLAPS,
        )
    ]
    return Systems(
        pa.Table.from_pylist(nodes, schema=assemble.NODES),
        pa.Table.from_pylist(members, schema=assemble.MEMBERS),
        pa.Table.from_pylist(list(points), schema=assemble.POINTS),
        *empty,
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
    """An entry that a source names, or a member of a drawn pair, is a held
    star."""

    def test_a_name_or_a_letter(self):
        held, counts = _held(
            [
                _entry(source=GAIA_ORBITS),
                _entry(source=GAIA_ORBITS, mass=0.5),
                _entry(source="wds", letter="B", label="B"),
                _entry(source="wds", letter="B", label="B"),
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
            (3, "B #4", "B", None),
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

    def test_a_simbad_name(self):
        held, _ = _held([_entry(source="simbad", letter="A", label="* phi And A")])
        assert held["own_name"].to_pylist() == ["Phi Andromedae A"]

    def test_the_letters_of_the_wds_and_the_msc_as_they_stand(self):
        held, _ = _held(
            [
                _entry(source="msc", letter="Aab", label="Aab"),
                _entry(source="wds", letter="S17", label="S17"),
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
