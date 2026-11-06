"""The display colour of a star, as `frontend/src/lib/scene/starfield/colour.ts`
gives it: BP - RP to a dwarf's Teff, then the Planckian locus in linear sRGB with
the largest channel at 1, in 512 steps of bytes."""

import numpy as np

from space_map_data.export.extrasolar.render import TEFF_BP_RP

LUT_SIZE = 512
_ROWS = np.array(TEFF_BP_RP[::-1])
_BP_RP = _ROWS[:, 1]
_TEFF = _ROWS[:, 0]
LUT_LOW = float(_BP_RP[0])
LUT_HIGH = float(_BP_RP[-1])


def planckian_rgb(teff: np.ndarray) -> np.ndarray:
    """`planckianRgb`: linear sRGB, shape (n, 3), with its largest channel at 1."""
    t = np.clip(teff, 1667.0, 25000.0)
    t1 = 1e3 / t
    t2 = t1 * t1
    t3 = t2 * t1
    x = np.where(
        t <= 4000,
        -0.2661239 * t3 - 0.2343589 * t2 + 0.8776956 * t1 + 0.17991,
        -3.0258469 * t3 + 2.1070379 * t2 + 0.2226347 * t1 + 0.24039,
    )
    x2 = x * x
    x3 = x2 * x
    y = np.select(
        [t <= 2222, t <= 4000],
        [
            -1.1063814 * x3 - 1.3481102 * x2 + 2.18555832 * x - 0.20219683,
            -0.9549476 * x3 - 1.37418593 * x2 + 2.09137015 * x - 0.16748867,
        ],
        3.081758 * x3 - 5.8733867 * x2 + 3.75112997 * x - 0.37001483,
    )
    big_x = x / y
    big_z = (1 - x - y) / y
    rgb = np.stack(
        (
            np.maximum(3.2404542 * big_x - 1.5371385 - 0.4985314 * big_z, 0),
            np.maximum(-0.969266 * big_x + 1.8760108 + 0.041556 * big_z, 0),
            np.maximum(0.0556434 * big_x - 0.2040259 + 1.0572252 * big_z, 0),
        ),
        axis=-1,
    )
    return rgb / rgb.max(axis=-1, keepdims=True)


def colour_table() -> np.ndarray:
    """The bytes of `buildLut`, shape (LUT_SIZE, 3), as floats of 1."""
    bp_rp = LUT_LOW + (LUT_HIGH - LUT_LOW) * np.arange(LUT_SIZE) / (LUT_SIZE - 1)
    teff = np.interp(bp_rp, _BP_RP, _TEFF)
    # Math.round rounds a half up, as floor(x + 0.5) does.
    return np.floor(planckian_rgb(teff) * 255 + 0.5) / 255


_TABLE = colour_table()


def star_colours(bp_rp: np.ndarray) -> np.ndarray:
    """`starColours`, shape (n, 3): the colour of each star, white for NaN."""
    scale = (LUT_SIZE - 1) / (LUT_HIGH - LUT_LOW)
    known = np.isfinite(bp_rp)
    at = np.floor(
        np.clip((np.nan_to_num(bp_rp) - LUT_LOW) * scale, 0, LUT_SIZE - 1) + 0.5
    )
    return np.where(known[:, None], _TABLE[at.astype(np.int32)], 1.0)
