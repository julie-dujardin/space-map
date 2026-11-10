"""The one distance of a star system.

Parallax noise puts the stars of a system far further apart in depth than they
are on the sky, though nearly all pairs agree within 3σ. So the points of a
system of two or more points share a distance.

A point votes with what places it by `placement`, as a parallax. Its rank
(`vote_rank`) says how far to trust it: a paper, a measured parallax, a 5σ
parallax that fidelity flags, any other distance. A node's own distance comes
from the best rank of the points below it: the most precise paper, else the
inverse-variance mean of their votes. A point counts once, however many stars
it holds. A Gaia solution that does not fit its star weighs less by
`parallax.veto_error`. The rank keeps a star that fidelity flags from pulling a
good star, and a prior from outweighing a flagged measure. The root and its
stars keep that rank as their `distance_method`, so a client can say how far
to trust the distance, and the root keeps the paper's point and the catalogues
of the votes, for the credits.

Membership decides who shares: `reduce` has already refuted a star that lies
far from its primary. A vote that still disagrees is nearly always a poor
parallax of a real pair, and the mean outweighs it.

The root takes its own distance. Each member then takes its parent's distance
plus its own offset, shrunk by its error and held at the cap: the parent's sky
radius, the widest separation of a member from the parent's primary. Noise
would otherwise fill the cap. So a member whose error is far above the cap
stays near its parent, a close pair inside a wide system stays close, and a
member that resolves its depth keeps it, as Proxima from α Cen. A member with
no vote takes its parent's distance. The bounds are the bounds of the root's
distance, wider by the cap at each level, so they hold the star.

A star's own paper still outranks this in the distance group, so it stays at
that distance. A point alone in its system keeps its own place.
"""

from collections import Counter
from typing import NamedTuple

import numpy as np
import pyarrow as pa

from space_map_data.extrasolar import sky
from space_map_data.extrasolar.systems.parallax import PARSEC_SEPARATION
from space_map_data.extrasolar.systems.resolve import (
    OTHER,
    PAPER,
    PARALLAX,
    SUSPECT,
    Facts,
)

DISTANCES = pa.schema(
    [
        ("key", pa.int64()),
        # The root of its system.
        ("node", pa.int64()),
        # In pc, with the bounds of `distance_lower` and `distance_upper`.
        ("distance", pa.float64()),
        ("lower", pa.float64()),
        ("upper", pa.float64()),
        # The root's `distance_method`.
        ("method", pa.string()),
    ]
)
# What the shared distance of a root rests on, null on every other node: its
# `distance_method`, the point whose paper gives it (0 for none), and the
# catalogues of the votes that it weighs, as `*_source` values.
BASIS = pa.schema(
    [
        ("distance_method", pa.string()),
        ("distance_paper", pa.int64()),
        ("distance_sources", pa.list_(pa.string())),
    ]
)
# The `distance_method` of each rank that can give a root its distance, so a
# client can say how far to trust it.
METHODS = {
    PAPER: "system-paper",
    PARALLAX: "system-parallax",
    SUSPECT: "system-flagged",
    OTHER: "system-estimate",
}
SYSTEMS_BY_PAPER = "systems whose distance is a paper's"
SYSTEMS_BY_PARALLAX = "systems whose distance is a mean parallax"
SYSTEMS_BY_SUSPECT = "systems whose distance is a mean of flagged parallaxes"
SYSTEMS_BY_OTHER = "systems whose distance comes from no measured parallax"
SYSTEMS_NO_DISTANCE = "systems of two or more points with no distance"
SYSTEMS_TWO_PAPERS = "systems with two papers"
POINTS_AT_THE_CAP = "points held at the cap of their parent"
POINTS_NO_VOTE = "points of a shared system with no place of their own"
POINTS_OUTRANKED = "points whose vote a better rank in their system outranks"


class Shared(NamedTuple):
    # DISTANCES of the points that share a distance.
    distances: pa.Table
    # The distance of each row of `nodes`, NaN for a row that shares none.
    nodes: np.ndarray
    # BASIS of each row of `nodes`.
    basis: pa.Table
    counts: Counter


def shared_distances(nodes: pa.Table, points: pa.Table, facts: Facts) -> Shared:
    """The shared distances of the systems of two or more points."""
    counts: Counter = Counter()
    numbers = nodes["node"].to_numpy()
    by_number = np.argsort(numbers)

    def row_of(wanted: np.ndarray) -> np.ndarray:
        return by_number[np.searchsorted(numbers[by_number], wanted)]

    ups = np.full(numbers.size, -1, np.int64)
    parents = nodes["parent"].to_numpy()
    ups[parents != 0] = row_of(parents[parents != 0])
    depth = nodes["depth"].to_numpy()
    ra = nodes["ra"].fill_null(np.nan).to_numpy()
    dec = nodes["dec"].fill_null(np.nan).to_numpy()

    systems = points["root"].to_numpy()
    _, inverse, sizes = np.unique(systems, return_inverse=True, return_counts=True)
    several = sizes[inverse] >= 2
    keys = points["key"].to_numpy()[several]
    systems = systems[several]
    # A point of a system of several points has a node above it.
    at = row_of(points["parent"].to_numpy()[several])
    held = points["node"].to_numpy()[several]
    rank = facts.column("vote_rank", keys)
    vote = facts.column("vote", keys)
    error = facts.column("vote_error", keys)
    source = pa.array(facts.texts("vote_source", keys), pa.string())
    point_ra, point_dec = facts.column("ra", keys), facts.column("dec", keys)

    # Each node's sums of the points below it, by rank.
    ranks = (PARALLAX, SUSPECT, OTHER)
    weight = np.zeros((len(ranks), numbers.size))
    total = np.zeros((len(ranks), numbers.size))
    for index, voters_of_rank in enumerate(ranks):
        take = rank == voters_of_rank
        np.add.at(weight[index], at[take], error[take] ** -2.0)
        np.add.at(total[index], at[take], vote[take] * error[take] ** -2.0)
    for level in range(int(depth.max(initial=0)), 0, -1):
        rows = np.flatnonzero(depth == level)
        for index in range(len(ranks)):
            np.add.at(weight[index], ups[rows], weight[index, rows])
            np.add.at(total[index], ups[rows], total[index, rows])

    paper = np.full(numbers.size, np.nan)
    paper_error = np.full(numbers.size, np.nan)
    paper_key = np.zeros(numbers.size, np.int64)
    papers = np.flatnonzero(rank == PAPER)
    worst_first = papers[
        np.argsort(-np.nan_to_num(error[papers] / vote[papers], nan=1))
    ]
    for point in worst_first.tolist():
        row = int(at[point])
        while row >= 0:
            paper[row], paper_error[row] = vote[point], error[point]
            paper_key[row] = keys[point]
            row = int(ups[row])
    _, per_system = np.unique(systems[papers], return_counts=True)
    counts[SYSTEMS_TWO_PAPERS] = int((per_system > 1).sum())

    with np.errstate(divide="ignore", invalid="ignore"):
        cases = [np.isfinite(paper), *(weight > 0)]
        parallax = np.select(cases, [paper, *(total / weight)], np.nan)
        sigma = np.select(cases, [paper_error, *(weight**-0.5)], np.nan)
        own = 1000.0 / parallax
        own_error = own * sigma / parallax
        low = 1000.0 / (parallax + sigma)
        high = np.where(parallax > sigma, 1000.0 / (parallax - sigma), np.nan)

    in_shared = np.isin(numbers, systems)
    root_rows = np.flatnonzero((ups < 0) & in_shared)
    distance = np.full(numbers.size, np.nan)
    lower = np.full(numbers.size, np.nan)
    upper = np.full(numbers.size, np.nan)
    distance[root_rows] = own[root_rows]
    lower[root_rows] = low[root_rows]
    upper[root_rows] = high[root_rows]
    # The rank that gives each node its distance, -1 for none.
    best = np.select(cases, [PAPER, *ranks], -1)
    method = np.full(numbers.size, None, object)
    for name, voters_of_rank in (
        (SYSTEMS_BY_PAPER, PAPER),
        (SYSTEMS_BY_PARALLAX, PARALLAX),
        (SYSTEMS_BY_SUSPECT, SUSPECT),
        (SYSTEMS_BY_OTHER, OTHER),
    ):
        of_rank = root_rows[best[root_rows] == voters_of_rank]
        method[of_rank] = METHODS[voters_of_rank]
        counts[name] = of_rank.size
    counts[SYSTEMS_NO_DISTANCE] = int((~np.isfinite(own[root_rows])).sum())
    root_of = row_of(systems)
    weighed = rank == best[root_of]
    basis = pa.table(
        {
            "distance_method": pa.array(method, pa.string()),
            "distance_paper": pa.array(
                np.where(method == METHODS[PAPER], paper_key, 0), pa.int64()
            ),
            "distance_sources": _distinct(
                root_of[weighed], source.filter(pa.array(weighed)), numbers.size
            ),
        },
        schema=BASIS,
    )
    counts[POINTS_NO_VOTE] = int((~np.isfinite(rank)).sum())
    measured_root = np.isin(systems, numbers[root_rows[weight[0, root_rows] > 0]])
    counts[POINTS_OUTRANKED] = int(((rank > PARALLAX) & measured_root).sum())

    # In arcsec: the widest member of each node from its primary.
    radius = np.zeros(numbers.size)
    is_point = nodes["point"].to_numpy(zero_copy_only=False)
    with_points = np.zeros(numbers.size, bool)
    with_points[at] = True
    for level in range(int(depth.max(initial=0)), 0, -1):
        rows = np.flatnonzero((depth == level) & with_points)
        with_points[ups[rows]] = True
    inner = np.flatnonzero((ups >= 0) & ~is_point & with_points)

    def widen(member_ra: np.ndarray, member_dec: np.ndarray, up: np.ndarray) -> None:
        apart = sky.separation(member_ra, member_dec, ra[up], dec[up])
        np.maximum.at(radius, up, np.nan_to_num(apart))

    widen(ra[inner], dec[inner], ups[inner])
    widen(point_ra, point_dec, at)

    def below(
        up: np.ndarray, wanted: np.ndarray, error: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """The distance and the bounds that members of `up` take, and whether
        the cap holds them."""
        base = distance[up]
        cap = radius[up] * base / (1000 * PARSEC_SEPARATION)
        with np.errstate(divide="ignore", invalid="ignore"):
            offset = (wanted - base) * cap**2 / (cap**2 + error**2)
        offset = np.nan_to_num(offset)
        return (
            base + np.clip(offset, -cap, cap),
            lower[up] - cap,
            upper[up] + cap,
            np.abs(offset) > cap,
        )

    for level in range(1, int(depth.max(initial=0)) + 1):
        rows = inner[depth[inner] == level]
        distance[rows], lower[rows], upper[rows], _ = below(
            ups[rows], own[rows], own_error[rows]
        )

    with np.errstate(divide="ignore", invalid="ignore"):
        wanted = 1000.0 / vote
        placed, bottom, top, capped = below(at, wanted, wanted * error / vote)
    placed = np.where(np.isfinite(point_ra + point_dec), placed, np.nan)
    holding = held != 0
    distance[row_of(held[holding])] = placed[holding]
    counts[POINTS_AT_THE_CAP] = int((capped & np.isfinite(placed)).sum())

    has = np.isfinite(placed)
    columns = {
        "key": keys[has],
        "node": systems[has],
        "distance": placed[has],
        "lower": bottom[has],
        "upper": top[has],
        "method": method[root_of][has],
    }
    table = pa.table(
        {
            name: pa.array(values, DISTANCES.field(name).type, from_pandas=True)
            for name, values in columns.items()
        },
        schema=DISTANCES,
    )
    return Shared(table, distance, basis, counts)


def no_basis(n: int) -> dict[str, pa.Array]:
    """BASIS of `n` nodes that are no root with a shared distance."""
    return {
        "distance_method": pa.nulls(n, pa.string()),
        "distance_paper": pa.array(np.zeros(n, np.int64)),
        "distance_sources": pa.nulls(n, pa.list_(pa.string())),
    }


def _distinct(rows: np.ndarray, values: pa.Array, n: int) -> pa.Array:
    """For each of `n` rows, the distinct `values` that `rows` puts there,
    sorted, null where none."""
    known = values.is_valid().to_numpy(zero_copy_only=False)
    texts = values.filter(pa.array(known)).to_numpy(zero_copy_only=False)
    names, codes = np.unique(texts.astype(str), return_inverse=True)
    pairs = np.unique(rows[known] * names.size + codes)
    at, code = np.divmod(pairs, names.size)
    lengths = np.bincount(at, minlength=n)
    offsets = np.r_[0, np.cumsum(lengths)].astype(np.int32)
    return pa.ListArray.from_arrays(
        pa.array(offsets),
        pa.array(names[code], pa.string()),
        mask=pa.array(lengths == 0),
    )
