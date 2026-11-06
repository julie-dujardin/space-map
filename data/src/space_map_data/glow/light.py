"""The light of one star, with the Sun's dust taken out.

The tree's `mag` is an absolute G that still holds the Sun's dust. The shader draws

    m = mag + DM(s) + K_G * max(A(camera, star) - A(Sun, star), -bound)

where `bound` is the most A0 a star can gain: no more than its colour shows it lost,
and no more than takes it to `BRIGHTEST_M0`. It is 0 with no colour. The shader reads
it as one byte of 0 to `BOUND_MAX`, so the grid takes the same byte. The grid takes
out `min(A(Sun, star), bound)`:

    M0 = mag - K_G * min(A(Sun, star), bound)

A star within the bound is drawn when `M0 < uLimit - DM(s) - K_G * A(camera, s)`. A
star past it has a rest `E = A(Sun, star) - bound`, and the shader draws it when
`M0 + DM(s) + K_G * max(A(camera, star) - E, 0) < uLimit`.

The constants and `dust_bound` are those of `frontend/src/lib/scene/dust/extinction.ts`.
"""

import numpy as np

K_G = 0.825
K_RGB = np.array((0.863, 1.004, 1.273))
# The bluest BP - RP of a star, and BP - RP per A0 at 550 nm.
BLUEST = -0.3
REDDENING = 0.447
# The brightest absolute G of any real star.
BRIGHTEST_M0 = -10.0
# The byte of the bound spans 0 to this many A0.
BOUND_MAX = 16.0


def dust_bound(bp_rp: np.ndarray, mag: np.ndarray) -> np.ndarray:
    """The most A0 a star can gain, as the shader reads it from its byte. A star with
    no colour gains none."""
    bp_rp, mag = np.asarray(bp_rp, np.float64), np.asarray(mag, np.float64)
    bound = np.minimum((bp_rp - BLUEST) / REDDENING, (mag - BRIGHTEST_M0) / K_G)
    # A NaN colour or magnitude fails the test and gives 0.
    bound = np.where(bound > 0, bound, 0.0)
    # `Math.round` takes a half up.
    byte = np.floor(np.minimum(bound, BOUND_MAX) / BOUND_MAX * 255.0 + 0.5)
    return byte / 255.0 * BOUND_MAX


def taken_out(column: np.ndarray, bp_rp: np.ndarray, mag: np.ndarray) -> np.ndarray:
    """The A0 that the grid gives back to each star."""
    return np.minimum(column, dust_bound(bp_rp, mag))


def dust_free_magnitude(mag: np.ndarray, taken: np.ndarray) -> np.ndarray:
    """M0."""
    return mag - K_G * taken


def star_flux(mag: np.ndarray, colour: np.ndarray, taken: np.ndarray) -> np.ndarray:
    """Linear flux per display channel at 10 pc, shape (n, 3). M = 0 in a channel of
    1 is 1. Each channel takes its own K, so a ray back through the same column
    gives the star's colour and flux."""
    return colour * 10.0 ** (-0.4 * (mag[:, None] - K_RGB * taken[:, None]))
