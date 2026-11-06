"""The textures of the light grid: linear flux density in half floats.

A half float filters exactly, so the textures need no decode and no compensation.
"""

import numpy as np

# A half float reaches 65504. A power of two keeps a value's bits.
TOP = 32768.0


def scale_of(values: np.ndarray) -> float:
    """The factor from flux density to the texture: a power of two, the same on every
    tier, so one uniform reads both."""
    top = float(values.max())
    if top <= 0:
        raise ValueError("no light in the grid")
    return float(2.0 ** np.floor(np.log2(TOP / top)))


def half_bits(values: np.ndarray) -> np.ndarray:
    """The uint16 bits of each value as a half float."""
    return np.ascontiguousarray(values.astype(np.float16)).view(np.uint16)


def bits_to_values(bits: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(bits, np.uint16).view(np.float16).astype(np.float32)


def encode_values(values: np.ndarray, scale: float) -> np.ndarray:
    """uint16 bits of a grid of eight values. The last value is the tint."""
    scaled = values.astype(np.float64)
    scaled[..., :-1] *= scale
    return half_bits(scaled)
