"""The textures of the emission: R8 codes for H-alpha, half floats for J.

H-alpha takes the dust's logarithmic code (`dust.encode.Encoding`), compensated for
LINEAR. On these steep H II edges the compensated codes still read about 3% high
over the volume, so the floor takes a gain that sets the mean read of LINEAR at
random points to the mean of the float cube. The decode stays
`floor * expm1(code / 255 * span)`.
"""

import numpy as np

from space_map_data.dust.encode import Encoding, compensate
from space_map_data.dust.march import linear_fetch

# Display flux per pc^3 at the bottom of the code. The faintest tenth of the ionised
# voxels is near 2e-9.
HALPHA_FLOOR = 1e-9
GAIN_POINTS = 4_000_000


def linear_read(codes: np.ndarray, encoding: Encoding, at: np.ndarray) -> np.ndarray:
    """LINEAR on the codes at texture coordinates, then the decode."""
    filtered = linear_fetch(np.asarray(codes, np.float32), at)
    return encoding.floor * np.expm1(filtered / 255.0 * encoding.span)


def halpha_codes(
    cube: np.ndarray, top: float, seed: int = 0
) -> tuple[np.ndarray, Encoding]:
    """Compensated codes of a cube [x, y, z] and its encoding, the floor with the
    gain folded in."""
    plain = Encoding(HALPHA_FLOOR, top)
    codes = compensate(cube, plain)
    at = np.random.default_rng(seed).random((GAIN_POINTS, 3))
    read = linear_read(codes, plain, at).mean()
    wanted = linear_fetch(cube, at).mean()
    gain = float(wanted / read)
    # expm1 scales with the floor, so the span keeps top / floor.
    return codes, Encoding(HALPHA_FLOOR * gain, top * gain)


def half_bits(values: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(values.astype(np.float16)).view(np.uint16)


def scale_of(values: np.ndarray, top: float = 32768.0) -> float:
    """A power of two that takes the largest value under `top`."""
    largest = float(np.max(values))
    return float(2.0 ** np.floor(np.log2(top / largest)))
