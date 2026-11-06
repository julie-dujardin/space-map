"""A star's interior from the grid tables, with ranges.

The fit gives each model point a weight from its distance to the star, in
the star's widths. Over the HR diagram the weight is a stack of boxes around
the star, BOXES widths wide on each side: a point in the inner box gets the
weight of every box. So the weight falls with the distance in steps, as a
Gaussian does. Over [Fe/H] the weight is a Gaussian, sampled at FEH_SAMPLES
widths and shared linearly between the two nearest grid [Fe/H]. A width
of log Teff or log L is the star's, with the grid's resolution added in
quadrature, so that a box always holds whole cells.

The value is the weighted mean of the points, and the range is one weighted
standard deviation on each side. So the range holds the spread in age and
stage and the errors of the inputs. The stage is the stage of most weight.

A quantity of AT_ZERO is 0 for the fully convective points and above 0 for
the others, so its posterior can have two modes. The fit takes it as the
fully convective share at 0 plus a Gaussian with the mean and the standard
deviation of the other points. The value is 0 when that share is half or
more, else the mean of the other points. The range runs between the
percentiles of this mixture at -1 and +1 standard deviation. With no fully
convective weight, value and range are those of the other quantities.

A star is outside the grid when no model point is within 3 of its widths:
its [Fe/H] samples miss the grid's [Fe/H], or its outer box holds no point.
"""

from dataclasses import dataclass, fields

import numpy as np
from scipy.special import ndtr, ndtri

from space_map_data.extrasolar.interiors.grid import (
    AT_ZERO,
    CHANNELS,
    COUNT,
    FIRST,
    LOG_L_AXIS,
    LOG_TEFF_AXIS,
    NO_STAGE,
    QUANTITIES,
    SECOND,
    STAGE,
    WEIGHT,
    ZERO,
    Tables,
)

# Rows in one pass, to bound the memory of the reads.
CHUNK = 200_000
# The resolution of the grid, dex: one and a half cells.
MIN_SIGMA_LOG_TEFF = 0.0075
MIN_SIGMA_LOG_L = 0.03
# The half-widths of the boxes in widths. The weight of a box is the step of
# the Gaussian at the middle of its band.
BOXES = np.array([1.0, 2.0, 3.0])
_LEVELS = np.exp(-0.5 * (BOXES - 0.5) ** 2)
BOX_WEIGHTS = _LEVELS - np.r_[_LEVELS[1:], 0.0]
FEH_SAMPLES = np.arange(-3.0, 3.01, 0.5)
FEH_WEIGHTS = np.exp(-0.5 * FEH_SAMPLES**2)
# The percentiles of a Gaussian at -1 and +1 standard deviation.
LOWER_PERCENTILE, UPPER_PERCENTILE = float(ndtr(-1.0)), float(ndtr(1.0))


@dataclass(frozen=True)
class Fit:
    """(stars, QUANTITIES) arrays, NaN outside the grid."""

    value: np.ndarray
    lower: np.ndarray
    upper: np.ndarray
    # An index of STAGES, NO_STAGE outside the grid.
    stage: np.ndarray
    inside: np.ndarray
    # Some [Fe/H] sample is on the grid.
    feh_inside: np.ndarray


def node_weights(nodes: np.ndarray, feh: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """The weight of each grid [Fe/H] for each star, (stars, nodes)."""
    out = np.zeros((feh.size, nodes.size))
    rows = np.arange(feh.size)
    for offset, weight in zip(FEH_SAMPLES, FEH_WEIGHTS, strict=True):
        at = feh + offset * sigma
        on = (at >= nodes[0]) & (at <= nodes[-1])
        low = np.clip(np.searchsorted(nodes, at, side="right") - 1, 0, nodes.size - 2)
        share = np.clip((at - nodes[low]) / (nodes[low + 1] - nodes[low]), 0.0, 1.0)
        out[rows, low] += np.where(on, weight * (1.0 - share), 0.0)
        out[rows, low + 1] += np.where(on, weight * share, 0.0)
    return out


def _mixture_percentile(
    zero: np.ndarray, mean: np.ndarray, std: np.ndarray, p: float
) -> np.ndarray:
    """The percentile `p` of a share `zero` at 0 and a Gaussian for the rest."""
    with np.errstate(invalid="ignore", divide="ignore"):
        rest = np.clip((p - zero) / (1.0 - zero), 0.0, 1.0)
        return np.where(zero >= p, 0.0, mean + std * ndtri(rest))


def _with_zero_mode(
    found: np.ndarray, mean: np.ndarray, lower: np.ndarray, upper: np.ndarray
) -> None:
    """Writes the value and range of each quantity of AT_ZERO into `mean`,
    `lower` and `upper`."""
    weight = found[:, WEIGHT]
    for k, name in enumerate(AT_ZERO):
        q = QUANTITIES.index(name)
        zero_weight = found[:, ZERO.start + k]
        rest = weight - zero_weight
        with np.errstate(invalid="ignore", divide="ignore"):
            zero = np.clip(zero_weight / weight, 0.0, 1.0)
            rest_mean = found[:, FIRST.start + q] / rest
            rest_std = np.sqrt(
                np.maximum(found[:, SECOND.start + q] / rest - rest_mean**2, 0.0)
            )
        rest_mean = np.where(zero < 1, rest_mean, 0.0)
        rest_std = np.where(zero < 1, rest_std, 0.0)
        mean[:, q] = np.where(zero >= 0.5, 0.0, rest_mean)
        lower[:, q] = _mixture_percentile(zero, rest_mean, rest_std, LOWER_PERCENTILE)
        upper[:, q] = _mixture_percentile(zero, rest_mean, rest_std, UPPER_PERCENTILE)


def _edges(
    centre: np.ndarray, sigma: np.ndarray, axis: tuple[float, float, float], size: int
) -> list[tuple[np.ndarray, np.ndarray]]:
    """The first cell and the cell past the last of each box, clipped to the
    axis. A box holds the cells whose centres it holds."""
    low, _, step = axis
    out = []
    for half in BOXES:
        first = np.ceil((centre - half * sigma - low) / step)
        past = np.floor((centre + half * sigma - low) / step) + 1
        first = np.clip(first, 0, size).astype(np.int64)
        out.append((first, np.maximum(first, np.clip(past, 0, size).astype(np.int64))))
    return out


def fit(
    tables: Tables,
    log_teff: np.ndarray,
    sigma_log_teff: np.ndarray,
    log_l: np.ndarray,
    sigma_log_l: np.ndarray,
    feh: np.ndarray,
    sigma_feh: np.ndarray,
) -> Fit:
    """The interior of each star. Every input must be finite."""
    inputs = (log_teff, sigma_log_teff, log_l, sigma_log_l, feh, sigma_feh)
    if not all(np.isfinite(a).all() for a in inputs):
        raise ValueError("fit: an input or a width is not finite")
    parts = [
        _fit(tables, *(a[at : at + CHUNK] for a in inputs))
        for at in range(0, max(len(log_teff), 1), CHUNK)
    ]
    return Fit(
        *(np.concatenate([getattr(p, f.name) for p in parts]) for f in fields(Fit))
    )


def _fit(
    tables: Tables,
    log_teff: np.ndarray,
    sigma_log_teff: np.ndarray,
    log_l: np.ndarray,
    sigma_log_l: np.ndarray,
    feh: np.ndarray,
    sigma_feh: np.ndarray,
) -> Fit:
    n_t, n_l = tables.sums.shape[1] - 1, tables.sums.shape[2] - 1
    teff_edges = _edges(
        log_teff, np.hypot(sigma_log_teff, MIN_SIGMA_LOG_TEFF), LOG_TEFF_AXIS, n_t
    )
    l_edges = _edges(log_l, np.hypot(sigma_log_l, MIN_SIGMA_LOG_L), LOG_L_AXIS, n_l)
    weights = node_weights(tables.feh, feh, sigma_feh)
    found = np.zeros((log_teff.size, CHANNELS))
    for node in range(tables.feh.size):
        rows = np.flatnonzero(weights[:, node] > 0)
        if not rows.size:
            continue
        sums = tables.sums[node]
        part = np.zeros((rows.size, CHANNELS))
        for box_weight, (i0, i1), (j0, j1) in zip(
            BOX_WEIGHTS, teff_edges, l_edges, strict=True
        ):
            a, b, c, d = i0[rows], i1[rows], j0[rows], j1[rows]
            part += box_weight * (sums[a, c] - sums[b, c] - sums[a, d] + sums[b, d])
        found[rows] += weights[rows, node, None] * part

    weight = found[:, WEIGHT]
    inside = (found[:, COUNT] > 0) & (weight > 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = found[:, FIRST] / weight[:, None]
        square = found[:, SECOND] / weight[:, None]
        std = np.sqrt(np.maximum(square - mean**2, 0.0))
    lower, upper = mean - std, mean + std
    _with_zero_mode(found, mean, lower, upper)
    stage = np.where(inside, np.argmax(found[:, STAGE], axis=1), NO_STAGE)
    nan = np.full(mean.shape, np.nan)
    return Fit(
        np.where(inside[:, None], mean, nan),
        np.where(inside[:, None], lower, nan),
        np.where(inside[:, None], upper, nan),
        stage.astype(np.uint8),
        inside,
        weights.sum(axis=1) > 0,
    )
