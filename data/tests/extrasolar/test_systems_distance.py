"""The shared distance of a star system, on real stars of the registry."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pyarrow as pa
import pytest

from space_map_data.extrasolar.placement import (
    placement,
    star_distance,
    with_orbit_parallax,
)
from space_map_data.extrasolar.sky import separation
from space_map_data.extrasolar.sources.literature import LITERATURE
from space_map_data.extrasolar.systems.distance import (
    POINTS_AT_THE_CAP,
    POINTS_NO_VOTE,
    POINTS_OUTRANKED,
    SYSTEMS_BY_OTHER,
    SYSTEMS_BY_PAPER,
    SYSTEMS_BY_PARALLAX,
    SYSTEMS_BY_SUSPECT,
    SYSTEMS_NO_DISTANCE,
    SYSTEMS_TWO_PAPERS,
    Shared,
    shared_distances,
)
from space_map_data.extrasolar.systems.nodes import GAIA_ORBITS
from space_map_data.extrasolar.systems.parallax import PARSEC_SEPARATION
from space_map_data.extrasolar.systems.registry import point_facts
from space_map_data.extrasolar.systems.resolve import (
    FACTS,
    OTHER,
    PAPER,
    PARALLAX,
    SUSPECT,
    Facts,
)
from space_map_data.extrasolar.tables import (
    POINT_SOURCE,
    SOURCE_COLUMN,
    STAR_SYSTEMS,
    merge_by_source_order,
)

# Only the columns that `shared_distances` reads.
NODE_ROWS = pa.schema(
    [
        ("node", pa.int64()),
        ("key", pa.int64()),
        ("parent", pa.int64()),
        ("root", pa.int64()),
        ("depth", pa.int16()),
        ("point", pa.bool_()),
        ("primary", pa.int64()),
        ("ra", pa.float64()),
        ("dec", pa.float64()),
    ]
)
POINT_ROWS = pa.schema(
    [
        ("key", pa.int64()),
        ("node", pa.int64()),
        ("parent", pa.int64()),
        ("root", pa.int64()),
    ]
)
# HIP 14384 in Gaia DR3 table 2.
PARALLAX_NSS, PARALLAX_NSS_ERROR = 7.62998, 0.06405


@dataclass(frozen=True)
class Star:
    key: int
    ra: float
    dec: float
    # What places it, as `point_facts` gives it. None for a star with no place.
    vote: float | None
    error: float | None
    rank: int | None = PARALLAX
    source: str | None = "gaia-dr3"

    @property
    def parsecs(self) -> float:
        assert self.vote is not None
        return 1000 / self.vote


PROXIMA = Star(27424668, 217.392321, -62.676075, 768.067, 0.050)
# Reylé et al. 2021 give A and B one distance, more precise than Hipparcos.
RIGIL_KENTAURUS = Star(
    27468735, 219.868508, -60.831879, 743.0, 1.3, source="reyle-2021"
)
TOLIMAN = Star(564339647, 219.863136, -60.833950, 743.0, 1.3, source="reyle-2021")
SIRIUS = Star(22137869, 101.284621, -16.721552, 379.210, 1.580, source="hipparcos-2007")
# RUWE 2.42 scales 0.231 mas.
SIRIUS_B = Star(559008781, 101.286626, -16.720933, 374.490, 0.559)
CAPELLA = Star(17162358, 79.172809, 45.996094, 76.200, 0.460, source="hipparcos-2007")
CAPELLA_H = Star(17162496, 79.349991, 45.837796, 74.952, 0.019)
CAPELLA_L = Star(1627775232, 79.350146, 45.836842, 75.184, 0.053)
CYGNI_A = Star(20182448, 316.748479, 38.763862, 285.995, 0.060)
CYGNI_B = Star(557053360, 316.753663, 38.756073, 286.005, 0.029)
CASTOR = Star(18400388, 113.648470, 31.887637, 64.120, 3.750, source="hipparcos-2007")
CASTOR_B = Star(555271300, 113.649794, 31.888504, None, None, None, None)
YY_GEM = Star(1092142212, 113.654977, 31.869063, 66.311, 0.024)
HD_284659 = Star(553914580, 70.550801, 22.942293, 8.170, 0.032)
# Fidelity 0.188.
GAJA = Star(17043668, 70.561262, 22.956827, 8.231, 1.128, SUSPECT)
# Fidelity flags A, at RUWE 10.7. B's parallax is -0.3 mas, so it has only a prior.
HD_58763A = Star(27000555, 111.548464, -20.402652, 4.747421, 1.602605, SUSPECT)
HD_58763B = Star(
    563871467, 111.548555, -20.402771, 0.21494, 0.122228, OTHER, "bailer-jones-2021"
)
# Each has only a prior: A's Hipparcos parallax and B's are under 5σ.
HD_56727A = Star(
    22109363, 109.362129, -18.720472, 0.231341, 0.063228, OTHER, "bailer-jones-2021"
)
HD_56727B = Star(
    558980275, 109.362257, -18.719691, 0.167285, 0.076832, OTHER, "bailer-jones-2021"
)
HD_139477 = Star(19693541, 233.83505, 60.08627, 51.22219, 0.01711)
LP_99_392 = Star(19693552, 233.85854, 60.08471, 51.34618, 0.01929)
# RUWE 18.4 scales 0.477 mas, up to MAX_SCALE.
HD_2057 = Star(17491282, 6.288326, 48.047481, 20.620, 1.910)
HD_2057_D = Star(8070554962, 6.282687, 48.046725, 18.489, 0.057)
HD_19994 = Star(22716826, 48.194346, -1.196405, 43.703, 0.133)
# SIMBAD's parallax of a star with no Gaia solution.
CETI_94_B = Star(
    559587738, 48.194166, -1.196998, 38.999, 0.590, source="simbad-parallax"
)
# Bond et al. 2017's parallax of Sirius, which its dynamical masses take.
SIRIUS_BY_PAPER = Star(
    22137869, 101.284621, -16.721552, 378.9, 1.4, PAPER, LITERATURE.name
)
# These papers are real, these places are not.
TAU2_CAP = Star(29261684, 79.0, -14.8, 1000 / 268.8, 0.62, PAPER, LITERATURE.name)
BETA_PHE = Star(25751115, 79.0, -14.81, 1000 / 55.77, 0.53, PAPER, LITERATURE.name)


def tree(
    nodes: Mapping[int, tuple[int, Sequence[Star | int]]],
    held: dict[int, int] | None = None,
) -> Shared:
    """`shared_distances` of the `nodes`: number → (parent, members), in member
    order, so the first member is the primary. A member is a Star or a node.
    `held` gives a star's key its own point node."""
    held = held or {}

    def primary(number: int) -> Star:
        first = nodes[number][1][0]
        return first if isinstance(first, Star) else primary(first)

    def depth(number: int) -> int:
        parent = nodes[number][0]
        return depth(parent) + 1 if parent else 0

    def root(number: int) -> int:
        parent = nodes[number][0]
        return root(parent) if parent else number

    def node_row(number: int, parent: int, top: int, level: int, star: Star) -> dict:
        return {
            "node": number,
            "key": star.key if number not in nodes else 0,
            "parent": parent,
            "root": top,
            "depth": level,
            "point": number not in nodes,
            "primary": star.key,
            "ra": star.ra,
            "dec": star.dec,
        }

    rows = [
        node_row(number, parent, root(number), depth(number), primary(number))
        for number, (parent, _) in nodes.items()
    ]
    points = []
    stars = []
    for number, (_, members) in nodes.items():
        for star in members:
            if isinstance(star, int):
                continue
            stars.append(star)
            inner = held.get(star.key, 0)
            points.append(
                {
                    "key": star.key,
                    "node": inner,
                    "parent": number,
                    "root": root(number),
                }
            )
            if inner:
                rows.append(
                    node_row(inner, number, root(number), depth(number) + 1, star)
                )
    facts = [
        {name: None for name in FACTS.names}
        | {
            "key": star.key,
            "ra": star.ra,
            "dec": star.dec,
            "vote": star.vote,
            "vote_error": star.error,
            "vote_rank": star.rank,
            "vote_source": star.source,
        }
        for star in stars
    ]
    return shared_distances(
        pa.Table.from_pylist(rows, schema=NODE_ROWS),
        pa.Table.from_pylist(points, schema=POINT_ROWS),
        Facts(pa.Table.from_pylist(facts, schema=FACTS)),
    )


def apart(first: Star, second: Star, parsecs: float) -> float:
    """The projected separation of two stars at this distance, in pc."""
    arcsec = float(separation(first.ra, first.dec, second.ra, second.dec))
    return arcsec * parsecs / (1000 * PARSEC_SEPARATION)


def placed(shared: Shared) -> dict[int, float]:
    table = shared.distances
    return dict(zip(table["key"].to_pylist(), table["distance"].to_pylist()))


def shrunk(star: Star, centre: float, cap: float) -> float:
    """Where `star` lands from `centre`, its offset shrunk by its own error."""
    assert star.error is not None and star.vote is not None
    sigma = star.parsecs * star.error / star.vote
    return centre + (star.parsecs - centre) * cap**2 / (cap**2 + sigma**2)


def mean(*stars: Star) -> float:
    """The distance of the inverse-variance mean parallax of `stars`."""
    weights = np.array([float(star.error or np.nan) ** -2 for star in stars])
    votes = np.array([float(star.vote or np.nan) for star in stars])
    return 1000 / float(np.sum(weights * votes) / np.sum(weights))


class TestOneDistance:
    def test_the_mean_is_by_inverse_variance_in_parallax(self):
        shared = tree({1: (0, [SIRIUS, SIRIUS_B])})
        expected = mean(SIRIUS, SIRIUS_B)
        assert shared.nodes[0] == pytest.approx(expected)
        assert shared.counts[SYSTEMS_BY_PARALLAX] == 1

    def test_an_offset_shrinks_by_its_error(self):
        """The errors of 61 Cyg are about as large as its width, so each star
        keeps a share of its offset."""
        shared = tree({1: (0, [CYGNI_A, CYGNI_B])})
        found = placed(shared)
        centre = shared.nodes[0]
        cap = apart(CYGNI_A, CYGNI_B, centre)
        for star in (CYGNI_A, CYGNI_B):
            assert found[star.key] == pytest.approx(shrunk(star, centre, cap))
            assert abs(found[star.key] - centre) < abs(star.parsecs - centre)
        assert found[CYGNI_A.key] > found[CYGNI_B.key]

    def test_noise_stays_at_the_centre(self):
        """Errors far over the width: noise no longer fills the cap."""
        shared = tree({1: (0, [SIRIUS, SIRIUS_B])})
        found = placed(shared)
        centre = shared.nodes[0]
        cap = apart(SIRIUS, SIRIUS_B, centre)
        for star in (SIRIUS, SIRIUS_B):
            assert abs(found[star.key] - centre) < 0.05 * cap
        assert shared.counts[POINTS_AT_THE_CAP] == 0

    def test_the_cap_holds_what_a_shrunk_offset_leaves(self):
        """These parallaxes put the pair 0.047 pc apart in depth, 7σ, against
        0.002 pc on the sky."""
        shared = tree({1: (0, [HD_139477, LP_99_392])})
        found = placed(shared)
        centre = shared.nodes[0]
        cap = apart(HD_139477, LP_99_392, centre)
        assert found[HD_139477.key] == pytest.approx(centre + cap)
        assert found[LP_99_392.key] == pytest.approx(centre - cap)
        assert shared.counts[POINTS_AT_THE_CAP] == 2

    def test_a_lone_point_has_no_row(self):
        """A root of one point has no depth to share."""
        shared = tree({1: (0, [CAPELLA])}, held={CAPELLA.key: 9})
        assert shared.distances.num_rows == 0
        assert np.isnan(shared.nodes).all()

    def test_a_point_counts_once(self):
        """Capella holds two stars, and they weigh as one point."""
        nodes = {1: (0, [CAPELLA, CAPELLA_H])}
        shared = tree(nodes, held={CAPELLA.key: 9})
        assert shared.nodes[0] == pytest.approx(mean(CAPELLA, CAPELLA_H))

    def test_a_point_that_holds_several_has_its_place_on_its_node(self):
        shared = tree({1: (0, [CAPELLA, CAPELLA_H])}, held={CAPELLA.key: 9})
        assert shared.nodes[1] == pytest.approx(placed(shared)[CAPELLA.key])


class TestLevels:
    def test_proxima_keeps_its_real_offset(self):
        """The root's radius holds Proxima's 0.044 pc from α Cen."""
        shared = tree(
            {
                1: (0, [2, PROXIMA]),
                2: (1, [RIGIL_KENTAURUS, TOLIMAN]),
            }
        )
        found = placed(shared)
        assert found[PROXIMA.key] == pytest.approx(1.3020, abs=1e-4)
        assert found[RIGIL_KENTAURUS.key] == pytest.approx(1000 / 743.0, abs=1e-4)
        assert found[TOLIMAN.key] == pytest.approx(1000 / 743.0, abs=1e-4)

    def test_a_close_pair_keeps_its_own_width(self):
        """H and L are 3.5″ apart. Capped at the system's 11′ they could lie
        0.09 pc apart, against 47 AU on the sky."""
        shared = tree({1: (0, [CAPELLA, 2]), 2: (1, [CAPELLA_H, CAPELLA_L])})
        found = placed(shared)
        gap = abs(found[CAPELLA_H.key] - found[CAPELLA_L.key])
        assert gap <= 2 * apart(CAPELLA_H, CAPELLA_L, shared.nodes[1])

    def test_a_node_shrinks_by_its_own_error(self):
        """Castor's Hipparcos error is 170 × the width of the system, so A and B
        stay at YY Gem, not at the cap on Castor's side."""
        shared = tree({1: (0, [2, YY_GEM]), 2: (1, [CASTOR, CASTOR_B])})
        cap = apart(CASTOR, YY_GEM, shared.nodes[0])
        assert abs(shared.nodes[1] - shared.nodes[0]) < 0.01 * cap

    def test_the_inner_node_has_the_mean_of_its_stars(self):
        shared = tree({1: (0, [CAPELLA, 2]), 2: (1, [CAPELLA_H, CAPELLA_L])})
        assert shared.nodes[0] == pytest.approx(mean(CAPELLA, CAPELLA_H, CAPELLA_L))
        assert shared.nodes[1] == pytest.approx(mean(CAPELLA_H, CAPELLA_L))

    def test_a_star_stays_inside_the_system(self):
        """Capella's own distance is 0.2 pc off, its sky radius 0.04 pc."""
        shared = tree({1: (0, [CAPELLA, 2]), 2: (1, [CAPELLA_H, CAPELLA_L])})
        radius = apart(CAPELLA, CAPELLA_H, shared.nodes[0])
        assert placed(shared)[CAPELLA.key] == pytest.approx(shared.nodes[0] - radius)

    def test_a_star_with_no_place_takes_its_node(self):
        """Castor B has no parallax. It stays beside Castor A, not at C."""
        shared = tree({1: (0, [2, YY_GEM]), 2: (1, [CASTOR, CASTOR_B])})
        found = placed(shared)
        assert found[CASTOR_B.key] == pytest.approx(shared.nodes[1])
        assert shared.counts[POINTS_NO_VOTE] == 1


class TestRanks:
    def test_a_flagged_star_does_not_pull_a_good_star(self):
        shared = tree({1: (0, [HD_284659, GAJA])})
        assert shared.nodes[0] == pytest.approx(HD_284659.parsecs)
        assert shared.counts[POINTS_OUTRANKED] == 1

    def test_a_system_of_flagged_stars_still_takes_a_distance(self):
        other = Star(HD_284659.key, HD_284659.ra, HD_284659.dec, 8.170, 0.032, SUSPECT)
        shared = tree({1: (0, [other, GAJA])})
        assert shared.nodes[0] == pytest.approx(mean(other, GAJA))
        assert shared.counts[SYSTEMS_BY_SUSPECT] == 1

    def test_a_flagged_parallax_outranks_a_prior(self):
        """A prior from a parallax of -0.3 mas put HD 58763A at 4,147 pc."""
        shared = tree({1: (0, [HD_58763A, HD_58763B])})
        assert shared.nodes[0] == pytest.approx(HD_58763A.parsecs)
        assert shared.counts[POINTS_OUTRANKED] == 0

    def test_a_system_of_priors_still_takes_a_distance(self):
        shared = tree({1: (0, [HD_56727A, HD_56727B])})
        assert shared.nodes[0] == pytest.approx(mean(HD_56727A, HD_56727B))
        assert shared.counts[SYSTEMS_BY_OTHER] == 1

    def test_a_system_with_no_place_takes_none(self):
        none = Star(HD_284659.key, HD_284659.ra, HD_284659.dec, None, None, None)
        shared = tree({1: (0, [none, CASTOR_B])})
        assert shared.distances.num_rows == 0
        assert shared.counts[SYSTEMS_NO_DISTANCE] == 1


class TestPapers:
    def test_a_paper_is_the_distance_of_its_system(self):
        shared = tree({1: (0, [HD_284659, TAU2_CAP])})
        assert shared.nodes[0] == pytest.approx(268.8)
        assert shared.counts[SYSTEMS_BY_PAPER] == 1

    def test_a_paper_outranks_a_more_precise_parallax(self):
        """Sirius B's Gaia parallax, 3σ under the paper's, would hold 89% of
        the mean. B still stays within the width of A."""
        shared = tree({1: (0, [SIRIUS_BY_PAPER, SIRIUS_B])})
        centre = shared.nodes[0]
        assert centre == pytest.approx(1000 / 378.9)
        assert abs(placed(shared)[SIRIUS_B.key] - centre) < apart(
            SIRIUS, SIRIUS_B, centre
        )
        assert shared.counts[SYSTEMS_BY_PAPER] == 1

    def test_the_most_precise_of_two_papers_wins(self):
        """β Phe's 3% beats τ² Cap's 17%, in either order."""
        for stars in ([TAU2_CAP, BETA_PHE], [BETA_PHE, TAU2_CAP]):
            shared = tree({1: (0, stars)})
            assert shared.nodes[0] == pytest.approx(55.77)
            assert shared.counts[SYSTEMS_TWO_PAPERS] == 1


class TestPoorVotes:
    """`reduce` decides who shares. A vote that still disagrees is outweighed."""

    def test_a_poor_parallax_of_a_real_pair_shares(self):
        """94 Cet B lies 8σ off its primary, 2″ away."""
        shared = tree({1: (0, [HD_19994, CETI_94_B])})
        assert shared.nodes[0] == pytest.approx(mean(HD_19994, CETI_94_B))
        assert set(placed(shared)) == {HD_19994.key, CETI_94_B.key}

    def test_a_ruined_parallax_goes_to_its_companion(self):
        """HD 2057 A has RUWE 18.4, and D is precise."""
        shared = tree({1: (0, [HD_2057, HD_2057_D])})
        assert 1000 / shared.nodes[0] == pytest.approx(18.49, abs=0.01)


class TestBounds:
    def test_they_hold_each_star(self):
        for nodes in (
            {1: (0, [2, PROXIMA]), 2: (1, [RIGIL_KENTAURUS, TOLIMAN])},
            {1: (0, [CAPELLA, 2]), 2: (1, [CAPELLA_H, CAPELLA_L])},
            {1: (0, [SIRIUS, SIRIUS_B])},
        ):
            rows = tree(nodes).distances.to_pylist()
            assert all(r["lower"] <= r["distance"] <= r["upper"] for r in rows)

    def test_a_paper_gives_them(self):
        rows = tree({1: (0, [HD_284659, TAU2_CAP])}).distances.to_pylist()
        assert all(r["upper"] > r["lower"] for r in rows)


NO_BASIS = {"distance_method": None, "distance_paper": 0, "distance_sources": None}


def basis(shared: Shared, row: int = 0) -> dict:
    """The basis of a row of the nodes."""
    return shared.basis.to_pylist()[row]


def methods(shared: Shared) -> set[str]:
    """The `distance_method` of the points that share a distance."""
    return set(shared.distances["method"].to_pylist())


class TestBasis:
    """What a root's distance rests on: its method, which its points take
    too, the star of its paper and the catalogues of its votes."""

    def test_a_paper(self):
        shared = tree({1: (0, [HD_284659, TAU2_CAP])})
        assert basis(shared) == {
            "distance_method": "system-paper",
            "distance_paper": TAU2_CAP.key,
            "distance_sources": [LITERATURE.name],
        }
        assert methods(shared) == {"system-paper"}

    def test_the_most_precise_paper_names_its_star(self):
        for stars in ([TAU2_CAP, BETA_PHE], [BETA_PHE, TAU2_CAP]):
            assert basis(tree({1: (0, stars)}))["distance_paper"] == BETA_PHE.key

    def test_measured_parallaxes_name_each_catalogue_once(self):
        """Reylé's distance of A and B, and Proxima's own Gaia parallax."""
        shared = tree({1: (0, [2, PROXIMA]), 2: (1, [RIGIL_KENTAURUS, TOLIMAN])})
        assert basis(shared) == {
            "distance_method": "system-parallax",
            "distance_paper": 0,
            "distance_sources": ["gaia-dr3", "reyle-2021"],
        }
        assert methods(shared) == {"system-parallax"}

    def test_flagged_parallaxes_leave_out_a_prior(self):
        shared = tree({1: (0, [HD_58763A, HD_58763B])})
        assert basis(shared) == {
            "distance_method": "system-flagged",
            "distance_paper": 0,
            "distance_sources": ["gaia-dr3"],
        }
        assert methods(shared) == {"system-flagged"}

    def test_other_distances_are_an_estimate(self):
        shared = tree({1: (0, [HD_56727A, HD_56727B])})
        assert basis(shared) == {
            "distance_method": "system-estimate",
            "distance_paper": 0,
            "distance_sources": ["bailer-jones-2021"],
        }
        assert methods(shared) == {"system-estimate"}

    def test_each_system_keeps_its_own(self):
        """Two systems out of number order, of different ranks."""
        shared = tree(
            {
                5: (0, [RIGIL_KENTAURUS, TOLIMAN]),
                1: (0, [HD_284659, TAU2_CAP]),
            }
        )
        assert basis(shared, 0) == {
            "distance_method": "system-parallax",
            "distance_paper": 0,
            "distance_sources": ["reyle-2021"],
        }
        assert basis(shared, 1)["distance_paper"] == TAU2_CAP.key
        by_key = dict(
            zip(
                shared.distances["key"].to_pylist(),
                shared.distances["method"].to_pylist(),
                strict=True,
            )
        )
        assert by_key == {
            RIGIL_KENTAURUS.key: "system-parallax",
            TOLIMAN.key: "system-parallax",
            HD_284659.key: "system-paper",
            TAU2_CAP.key: "system-paper",
        }

    def test_only_the_root_has_one(self):
        shared = tree({1: (0, [CAPELLA, 2]), 2: (1, [CAPELLA_H, CAPELLA_L])})
        assert basis(shared)["distance_sources"] == ["gaia-dr3", "hipparcos-2007"]
        assert basis(shared, 1) == NO_BASIS

    def test_a_system_with_no_place_has_none(self):
        none = Star(HD_284659.key, HD_284659.ra, HD_284659.dec, None, None, None, None)
        assert basis(tree({1: (0, [none, CASTOR_B])})) == NO_BASIS

    def test_a_lone_point_has_none(self):
        shared = tree({1: (0, [CAPELLA])}, held={CAPELLA.key: 9})
        assert shared.basis.to_pylist() == [NO_BASIS, NO_BASIS]


def point_row(**values) -> dict:
    return {"id": 1, "astrometry_source": "gaia-dr3", **values}


def votes(rows: list[dict], orbits: pa.Table | None = None) -> pa.Table:
    """FACTS from Point source `rows`."""
    point = pa.Table.from_pylist(rows, schema=POINT_SOURCE.schema)
    ids = point["id"].to_pylist()
    n = len(ids)
    positions = pa.table(
        {
            "key": pa.array(ids, pa.int64()),
            "ra": pa.array([10.0] * n, pa.float64()),
            "dec": pa.array([10.0] * n, pa.float64()),
            "pmra": pa.array([0.0] * n, pa.float32()),
            "pmdec": pa.array([0.0] * n, pa.float32()),
            "mag": pa.array([5.0] * n, pa.float32()),
        }
    )
    meta = pa.table(
        {
            "id": pa.array(ids, pa.int64()),
            "name": pa.array([None] * n, pa.string()),
            "name_source": pa.array([None] * n, pa.string()),
        }
    )
    return point_facts(positions, point, meta, orbits)


class TestVotes:
    def test_a_gaia_error_counts_by_its_ruwe(self):
        row = point_row(parallax=374.49, parallax_error=0.231, ruwe=2.42)
        found = votes([row]).to_pylist()[0]
        assert found["vote"] == pytest.approx(374.49, rel=1e-5)
        assert found["vote_error"] == pytest.approx(0.231 * 2.42, rel=1e-5)
        assert found["vote_rank"] == PARALLAX
        assert found["vote_source"] == "gaia-dr3"

    def test_a_hipparcos_error_stands(self):
        row = point_row(
            astrometry_source="hipparcos-2007",
            parallax=379.21,
            parallax_error=1.58,
            ruwe=2.42,
        )
        found = votes([row]).to_pylist()[0]
        assert found["vote_error"] == pytest.approx(1.58)
        assert found["vote_source"] == "hipparcos-2007"

    def test_an_orbit_parallax_stands_for_the_parallax(self):
        """HIP 14384, as the render tree places it."""
        row = point_row(parallax=7.3775, parallax_error=0.1190, ruwe=7.017)
        orbits = pa.table(
            {
                "id": pa.array([1], pa.int64()),
                "nss_solution_type": ["Orbital"],
                "parallax_nss": pa.array([PARALLAX_NSS], pa.float32()),
                "parallax_nss_error": pa.array([PARALLAX_NSS_ERROR], pa.float32()),
            }
        )
        found = votes([row], orbits).to_pylist()[0]
        assert found["vote"] == pytest.approx(PARALLAX_NSS, rel=1e-5)
        assert found["vote_error"] == pytest.approx(PARALLAX_NSS_ERROR, rel=1e-5)
        assert found["distance"] == pytest.approx(1000 / PARALLAX_NSS, rel=1e-5)
        assert found["vote_source"] == GAIA_ORBITS

    def test_a_measured_group_that_places_the_star_votes(self):
        """α Cen A: Reylé et al. 2021 beat Hipparcos, as the placement says."""
        row = point_row(
            astrometry_source="hipparcos-2007",
            parallax=754.81,
            parallax_error=4.11,
            distance=1.3459,
            distance_lower=1.3435,
            distance_upper=1.3483,
            distance_source="reyle-2021",
            distance_method="parallax",
        )
        found = votes([row]).to_pylist()[0]
        assert found["vote"] == pytest.approx(1000 / 1.3459, rel=1e-5)
        assert found["vote_error"] == pytest.approx(1.33, abs=0.01)
        assert found["vote_rank"] == PARALLAX
        assert found["vote_source"] == "reyle-2021"

    def test_a_flagged_parallax_ranks_over_a_prior(self):
        """Gaja, whose fidelity is 0.188. Hipparcos saw it."""
        row = point_row(
            parallax=8.231,
            parallax_error=0.405,
            ruwe=2.79,
            fidelity_v2=0.188,
            hipparcos_photometry_source="hipparcos-2007",
        )
        found = votes([row]).to_pylist()[0]
        assert found["vote_rank"] == SUSPECT
        assert found["vote_source"] == "gaia-dr3"

    def test_a_prior_ranks_last(self):
        row = point_row(
            distance=10597.5,
            distance_lower=8000.0,
            distance_upper=13000.0,
            distance_source="bailer-jones-2021",
            distance_method="geometric",
            parallax=-0.541,
            parallax_error=0.150,
        )
        found = votes([row]).to_pylist()[0]
        assert found["vote_rank"] == OTHER
        assert found["vote_source"] == "bailer-jones-2021"

    def test_a_distance_with_no_error_counts_as_all_error(self):
        row = point_row(
            astrometry_source=None,
            host_distance=210.0,
            host_star_source="nasa-exoplanet-archive",
        )
        found = votes([row]).to_pylist()[0]
        assert found["vote_error"] == pytest.approx(found["vote"])
        assert found["vote_rank"] == OTHER
        assert found["vote_source"] == "nasa-exoplanet-archive"

    def test_a_paper_ranks_first(self):
        """τ² Cap, as literature.py gives it."""
        row = point_row(
            astrometry_source="hipparcos-2007",
            parallax=2.87,
            parallax_error=0.65,
            distance=268.8,
            distance_lower=230.4,
            distance_upper=322.6,
            distance_source=LITERATURE.name,
            distance_method="dynamical",
        )
        found = votes([row]).to_pylist()[0]
        assert found["vote"] == pytest.approx(1000 / 268.8, rel=1e-5)
        assert found["vote_rank"] == PAPER
        assert found["vote_source"] == LITERATURE.name

    def test_a_star_with_no_place_has_no_vote(self):
        found = votes([point_row(parallax=-0.1, parallax_error=1.0)]).to_pylist()[0]
        assert found["vote_rank"] is None
        assert found["vote_source"] is None

    def test_a_committed_system_distance_is_no_fact(self):
        """Castor B in a registry: its distance is the last ingest's result."""
        row = point_row(
            astrometry_source="gaia-dr3-named",
            distance=15.5958,
            distance_source=STAR_SYSTEMS,
            distance_method="system-parallax",
        )
        found = votes([row]).to_pylist()[0]
        assert found["distance"] is None
        assert found["vote"] is None
        assert found["vote_rank"] is None

    def test_under_a_committed_system_distance_the_parallax_stands(self):
        """So a dry run after an ingest reads the star's own place."""
        row = point_row(
            parallax=74.952,
            parallax_error=0.019,
            ruwe=1.11,
            distance=13.3375,
            distance_source=STAR_SYSTEMS,
            distance_method="system-parallax",
        )
        found = votes([row]).to_pylist()[0]
        assert found["distance"] == pytest.approx(1000 / 74.952, rel=1e-6)
        assert found["vote_rank"] == PARALLAX


def rows_of(**values) -> pa.Table:
    row = {"id": 1, "astrometry_source": "gaia-dr3"} | values
    return with_orbit_parallax(
        pa.Table.from_pylist([row], schema=POINT_SOURCE.schema), None
    )


A_SYSTEM = {
    "distance": 13.3375,
    "distance_source": STAR_SYSTEMS,
    "distance_method": "system-parallax",
}
A_PARALLAX = {"parallax": 74.952, "parallax_error": 0.019}


class TestPlacement:
    def test_the_system_outranks_the_parallax(self):
        table = rows_of(**A_SYSTEM, **A_PARALLAX)
        where = placement(table)
        assert where.by_group[0] and not where.by_parallax[0]
        assert star_distance(table, where)[0][0] == pytest.approx(13.3375)

    def test_a_paper_outranks_the_system(self):
        """The merge keeps one source, so the row of a paper says `literature`."""
        table = rows_of(distance=268.8, distance_source=LITERATURE.name, **A_PARALLAX)
        assert star_distance(table, placement(table))[0][0] == pytest.approx(268.8)

    def test_the_system_outranks_a_catalogue_distance(self):
        table = rows_of(**A_SYSTEM, host_distance=210.0)
        where = placement(table)
        assert where.by_group[0] and not where.by_catalogue[0]

    def test_a_flagged_star_of_a_system_is_placed(self):
        table = rows_of(
            **A_SYSTEM,
            **A_PARALLAX,
            fidelity_v2=0.1,
            hipparcos_photometry_source="hipparcos-2007",
        )
        where = placement(table)
        assert where.by_group[0] and not where.by_suspect[0]

    def test_with_no_system_the_parallax_stands(self):
        where = placement(rows_of(**A_PARALLAX))
        assert where.by_parallax[0]

    def test_the_merge_ranks_the_system_under_a_paper_only(self):
        columns = {f.name: f for f in POINT_SOURCE.group("distance").columns}
        rows = pa.Table.from_pylist(
            [
                {"id": 1, SOURCE_COLUMN: "bailer-jones-2021", "distance": 10.0},
                {"id": 1, SOURCE_COLUMN: "simbad-parallax", "distance": 11.0},
                {"id": 1, SOURCE_COLUMN: STAR_SYSTEMS, "distance": 12.0},
                {"id": 2, SOURCE_COLUMN: STAR_SYSTEMS, "distance": 12.0},
                {"id": 2, SOURCE_COLUMN: LITERATURE.name, "distance": 13.0},
            ],
            schema=pa.schema(
                [("id", pa.int64()), (SOURCE_COLUMN, pa.string()), columns["distance"]]
            ),
        )
        for field in POINT_SOURCE.group_fields:
            if field.name not in rows.column_names:
                rows = rows.append_column(field, pa.nulls(rows.num_rows, field.type))
        merged = merge_by_source_order(POINT_SOURCE, rows)
        found = dict(
            zip(merged["id"].to_pylist(), merged["distance_source"].to_pylist())
        )
        assert found == {1: STAR_SYSTEMS, 2: LITERATURE.name}
