"""The storage form of the light grid and its read, as a shader does it.

A voxel holds eight values in two RGBA16F texels, so a sample takes two fetches:

    A: L(all), L(M0 > -5), L(M0 > -2), L(M0 > 0)
    B: L(M0 > 1), L(M0 > 3), L(M0 > 5), tint

L is the summed R + G + B flux density of the stars fainter than an edge. It falls
with M, and a filtered read of a falling curve still falls, so LINEAR is safe. Between
two edges a sample mixes them by a `place` that comes from the summed light of all
stars at that M, so the sum over all voxels is exact at every M. Past the last edge
the mix goes to zero the same way. `tint` is B / (R + B) of L(M0 > 0), and it moves the
colour of the summed light at M along the blackbody locus.
"""

from dataclasses import dataclass

import numpy as np

from space_map_data.dust.nest import smoothstep

# The faint edges. The first value of a voxel holds all its stars.
EDGES = (-5.0, -2.0, 0.0, 1.0, 3.0, 5.0)
VALUES = len(EDGES) + 2
# Which edge the tint is measured at: the median cut over real views.
TINT_EDGE = 2
# Steps of the summed curves, and of the table a shader reads.
CURVE_LOW = -20.0
CURVE_HIGH = 20.0
CURVE_STEP = 0.05
TABLE_STEP = 0.5
FADE_MAG = 1.0


def curve_points() -> np.ndarray:
    n = round((CURVE_HIGH - CURVE_LOW) / CURVE_STEP)
    return CURVE_LOW + CURVE_STEP * np.arange(n + 1)


def curve_bin(m0: np.ndarray) -> np.ndarray:
    """The curve bin of each star; a bin k holds M0 in the k-th step."""
    points = curve_points()
    at = np.floor((m0 - CURVE_LOW) / CURVE_STEP).astype(np.int64)
    return np.clip(at, 0, len(points) - 2)


def fainter_curve(histogram: np.ndarray) -> np.ndarray:
    """Light fainter than each curve point, from a histogram by curve bin, with a
    last axis of channels."""
    tail = np.cumsum(histogram[::-1], axis=0)[::-1]
    return np.concatenate((tail, np.zeros((1, *histogram.shape[1:]))))


def soft_curve(curve: np.ndarray) -> np.ndarray:
    """As `fainter_curve`, with each star weighted by 1 - fade(M - M0), the part of
    its light that a star at the fade does not draw."""
    points = curve_points()
    width = round(FADE_MAG / CURVE_STEP)
    fade = smoothstep((np.arange(width) + 0.5) / width)
    density = -np.diff(curve, axis=0)
    out = np.zeros_like(curve)
    for k in range(len(points)):
        # Bins k - width .. k - 1 are under the cut by 1 mag at most.
        low = max(k - width, 0)
        kept = curve[k]
        weights = 1 - fade[::-1][-(k - low) :] if k > low else np.zeros(0)
        out[k] = kept + (
            density[low:k] * weights.reshape(-1, *[1] * (curve.ndim - 1))
        ).sum(axis=0)
    return out


@dataclass(frozen=True)
class Table:
    """Where a cut falls among the values of a voxel, and the colour of the summed
    light there. `place` runs from 0 at the first value to 7, past the last edge,
    where the light is 0. `colour` is the share of R, G and B."""

    magnitudes: np.ndarray
    place: np.ndarray
    place_soft: np.ndarray
    colour: np.ndarray
    # B / (R + B) of the summed light at the tint edge.
    neutral_tint: float


def _places(summed: np.ndarray, wanted: np.ndarray, at: np.ndarray) -> np.ndarray:
    """The place of each `at`: where the light of `wanted` falls among the values a
    voxel holds, which `summed` gives at the edges. Both are on the curve points."""
    points = curve_points()
    knots = np.interp((-np.inf, *EDGES), points, summed, left=summed[0])
    knots[0] = summed[0]
    # Index 7 is the zero past the last edge.
    knots = np.concatenate((knots, (0.0,)))
    here = np.interp(at, points, wanted)
    # interp wants a rising x: knots fall.
    return np.interp(-here, -knots, np.arange(len(knots)))


def make_table(histogram: np.ndarray) -> Table:
    """`histogram` is the light of all stars by curve bin and channel."""
    points = curve_points()
    curve = fainter_curve(histogram)
    summed = curve.sum(axis=1)
    soft = soft_curve(curve).sum(axis=1)
    n = round((CURVE_HIGH - CURVE_LOW) / TABLE_STEP)
    magnitudes = CURVE_LOW + TABLE_STEP * np.arange(n + 1)
    colour = np.stack(
        [np.interp(magnitudes, points, curve[:, c]) for c in range(3)], axis=1
    )
    light_at = colour.sum(axis=1, keepdims=True)
    # Past the faintest star there is no light to take a colour from.
    shares = np.divide(
        colour, light_at, out=np.full_like(colour, np.nan), where=light_at > 0
    )
    known = np.flatnonzero(np.isfinite(shares[:, 0]))
    shares = np.where(np.isfinite(shares), shares, shares[known[-1]])
    edge = (
        np.interp(EDGES[TINT_EDGE], points, curve[:, 0]),
        np.interp(EDGES[TINT_EDGE], points, curve[:, 2]),
    )
    return Table(
        magnitudes,
        _places(summed, summed, magnitudes),
        _places(summed, soft, magnitudes),
        shares,
        float(edge[1] / (edge[0] + edge[1])),
    )


def voxel_values(light: np.ndarray) -> np.ndarray:
    """The eight values of each voxel from its light by bin, shape (..., bins, 3).

    Bin 0 is brighter than the first edge. The last value is the tint, NaN in a voxel
    with no light at the tint edge."""
    tail = np.cumsum(light[..., ::-1, :], axis=-2)[..., ::-1, :]
    summed = tail.sum(axis=-1)
    out = np.empty((*light.shape[:-2], VALUES), np.float64)
    out[..., : VALUES - 1] = summed
    at = tail[..., TINT_EDGE + 1, :]
    red_blue = at[..., 0] + at[..., 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        out[..., VALUES - 1] = at[..., 2] / red_blue
    return out


def shares(place: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The weights of the eight values for each place, shape (n, 8): the triangle of
    `place` over the seven L values, as `max(1 - abs(place - k), 0)`, and the weight
    of the zero past the last edge."""
    k = np.arange(VALUES - 1)
    weights = np.maximum(1 - np.abs(place[:, None] - k), 0.0)
    return weights, np.maximum(1 - np.abs(place - (VALUES - 1)), 0.0)


def rgb_of(
    light: np.ndarray, tint: np.ndarray, base: np.ndarray, neutral: float
) -> np.ndarray:
    """R, G, B from a read: the colour of the summed light moved by the tint."""
    t = np.clip(tint, 1e-3, 1 - 1e-3)
    factors = np.stack(((1 - t) / (1 - neutral), np.ones_like(t), t / neutral), axis=1)
    colour = base * factors
    return (colour / colour.sum(axis=1, keepdims=True)) * light[:, None]


def read_table(table: Table, m_cut: np.ndarray, soft: bool = False):
    """The table at a cut, as a shader reads it with linear steps."""
    place = np.interp(
        m_cut, table.magnitudes, table.place_soft if soft else table.place
    )
    colour = np.stack(
        [np.interp(m_cut, table.magnitudes, table.colour[:, c]) for c in range(3)],
        axis=1,
    )
    return place, colour


def read_values(
    filtered: np.ndarray, m_cut: np.ndarray, table: Table, soft: bool = False
):
    """R, G, B from the eight filtered values of each sample, shape (n, 8)."""
    place, base = read_table(table, m_cut, soft)
    weights, _ = shares(place)
    return rgb_of(
        (filtered[:, : VALUES - 1] * weights).sum(axis=1),
        filtered[:, VALUES - 1],
        base,
        table.neutral_tint,
    )
