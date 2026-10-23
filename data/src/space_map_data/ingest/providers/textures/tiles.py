"""Tile pyramids: an equirectangular map cut into WebP tiles at doubling sizes.

Level ``z`` covers the globe with ``2^(z+1) × 2^z`` tiles, so level 0 is two
tiles side by side. A tile is ``{z}/{x}/{y}.webp``, ``x`` counted east from
180°W and ``y`` south from the north pole, in the renderer's alignment.

The finest level is resampled from the source one tile row at a time, and each
coarser level is the 2×2 average of the one above. Memory stays near a few tile
rows, however large the source is.

A level too wide for that is built in square blocks instead, each one the
footprint of a single tile a few levels down, and can resume after a stop.

A colour pyramid can take its fine detail from sharper greyscale maps: see
``PyramidBuilder._sharpen``.

Each pyramid also has a cap over each pole, in a projection that does not
stretch there: see ``Cap``.
"""

import hashlib
import json
import logging
import math
import os
import shutil
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import Path
from typing import Protocol

import numpy as np
import tifffile
from PIL import Image
from scipy import ndimage, spatial

from . import config
from .encoding import linear_to_srgb, webp_kwargs
from .image_io import (
    GAP_REPAIR_PASSES,
    NODATA_THRESHOLD,
    ChunkedTiff,
    HeightRaster,
    mean_column,
    memmap_page,
    open_height_raster,
    open_image,
    open_pds_height_raster,
    open_pds_image,
    read_pds_label,
    repair_thin_gaps,
)

log = logging.getLogger(__name__)

# Bump when the same inputs would now produce different tiles.
RECIPE = 1
# The same, for the pyramids that take their detail from brightness layers.
SHARPEN_RECIPE = 2
# The same, for the terrain models that fill their gaps from a coarser one.
FILL_RECIPE = 2

# Bicubic reach in source pixels at unit scale; it widens when shrinking.
_FILTER_SUPPORT = 2.0
# Source pixels a window holds at a time. Near a pole a cap square maps to a
# few columns of a narrow grid, each thousands of source columns wide: read
# whole, the squares of one row outgrow the build's memory.
_WINDOW_PIXELS = 1 << 24
# Sizes in blocks for the offset of a terrain model's fill from the measured
# model at their border: the reach of the median of its samples, the blur
# along the border, and the distance from the border where the fill keeps its
# own heights.
_FILL_SEAM_MEDIAN = 10.0
_FILL_SEAM_BLUR = 5.0
_FILL_SEAM_REACH = 15.0
# Fewest output columns in a piece of a window: each piece reads the filter's
# reach again on both sides.
_WINDOW_COLUMNS = 32
# Source rows per chunk when scanning a DEM for its height range.
_SCAN_ROWS = 1024
# Output columns reprojected or sharpened at a time, to bound the working
# arrays: a whole row of the finest level is 131,072 px wide.
_REPROJECT_COLUMNS = 16384
_SHARPEN_COLUMNS = 16384
HEIGHT_LEVELS = 65535
# Finest level the builder can hold a whole tile row of: level 8 is 524,288 px
# wide, 1.6 GB a row as RGB.
MAX_BAND_LEVEL = 8
# Above it the finest level is built in blocks of 2^4 tiles a side, each the
# footprint of one tile four levels down.
BLOCK_LEVELS = 4
# Blocks built at once. Each holds about 2.5 GB at its peak.
BLOCK_WORKERS = 4
# A blur wider than twice this many pixels runs on a reduced copy that keeps
# this many: the blur only has to hold what is coarser than itself.
_REDUCED_SIGMA = 8.0
# Rows of a block sharpened at a time. A source finer than the level reads
# several of its own rows for each one.
_SHARPEN_ROWS = 512
# A cap's sides touch latitude 45°: the tangent of half that colatitude.
_CAP_EDGE = math.tan(math.pi / 8)
# Side of the squares a cap is reprojected in. A square keeps the source read
# small: the latitudes and longitudes of a long strip span far more than its
# own pixels.
_CAP_CHUNK = 2048
# Narrowest an equirectangular grid is read for a cap, right at the pole.
_CAP_MIN_WIDTH = 16
# Squares reprojected at once.
_CAP_WORKERS = 8
# Where a pyramid keeps each cap, and whether it is the north one.
CAP_FOLDERS = {"north": True, "south": False}

_SRGB_TO_LINEAR = np.where(
    np.arange(256) <= 10,
    np.arange(256) / 255 / 12.92,
    ((np.arange(256) / 255 + 0.055) / 1.055) ** 2.4,
).astype(np.float32)
_LINEAR_TO_SRGB = np.rint(linear_to_srgb(np.linspace(0.0, 1.0, 65536)) * 255).astype(
    np.uint8
)


def level_width(level: int) -> int:
    return 2 * config.TILE_SIZE << level


def finest_level(source_width: int) -> int:
    """The level that holds the source's detail without a needless doubling."""
    level = 0
    while level_width(level) * (1 + config.TILE_LEVEL_SLACK) < source_width:
        level += 1
    return level


@dataclass(frozen=True)
class Placement:
    """Where a raster sits on the globe: its latitude band (full longitude)
    and the manifest's alignment fields."""

    lat_top: float = 90.0
    lat_bottom: float = -90.0
    west_positive: bool = False
    lon_at_left_deg: float = -180.0

    def covers(self, lats: np.ndarray) -> np.ndarray:
        return (lats <= self.lat_top) & (lats >= self.lat_bottom)


@dataclass(frozen=True)
class Cap:
    """One pole's grid: a square of the polar stereographic projection whose
    sides touch latitude 45°. Its pixels are close to the size of the same
    equirectangular level's at the pole.

    Level ``z`` has ``2^(z-1)`` tiles a side, so level 1 is one tile. The cap
    is drawn as seen from above its pole, the prime meridian to the right:
    east turns counter-clockwise in the north and clockwise in the south.
    """

    north: bool
    level: int

    @property
    def size(self) -> int:
        return config.TILE_SIZE << (self.level - 1)

    def plane(
        self, y0: int, y1: int, x0: int, x1: int
    ) -> tuple[np.ndarray, np.ndarray]:
        """Pixel centres on the projection plane: ``x`` of the columns to the
        right and ``y`` of the rows up, 1 at the middle of a side."""
        half = self.size / 2
        x = (np.arange(x0, x1) + 0.5) / half - 1.0
        y = 1.0 - (np.arange(y0, y1) + 0.5) / half
        return x, y

    def latitudes(self, y0: int, y1: int, x0: int, x1: int) -> np.ndarray:
        x, y = self.plane(y0, y1, x0, x1)
        reach = np.hypot(x[None, :], y[:, None])
        colatitude = np.degrees(2 * np.arctan(reach * _CAP_EDGE))
        return 90.0 - colatitude if self.north else colatitude - 90.0


class Source(Protocol):
    """A raster the builder can sample into rows of the output grid."""

    @property
    def placement(self) -> Placement: ...

    @property
    def width(self) -> int:
        """Pixels around the equator at the raster's own resolution."""
        ...

    @property
    def dimensions(self) -> list[int]: ...

    def window(self, out_w: int, lat_edges: np.ndarray, x0: int, x1: int) -> np.ndarray:
        """Columns ``x0:x1`` of the output rows bounded by ``lat_edges``, on a
        grid ``out_w`` wide. Columns outside the grid wrap around the globe."""
        ...

    def cap(self, cap: Cap, y0: int, y1: int, x0: int, x1: int) -> np.ndarray:
        """Rows ``y0:y1`` and columns ``x0:x1`` of ``cap``. Pixels past its
        sides are the ground further from the pole."""
        ...

    def release(self) -> None:
        """Drop what was read into memory; the rows it covers are done."""
        ...


# Files a mosaic keeps mapped. The page tables of a mapping stay until it is
# unmapped, at 1/512 of the bytes read through it: Mars' 8.9 TB of quads held
# mapped is 17 GB of them.
_MOSAIC_OPEN = 256


class Mosaic:
    """Adjoining rasters of one size, read as a single array: rows north to
    south, each row west to east.

    A cell given as a path is opened by ``open_cell`` when a read touches it
    and let go once enough others were read since, so a mosaic of thousands
    of files only maps the few under the window. Cells are grey unless
    ``open_cell`` gives colour.
    """

    def __init__(
        self,
        grid: Sequence[Sequence[np.ndarray | Path]],
        open_cell: Callable[[Path], np.ndarray | ChunkedTiff] | None = None,
    ) -> None:
        self._grid = [list(row) for row in grid]
        self._open = open_cell or _open_grey
        self._mapped: OrderedDict[tuple[int, int], np.ndarray | ChunkedTiff] = (
            OrderedDict()
        )
        self._lock = threading.Lock()
        first = self._grid[0][0]
        if isinstance(first, Path):
            first = self._open(first)
        self._tile_h, self._tile_w = first.shape[:2]
        self._bands = tuple(first.shape[2:])
        for row in self._grid:
            for cell in row:
                if isinstance(cell, np.ndarray):
                    self._check(cell)
        self.shape = (
            self._tile_h * len(grid),
            self._tile_w * len(grid[0]),
            *self._bands,
        )

    def _check(self, tile: np.ndarray | ChunkedTiff) -> None:
        if tile.shape != (self._tile_h, self._tile_w, *self._bands):
            raise ValueError("mosaic tiles differ in size")

    def _tile(self, row: int, col: int) -> np.ndarray | ChunkedTiff:
        cell = self._grid[row][col]
        if isinstance(cell, np.ndarray):
            return cell
        with self._lock:
            tile = self._mapped.get((row, col))
            if tile is None:
                tile = self._mapped[row, col] = self._open(cell)
                self._check(tile)
                if len(self._mapped) > _MOSAIC_OPEN:
                    # A read that still holds the oldest keeps it mapped.
                    self._mapped.popitem(last=False)
            else:
                self._mapped.move_to_end((row, col))
        return tile

    def read(self, y0: int, y1: int, x0: int, x1: int) -> np.ndarray:
        th, tw = self._tile_h, self._tile_w
        bands = []
        for row in range(y0 // th, (y1 - 1) // th + 1):
            top = row * th
            parts = [
                self._tile(row, col)[
                    max(y0, top) - top : min(y1, top + th) - top,
                    max(x0, col * tw) - col * tw : min(x1, (col + 1) * tw) - col * tw,
                ]
                for col in range(x0 // tw, (x1 - 1) // tw + 1)
            ]
            bands.append(np.concatenate(parts, axis=1))
        return np.concatenate(bands, axis=0)

    def release(self) -> None:
        """Let go of the files opened so far, and of what was decoded of
        them; a later read opens them again."""
        with self._lock:
            self._mapped.clear()


class Region:
    """A raster of a part of the globe, read as one that covers all of it at
    the same pixel size. Where it has nothing it reads as ``blank``. Without
    one, that is what a brightness reader takes as not observed: zero, or NaN
    for float samples."""

    def __init__(
        self,
        pixels: np.ndarray | ChunkedTiff | SmoothedFill,
        west: float,
        east: float,
        north: float,
        south: float,
        blank: float | None = None,
    ) -> None:
        height, width = pixels.shape
        self._pixels = pixels
        self._blank = blank
        self.shape = (
            round(height * 180.0 / (north - south)),
            round(width * 360.0 / (east - west)),
        )
        self._top = round((90.0 - north) / 180.0 * self.shape[0])
        self._left = round((west + 180.0) % 360.0 / 360.0 * self.shape[1])
        if self._left + width > self.shape[1]:
            raise ValueError("a regional raster across the 180° meridian")

    @property
    def calibrated(self) -> bool:
        """Whether the samples are measured values, as float samples are, and
        not a picture stretched for viewing. Their noise puts a real sample in
        shadow at or below zero."""
        return self._pixels.dtype.kind == "f"

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """West, east, north and south edge in degrees, on the grid that
        ``read`` uses."""
        rows, columns = self.shape
        height, width = self._pixels.shape
        return (
            self._left / columns * 360.0 - 180.0,
            (self._left + width) / columns * 360.0 - 180.0,
            90.0 - self._top / rows * 180.0,
            90.0 - (self._top + height) / rows * 180.0,
        )

    def read(self, y0: int, y1: int, x0: int, x1: int) -> np.ndarray:
        blank = self._blank
        if blank is None:
            blank = np.nan if self.calibrated else 0
        out = np.full((y1 - y0, x1 - x0), blank, dtype=self._pixels.dtype)
        height, width = self._pixels.shape
        top, bottom = max(y0, self._top), min(y1, self._top + height)
        left, right = max(x0, self._left), min(x1, self._left + width)
        if top < bottom and left < right:
            out[top - y0 : bottom - y0, left - x0 : right - x0] = self._pixels[
                top - self._top : bottom - self._top,
                left - self._left : right - self._left,
            ]
        return out


def _bicubic(
    band: np.ndarray, size: tuple[int, int], box: tuple[float, float, float, float]
) -> np.ndarray:
    resized = Image.fromarray(band).resize(size, Image.Resampling.BICUBIC, box=box)
    return np.asarray(resized)


def _fill_pixels(values: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """The pixels of blocks of one height. A pixel that holds the value of a
    neighbour in its row and of a neighbour in its column is one; a measured
    model almost never holds such values. So are the pixels joined to it by
    neighbours of equal value: where a measured model cuts a block to a strip
    one pixel wide, the strip has no equal neighbour across it."""
    either = []
    for axis in (0, 1):
        ahead = [slice(None)] * 2
        behind = [slice(None)] * 2
        ahead[axis], behind[axis] = slice(1, None), slice(None, -1)
        a, b = tuple(ahead), tuple(behind)
        same = (values[a] == values[b]) & valid[a] & valid[b]
        out = np.zeros(values.shape, dtype=bool)
        out[a] |= same
        out[b] |= same
        either.append(out)
    labels, count = ndimage.label(either[0] | either[1])
    keep = np.zeros(count + 1, dtype=bool)
    keep[labels[either[0] & either[1]]] = True
    keep[0] = False
    return keep[labels]


class SmoothedFill:
    """The samples of a terrain model that fills its gaps with a coarser
    model, enlarged to blocks of ``block`` pixels that hold one height. Each
    block edge is a step in the ground, and where the two models meet they
    can stand apart by metres. A pixel of the fill reads as the smooth surface
    through the means of the blocks, moved to meet the measured model at
    their border. Within a block of the fill, the measured model comes in
    from that surface; further in it reads as it is. ``nodata`` is the raw
    value of the file for no data.
    """

    # Sums over the measured pixels of each block that a plane through them
    # needs. A pixel's u is its column and its w its row from the block's
    # centre, and v is its height.
    _MOMENTS = ("n", "v", "u", "w", "uu", "uw", "ww", "uv", "wv")

    def __init__(
        self, samples: np.ndarray | ChunkedTiff, block: int, nodata: float | None
    ) -> None:
        self._samples = samples
        self._block = block
        self._nodata = nodata
        height, width = samples.shape[:2]
        self.shape = (height, width)
        self.dtype = np.dtype(np.float32)
        rows, columns = -(-height // block), -(-width // block)
        fill_count = np.zeros((rows, columns))
        fill_total = np.zeros((rows, columns))
        moments = {name: np.zeros((rows, columns)) for name in self._MOMENTS}
        offsets = np.arange(block) - (block - 1) / 2

        def weigh(pixels: np.ndarray, row_power: int, column_power: int) -> np.ndarray:
            return np.einsum(
                "awbu,w,u->ab", pixels, offsets**row_power, offsets**column_power
            )

        filled = seen = 0
        step = max(_WINDOW_PIXELS // width // block, 1) * block
        for top in range(0, height, step):
            values, valid = self._values(top, min(top + step, height), 0, width)
            fill = _fill_pixels(values, valid)
            filled += int(fill.sum())
            seen += int(valid.sum())
            pad = ((0, -values.shape[0] % block), (0, columns * block - width))
            band = slice(top // block, top // block + -(-values.shape[0] // block))

            def blocks(pixels: np.ndarray, pad=pad) -> np.ndarray:
                return np.pad(pixels, pad).reshape(-1, block, columns, block)

            in_fill = blocks(fill.astype(np.float64))
            measured = blocks((valid & ~fill).astype(np.float64))
            heights = blocks(np.where(valid, values, 0.0).astype(np.float64))
            fill_count[band] = weigh(in_fill, 0, 0)
            fill_total[band] = weigh(in_fill * heights, 0, 0)
            heights *= measured
            for name, pixels in (("n", measured), ("v", heights)):
                moments[name][band] = weigh(pixels, 0, 0)
            for name, pixels, row_power, column_power in (
                ("u", measured, 0, 1),
                ("w", measured, 1, 0),
                ("uu", measured, 0, 2),
                ("uw", measured, 1, 1),
                ("ww", measured, 2, 0),
                ("uv", heights, 0, 1),
                ("wv", heights, 1, 0),
            ):
                moments[name][band] = weigh(pixels, row_power, column_power)
        rise, apart = self._rise(fill_count, fill_total, moments)
        total = fill_total + rise * fill_count + moments["v"]
        count = fill_count + moments["n"]
        # A block less than half in the model is no sample of it.
        means = np.full((rows, columns), np.nan, dtype=np.float32)
        np.divide(total, count, out=means, where=count >= block * block / 2)
        gaps = np.isnan(means)
        if gaps.all():
            raise ValueError("no block of the terrain model holds data")
        # The filter reads past the model, so each gap takes the nearest block.
        nearest = ndimage.distance_transform_edt(
            gaps, return_distances=False, return_indices=True
        )
        self._means = means[tuple(nearest)]
        apart = np.abs(apart) if apart.size else np.zeros(1)
        log.info(
            "terrain model fill in blocks of %d px: %.1f%% of its samples, "
            "%.1f m from the measured model at their border (median), %.1f m at most",
            block,
            100.0 * filled / max(seen, 1),
            float(np.median(apart)),
            float(apart.max()),
        )

    def _offsets(
        self,
        fill_count: np.ndarray,
        fill_total: np.ndarray,
        moments: dict[str, np.ndarray],
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """The blocks of the fill at its border with the measured model, as
        rows and columns, and how far the fill stands above it in each."""
        block = self._block
        rows, columns = fill_count.shape
        near = ndimage.convolve(moments["n"], np.ones((3, 3)), mode="constant")
        r, c = np.nonzero((fill_count >= block) & (near >= block * block))
        # The moments of the measured pixels in the blocks around each block,
        # about its centre.
        s = {name: np.zeros(r.size) for name in self._MOMENTS}
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                rr, cc = r + dy, c + dx
                inside = (rr >= 0) & (rr < rows) & (cc >= 0) & (cc < columns)
                rr, cc = np.clip(rr, 0, rows - 1), np.clip(cc, 0, columns - 1)
                m = {k: np.where(inside, a[rr, cc], 0.0) for k, a in moments.items()}
                x, y = dx * block, dy * block
                s["n"] += m["n"]
                s["v"] += m["v"]
                s["u"] += m["u"] + x * m["n"]
                s["w"] += m["w"] + y * m["n"]
                s["uu"] += m["uu"] + 2 * x * m["u"] + x * x * m["n"]
                s["uw"] += m["uw"] + x * m["w"] + y * m["u"] + x * y * m["n"]
                s["ww"] += m["ww"] + 2 * y * m["w"] + y * y * m["n"]
                s["uv"] += m["uv"] + x * m["v"]
                s["wv"] += m["wv"] + y * m["v"]
        n = s["n"]
        mu, mw, mv = s["u"] / n, s["w"] / n, s["v"] / n
        cuu = s["uu"] / n - mu * mu
        cww = s["ww"] / n - mw * mw
        cuw = s["uw"] / n - mu * mw
        cuv = s["uv"] / n - mu * mv
        cwv = s["wv"] / n - mw * mv
        det = cuu * cww - cuw * cuw
        # A plane needs measured pixels spread both ways: across a thin strip
        # its slope is by chance.
        spread = det >= (block * block / 12) ** 2 / 4
        r, c = r[spread], c[spread]
        det = det[spread]
        along_u = (cuv * cww - cwv * cuw)[spread] / det
        along_w = (cwv * cuu - cuv * cuw)[spread] / det
        # The slope of the ground is no offset: the fill is compared with the
        # plane at its own place.
        plane = mv[spread] - along_u * mu[spread] - along_w * mw[spread]
        return r, c, fill_total[r, c] / fill_count[r, c] - plane

    def _rise(
        self,
        fill_count: np.ndarray,
        fill_total: np.ndarray,
        moments: dict[str, np.ndarray],
    ) -> tuple[np.ndarray, np.ndarray]:
        """How far each block of the fill moves up to meet the measured model,
        and how far the fill stood above it in each block at their border."""
        rows, columns = fill_count.shape
        r, c, apart = self._offsets(fill_count, fill_total, moments)
        rise = np.zeros((rows, columns))
        if not apart.size:
            return rise, apart
        # A bad patch at the edge of the measured model, as a pit filled in by
        # interpolation, gives a few samples far from the rest.
        places = np.column_stack([r, c])
        near = spatial.KDTree(places).query_ball_point(places, _FILL_SEAM_MEDIAN)
        typical = np.array([np.median(apart[group]) for group in near])
        at = np.zeros((rows, columns))
        at[r, c] = 1.0
        sums = np.zeros((rows, columns))
        sums[r, c] = -typical
        # Smoothed along the border: the measured ground has relief of its own.
        weight = ndimage.gaussian_filter(at, _FILL_SEAM_BLUR)
        np.divide(
            ndimage.gaussian_filter(sums, _FILL_SEAM_BLUR),
            weight,
            out=rise,
            where=weight > 0,
        )
        # Away from the border the fill keeps its own heights.
        reach = ndimage.distance_transform_edt(at == 0)
        rise *= np.clip(1.0 - reach / _FILL_SEAM_REACH, 0.0, 1.0)
        return rise, apart

    def _values(
        self, y0: int, y1: int, x0: int, x1: int
    ) -> tuple[np.ndarray, np.ndarray]:
        """Raw samples of a window as floats, and where they hold data."""
        values = np.array(self._samples[y0:y1, x0:x1], dtype=np.float32)
        valid = np.isfinite(values) & (values > NODATA_THRESHOLD)
        if self._nodata is not None:
            valid &= values != np.float32(self._nodata)
        return values, valid

    def __getitem__(self, key: tuple[slice, slice]) -> np.ndarray:
        height, width = self.shape
        y0, y1, _ = key[0].indices(height)
        x0, x1, _ = key[1].indices(width)
        # The test for fill reads the rest of the block of each pixel, and the
        # fade of the measured model reads a block past it.
        block = self._block
        top, left = max(y0 - block, 0), max(x0 - block, 0)
        values, valid = self._values(
            top, min(y1 + block, height), left, min(x1 + block, width)
        )
        inner = (slice(y0 - top, y1 - top), slice(x0 - left, x1 - left))
        fill = _fill_pixels(values, valid)
        out = values[inner]
        if not fill.any():
            return out
        near = ndimage.distance_transform_edt(~fill)[inner]
        fill = fill[inner]
        smooth = self._smooth(y0, y1, x0, x1)
        out[fill] = smooth[fill]
        # The measured model comes in from the smooth surface over a block:
        # its relief, cut at the border, would be a step.
        edge = valid[inner] & ~fill & (near < block)
        out[edge] = smooth[edge] + (out[edge] - smooth[edge]) * near[edge] / block
        return out

    def _smooth(self, y0: int, y1: int, x0: int, x1: int) -> np.ndarray:
        """The surface through the means of the blocks, over a window of pixels.
        A block's mean stands at its centre."""
        block = self._block
        rows, columns = self._means.shape
        # The filter reads two blocks past the window.
        b0, b1 = max(y0 // block - 2, 0), min(-(-y1 // block) + 2, rows)
        a0, a1 = max(x0 // block - 2, 0), min(-(-x1 // block) + 2, columns)
        box = (x0 / block - a0, y0 / block - b0, x1 / block - a0, y1 / block - b0)
        return _bicubic(self._means[b0:b1, a0:a1], (x1 - x0, y1 - y0), box)


@dataclass
class Layer:
    """An equirectangular raster, read in row bands."""

    # (H, W) heights or brightness, or colour as (H, W, 3), planar (3, H, W),
    # or one grey band (H, W) with ``grey`` set.
    pixels: np.ndarray | Mosaic | Region | ChunkedTiff
    placement: Placement
    planar: bool = False
    grey: bool = False
    # Raw samples → float32 values, gaps as NaN. Colour passes through. It may
    # give several fields per sample, as (H, W, n): each is resampled alone.
    to_values: Callable[[np.ndarray], np.ndarray] | None = None
    # A stored colour column with no data, read as the mean of its neighbours.
    dead_column: int | None = None

    @property
    def height(self) -> int:
        return self.pixels.shape[1 if self.planar else 0]

    @property
    def width(self) -> int:
        return self.pixels.shape[2 if self.planar else 1]

    @property
    def dimensions(self) -> list[int]:
        return [self.width, self.height]

    def rows(self, y0: int, y1: int) -> np.ndarray:
        return self.read(y0, y1, 0, self.width)

    def read(self, y0: int, y1: int, c0: int, c1: int) -> np.ndarray:
        """Rows ``y0:y1`` and columns ``c0:c1`` in the renderer's alignment:
        east to the right, 180°W at column 0. Columns wrap around the globe."""
        if self.to_values is None:
            band = self._stored(y0, y1, c0, c1)
            if self.grey:
                band = np.repeat(band[..., None], 3, axis=-1)
            return np.ascontiguousarray(band)
        # A dead edge column would otherwise sink to the fill height and cut a
        # trench along its meridian. The repair reads as far as it fills, so a
        # part of the raster needs that much around it to match the whole.
        reach = GAP_REPAIR_PASSES
        top, bottom = max(y0 - reach, 0), min(y1 + reach, self.height)
        band = self.to_values(self._stored(top, bottom, c0 - reach, c1 + reach))
        finite = np.isfinite(band)
        if not finite.all():
            repair_thin_gaps(band, finite)
        return np.ascontiguousarray(band[y0 - top : y1 - top, reach:-reach])

    def _stored(self, y0: int, y1: int, c0: int, c1: int) -> np.ndarray:
        width = self.width
        place = self.placement
        shift = round((place.lon_at_left_deg + 180.0) / 360.0 * width) % width
        parts = []
        column = c0
        while column < c1:
            start = (column - shift) % width
            count = min(c1 - column, width - start)
            parts.append(self._eastward(y0, y1, start, start + count))
            column += count
        return parts[0] if len(parts) == 1 else np.concatenate(parts, axis=1)

    def _eastward(self, y0: int, y1: int, a0: int, a1: int) -> np.ndarray:
        """Stored samples for columns ``a0:a1`` counted east from the raster's
        own first meridian."""
        s0, s1 = a0, a1
        if self.placement.west_positive:
            s0, s1 = self.width - a1, self.width - a0
        part = self._samples(y0, y1, s0, s1)
        dead = self.dead_column
        if dead is not None and s0 <= dead < s1:
            west, east = (
                self._samples(y0, y1, column, column + 1)
                for column in ((dead - 1) % self.width, (dead + 1) % self.width)
            )
            part = np.array(part)
            part[:, dead - s0] = mean_column(west, east)[:, 0]
        return part[:, ::-1] if self.placement.west_positive else part

    def _samples(self, y0: int, y1: int, s0: int, s1: int) -> np.ndarray:
        pixels = self.pixels
        if isinstance(pixels, (Mosaic, Region)):
            return pixels.read(y0, y1, s0, s1)
        if isinstance(pixels, ChunkedTiff):
            return pixels[y0:y1, s0:s1]
        if self.planar:
            return np.moveaxis(np.asarray(pixels[:, y0:y1, s0:s1]), 0, -1)
        return np.asarray(pixels[y0:y1, s0:s1])

    def source_row(self, lat: float) -> float:
        place = self.placement
        return (place.lat_top - lat) / (place.lat_top - place.lat_bottom) * self.height

    def inside(self, lats: np.ndarray) -> np.ndarray:
        """Blend weight at each latitude: 1 inside the layer, fading to 0 at
        an edge that is not a pole."""
        place = self.placement
        inside = np.full(lats.shape, np.inf)
        if place.lat_top < 90.0:
            inside = np.minimum(inside, place.lat_top - lats)
        if place.lat_bottom > -90.0:
            inside = np.minimum(inside, lats - place.lat_bottom)
        return np.clip(inside / config.TILE_INSET_FEATHER_DEG, 0.0, 1.0)

    def weights(self, lat_edges: np.ndarray) -> np.ndarray:
        """Blend weight per output row. Rows not wholly inside get 0."""
        return np.minimum(self.inside(lat_edges[:-1]), self.inside(lat_edges[1:]))

    def resample(self, out_w: int, lat_edges: np.ndarray) -> np.ndarray:
        return self.window(out_w, lat_edges, 0, out_w)

    def window(self, out_w: int, lat_edges: np.ndarray, x0: int, x1: int) -> np.ndarray:
        rows = self.source_row(float(lat_edges[-1])) - self.source_row(
            float(lat_edges[0])
        )
        per_column = max(rows, 1.0) * max(self.width / out_w, 1.0)
        step = max(int(_WINDOW_PIXELS / per_column), _WINDOW_COLUMNS)
        if x1 - x0 <= step:
            return self._window(out_w, lat_edges, x0, x1)
        return np.concatenate(
            [
                self._window(out_w, lat_edges, x, min(x + step, x1))
                for x in range(x0, x1, step)
            ],
            axis=1,
        )

    def _window(
        self, out_w: int, lat_edges: np.ndarray, x0: int, x1: int
    ) -> np.ndarray:
        out_h = lat_edges.size - 1
        top = self.source_row(float(lat_edges[0]))
        bottom = self.source_row(float(lat_edges[-1]))
        scale = self.width / out_w
        left, right = x0 * scale, x1 * scale
        # The filter reads past the pixels it maps, and across the ±180° seam.
        pad_y = math.ceil(_FILTER_SUPPORT * max(1.0, (bottom - top) / out_h)) + 1
        pad_x = math.ceil(_FILTER_SUPPORT * max(1.0, scale)) + 1
        y0 = max(0, math.floor(top) - pad_y)
        y1 = min(self.height, math.ceil(bottom) + pad_y)
        c0 = math.floor(left) - pad_x
        c1 = math.ceil(right) + pad_x
        band = self.read(y0, y1, c0, c1)
        # A row whose centre is inside the raster can reach half a pixel past
        # its edge. Repeat the edge row there: clamping the box instead would
        # stretch the rows of this call, by an amount that depends on how many
        # were asked for.
        above = math.ceil(-top) if top < -1e-6 else 0
        below = math.ceil(bottom - self.height) if bottom > self.height + 1e-6 else 0
        if above or below:
            band = np.pad(
                band, ((above, below), *([(0, 0)] * (band.ndim - 1))), mode="edge"
            )
        box = (
            left - c0,
            max(0.0, top - y0 + above),
            right - c0,
            min(float(band.shape[0]), bottom - y0 + above),
        )
        size = (x1 - x0, out_h)
        if band.ndim == 3 and band.dtype != np.uint8:
            fields = [
                _bicubic(band[..., field], size, box) for field in range(band.shape[2])
            ]
            return np.stack(fields, axis=-1)
        return _bicubic(band, size, box)

    def cap(self, cap: Cap, y0: int, y1: int, x0: int, x1: int) -> np.ndarray:
        """Read through patches of an equirectangular grid, each as wide as
        the pixels it serves need. Towards the pole the meridians close in: at
        the grid's full width a cap pixel would span many columns and take one
        of them, where a narrower grid holds their average.
        """
        # A raster about as fine as the cap is read at twice the cap's
        # density: the step from patch to cap is bilinear, and at one sample
        # a pixel that blurs by an amount that changes across the cap.
        dense = 2 if 4 * self.width > level_width(cap.level) else 1
        finer = self.width > level_width(cap.level)
        rows = (config.TILE_SIZE << cap.level) * dense
        width = level_width(cap.level) * dense
        x, y = cap.plane(y0, y1, x0, x1)
        reach = np.hypot(x[None, :], y[:, None])
        row = np.arctan(reach * _CAP_EDGE) * (2 * rows / math.pi)
        lon = np.arctan2(y[:, None], x[None, :])
        if not cap.north:
            row = rows - row
            lon = -lon
        # Counted from the square's own meridian, so no column jumps at ±180°.
        middle = float(lon[lon.shape[0] // 2, lon.shape[1] // 2])
        turn = np.remainder(lon - middle + math.pi, 2 * math.pi) - math.pi
        column = (middle + math.pi + turn) * (width / (2 * math.pi))
        # At full width a column is π/4 · reach of a cap pixel wide.
        with np.errstate(divide="ignore"):
            halvings = np.floor(np.log2(4 / math.pi / reach))
        most = int(math.log2(width // _CAP_MIN_WIDTH))
        halvings = np.clip(halvings, 0, most).astype(np.int8).ravel()
        # Ground outside the raster's band reads its edge row, as a window does.
        place = self.placement
        first = (90.0 - place.lat_top) / 180.0 * rows
        last = (90.0 - place.lat_bottom) / 180.0 * rows
        row = np.clip(row.ravel(), first + 0.5, last - 0.5) - 0.5
        column = column.ravel()

        out: np.ndarray | None = None
        for k in range(int(halvings.min()), int(halvings.max()) + 1):
            pick = halvings == k
            if not pick.any():
                continue
            r = row[pick]
            c = column[pick] / (1 << k) - 0.5
            r0 = max(math.floor(first), math.floor(r.min()))
            r1 = min(math.ceil(last), math.floor(r.max()) + 2)
            c0, c1 = math.floor(c.min()), math.floor(c.max()) + 2
            if finer:
                patch = self._doubled(width >> k, rows, r0, r1, c0, c1)
            else:
                lat_edges = 90.0 - np.arange(r0, r1 + 1) * (180.0 / rows)
                patch = self.window(width >> k, lat_edges, c0, c1)
            if out is None:
                out = np.empty((row.size, *patch.shape[2:]), dtype=patch.dtype)
            at = [r - r0, c - c0]
            if patch.ndim == 2:
                out[pick] = ndimage.map_coordinates(
                    patch, at, out.dtype, order=1, mode="nearest"
                )
                continue
            for channel in range(patch.shape[2]):
                out[pick, channel] = ndimage.map_coordinates(
                    patch[..., channel], at, out.dtype, order=1, mode="nearest"
                )
        assert out is not None
        return out.reshape(y1 - y0, x1 - x0, *out.shape[1:])

    def _doubled(
        self, width: int, rows: int, r0: int, r1: int, c0: int, c1: int
    ) -> np.ndarray:
        """Rows ``r0:r1`` and columns ``c0:c1`` of a grid ``width`` wide and
        ``rows`` from pole to pole, read at half that density and doubled.

        For a raster finer than the cap. Read straight at twice the cap's
        density, it would keep detail the cap cannot hold, and the bilinear
        step lets half of that through as noise. A window at the cap's own
        density drops it first.
        """
        # The doubling reads two pixels past each of its own.
        top, left = r0 // 2 - 2, c0 // 2 - 2
        bottom, right = -(-r1 // 2) + 2, -(-c1 // 2) + 2
        lat_edges = 90.0 - np.arange(top, bottom + 1) * (360.0 / rows)
        half = Image.fromarray(self.window(width // 2, lat_edges, left, right))
        doubled = half.resize(
            (2 * half.width, 2 * half.height), Image.Resampling.BICUBIC
        )
        return np.asarray(doubled)[
            r0 - 2 * top : r1 - 2 * top, c0 - 2 * left : c1 - 2 * left
        ]

    def release(self) -> None:
        if isinstance(self.pixels, Mosaic):
            self.pixels.release()


@dataclass
class PolarLayer:
    """A polar stereographic raster over one cap, as its PDS label places it.

    Sampled without a prefilter, so it must not be much finer than the level
    it feeds; the finest level is chosen from the layers' own widths.
    """

    path: Path
    placement: Placement
    to_values: Callable[[np.ndarray], np.ndarray]
    # Metres per pixel at the pole.
    scale_m: float
    radius_m: float
    centre_lon_deg: float
    # Array indices (line, sample) of the pole.
    pole: tuple[float, float]
    _values: np.ndarray | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def width(self) -> int:
        return round(2 * math.pi * self.radius_m / self.scale_m)

    @property
    def dimensions(self) -> list[int]:
        side = round(2 * self.pole[0]) + 1
        return [side, side]

    def resample(self, out_w: int, lat_edges: np.ndarray) -> np.ndarray:
        return self.window(out_w, lat_edges, 0, out_w)

    def _image(self) -> np.ndarray:
        with self._lock:
            if self._values is None:
                # Read whole: a ring of latitude touches every row of the image.
                self._values = self.to_values(np.asarray(open_pds_image(self.path)))
            return self._values

    def window(self, out_w: int, lat_edges: np.ndarray, x0: int, x1: int) -> np.ndarray:
        values = self._image()
        lats = np.radians((lat_edges[:-1] + lat_edges[1:]) / 2)
        reach = 2 * self.radius_m / self.scale_m * np.tan(np.pi / 4 - np.abs(lats) / 2)
        lons = -180.0 + (np.arange(x0, x1) + 0.5) * 360.0 / out_w
        angle = np.radians(lons - self.centre_lon_deg)
        # In the north the central meridian runs down the image from the pole,
        # in the south up.
        down = 1.0 if self.placement.lat_top == 90.0 else -1.0
        out = np.empty((lats.size, x1 - x0), dtype=np.float32)
        for i in range(0, x1 - x0, _REPROJECT_COLUMNS):
            part = angle[i : i + _REPROJECT_COLUMNS]
            line = self.pole[0] + down * reach[:, None] * np.cos(part)[None, :]
            sample = self.pole[1] + reach[:, None] * np.sin(part)[None, :]
            out[:, i : i + _REPROJECT_COLUMNS] = ndimage.map_coordinates(
                values, [line, sample], order=1, mode="nearest"
            )
        return out

    def cap(self, cap: Cap, y0: int, y1: int, x0: int, x1: int) -> np.ndarray:
        """The image and the cap are the same projection about the same pole,
        so a cap pixel maps to an image pixel by a turn and a scale."""
        half = cap.size / 2
        # Image pixels to one unit of the cap's plane.
        span = 2 * self.radius_m / self.scale_m * _CAP_EDGE
        turn = math.radians(self.centre_lon_deg)
        cos, sin = math.cos(turn), math.sin(turn)
        # East is up the cap in the north and down it in the south; see
        # ``window`` for which way the central meridian runs.
        east = 1.0 if cap.north else -1.0
        down = 1.0 if self.placement.lat_top == 90.0 else -1.0
        left, top = x0 / half - 1.0, 1.0 - y0 / half
        # Both count from the corner of their first pixel here.
        matrix = (
            -span * sin / half,
            -span * east * cos / half,
            self.pole[1] + 0.5 + span * (east * top * cos - left * sin),
            down * span * cos / half,
            -down * span * east * sin / half,
            self.pole[0] + 0.5 + down * span * (left * cos + east * top * sin),
        )
        image = Image.fromarray(self._image())
        return np.asarray(
            image.transform(
                (x1 - x0, y1 - y0),
                Image.Transform.AFFINE,
                matrix,
                Image.Resampling.BICUBIC,
            )
        )

    def release(self) -> None:
        self._values = None


def _load_whole(path: Path, channels: int) -> Image.Image:
    """Refuse to decode an image that cannot be read in bands when it would
    take more memory than a build may hold."""
    try:
        with Image.open(path) as probe:
            decoded = probe.width * probe.height * channels
    except Exception:
        # Not a format PIL reads; the fallback readers take small files only.
        decoded = 0
    if decoded > config.TILE_MAX_LOAD_BYTES:
        raise ValueError(
            f"{path.name}: {decoded / 2**30:.1f} GiB once decoded, and its "
            "storage cannot be read in bands; store it as an uncompressed TIFF"
        )
    return open_image(path) if channels == 3 else Image.open(path).convert("L")


def open_colour_layer(
    path: Path, placement: Placement, dead_column: int | None = None
) -> Layer:
    """A colour source, memory-mapped when it is stored as plain 8-bit samples:
    RGB, or one grey band."""
    if path.suffix.lower() in (".tif", ".tiff"):
        with tifffile.TiffFile(str(path)) as tif:
            page = tif.pages[0]
            assert isinstance(page, tifffile.TiffPage)  # page 0 is always full
            grey = page.axes == "YX"
            planar = page.axes == "SYX" and page.shape[0] == 3
            chunky = page.axes == "YXS" and page.shape[2] == 3
            if page.dtype == np.uint8 and (grey or planar or chunky):
                pixels = memmap_page(path, page)
                if pixels is not None:
                    return Layer(
                        pixels,
                        placement,
                        planar=planar,
                        grey=grey,
                        dead_column=dead_column,
                    )
    return Layer(np.asarray(_load_whole(path, 3)), placement, dead_column=dead_column)


def _colour_cell(path: Path) -> np.ndarray | ChunkedTiff:
    """One file of a colour grid, mapped in place or read by chunk. A grid is
    gigabytes a file, and a dozen of them would not fit decoded whole."""
    with tifffile.TiffFile(str(path)) as tif:
        page = tif.pages[0]
        assert isinstance(page, tifffile.TiffPage)  # page 0 is always full
        chunky = page.axes == "YXS" and page.dtype == np.uint8
        pixels = memmap_page(path, page) if chunky else None
    if pixels is not None:
        return pixels
    chunked = ChunkedTiff(path)
    if chunked.shape[2:] != (3,):
        raise ValueError(f"{path.name}: one band in a grid of colour files")
    return chunked


def open_colour_grid(
    grid: Sequence[Sequence[Path]],
    placement: Placement,
    dead_column: int | None = None,
) -> Layer:
    """A colour source in adjoining files, rows north to south: one file, or
    a grid of them. ``dead_column`` counts across the whole grid."""
    if len(grid) == 1 and len(grid[0]) == 1:
        return open_colour_layer(grid[0][0], placement, dead_column)
    return Layer(Mosaic(grid, _colour_cell), placement, dead_column=dead_column)


def soften(pixels: np.ndarray, sigma: float, around: bool = False) -> np.ndarray:
    """sRGB ``pixels`` blurred by ``sigma`` in linear light, ``around`` the
    globe for a whole map: the tint stays and the features go."""
    linear = _SRGB_TO_LINEAR[pixels]
    mode = ("nearest", "wrap") if around else "nearest"
    for channel in range(3):
        linear[..., channel] = ndimage.gaussian_filter(
            linear[..., channel], sigma, mode=mode
        )
    linear *= 65535.0
    np.clip(linear, 0, 65535, out=linear)
    return _LINEAR_TO_SRGB[linear.astype(np.uint16)]


def softened(layer: Layer, sigma: float) -> Layer:
    """A colour map blurred by ``sigma`` of its pixels. Where its features sit
    a few pixels from those of the brightness layers, each would show twice."""
    place = layer.placement
    return Layer(
        soften(layer.rows(0, layer.height), sigma, around=True),
        Placement(lat_top=place.lat_top, lat_bottom=place.lat_bottom),
    )


def _height_values(raster: HeightRaster) -> Callable[[np.ndarray], np.ndarray]:
    """Raw samples of ``raster`` → float32 km, NaN where it has no data."""

    def to_km(raw: np.ndarray) -> np.ndarray:
        km = (raw.astype(np.float32) * raster.scale + raster.offset) * raster.unit_km
        if raw.dtype.kind == "f":
            km[~(np.isfinite(raw) & (raw > NODATA_THRESHOLD))] = np.nan
        if raster.nodata is not None:
            km[raw == raster.nodata] = np.nan
        return km

    return to_km


def height_layer(raster: HeightRaster, placement: Placement) -> Layer:
    return Layer(raster.samples, placement, to_values=_height_values(raster))


def height_quantum_km(raster: HeightRaster) -> float:
    """Smallest height difference the file can state; 0 for float samples."""
    if raster.samples.dtype.kind not in "iu":
        return 0.0
    return abs(raster.scale) * raster.unit_km


def brightness_values(
    gamma: float | None, shadows: bool = False
) -> Callable[[np.ndarray], np.ndarray]:
    """Greyscale samples → float32 brightness, NaN where a sample is not
    positive: nothing was observed there. ``gamma`` is the display curve of
    integer samples stretched for viewing, undone here so that brightness
    ratios are ratios of light.

    ``shadows`` is for calibrated samples: one at or below zero is real, and
    only the null value of the file marks what was not observed."""
    # 8-bit samples, the common case by terabytes, take one table lookup.
    table = None
    if gamma is not None:
        table = (np.arange(256, dtype=np.float32) / 255.0) ** np.float32(gamma)
        table[0] = np.nan

    def convert(raw: np.ndarray) -> np.ndarray:
        if table is not None and raw.dtype == np.uint8:
            return table[raw]
        values = raw.astype(np.float32)
        if shadows:
            gaps = ~(values > NODATA_THRESHOLD)
            np.maximum(values, 0.0, out=values)
            values[gaps] = np.nan
        else:
            values[~(values > 0)] = np.nan
        if gamma is not None:
            values /= np.float32(np.iinfo(raw.dtype).max)
            values **= np.float32(gamma)
        return values

    return convert


_brightness = brightness_values(None)


def _open_grey(path: Path) -> np.ndarray:
    if path.suffix.lower() == ".img":
        return open_pds_image(path)
    with tifffile.TiffFile(str(path)) as tif:
        page = tif.pages[0]
        assert isinstance(page, tifffile.TiffPage)  # page 0 is always full
        pixels = memmap_page(path, page) if page.ndim == 2 else None
    if pixels is not None:
        return pixels
    return np.asarray(_load_whole(path, 1))


def _compressed(path: Path) -> bool:
    """Whether a file is a one-band TIFF that cannot be mapped in place."""
    if path.suffix.lower() not in (".tif", ".tiff"):
        return False
    with tifffile.TiffFile(str(path)) as tif:
        page = tif.pages[0]
        assert isinstance(page, tifffile.TiffPage)  # page 0 is always full
        return page.ndim == 2 and memmap_page(path, page) is None


def open_brightness_layer(
    grid: Sequence[Sequence[Path]], placement: Placement, gamma: float | None = None
) -> Layer:
    """Greyscale rasters in the equirectangular projection: one file, or a grid
    of adjoining ones."""
    pixels: np.ndarray | Mosaic | ChunkedTiff
    if len(grid) > 1 or len(grid[0]) > 1:
        pixels = Mosaic(grid)
    elif _compressed(grid[0][0]):
        # Decoded band by band: whole, a mosaic of this kind is gigabytes.
        pixels = ChunkedTiff(grid[0][0])
    else:
        pixels = _open_grey(grid[0][0])
    return Layer(pixels, placement, to_values=brightness_values(gamma))


def _geotiff_bounds(path: Path) -> tuple[float, float, float, float]:
    """West, east, north and south edge of an equirectangular GeoTIFF, in
    degrees."""
    with tifffile.TiffFile(str(path)) as tif:
        page = tif.pages[0]
        assert isinstance(page, tifffile.TiffPage)  # page 0 is always full
        keys = page.geotiff_tags or {}
        height, width = page.shape[:2]
    # 17: the equirectangular projection.
    if keys.get("ProjCoordTransGeoKey") != 17 or "ModelTiepoint" not in keys:
        raise ValueError(f"{path.name}: not an equirectangular GeoTIFF")
    # The edges below hold for metres counted from the equator and the central
    # meridian, with the first pixel at the tiepoint. 9001: metres.
    origin = (
        keys.get("ProjCenterLatGeoKey", 0.0),
        keys.get("ProjNatOriginLatGeoKey", 0.0),
        keys.get("ProjFalseEastingGeoKey", 0.0),
        keys.get("ProjFalseNorthingGeoKey", 0.0),
        *keys["ModelTiepoint"][:2],
    )
    if any(origin) or keys.get("ProjLinearUnitsGeoKey", 9001) != 9001:
        raise ValueError(f"{path.name}: a projection origin or unit not read here")
    radius = keys["GeogSemiMajorAxisGeoKey"]
    # Metres east of the central meridian shrink by the cosine of the
    # latitude the projection is true at.
    true_at = math.radians(keys.get("ProjStdParallel1GeoKey", 0.0))
    centre = keys.get("ProjCenterLongGeoKey", keys.get("ProjNatOriginLongGeoKey", 0.0))
    step_x, step_y = keys["ModelPixelScale"][:2]
    x0, y0 = keys["ModelTiepoint"][3:5]
    # 2: the tiepoint is the centre of the first pixel, not its corner.
    if keys.get("GTRasterTypeGeoKey") == 2:
        x0, y0 = x0 - step_x / 2, y0 + step_y / 2
    per_degree = math.radians(radius)
    west = centre + x0 / (per_degree * math.cos(true_at))
    north = y0 / per_degree
    return (
        west,
        west + width * step_x / (per_degree * math.cos(true_at)),
        north,
        north - height * step_y / per_degree,
    )


def _pds_bounds(path: Path) -> tuple[float, float, float, float]:
    """West, east, north and south edge of an equirectangular PDS3 image, in
    degrees, as its label states them."""
    label = read_pds_label(path)
    if label.get("MAP_PROJECTION_TYPE") != "EQUIRECTANGULAR":
        raise ValueError(f"{path.name}: not an equirectangular image")
    if label.get("POSITIVE_LONGITUDE_DIRECTION", "EAST") != "EAST":
        raise ValueError(f"{path.name}: longitudes counted west")
    west = float(label["WESTERNMOST_LONGITUDE"])
    east = float(label["EASTERNMOST_LONGITUDE"])
    # Longitudes from 0° to 360°, and an image across the prime meridian.
    if east <= west:
        east += 360.0
    return (
        west,
        east,
        float(label["MAXIMUM_LATITUDE"]),
        float(label["MINIMUM_LATITUDE"]),
    )


def open_region_layer(path: Path, gamma: float | None = None) -> Layer:
    """A greyscale raster of a part of the globe, as a brightness layer: an
    equirectangular GeoTIFF or PDS3 image."""
    pixels: np.ndarray | ChunkedTiff
    if path.suffix.lower() == ".img":
        pixels, bounds = open_pds_image(path), _pds_bounds(path)
    else:
        # A site mosaic stored in compressed chunks is too large to decode whole.
        pixels = ChunkedTiff(path) if _compressed(path) else _open_grey(path)
        bounds = _geotiff_bounds(path)
    region = Region(pixels, *bounds)
    return Layer(
        region, Placement(), to_values=brightness_values(gamma, region.calibrated)
    )


def open_height_region_layer(
    path: Path,
    *,
    unit: str = "m",
    scale: float | None = None,
    offset: float | None = None,
    nodata: float | None = None,
    fill_block: int | None = None,
) -> Layer:
    """A height raster of a part of the globe: an equirectangular GeoTIFF or
    PDS3 image. ``scale``, ``offset`` and ``nodata`` default to what the file
    states. ``fill_block`` is the side of the blocks of one height with which
    the raster fills its gaps from a coarser model: see ``SmoothedFill``."""
    if path.suffix.lower() == ".img":
        raster, bounds = open_pds_height_raster(path, unit=unit), _pds_bounds(path)
    else:
        # A site DTM stored in compressed chunks is too large to decode whole.
        raster = open_height_raster(path, unit=unit, chunked=_compressed(path))
        bounds = _geotiff_bounds(path)
    raster = replace(
        raster,
        scale=raster.scale if scale is None else scale,
        offset=raster.offset if offset is None else offset,
        nodata=raster.nodata if nodata is None else nodata,
    )
    blank = raster.nodata
    if raster.samples.dtype.kind == "f":
        blank = np.nan
    elif blank is None:
        # Zero outside the raster would read as ground at the datum.
        raise ValueError(f"{path.name}: integer heights with no value for no data")
    if isinstance(raster.samples, ChunkedTiff):
        raster.samples.blank = blank
    samples: np.ndarray | ChunkedTiff | SmoothedFill = raster.samples
    if fill_block:
        samples = SmoothedFill(samples, fill_block, raster.nodata)
    region = Region(samples, *bounds, blank=blank)
    return Layer(region, Placement(), to_values=_height_values(raster))


def open_polar_brightness_layer(
    path: Path, placement: Placement, gamma: float | None = None
) -> PolarLayer:
    label = read_pds_label(path)
    if label.get("MAP_PROJECTION_TYPE") != "POLAR STEREOGRAPHIC":
        raise ValueError(f"{path.name}: not a polar stereographic image")
    return PolarLayer(
        path,
        placement,
        brightness_values(gamma),
        scale_m=float(label["MAP_SCALE"]),
        radius_m=float(label["A_AXIS_RADIUS"]) * 1000.0,
        centre_lon_deg=float(label["CENTER_LONGITUDE"]),
        # The label counts from the image's edge, the array from the centre of
        # its first pixel.
        pole=(
            float(label["LINE_PROJECTION_OFFSET"]) - 0.5,
            float(label["SAMPLE_PROJECTION_OFFSET"]) - 0.5,
        ),
    )


def height_range_km(layers: Sequence[Layer]) -> tuple[float, float, int]:
    """Lowest and highest valid height across the layers, and the count of
    samples in gaps too wide to interpolate."""
    lo, hi, gaps = math.inf, -math.inf, 0
    for layer in layers:
        for y0 in range(0, layer.height, _SCAN_ROWS):
            km = layer.rows(y0, min(y0 + _SCAN_ROWS, layer.height))
            valid = np.isfinite(km)
            gaps += int(km.size - valid.sum())
            if valid.any():
                lo = min(lo, float(km[valid].min()))
                hi = max(hi, float(km[valid].max()))
    if lo > hi:
        raise ValueError("no valid height samples")
    return lo, hi, gaps


@dataclass(frozen=True)
class HeightCoding:
    """Heights in a lossless RGB tile: red is the high byte, green the low
    byte, and ``km = bias_km + step_km · (256·R + G + B/256)``. A pyramid's own
    tiles hold 16 bits and blue is zero. The tiles of a patch use blue too:
    their pixels are a hundred times as fine as the pyramid's, and a whole
    step from one to the next would be a staircase."""

    bias_km: float
    step_km: float
    # Height the gaps in the source sink to.
    fill_km: float

    @classmethod
    def for_range(
        cls, lo_km: float, hi_km: float, quantum_km: float, fill_km: float | None
    ) -> HeightCoding:
        """Step at the source's own quantum when 16 bits span the range at it —
        a finer step only stores resampling noise, at a bit per pixel each
        halving."""
        step = max(quantum_km, (hi_km - lo_km) / HEIGHT_LEVELS, 1e-9)
        return cls(lo_km, step, lo_km if fill_km is None else fill_km)

    def pack(self, km: np.ndarray) -> np.ndarray:
        code = np.rint((km - self.bias_km) / self.step_km)
        code = np.clip(code, 0, HEIGHT_LEVELS).astype(np.uint16)
        rgb = np.zeros((*code.shape, 3), dtype=np.uint8)
        rgb[..., 0] = code >> 8
        rgb[..., 1] = code & 0xFF
        return rgb

    def pack_fine(self, km: np.ndarray, parts: int = 256) -> np.ndarray:
        """``km`` in three bytes, rounded to one of ``parts`` of a step: a
        power of two, 256 at most."""
        # A float32 cannot hold 24 bits and their rounding.
        code = np.rint((km.astype(np.float64) - self.bias_km) * (parts / self.step_km))
        code *= 256 // parts
        code = np.clip(code, 0, HEIGHT_LEVELS * 256 + 255).astype(np.uint32)
        rgb = np.empty((*code.shape, 3), dtype=np.uint8)
        rgb[..., 0] = code >> 16
        rgb[..., 1] = (code >> 8) & 0xFF
        rgb[..., 2] = code & 0xFF
        return rgb

    def unpack(self, rgb: np.ndarray) -> np.ndarray:
        """The heights of a tile, in km."""
        code = (
            rgb[..., 0].astype(np.float64) * 256.0 + rgb[..., 1] + rgb[..., 2] / 256.0
        )
        return (self.bias_km + self.step_km * code).astype(np.float32)


def detail_ratio(fine: np.ndarray, sigma: float) -> np.ndarray:
    """A brightness map over itself blurred by ``sigma`` pixels: what it shows
    that a map of that blur cannot. 1 where nothing was observed (NaN).

    The caller pads ``fine`` by the blur's reach and crops the result.
    """
    seen = np.isfinite(fine)
    fine = np.where(seen, fine, 0.0)
    # Blur what was observed and divide by the blurred coverage, so a gap does
    # not darken its surroundings.
    coarse = ndimage.gaussian_filter(fine, sigma, mode="nearest")
    coverage = ndimage.gaussian_filter(seen.astype(np.float32), sigma, mode="nearest")
    usable = seen & (coverage > 0.5) & (coarse > 0)
    ratio = np.ones_like(fine)
    np.divide(fine * coverage, coarse, out=ratio, where=usable)
    return np.clip(ratio, *config.TILE_SHARPEN_RANGE)


def apply_detail(colour: np.ndarray, ratio: np.ndarray) -> np.ndarray:
    """sRGB ``colour`` scaled by ``ratio`` in linear light."""
    linear = _SRGB_TO_LINEAR[colour]
    linear *= ratio[..., None]
    linear *= 65535.0
    np.clip(linear, 0, 65535, out=linear)
    return _LINEAR_TO_SRGB[linear.astype(np.uint16)]


def _over(under: np.ndarray, patch: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """``patch`` over ``under`` at weight ``alpha``. A gap in the patch shows
    what is under it."""
    if patch.dtype.kind == "f":
        seen = np.isfinite(patch)
        if not seen.all():
            alpha = alpha * seen
            patch = np.where(seen, patch, 0.0)
    mixed = under * (1.0 - alpha) + patch * alpha
    if under.dtype == np.uint8:
        mixed = np.rint(mixed)
    return mixed.astype(under.dtype)


def _halve(band: np.ndarray) -> np.ndarray:
    """2×2 box average."""
    if band.dtype == np.uint8:
        # Four strided adds: many times faster than a blocked sum on an array
        # this size, and the same integers.
        total = band[0::2, 0::2].astype(np.uint16)
        total += band[0::2, 1::2]
        total += band[1::2, 0::2]
        total += band[1::2, 1::2]
        total += 2
        total >>= 2
        return total.astype(np.uint8)
    h, w = band.shape[:2]
    blocks = band.reshape(h // 2, 2, w // 2, 2, *band.shape[2:])
    return blocks.mean(axis=(1, 3), dtype=np.float32)


@dataclass
class PyramidStats:
    max_level: int
    tiles: list[int] = field(default_factory=list)
    size_bytes: list[int] = field(default_factory=list)

    @classmethod
    def empty(cls, max_level: int) -> PyramidStats:
        return cls(max_level, [0] * (max_level + 1), [0] * (max_level + 1))

    def add(self, other: PyramidStats) -> None:
        for level in range(self.max_level + 1):
            self.tiles[level] += other.tiles[level]
            self.size_bytes[level] += other.size_bytes[level]

    def levels(self, first: int = 0) -> list[dict]:
        return [
            {"level": z, "tiles": self.tiles[z], "size_bytes": self.size_bytes[z]}
            for z in range(first, self.max_level + 1)
        ]


# Where a block build keeps what it needs to resume, inside its output.
_STATE_DIR = ".build"
_CHECKPOINT = "checkpoint.npz"


def resumable(out_dir: Path, token: str) -> bool:
    """Whether ``out_dir`` holds a build of the same inputs, stopped or done."""
    path = out_dir / _STATE_DIR / _CHECKPOINT
    if not path.exists():
        return False
    with np.load(path) as saved:
        return str(saved["token"]) == token


def clear_state(out_dir: Path) -> None:
    """Drop the saved progress of the build in ``out_dir``."""
    shutil.rmtree(out_dir / _STATE_DIR, ignore_errors=True)


class PyramidBuilder:
    """Writes one pyramid under ``out_dir``.

    ``layers`` is the base raster, then the insets that replace it over the
    band each one covers. ``brightness`` layers refine a colour base instead:
    they supply the detail finer than the base resolves, blended at
    ``sharpen_sigma`` base pixels.

    ``checkpoint`` names the inputs. A block build saves its progress under
    that name after each row of blocks, and any build saves when it is done.
    A build picks up from a save of the same name and writes again the tiles
    deleted from it, so a fix that touches few tiles rebuilds only those. To
    find them it lists only the folders that changed after the save. The
    caller clears ``out_dir`` when there is no save to pick up, and drops the
    saves with ``clear_state`` once the output is in place.
    """

    # Coarsest level: two tiles side by side.
    min_level = 0

    def __init__(
        self,
        name: str,
        layers: Sequence[Layer],
        out_dir: Path,
        max_level: int,
        coding: HeightCoding | None = None,
        brightness: Sequence[Source] = (),
        sharpen_sigma: float | None = None,
        checkpoint: str = "",
    ) -> None:
        self.name = name
        self.layers = layers
        self.brightness = brightness
        self.out_dir = out_dir
        self.max_level = max_level
        self.coding = coding
        self.sharpen_sigma = (
            config.TILE_SHARPEN_SIGMA if sharpen_sigma is None else sharpen_sigma
        )
        self.checkpoint = checkpoint
        self._save_kwargs = (
            webp_kwargs(lossless=False)
            if coding is None
            else config.TILE_LOSSLESS_KWARGS
        )
        # One tile row per level, waiting for the row below it.
        self._held: dict[int, np.ndarray] = {}
        # Per level, the change time of each column folder when it was whole.
        self._listed: dict[int, np.ndarray] = {}
        self._settled = 0
        self._stats = PyramidStats.empty(max_level)
        self._lock = threading.Lock()

    def build(self) -> PyramidStats:
        # A blur hundreds of pixels wide takes minutes on a row of tiles. A
        # block runs it on a reduced copy.
        wide_blur = (
            bool(self.brightness)
            and self._sigma() >= 2 * _REDUCED_SIGMA
            and self.max_level - BLOCK_LEVELS >= self.min_level
        )
        blocked = self.max_level > MAX_BAND_LEVEL or wide_blur
        rows = self._rows(self.max_level - BLOCK_LEVELS if blocked else self.max_level)
        start = self._restore()
        with ThreadPoolExecutor(os.cpu_count()) as pool:
            if start < rows:
                self._write_levels(pool, blocked, start, rows)
            if start:
                self._fill(pool)
            self._listed = {
                level: self._changed_at(pool, level)
                for level in range(self.min_level, self.max_level + 1)
            }
        self._save(rows)
        return self._stats

    def _write_levels(
        self, pool: ThreadPoolExecutor, blocked: bool, start: int, rows: int
    ) -> None:
        for level in range(self.min_level, self.max_level + 1):
            for x in range(self._columns(level)):
                (self.out_dir / str(level) / str(x)).mkdir(parents=True, exist_ok=True)
        if blocked:
            if start:
                log.info("%s: resuming at block row %d", self.name, start + 1)
            self._build_blocks(pool, start)
            return
        for row, band in enumerate(self._finest_rows()):
            self._emit(pool, self.max_level, row, band)
            if (row + 1) % 8 == 0 or row + 1 == rows:
                log.info("%s: tile row %d of %d", self.name, row + 1, rows)

    def _fill(self, pool: ThreadPoolExecutor) -> None:
        """Write again the tiles deleted from a build of the same inputs. A
        block that holds one is built again as the build built it; a tile
        coarser than a block comes from the four on disk under it. The stats
        still count them."""
        present = {
            level: self._present(pool, level)
            for level in range(self.min_level, self.max_level + 1)
        }
        count = sum(int((~found).sum()) for found in present.values())
        if not count:
            return
        log.info("%s: writing %d deleted tiles again", self.name, count)
        for level, found in present.items():
            for x in np.flatnonzero(~found.all(axis=1)).tolist():
                (self.out_dir / str(level) / str(x)).mkdir(parents=True, exist_ok=True)
        depth = min(BLOCK_LEVELS, self.max_level - self.min_level)
        top = self.max_level - depth
        blocks = {
            (x >> (level - top), y >> (level - top))
            for level in range(top, self.max_level + 1)
            for x, y in np.argwhere(~present[level]).tolist()
        }

        def block(at: tuple[int, int]) -> None:
            bx, by = at
            side = config.TILE_SIZE << depth
            values = self._window(
                by * side, (by + 1) * side, bx * side, (bx + 1) * side
            )
            for level in range(self.max_level, top - 1, -1):
                span = 1 << (level - top)
                size = values.shape[0] // span
                for i, j in np.argwhere(
                    ~present[level][
                        bx * span : (bx + 1) * span, by * span : (by + 1) * span
                    ]
                ).tolist():
                    tile = values[j * size : (j + 1) * size, i * size : (i + 1) * size]
                    self._put(level, bx * span + i, by * span + j, tile)
                if level > top:
                    values = _halve(values)

        with ThreadPoolExecutor(BLOCK_WORKERS) as workers:
            list(workers.map(block, sorted(blocks)))
        missing = {level: np.argwhere(~found) for level, found in present.items()}
        for level in range(top - 1, self.min_level - 1, -1):

            def coarser(at: list[int], level: int = level) -> None:
                x, y = at
                under = [
                    np.concatenate(
                        [self._load(level + 1, 2 * x + i, 2 * y + j) for i in (0, 1)],
                        axis=1,
                    )
                    for j in (0, 1)
                ]
                self._put(level, x, y, _halve(np.concatenate(under)))

            list(pool.map(coarser, missing[level].tolist()))

    def _present(self, pool: ThreadPoolExecutor, level: int) -> np.ndarray:
        """Which tiles of ``level`` are on disk, as [column, row]. A folder
        that has not changed since the save is whole."""
        found = np.zeros((self._columns(level), self._rows(level)), dtype=bool)
        listed = self._listed.get(level)

        def scan(x: int) -> None:
            folder = self.out_dir / str(level) / str(x)
            try:
                changed = folder.stat().st_mtime_ns
            except FileNotFoundError:
                return
            if listed is not None and changed == listed[x] and changed < self._settled:
                found[x] = True
                return
            stems = (name.removesuffix(".webp") for name in os.listdir(folder))
            found[x, [int(stem) for stem in stems if stem.isdigit()]] = True

        list(pool.map(scan, range(found.shape[0])))
        return found

    def _changed_at(self, pool: ThreadPoolExecutor, level: int) -> np.ndarray:
        """The change time of each column folder of ``level``, in ns."""

        def changed(x: int) -> int:
            return (self.out_dir / str(level) / str(x)).stat().st_mtime_ns

        return np.array(list(pool.map(changed, range(self._columns(level)))))

    def _load(self, level: int, x: int, y: int) -> np.ndarray:
        """The values of a tile on disk."""
        with Image.open(self._tile_path(level, x, y)) as image:
            rgb = np.asarray(image.convert("RGB"))
        return rgb if self.coding is None else self.coding.unpack(rgb)

    def _tile_path(self, level: int, x: int, y: int) -> Path:
        return self.out_dir / str(level) / str(x) / f"{y}.webp"

    def _put(self, level: int, x: int, y: int, tile: np.ndarray) -> int:
        """Encode one tile and return its size. It takes its name once whole:
        a tile on disk is never cut short."""
        if self.coding is not None:
            tile = self.coding.pack(tile)
        path = self._tile_path(level, x, y)
        part = path.with_name(f".{path.name}")
        Image.fromarray(tile).save(part, "webp", **self._save_kwargs)
        part.replace(path)
        return path.stat().st_size

    def _columns(self, level: int) -> int:
        return 2 << level

    def _rows(self, level: int) -> int:
        return 1 << level

    def _sigma(self) -> float:
        """Width of the sharpening blur in pixels of the finest level."""
        return self.sharpen_sigma * level_width(self.max_level) / self.layers[0].width

    def _lat_edges(self, y0: int, y1: int) -> np.ndarray:
        """Latitudes bounding the finest level's rows ``y0:y1``."""
        deg_per_row = 180.0 / (config.TILE_SIZE << self.max_level)
        return 90.0 - np.arange(y0, y1 + 1) * deg_per_row

    def _finest_rows(self) -> Iterator[np.ndarray]:
        size = config.TILE_SIZE
        width = level_width(self.max_level)
        base, *insets = self.layers
        for row in range(1 << self.max_level):
            y0, y1 = row * size, (row + 1) * size
            band = self._composite(
                base, insets, width, self._lat_edges(y0, y1), 0, width
            )
            if self.brightness:
                band = self._sharpen(band, y0, y1)
            yield band

    def _build_blocks(self, pool: ThreadPoolExecutor, start: int) -> None:
        """Build the finest levels block by block. Each block is the footprint
        of one tile ``BLOCK_LEVELS`` down; a row of those tiles then feeds the
        coarser levels like any tile row."""
        band_level = self.max_level - BLOCK_LEVELS
        columns, rows = self._columns(band_level), self._rows(band_level)
        with ThreadPoolExecutor(BLOCK_WORKERS) as workers:
            for row in range(start, rows):
                parts = workers.map(partial(self._block, pool, row), range(columns))
                self._emit(pool, band_level, row, np.concatenate(list(parts), axis=1))
                self._save(row + 1)
                log.info("%s: block row %d of %d", self.name, row + 1, rows)

    def _block(self, pool: ThreadPoolExecutor, row: int, col: int) -> np.ndarray:
        """Write one block's tiles at the finest levels; return its single tile
        ``BLOCK_LEVELS`` down, not yet encoded."""
        side = config.TILE_SIZE << BLOCK_LEVELS
        y0, x0 = row * side, col * side
        values = self._window(y0, y0 + side, x0, x0 + side)
        for depth in range(BLOCK_LEVELS):
            span = 1 << (BLOCK_LEVELS - depth)
            self._write_tiles(
                pool, self.max_level - depth, col * span, row * span, values
            )
            values = _halve(values)
        return values

    def _window(self, y0: int, y1: int, x0: int, x1: int) -> np.ndarray:
        """Rows ``y0:y1`` and columns ``x0:x1`` of the finest level."""
        base, *insets = self.layers
        values = self._composite(
            base, insets, level_width(self.max_level), self._lat_edges(y0, y1), x0, x1
        )
        if self.brightness:
            values = self._sharpen_block(values, y0, y1, x0, x1)
        return values

    def _composite(
        self,
        base: Layer,
        insets: list[Layer],
        width: int,
        lat_edges: np.ndarray,
        x0: int,
        x1: int,
    ) -> np.ndarray:
        weights = [inset.weights(lat_edges) for inset in insets]
        # An inset at full weight over the whole band hides everything under
        # it, where it has data.
        full = [i for i, weight in enumerate(weights) if (weight == 1.0).all()]
        top = full[-1] if full else -1
        if top < 0:
            band = self._filled(base.window(width, lat_edges, x0, x1))
        else:
            band = insets[top].window(width, lat_edges, x0, x1)
            if band.dtype.kind == "f" and not np.isfinite(band).all():
                under = self._composite(base, insets[:top], width, lat_edges, x0, x1)
                band = np.where(np.isfinite(band), band, under)
        for inset, weight in zip(insets[top + 1 :], weights[top + 1 :]):
            (rows,) = np.nonzero(weight)
            if rows.size == 0:
                continue
            first, last = int(rows[0]), int(rows[-1]) + 1
            patch = inset.window(width, lat_edges[first : last + 1], x0, x1)
            alpha = weight[first:last].reshape(-1, *([1] * (band.ndim - 1)))
            if not band.flags.writeable:
                band = band.copy()
            band[first:last] = _over(band[first:last], patch, alpha)
        return band

    def _filled(self, values: np.ndarray) -> np.ndarray:
        """Heights with their gaps at the fill height."""
        if self.coding is not None and not np.isfinite(values).all():
            values = np.where(np.isfinite(values), values, self.coding.fill_km)
        return values

    def _brightness_window(self, y0: int, y1: int, x0: int, x1: int) -> np.ndarray:
        """Brightness over rows ``y0:y1`` and columns ``x0:x1`` of the finest
        level, NaN where no layer has data. Rows past a pole are NaN, columns
        past the edge wrap."""
        out = np.full((y1 - y0, x1 - x0), np.nan, dtype=np.float32)
        top, bottom = max(y0, 0), min(y1, config.TILE_SIZE << self.max_level)
        if top >= bottom:
            return out
        width = level_width(self.max_level)
        lat_edges = self._lat_edges(top, bottom)
        centres = (lat_edges[:-1] + lat_edges[1:]) / 2
        for layer in self.brightness:
            (rows,) = np.nonzero(layer.placement.covers(centres))
            if rows.size:
                first, last = int(rows[0]), int(rows[-1]) + 1
                fresh = layer.window(width, lat_edges[first : last + 1], x0, x1)
                held = out[top - y0 + first : top - y0 + last]
                np.copyto(held, fresh, where=np.isfinite(fresh))
        return out

    def _sharpen(self, band: np.ndarray, y0: int, y1: int) -> np.ndarray:
        """Give the colour band the detail its base is too coarse to hold.

        The brightness map is divided by itself blurred to the base's
        resolution, which leaves only what the base cannot show, and the base
        is multiplied by that ratio in linear light. Tone and colour stay the
        base's, so a coarse level still matches the whole-globe tiers.
        """
        width = band.shape[1]
        sigma = self._sigma()
        margin = int(4 * sigma + 0.5) + 1
        top = max(0, y0 - margin)
        bottom = min(config.TILE_SIZE << self.max_level, y1 + margin)
        fine = self._brightness_window(top, bottom, 0, width)

        # Where the next band starts reading: a layer wholly north of it is done.
        next_top = float(self._lat_edges(max(0, y1 - margin), max(0, y1 - margin))[0])
        for layer in self.brightness:
            if layer.placement.lat_bottom > next_top:
                layer.release()

        out = np.empty_like(band)
        for x0 in range(0, width, _SHARPEN_COLUMNS):
            x1 = min(x0 + _SHARPEN_COLUMNS, width)
            # The blur reads across the ±180° seam.
            columns = np.arange(x0 - margin, x1 + margin)
            block = fine.take(columns, axis=1, mode="wrap")
            ratio = detail_ratio(block, sigma)[y0 - top : y1 - top, margin:-margin]
            out[:, x0:x1] = apply_detail(band[:, x0:x1], ratio)
        return out

    def _sharpen_block(
        self, colour: np.ndarray, y0: int, y1: int, x0: int, x1: int
    ) -> np.ndarray:
        """``_sharpen`` for one block.

        Where the blur spans hundreds of pixels it runs on a reduced copy of
        the brightness, which holds everything a blur that wide keeps, and is
        stretched back over the block.
        """
        sigma = self._sigma()
        if sigma < 2 * _REDUCED_SIGMA:
            margin = int(4 * sigma + 0.5) + 1
            fine = self._brightness_window(
                y0 - margin, y1 + margin, x0 - margin, x1 + margin
            )
            ratio = detail_ratio(fine, sigma)[margin:-margin, margin:-margin]
            return apply_detail(colour, ratio)

        step = 1 << int(math.log2(sigma / _REDUCED_SIGMA))
        margin = math.ceil(4 * sigma / step) * step
        top, left = y0 - margin, x0 - margin
        reduced = ((y1 - top + margin) // step, (x1 - left + margin) // step)
        # Per reduced cell: the mean brightness with gaps as zero, and the
        # share of the cell that was observed.
        mean = np.zeros(reduced, dtype=np.float32)
        share = np.zeros(reduced, dtype=np.float32)
        # Half precision: a tenth of a percent on a ratio, for half the memory.
        inner = np.empty((y1 - y0, x1 - x0), dtype=np.float16)
        for s0 in range(top, y1 + margin, _SHARPEN_ROWS):
            s1 = min(s0 + _SHARPEN_ROWS, y1 + margin)
            fine = self._brightness_window(s0, s1, left, x1 + margin)
            seen = np.isfinite(fine)
            rows = slice((s0 - top) // step, (s1 - top) // step)
            a, b = max(s0, y0), min(s1, y1)
            if a < b:
                inner[a - y0 : b - y0] = fine[
                    a - s0 : b - s0, margin : margin + x1 - x0
                ]
            fine[~seen] = 0.0
            mean[rows] = np.asarray(Image.fromarray(fine).reduce(step))
            share[rows] = np.asarray(
                Image.fromarray(seen.astype(np.float32)).reduce(step)
            )

        if not share.any():
            return colour
        coverage = ndimage.gaussian_filter(share, sigma / step, mode="nearest")
        coarse = ndimage.gaussian_filter(mean, sigma / step, mode="nearest")
        np.divide(coarse, coverage, out=coarse, where=coverage > 0)
        coarse_image = Image.fromarray(coarse)
        coverage_image = Image.fromarray(coverage)

        out = np.empty_like(colour)
        for s0 in range(y0, y1, _SHARPEN_ROWS):
            s1 = min(s0 + _SHARPEN_ROWS, y1)
            box = (
                margin / step,
                (s0 - top) / step,
                (margin + x1 - x0) / step,
                (s1 - top) / step,
            )
            size = (x1 - x0, s1 - s0)
            smooth = Image.Resampling.BILINEAR
            low = np.asarray(coarse_image.resize(size, smooth, box=box))
            coverage = np.asarray(coverage_image.resize(size, smooth, box=box))
            fine = inner[s0 - y0 : s1 - y0].astype(np.float32)
            usable = np.isfinite(fine) & (coverage > 0.5) & (low > 0)
            ratio = np.ones_like(fine)
            np.divide(fine, low, out=ratio, where=usable)
            np.clip(ratio, *config.TILE_SHARPEN_RANGE, out=ratio)
            out[s0 - y0 : s1 - y0] = apply_detail(colour[s0 - y0 : s1 - y0], ratio)
        return out

    def _emit(
        self, pool: ThreadPoolExecutor, level: int, row: int, band: np.ndarray
    ) -> None:
        self._write_tiles(pool, level, 0, row, band)
        if level == self.min_level:
            return
        held = self._held.pop(level, None)
        if held is None:
            self._held[level] = band
            return
        self._emit(pool, level - 1, row // 2, _halve(np.concatenate([held, band])))

    def _write_tiles(
        self,
        pool: ThreadPoolExecutor,
        level: int,
        tile_x: int,
        tile_y: int,
        values: np.ndarray,
    ) -> None:
        """Encode ``values`` as the tiles of ``level`` whose north-west one is
        ``(tile_x, tile_y)``."""
        size = config.TILE_SIZE
        across = values.shape[1] // size

        def save(index: int) -> int:
            down, right = divmod(index, across)
            tile = values[
                down * size : (down + 1) * size, right * size : (right + 1) * size
            ]
            return self._put(level, tile_x + right, tile_y + down, tile)

        sizes = list(pool.map(save, range(across * (values.shape[0] // size))))
        with self._lock:
            self._stats.tiles[level] += len(sizes)
            self._stats.size_bytes[level] += sum(sizes)

    def _save(self, next_row: int) -> None:
        """Record that every block row before ``next_row`` is written, with the
        rows the coarser levels still wait on."""
        state = self.out_dir / _STATE_DIR
        state.mkdir(exist_ok=True)
        partial = state / f"partial.{_CHECKPOINT}"
        arrays: dict[str, np.ndarray] = {
            "token": np.array(self.checkpoint),
            "next_row": np.array(next_row),
            "tiles": np.array(self._stats.tiles),
            "size_bytes": np.array(self._stats.size_bytes),
            **{f"held_{level}": band for level, band in self._held.items()},
            **{f"listed_{level}": times for level, times in self._listed.items()},
        }
        np.savez(partial, allow_pickle=False, **arrays)
        partial.replace(state / _CHECKPOINT)

    def _restore(self) -> int:
        """Load a saved build of the same inputs; return its next row."""
        if not resumable(self.out_dir, self.checkpoint):
            return 0
        path = self.out_dir / _STATE_DIR / _CHECKPOINT
        # A folder that changed in the last second before the save can change
        # again in the same tick of its clock.
        self._settled = path.stat().st_mtime_ns - 10**9
        with np.load(path) as saved:
            self._stats.tiles = saved["tiles"].tolist()
            self._stats.size_bytes = saved["size_bytes"].tolist()
            self._held = {
                int(key.removeprefix("held_")): saved[key]
                for key in saved.files
                if key.startswith("held_")
            }
            self._listed = {
                int(key.removeprefix("listed_")): saved[key]
                for key in saved.files
                if key.startswith("listed_")
            }
            return int(saved["next_row"])


class CapBuilder(PyramidBuilder):
    """Writes one pole's cap of a pyramid under ``out_dir``: the same layers
    on a ``Cap`` grid, from ``max_level`` down to the cap's single tile.

    Brightness layers refine the colour on the cap's own grid, where the blur
    is as wide in every direction on the ground. On the equirectangular grid
    it narrows east-west towards a pole.
    """

    min_level = 1

    def __init__(self, name: str, north: bool, *args, **kwargs) -> None:
        super().__init__(name, *args, **kwargs)
        self.cap = Cap(north, self.max_level)
        self._samplers = ThreadPoolExecutor(_CAP_WORKERS)

    def build(self) -> PyramidStats:
        try:
            return super().build()
        finally:
            self._samplers.shutdown()
            for layer in self.brightness:
                layer.release()

    def _columns(self, level: int) -> int:
        return 1 << (level - 1)

    def _rows(self, level: int) -> int:
        return 1 << (level - 1)

    def _sigma(self) -> float:
        # A cap pixel at the pole against an equirectangular one.
        return super()._sigma() * (math.pi / 8) / _CAP_EDGE

    def _finest_rows(self) -> Iterator[np.ndarray]:
        size = config.TILE_SIZE
        for row in range(self._rows(self.max_level)):
            yield self._window(row * size, (row + 1) * size, 0, self.cap.size)

    def _window(self, y0: int, y1: int, x0: int, x1: int) -> np.ndarray:
        parts = []
        # In pieces: the blur of a whole row would hold several copies of it.
        for left in range(x0, x1, _SHARPEN_COLUMNS):
            right = min(left + _SHARPEN_COLUMNS, x1)
            values = self._gather(self._composite_square, y0, y1, left, right)
            if self.brightness:
                values = self._sharpen_block(values, y0, y1, left, right)
            parts.append(values)
        return parts[0] if len(parts) == 1 else np.concatenate(parts, axis=1)

    def _gather(
        self,
        read: Callable[[int, int, int, int], np.ndarray],
        y0: int,
        y1: int,
        x0: int,
        x1: int,
    ) -> np.ndarray:
        """``read`` over the rectangle, a square at a time."""
        squares = [
            (top, min(top + _CAP_CHUNK, y1), left, min(left + _CAP_CHUNK, x1))
            for top in range(y0, y1, _CAP_CHUNK)
            for left in range(x0, x1, _CAP_CHUNK)
        ]
        out: np.ndarray | None = None
        parts = self._samplers.map(lambda square: read(*square), squares)
        for (top, bottom, left, right), part in zip(squares, parts):
            if out is None:
                out = np.empty((y1 - y0, x1 - x0, *part.shape[2:]), dtype=part.dtype)
            out[top - y0 : bottom - y0, left - x0 : right - x0] = part
        assert out is not None
        return out

    def _composite_square(self, y0: int, y1: int, x0: int, x1: int) -> np.ndarray:
        base, *insets = self.layers
        values = self._filled(base.cap(self.cap, y0, y1, x0, x1))
        if not insets:
            return values
        lats = self.cap.latitudes(y0, y1, x0, x1)
        for inset in insets:
            weight = inset.inside(lats)
            if not weight.any():
                continue
            patch = inset.cap(self.cap, y0, y1, x0, x1)
            alpha = weight.reshape(*weight.shape, *([1] * (values.ndim - 2)))
            values = _over(values, patch, alpha)
        return values

    def _brightness_window(self, y0: int, y1: int, x0: int, x1: int) -> np.ndarray:
        """Brightness over rows ``y0:y1`` and columns ``x0:x1`` of the cap, NaN
        where no layer has data."""

        def read(*square: int) -> np.ndarray:
            lats = self.cap.latitudes(*square)
            out = np.full(lats.shape, np.nan, dtype=np.float32)
            for layer in self.brightness:
                seen = layer.placement.covers(lats)
                if seen.any():
                    fresh = layer.cap(self.cap, *square)
                    seen &= np.isfinite(fresh)
                    out[seen] = fresh[seen]
            return out

        return self._gather(read, y0, y1, x0, x1)


def signature_version(signature: dict) -> str:
    """Short digest of everything that decides a pyramid's bytes — the token
    the renderer puts on tile URLs, so a rebuild is never served from cache."""
    blob = json.dumps(signature, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:10]
