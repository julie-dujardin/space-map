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
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np
import tifffile
from PIL import Image
from scipy import ndimage

from . import config
from .encoding import linear_to_srgb, webp_kwargs
from .image_io import (
    NODATA_THRESHOLD,
    HeightRaster,
    memmap_page,
    open_image,
    open_pds_image,
    read_pds_label,
    GAP_REPAIR_PASSES,
    repair_thin_gaps,
)

log = logging.getLogger(__name__)

# Bump when the same inputs would now produce different tiles.
RECIPE = 1
# The same, for the pyramids that take their detail from brightness layers.
SHARPEN_RECIPE = 2

# Bicubic reach in source pixels at unit scale; it widens when shrinking.
_FILTER_SUPPORT = 2.0
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


class Mosaic:
    """Adjoining rasters of one size, read as a single array: rows north to
    south, each row west to east.

    A cell given as a path is opened when a read first touches it, so a mosaic
    of thousands of files only maps the few under the window.
    """

    def __init__(self, grid: Sequence[Sequence[np.ndarray | Path]]) -> None:
        self._grid = [list(row) for row in grid]
        self._tile_h, self._tile_w = self._tile(0, 0).shape
        for row in self._grid:
            for cell in row:
                if isinstance(cell, np.ndarray):
                    self._check(cell)
        self.shape = (self._tile_h * len(grid), self._tile_w * len(grid[0]))

    def _check(self, tile: np.ndarray) -> None:
        if tile.shape != (self._tile_h, self._tile_w):
            raise ValueError("mosaic tiles differ in size")

    def _tile(self, row: int, col: int) -> np.ndarray:
        cell = self._grid[row][col]
        if isinstance(cell, Path):
            cell = self._grid[row][col] = _open_grey(cell)
            if (row, col) != (0, 0):
                self._check(cell)
        return cell

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


@dataclass
class Layer:
    """An equirectangular raster, read in row bands."""

    # (H, W) heights or brightness, or colour as (H, W, 3), planar (3, H, W),
    # or one grey band (H, W) with ``grey`` set.
    pixels: np.ndarray | Mosaic
    placement: Placement
    planar: bool = False
    grey: bool = False
    # Raw samples → float32 values, gaps as NaN. Colour passes through.
    to_values: Callable[[np.ndarray], np.ndarray] | None = None

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
        pixels = self.pixels
        if isinstance(pixels, Mosaic):
            part = pixels.read(y0, y1, s0, s1)
        elif self.planar:
            part = np.moveaxis(np.asarray(pixels[:, y0:y1, s0:s1]), 0, -1)
        else:
            part = np.asarray(pixels[y0:y1, s0:s1])
        return part[:, ::-1] if self.placement.west_positive else part

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
        resized = Image.fromarray(band).resize(
            (x1 - x0, out_h), Image.Resampling.BICUBIC, box=box
        )
        return np.asarray(resized)

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
        pass


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


def open_colour_layer(path: Path, placement: Placement) -> Layer:
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
                    return Layer(pixels, placement, planar=planar, grey=grey)
    return Layer(np.asarray(_load_whole(path, 3)), placement)


def height_layer(raster: HeightRaster, placement: Placement) -> Layer:
    def to_km(raw: np.ndarray) -> np.ndarray:
        km = (raw.astype(np.float32) * raster.scale + raster.offset) * raster.unit_km
        if raw.dtype.kind == "f":
            km[~(np.isfinite(raw) & (raw > NODATA_THRESHOLD))] = np.nan
        if raster.nodata is not None:
            km[raw == raster.nodata] = np.nan
        return km

    return Layer(raster.samples, placement, to_values=to_km)


def height_quantum_km(raster: HeightRaster) -> float:
    """Smallest height difference the file can state; 0 for float samples."""
    if raster.samples.dtype.kind not in "iu":
        return 0.0
    return abs(raster.scale) * raster.unit_km


def brightness_values(gamma: float | None) -> Callable[[np.ndarray], np.ndarray]:
    """Greyscale samples → float32 brightness, NaN where a sample is not
    positive: nothing was observed there. ``gamma`` is the display curve of
    integer samples stretched for viewing, undone here so that brightness
    ratios are ratios of light."""
    # 8-bit samples, the common case by terabytes, take one table lookup.
    table = None
    if gamma is not None:
        table = (np.arange(256, dtype=np.float32) / 255.0) ** np.float32(gamma)
        table[0] = np.nan

    def convert(raw: np.ndarray) -> np.ndarray:
        if table is not None and raw.dtype == np.uint8:
            return table[raw]
        values = raw.astype(np.float32)
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


def open_brightness_layer(
    grid: Sequence[Sequence[Path]], placement: Placement, gamma: float | None = None
) -> Layer:
    """Greyscale rasters in the equirectangular projection: one file, or a grid
    of adjoining ones."""
    single = len(grid) == 1 and len(grid[0]) == 1
    return Layer(
        _open_grey(grid[0][0]) if single else Mosaic(grid),
        placement,
        to_values=brightness_values(gamma),
    )


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
    """16-bit heights in a lossless RGB tile: red is the high byte, green the
    low byte, and ``km = bias_km + step_km · (256·R + G)``."""

    bias_km: float
    step_km: float
    # Height the gaps in the source sink to.
    fill_km: float

    @classmethod
    def for_range(
        cls, lo_km: float, hi_km: float, quantum_km: float, fill_km: float | None
    ) -> "HeightCoding":
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
    def empty(cls, max_level: int) -> "PyramidStats":
        return cls(max_level, [0] * (max_level + 1), [0] * (max_level + 1))

    def add(self, other: "PyramidStats") -> None:
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
    that name after each row of blocks, any build when it is done, and a
    build picks up from a save of the same name. The caller clears ``out_dir``
    when there is none to pick up, and drops the saves with ``clear_state``
    once the output is in place.
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
        self._stats = PyramidStats.empty(max_level)
        self._lock = threading.Lock()

    def build(self) -> PyramidStats:
        blocked = self.max_level > MAX_BAND_LEVEL
        rows = self._rows(self.max_level - BLOCK_LEVELS if blocked else self.max_level)
        start = self._restore()
        if start == rows:
            return self._stats
        for level in range(self.min_level, self.max_level + 1):
            for x in range(self._columns(level)):
                (self.out_dir / str(level) / str(x)).mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(os.cpu_count()) as pool:
            if blocked:
                if start:
                    log.info("%s: resuming at block row %d", self.name, start + 1)
                self._build_blocks(pool, start)
            else:
                for row, band in enumerate(self._finest_rows()):
                    self._emit(pool, self.max_level, row, band)
                    if (row + 1) % 8 == 0 or row + 1 == rows:
                        log.info("%s: tile row %d of %d", self.name, row + 1, rows)
                self._save(rows)
        return self._stats

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
                parts = workers.map(
                    lambda col: self._block(pool, row, col), range(columns)
                )
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
            if self.coding is not None:
                tile = self.coding.pack(tile)
            folder = self.out_dir / str(level) / str(tile_x + right)
            path = folder / f"{tile_y + down}.webp"
            Image.fromarray(tile).save(path, "webp", **self._save_kwargs)
            return path.stat().st_size

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
        }
        np.savez(partial, allow_pickle=False, **arrays)
        partial.replace(state / _CHECKPOINT)

    def _restore(self) -> int:
        """Load a saved build of the same inputs; return its next row."""
        if not resumable(self.out_dir, self.checkpoint):
            return 0
        with np.load(self.out_dir / _STATE_DIR / _CHECKPOINT) as saved:
            self._stats.tiles = saved["tiles"].tolist()
            self._stats.size_bytes = saved["size_bytes"].tolist()
            self._held = {
                int(key.removeprefix("held_")): saved[key]
                for key in saved.files
                if key.startswith("held_")
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
