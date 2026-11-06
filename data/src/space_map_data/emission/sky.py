"""Maps of the sky from the Sun on HEALPix spheres, NESTED, in Galactic coordinates.

Nest axes are Galactic: x to l = 0, b = 0, y to l = 90 deg, z to b = 90 deg, so a
pixel's unit vector is its direction on nest axes.
"""

from functools import cache

import numpy as np
from astropy import units as u
from cdshealpix import nested
from scipy.spatial import KDTree


def depth_of(nside: int) -> int:
    return int(np.log2(nside))


@cache
def directions(nside: int) -> np.ndarray:
    """The unit vector of each pixel centre, shape (12 nside^2, 3)."""
    lon, lat = nested.healpix_to_lonlat(np.arange(12 * nside**2), depth_of(nside))
    lam, beta = lon.to_value(u.rad), lat.to_value(u.rad)
    return np.column_stack(
        (np.cos(beta) * np.cos(lam), np.cos(beta) * np.sin(lam), np.sin(beta))
    )


def latitudes(nside: int) -> np.ndarray:
    """Galactic latitude of each pixel centre, deg."""
    return np.degrees(np.arcsin(np.clip(directions(nside)[:, 2], -1, 1)))


def longitudes(nside: int) -> np.ndarray:
    d = directions(nside)
    return np.degrees(np.arctan2(d[:, 1], d[:, 0])) % 360.0


def degrade(sky: np.ndarray, nside_out: int) -> np.ndarray:
    """The mean over the NESTED children of each coarser pixel."""
    children = len(sky) // (12 * nside_out**2)
    return sky.reshape(-1, children).mean(axis=1)


def pixel_of(d: np.ndarray, nside: int) -> np.ndarray:
    """The pixel holding each unit vector."""
    lon = np.arctan2(d[:, 1], d[:, 0]) % (2 * np.pi)
    lat = np.arcsin(np.clip(d[:, 2], -1, 1))
    return nested.lonlat_to_healpix(lon * u.rad, lat * u.rad, depth_of(nside)).astype(
        np.int64
    )


def smooth(sky: np.ndarray, sigma_deg: float) -> np.ndarray:
    """A Gaussian of `sigma_deg` on the sphere, to 3 sigma, pixels of equal area."""
    if sigma_deg <= 0:
        return sky.copy()
    nside = int(np.sqrt(len(sky) / 12))
    d = directions(nside)
    tree = KDTree(d)
    sigma = np.radians(sigma_deg)
    reach = 2 * np.sin(3 * sigma / 2)
    out = np.empty(len(sky))
    chunk = 4096
    for start in range(0, len(sky), chunk):
        part = d[start : start + chunk]
        lists = tree.query_ball_point(part, reach)
        for i, near in enumerate(lists):
            near = np.asarray(near)
            cos = np.clip(d[near] @ part[i], -1, 1)
            w = np.exp(-0.5 * (np.arccos(cos) / sigma) ** 2)
            out[start + i] = (w * sky[near]).sum() / w.sum()
    return out


def interpolate(sky: np.ndarray, d: np.ndarray, tree: KDTree) -> np.ndarray:
    """A map at unit vectors, by the inverse-distance mean of the four nearest pixel
    centres: smooth enough for a map that is itself smooth at a few pixels. `tree`
    holds the map's `directions`."""
    dist, index = tree.query(d, k=4)
    w = 1.0 / np.maximum(dist, 1e-9) ** 2
    return (w * sky[index]).sum(axis=1) / w.sum(axis=1)


def paint(
    axes: np.ndarray, sigma_rad: np.ndarray, flux: np.ndarray, nside: int
) -> np.ndarray:
    """Gaussian balls on a sky: `flux` (n, c) spread about each unit vector of `axes`
    with its `sigma_rad`, per sr, shape (pixels, c). A ball under half a pixel takes
    half a pixel, so each lands on its pixel and its neighbours."""
    d = directions(nside)
    pixel_sr = 4 * np.pi / len(d)
    pixel = np.sqrt(pixel_sr)
    tree = KDTree(d)
    out = np.zeros((len(d), flux.shape[1]))
    for i in range(len(axes)):
        sigma = max(sigma_rad[i], pixel / 2)
        reach = 3 * sigma + 2 * pixel
        near = np.asarray(tree.query_ball_point(axes[i], 2 * np.sin(reach / 2)))
        if len(near) == 0:
            near = np.array([tree.query(axes[i])[1]])
        angle = np.arccos(np.clip(d[near] @ axes[i], -1, 1))
        w = np.exp(-0.5 * (angle / sigma) ** 2)
        out[near] += flux[i] * (w / w.sum() / pixel_sr)[:, None]
    return out


def band_mask(nside: int, low: float, high: float) -> np.ndarray:
    b = np.abs(latitudes(nside))
    return (b >= low) & (b < high)


def disc_mask(nside: int, l_deg: float, b_deg: float, radius_deg: float) -> np.ndarray:
    lam, beta = np.radians(l_deg), np.radians(b_deg)
    axis = np.array(
        (np.cos(beta) * np.cos(lam), np.cos(beta) * np.sin(lam), np.sin(beta))
    )
    return directions(nside) @ axis >= np.cos(np.radians(radius_deg))
