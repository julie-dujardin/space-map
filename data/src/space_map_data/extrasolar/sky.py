"""HEALPix cells, sky regions and disc searches, all nested and ICRS.

A cell is a level-10 HEALPix cell, the cell of an ID. A region is a level-3
cell, the unit in which the registry and the tables are stored and processed.
Level 3 gives 768 regions. The positionable Gaia DR3 stars give a mean of 250k
rows per region and a maximum of about 1.9 M (measured from the gaia_source
chunk footers), so one region with its eight neighbours stays well under 2 GB,
and a store has few files for the backup to the NAS.

In the nested scheme the cells of one region are a contiguous range.
"""

from typing import overload

import astropy.units as u
import numpy as np
from astropy.coordinates import Latitude, Longitude
from cdshealpix import nested

from space_map_data.extrasolar.ids import CELL_LEVEL

REGION_LEVEL = 3
REGION_COUNT = 12 * 4**REGION_LEVEL
REGION_SHIFT = 2 * (CELL_LEVEL - REGION_LEVEL)

# Mean cell width at level 0, in degrees.
LEVEL0_SIZE = np.degrees(np.sqrt(4 * np.pi / 12))
# A disc of radius COVER × (mean cell width) around any point is inside the
# point's cell and its neighbours. Random probes first leave the 3×3 block at
# 0.65–0.7, near the poles and the base-pixel corners included.
COVER = 0.5
# Matching searches cells of this level, about 3.2″ wide, so a disc of a few
# arcsec sees few candidates in the densest star fields.
MATCH_LEVEL = 16


def cells(ra: np.ndarray, dec: np.ndarray, level: int = CELL_LEVEL) -> np.ndarray:
    """The nested cells of ICRS positions in degrees, as int64."""
    lon = Longitude(np.asarray(ra, np.float64), u.deg)
    lat = Latitude(np.asarray(dec, np.float64), u.deg)
    return nested.lonlat_to_healpix(lon, lat, level).astype(np.int64)


@overload
def region_of(cell: int) -> int: ...
@overload
def region_of(cell: np.ndarray) -> np.ndarray: ...
def region_of(cell):
    return cell >> REGION_SHIFT


def region_cells(region: int) -> tuple[int, int]:
    """The cells of `region`, as a half-open range."""
    return region << REGION_SHIFT, (region + 1) << REGION_SHIFT


def neighbour_regions(region: int) -> list[int]:
    """The regions that touch `region`, without it."""
    found = nested.neighbours(np.array([region], np.uint64), REGION_LEVEL)[0]
    return sorted({int(r) for r in found if r >= 0 and r != region})


def separation(
    ra1: np.ndarray | float,
    dec1: np.ndarray | float,
    ra2: np.ndarray | float,
    dec2: np.ndarray | float,
) -> np.ndarray:
    """Angular distance in arcsec between positions in degrees."""
    ra1, dec1, ra2, dec2 = (np.radians(a) for a in (ra1, dec1, ra2, dec2))
    h = (
        np.sin((dec2 - dec1) / 2) ** 2
        + np.cos(dec1) * np.cos(dec2) * np.sin((ra2 - ra1) / 2) ** 2
    )
    return np.degrees(2 * np.arcsin(np.sqrt(np.clip(h, 0, 1)))) * 3600


def disc_ranges(
    ra: np.ndarray, dec: np.ndarray, radius: np.ndarray, level: int = MATCH_LEVEL
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Cell ranges at `level` that hold every point within `radius` arcsec.

    Returns (row, low, high): row indexes into the inputs, and half-open cell
    ranges. Each disc takes the 3×3 block around its centre at the finest
    level up to `level` whose cells are wide enough for it, so the ranges hold
    more than the disc.
    """
    ra = np.asarray(ra, np.float64)
    dec = np.asarray(dec, np.float64)
    radius_deg = np.asarray(radius, np.float64) / 3600
    with np.errstate(divide="ignore"):
        fit = np.floor(np.log2(COVER * LEVEL0_SIZE / radius_deg))
    fits = np.clip(fit, -1, level).astype(np.int64)

    rows, lows, highs = [], [], []
    whole = np.flatnonzero(fits < 0)
    rows.append(whole)
    lows.append(np.zeros(whole.size, np.int64))
    highs.append(np.full(whole.size, 12 * 4**level, np.int64))

    centre = cells(ra, dec, level)
    for fit_level in np.unique(fits[fits >= 0]).tolist():
        picked = np.flatnonzero(fits == fit_level)
        shift = 2 * (level - fit_level)
        block = nested.neighbours(
            (centre[picked] >> shift).astype(np.uint64), fit_level
        ).astype(np.int64)
        row = np.repeat(picked, block.shape[1])
        block = block.ravel()
        keep = block >= 0
        rows.append(row[keep])
        lows.append(block[keep] << shift)
        highs.append((block[keep] + 1) << shift)
    return np.concatenate(rows), np.concatenate(lows), np.concatenate(highs)


def regions_of_ranges(
    low: np.ndarray, high: np.ndarray, level: int = MATCH_LEVEL
) -> list[int]:
    """The regions that cell ranges at `level` touch."""
    shift = 2 * (level - REGION_LEVEL)
    first = low >> shift
    last = (high - 1) >> shift
    found: set[int] = set()
    for a, b in set(zip(first.tolist(), last.tolist())):
        found.update(range(a, b + 1))
    return sorted(found)
