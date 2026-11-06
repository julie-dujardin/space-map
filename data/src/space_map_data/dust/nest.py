"""The levels of the nest, its frame and the hand-over weights.

Positions are Sun-centred Galactic Cartesian in pc: x to the Galactic centre,
y to l = 90 deg, z to the north Galactic pole. An array of a level has the index
order [ix, iy, iz].
"""

from dataclasses import dataclass

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord

# Edenhofer ends at 1,248 pc and its 2 kpc map at 1,995 pc.
LOCAL_FADE = (1050.0, 1240.0)
REGIONAL_FADE = (1500.0, 1950.0)
# The EXPLORE cubes end at |z| = 400 pc and at their box edges.
CUBE_Z_FADE = (340.0, 395.0)
CUBE_25_FADE = (2400.0, 2990.0)
CUBE_50_FADE = (4000.0, 4980.0)


@dataclass(frozen=True)
class Level:
    index: int
    half: tuple[float, float, float]
    shape: tuple[int, int, int]

    @property
    def voxel(self) -> np.ndarray:
        return 2 * np.array(self.half) / np.array(self.shape)

    @property
    def low_shape(self) -> tuple[int, int, int]:
        nx, ny, nz = self.shape
        return nx // 2, ny // 2, nz // 2

    def centres(self, axis: int) -> np.ndarray:
        n = self.shape[axis]
        return (np.arange(n) + 0.5) * self.voxel[axis] - self.half[axis]


LEVELS = (
    Level(0, (20000.0, 20000.0, 2000.0), (512, 512, 64)),
    Level(1, (3000.0, 3000.0, 3000.0), (256, 256, 256)),
    Level(2, (1250.0, 1250.0, 1250.0), (256, 256, 256)),
    Level(3, (250.0, 250.0, 250.0), (256, 256, 256)),
)


def galactic_to_icrs() -> np.ndarray:
    """The matrix M with v_icrs = M v_galactic."""
    axes = SkyCoord(
        l=[0.0, 90.0, 0.0] * u.deg, b=[0.0, 0.0, 90.0] * u.deg, frame="galactic"
    ).icrs
    return np.array(axes.cartesian.xyz.value)


def lonlat(
    x: np.ndarray, y: np.ndarray, z: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Galactic longitude and latitude in radians, and the distance in pc."""
    r = np.sqrt(x * x + y * y + z * z)
    lon = np.arctan2(y, x)
    lon = np.where(lon < 0, lon + 2 * np.pi, lon)
    lat = np.arcsin(np.clip(z / np.maximum(r, 1e-9), -1, 1))
    return lon, lat, r


def directions(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """Unit vectors, shape (n, 3), from Galactic longitude and latitude in radians."""
    return np.stack(
        (np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)), axis=-1
    )


def smoothstep(t: np.ndarray) -> np.ndarray:
    """0 below 0, 1 above 1, 3 t^2 - 2 t^3 between."""
    s = np.clip(t, 0.0, 1.0)
    return s * s * (3.0 - 2.0 * s)


def fade_out(
    t: np.ndarray, start: float | np.ndarray, end: float | np.ndarray
) -> np.ndarray:
    """1 below `start`, 0 above `end`, smooth in the band."""
    return 1.0 - smoothstep((t - start) / (end - start))


def local_weight(r: np.ndarray) -> np.ndarray:
    """The share of Edenhofer 2024."""
    return fade_out(r, *LOCAL_FADE)


def regional_weight(r: np.ndarray) -> np.ndarray:
    """The share of the Edenhofer 2 kpc map in what the local layer leaves."""
    return fade_out(r, *REGIONAL_FADE)


def cube_weights(
    x: np.ndarray, y: np.ndarray, z: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """The shares of the 25 pc cube and of the 50 pc cube in what it leaves."""
    plane = np.maximum(np.abs(x), np.abs(y))
    height = fade_out(np.abs(z), *CUBE_Z_FADE)
    return (
        fade_out(plane, *CUBE_25_FADE) * height,
        fade_out(plane, *CUBE_50_FADE) * height,
    )
