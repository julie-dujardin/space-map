"""Patches: areas where a tile pyramid goes deeper than its finest level.

A landing site can have a mosaic a hundred times as sharp as the map of its
body. A patch holds it as the tiles of the levels past the pyramid's own, for
the ground the mosaic covers and no more.

A patch is built on the tiles of its pyramid. Their colour and their broad
tone stay, so a patch joins the map around it without a step. Everything
finer comes from the mosaic alone: the map's own detail may sit some pixels
from the mosaic's, and each feature would otherwise show twice.

A colour patch also shows in the finest levels of the pyramid itself, as far
up as its mosaic has detail that the map lacks. A view that goes in would
otherwise change one picture of the ground for another where the patch starts.

A patch of a height pyramid is built the same way from a terrain model of the
site: the broad heights stay those of the pyramid, and the model gives the
relief below that scale. The two are tied to the body by different
measurements, and can stand some metres apart.

A patch of rasters in the polar stereographic projection goes on the cap of
their pole, with the same layout inside the cap's folder.
"""

import logging
import math
import shutil
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from . import config, tiles
from .encoding import webp_kwargs

log = logging.getLogger(__name__)

# Bumped when a change to the build changes the bytes of a patch's tiles.
RECIPE = 4
# The same for the tiles of a height patch.
HEIGHT_RECIPE = 2
# Inside a pyramid: its own tiles that a patch is drawn over, and what each
# patch draws over them. The tiles can then be made again when a patch changes
# or goes.
_OWN_DIR = ".map"
_OVER_DIR = ".over"
# Levels made from one read of the rasters: a block is 4 × 4 of the finest tiles.
_BLOCK_LEVELS = 2
# Levels of blocks built side by side, each held until its group is done.
_GROUP_LEVELS = 3
# Blocks in the works at a time: each holds about 1 GB.
_WORKERS = 4
# Raster pixels a read holds at a time. Whole rows: a tall, narrow read of a
# file on a network mount fetches a page for every row.
_READ_PIXELS = 1 << 25
# Pixels read around a patch past the blur, and around a raster past its edge.
_MARGIN = 4
# Most parts of a height step that a tile states: all the third byte holds.
_STEP_PARTS = 256
# Pixels of a height patch's finest level over which a raster comes in from
# its edge.
_SEAM = 16
# Least broad brightness the detail of a calibrated raster is compared with,
# as a share of the raster's average. A shadow wider than the blur has almost
# none of its own: its noise would otherwise count as detail as strong as the
# ground's.
_SHADOW_FLOOR = 0.2


def _resized(
    image: Image.Image,
    box: tuple[float, float, float, float],
    size: tuple[int, int],
    smooth: bool = False,
) -> np.ndarray:
    """``box`` of ``image`` at ``size``: smooth for colour and for a map that
    is ``smooth``, linear for the slow fields that correct one."""
    filter_ = (
        Image.Resampling.BICUBIC
        if smooth or image.mode == "RGB"
        else Image.Resampling.BILINEAR
    )
    return np.asarray(image.resize(size, filter_, box=box))


type Raster = tiles.Layer | tiles.PolarRegionLayer


def _region(raster: Raster) -> tiles.Region | tiles.PolarRegion:
    pixels = raster.pixels
    assert isinstance(pixels, (tiles.Region, tiles.PolarRegion))
    return pixels


def _bounds(raster: Raster) -> tuple[float, float, float, float]:
    return _region(raster).bounds


def chart(rasters: Sequence[Raster]) -> str:
    """The folder of the chart that a patch of ``rasters`` is on: ``""`` for
    the map, or the cap of the pole that polar rasters are around."""
    found = set()
    for raster in rasters:
        region = _region(raster)
        if isinstance(region, tiles.PolarRegion):
            found.add("north" if region.place.north else "south")
        else:
            found.add("")
    if len(found) > 1:
        raise ValueError("the files of one patch are on different charts")
    return found.pop()


def fields[R: tiles.Layer | tiles.PolarRegionLayer](raster: R) -> R:
    """A raster as two fields that can be resampled: its values with nothing
    where it has no data, and the share of data. A site mosaic is strips with
    gaps between them, and one missing pixel under a filter would otherwise
    take the whole output pixel with it."""
    to_values = raster.to_values
    assert to_values is not None

    def convert(raw: np.ndarray) -> np.ndarray:
        values = to_values(raw)
        seen = np.isfinite(values)
        filled = np.where(seen, values, np.float32(0.0))
        return np.stack([filled, seen.astype(np.float32)], axis=-1)

    return replace(raster, to_values=convert)


def _inside(here: np.ndarray) -> np.ndarray:
    """How far inside the data of a raster each pixel is: 0 where there is
    none, 1 from ``_SEAM`` pixels in."""
    if here.all():
        return np.ones(here.shape, dtype=np.float32)
    deep = ndimage.distance_transform_edt(here)
    return np.clip(deep / _SEAM, 0.0, 1.0).astype(np.float32)


def map_levels(sigma: float, base_level: int, cap: bool = False) -> int:
    """How many of a pyramid's own levels a patch shows in, from the finest
    up. The blur is half as many pixels wide at each level: at one pixel the
    rasters have no detail left that the map lacks. A cap starts at level 1."""
    if sigma <= 1.0:
        return 0
    return min(math.ceil(math.log2(sigma)), base_level + (0 if cap else 1))


def own_tile(pyramid: Path, level: int, x: int, y: int) -> Path:
    """The tile as the pyramid built it, which stands aside while a patch is
    drawn over it."""
    name = Path(str(level), str(x), f"{y}.webp")
    aside = pyramid / _OWN_DIR / name
    return aside if aside.exists() else pyramid / name


def first_range(
    base_level: int, max_level: int, x: Sequence[int], y: Sequence[int]
) -> tuple[int, int, int, int]:
    """The tiles of a patch at its coarsest level, from its range at its
    finest: first and last column, then first and last row."""
    shift = max_level - base_level - 1
    return x[0] >> shift, x[1] >> shift, y[0] >> shift, y[1] >> shift


def share_tiles(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    """Whether two tile ranges of one level have a tile in common."""
    return a[0] <= b[1] and b[0] <= a[1] and a[2] <= b[3] and b[2] <= a[3]


class PatchBuilder:
    """Builds the tiles of one patch from the finest tiles of its pyramid and
    the patch's rasters.

    The finest level comes from the rasters, block by block, and each level
    above it from the one below, as in a pyramid. ``sigma`` is the scale below
    which the rasters give all the detail, in pixels of the pyramid's finest
    level. ``coding`` is that of a height pyramid, whose rasters are then
    heights.
    """

    def __init__(
        self,
        name: str,
        pyramid: Path,
        base_level: int,
        rasters: Sequence[Raster],
        out_dir: Path,
        sigma: float,
        max_level: int | None = None,
        coding: tiles.HeightCoding | None = None,
    ) -> None:
        self.name = name
        self.pyramid = pyramid
        self.base_level = base_level
        self.rasters = rasters
        self.out_dir = out_dir
        self.sigma = sigma
        self.coding = coding
        # ``pyramid`` is the folder of the patch's chart, a cap's for a cap patch.
        self.chart = chart(rasters)
        # Heights in three bytes do not mix by alpha as colours do.
        self.map_levels = (
            map_levels(sigma, base_level, bool(self.chart)) if coding is None else 0
        )
        # A raster away from the equator has wider pixels in longitude than in
        # latitude: the finer of the two decides.
        self.full_width = max(
            max(raster.width, 2 * raster.height) for raster in rasters
        )
        self.level = (
            tiles.finest_level(self.full_width) if max_level is None else max_level
        )
        self._fields = [fields(raster) for raster in rasters]
        if self.level <= base_level:
            raise ValueError(f"{name}: no finer than level {base_level} of its map")
        edges = [_bounds(raster) for raster in rasters]
        self.west = min(edge[0] for edge in edges)
        self.east = max(edge[1] for edge in edges)
        self.north = max(edge[2] for edge in edges)
        self.south = min(edge[3] for edge in edges)
        if self.chart:
            planes = [_polar(raster).plane_bounds() for raster in rasters]
            # Fractions of the cap's width and height from its top-left corner.
            self._cap_box = (
                (1.0 + min(plane[0] for plane in planes)) / 2,
                (1.0 + max(plane[1] for plane in planes)) / 2,
                (1.0 - max(plane[3] for plane in planes)) / 2,
                (1.0 - min(plane[2] for plane in planes)) / 2,
            )
        self.stats = tiles.PyramidStats.empty(self.level)
        self._lock = threading.Lock()
        self._save_kwargs = (
            webp_kwargs(lossless=False)
            if coding is None
            else config.TILE_LOSSLESS_KWARGS
        )
        # Level of the tile a block leaves, and of the tile a group leaves.
        self._block_level = max(self.level - _BLOCK_LEVELS, base_level + 1)
        self._group_level = max(self._block_level - _GROUP_LEVELS, base_level + 1)

    def columns(self, level: int) -> int:
        return 1 << (level - 1) if self.chart else 2 << level

    def rows(self, level: int) -> int:
        return 1 << (level - 1) if self.chart else 1 << level

    def tile_range(self, level: int) -> tuple[int, int, int, int]:
        """First and last column, then first and last row, of the tiles of
        ``level`` that the rasters touch."""
        columns, rows = self.columns(level), self.rows(level)
        if self.chart:
            left, right, top, bottom = self._cap_box
        else:
            left, right = (self.west + 180.0) / 360.0, (self.east + 180.0) / 360.0
            top, bottom = (90.0 - self.north) / 180.0, (90.0 - self.south) / 180.0
        return (
            math.floor(left * columns),
            math.ceil(right * columns) - 1,
            math.floor(top * rows),
            math.ceil(bottom * rows) - 1,
        )

    def _touched(self, level: int, x: int, y: int) -> bool:
        x0, x1, y0, y1 = self.tile_range(level)
        return x0 <= x <= x1 and y0 <= y <= y1

    def build(self) -> tiles.PyramidStats:
        ground = _Ground(self) if self.coding is None else _HeightGround(self)
        first = self.base_level + 1
        for level in range(first, self.level + 1):
            x0, x1, _, _ = self.tile_range(level)
            for x in range(x0, x1 + 1):
                (self.out_dir / str(level) / str(x)).mkdir(parents=True, exist_ok=True)
        x0, x1, y0, y1 = self.tile_range(first)
        over = _Over(self, ground) if self.map_levels else None
        with ThreadPoolExecutor(_WORKERS) as pool:
            for y in range(y0, y1 + 1):
                for x in range(x0, x1 + 1):
                    values = self._tile(pool, ground, first, x, y)
                    if over:
                        over.take(x, y, values)
                log.info(
                    "%s: tile row %d of %d, %d tiles",
                    self.name,
                    y - y0 + 1,
                    y1 - y0 + 1,
                    sum(self.stats.tiles),
                )
        if over:
            # The ground is as large again, and the tiles do not need it.
            del ground
            over.write(self.out_dir / _OVER_DIR)
        return self.stats

    def fine(
        self,
        index: int,
        level: int,
        y0: int,
        y1: int,
        x0: int,
        x1: int,
        pool: ThreadPoolExecutor | None = None,
    ) -> np.ndarray:
        """Values of raster ``index`` over a pixel window of ``level``, NaN
        where less than half of a pixel has data. A window that takes many
        reads can share them out over ``pool``."""
        if self.chart:
            return self._fine_cap(index, level, y0, y1, x0, x1, pool)
        raster = self.rasters[index]
        fields = self._fields[index]
        assert isinstance(fields, tiles.Layer)
        rows = config.TILE_SIZE << level
        width = tiles.level_width(level)
        out = np.full((y1 - y0, x1 - x0), np.nan, dtype=np.float32)
        # Only the part of the window the raster is in: the rest of it would
        # be read as so many pixels of nothing.
        west, east, north, south = _bounds(raster)
        left = max(x0, math.floor((west + 180.0) / 360.0 * width) - _MARGIN)
        right = min(x1, math.ceil((east + 180.0) / 360.0 * width) + _MARGIN)
        first = max(y0, math.floor((90.0 - north) / 180.0 * rows) - _MARGIN)
        last = min(y1, math.ceil((90.0 - south) / 180.0 * rows) + _MARGIN)
        if left >= right or first >= last:
            return out
        per_row = (right - left) * raster.width / width * raster.height / rows
        step = max(int(_READ_PIXELS / max(per_row, 1.0)), 1)

        def band(top: int) -> None:
            bottom = min(top + step, last)
            lat_edges = 90.0 - np.arange(top, bottom + 1) * (180.0 / rows)
            both = fields.window(width, lat_edges, left, right)
            total, seen = both[..., 0], both[..., 1]
            held = out[top - y0 : bottom - y0, left - x0 : right - x0]
            np.divide(total, seen, out=held, where=seen > 0.5)

        list((pool.map if pool else map)(band, range(first, last, step)))
        return out

    def _fine_cap(
        self,
        index: int,
        level: int,
        y0: int,
        y1: int,
        x0: int,
        x1: int,
        pool: ThreadPoolExecutor | None = None,
    ) -> np.ndarray:
        """``fine`` on the grid of a cap."""
        raster = _polar(self.rasters[index])
        fields = self._fields[index]
        assert isinstance(fields, tiles.PolarRegionLayer)
        cap = tiles.Cap(self.chart == "north", level)
        half = cap.size / 2
        out = np.full((y1 - y0, x1 - x0), np.nan, dtype=np.float32)
        plane_left, plane_right, plane_bottom, plane_top = raster.plane_bounds()
        left = max(x0, math.floor((1.0 + plane_left) * half) - _MARGIN)
        right = min(x1, math.ceil((1.0 + plane_right) * half) + _MARGIN)
        first = max(y0, math.floor((1.0 - plane_top) * half) - _MARGIN)
        last = min(y1, math.ceil((1.0 - plane_bottom) * half) + _MARGIN)
        if left >= right or first >= last:
            return out
        per_row = (right - left) * fields.per_cap_pixel(cap) ** 2
        step = max(int(_READ_PIXELS / max(per_row, 1.0)), 1)

        def band(top: int) -> None:
            bottom = min(top + step, last)
            both = fields.cap(cap, top, bottom, left, right)
            total, seen = both[..., 0], both[..., 1]
            held = out[top - y0 : bottom - y0, left - x0 : right - x0]
            np.divide(total, seen, out=held, where=seen > 0.5)

        list((pool.map if pool else map)(band, range(first, last, step)))
        return out

    def _tile(
        self, pool: ThreadPoolExecutor, ground: _Ground, level: int, x: int, y: int
    ) -> np.ndarray:
        """Write the tile and every tile under it that the rasters touch;
        return its pixels."""
        if not self._touched(level, x, y):
            return ground.map_tile(level, x, y)
        if level == self._block_level:
            return self._block(ground, x, y)
        if level == self._group_level:
            # Its blocks side by side, then down to the tile itself.
            depth = self._block_level - level
            side = 1 << depth
            blocks = list(
                pool.map(
                    lambda i: self._tile(
                        pool,
                        ground,
                        self._block_level,
                        (x << depth) + i % side,
                        (y << depth) + i // side,
                    ),
                    range(side * side),
                )
            )
            values = np.concatenate(
                [
                    np.concatenate(blocks[row * side : (row + 1) * side], axis=1)
                    for row in range(side)
                ]
            )
            return self._reduce(
                values, self._block_level, x << depth, y << depth, depth
            )
        quads = [
            [
                self._tile(pool, ground, level + 1, 2 * x + dx, 2 * y + dy)
                for dx in (0, 1)
            ]
            for dy in (0, 1)
        ]
        values = np.concatenate([np.concatenate(row, axis=1) for row in quads])
        return self._reduce(values, level + 1, 2 * x, 2 * y, 1)

    def _block(self, ground: _Ground, x: int, y: int) -> np.ndarray:
        depth = self.level - self._block_level
        side = 1 << depth
        values = ground.block(self.level, x << depth, y << depth, side, side)
        self._write(self.level, x << depth, y << depth, values)
        return self._reduce(values, self.level, x << depth, y << depth, depth)

    def _reduce(
        self, values: np.ndarray, level: int, tile_x: int, tile_y: int, depth: int
    ) -> np.ndarray:
        """Halve ``values``, the tiles of ``level`` from ``(tile_x, tile_y)``,
        ``depth`` times, and write each level on the way."""
        for step in range(1, depth + 1):
            values = tiles._halve(values)
            self._write(level - step, tile_x >> step, tile_y >> step, values)
        return values

    def _write(self, level: int, tile_x: int, tile_y: int, values: np.ndarray) -> None:
        """Encode the tiles of ``values`` that the rasters touch."""
        size = config.TILE_SIZE
        count = total = 0
        for down in range(values.shape[0] // size):
            for right in range(values.shape[1] // size):
                x, y = tile_x + right, tile_y + down
                if not self._touched(level, x, y):
                    continue
                tile = values[
                    down * size : (down + 1) * size, right * size : (right + 1) * size
                ]
                if self.coding is not None:
                    # A step as fine against a pixel as the pyramid's own: a
                    # level's pixels are half as wide as those of the level
                    # above, and a finer step would store noise.
                    parts = min(1 << (level - self.base_level), _STEP_PARTS)
                    tile = self.coding.pack_fine(tile, parts)
                path = self.out_dir / str(level) / str(x) / f"{y}.webp"
                Image.fromarray(tile).save(path, "webp", **self._save_kwargs)
                count += 1
                total += path.stat().st_size
        with self._lock:
            self.stats.tiles[level] += count
            self.stats.size_bytes[level] += total


class _Ground:
    """What a patch is built on, on the grid of the pyramid's finest level:
    the map there, the same map with its detail blurred away, the rasters
    blurred as much, and how far inside the rasters each pixel is."""

    # A map of heights is enlarged smoothly: a crease at each of its pixels
    # would be lit as one.
    smooth = False

    def __init__(self, patch: PatchBuilder) -> None:
        self.patch = patch
        level = patch.base_level
        size = config.TILE_SIZE
        reach = math.ceil(4 * patch.sigma) + _MARGIN
        # The first level of the patch decides the ground it needs: its tiles
        # reach the furthest past the rasters.
        x0, x1, y0, y1 = patch.tile_range(level + 1)
        half = size // 2
        self.left = x0 * half - reach
        self.top = max(y0 * half - reach, 0)
        right = (x1 + 1) * half + reach
        bottom = min((y1 + 1) * half + reach, size * patch.rows(level))
        if patch.chart:
            # A cap ends at its sides. Only the map goes around.
            self.left = max(self.left, 0)
            right = min(right, size * patch.columns(level))

        plain = self._map(level, self.top, bottom, self.left, right)
        # Per raster, what the blocks need of it.
        self.held: list[Image.Image] = []
        seen = np.zeros(plain.shape[:2], dtype=bool)
        # The one read of the rasters from end to end.
        with ThreadPoolExecutor(_WORKERS) as pool:
            for index in range(len(patch.rasters)):
                fine = patch.fine(
                    index, level, self.top, bottom, self.left, right, pool
                )
                here = np.isfinite(fine)
                self._take(index, plain, fine, here)
                seen |= here
        # Full weight one blur inside the rasters: at their edge the patch
        # fades into the map.
        inside = ndimage.distance_transform_edt(seen)
        weight = np.clip(inside / max(patch.sigma, 1.0), 0.0, 1.0).astype(np.float32)
        # Held as images: every block cuts its part from each, and an array
        # would be copied whole each time.
        self.weight = Image.fromarray(weight)
        self.plain = Image.fromarray(plain)
        self._keep(plain)

    def _take(
        self, index: int, plain: np.ndarray, fine: np.ndarray, here: np.ndarray
    ) -> None:
        """Hold what the blocks need of raster ``index``, read as ``fine`` on
        the grid of ``plain``: for a colour map, the raster blurred."""
        sigma = self.patch.sigma
        # Each raster blurred on its own: two mosaics of one place differ in
        # brightness by their sun, and only what each shows within itself is
        # detail.
        coverage = ndimage.gaussian_filter(here.astype(np.float32), sigma)
        coarse = ndimage.gaussian_filter(np.where(here, fine, 0.0), sigma)
        low = np.ones_like(fine)
        np.divide(coarse, coverage, out=low, where=coverage > 0.05)
        if _region(self.patch.rasters[index]).calibrated and here.any():
            floor = _SHADOW_FLOOR * float(fine[here].mean())
            np.maximum(low, floor, out=low)
        self.held.append(Image.fromarray(low))

    def _keep(self, plain: np.ndarray) -> None:
        self.soft = Image.fromarray(tiles.soften(plain, self.patch.sigma))

    def _decode(self, tile: Image.Image) -> np.ndarray:
        """A tile of the pyramid as the values a patch is made of."""
        return np.asarray(tile.convert("RGB"))

    def _map(self, level: int, y0: int, y1: int, x0: int, x1: int) -> np.ndarray:
        """Pixels of the pyramid's own tiles; columns of the map wrap around
        the globe."""
        size = config.TILE_SIZE
        columns = self.patch.columns(level)
        out: np.ndarray | None = None
        for ty in range(y0 // size, (y1 - 1) // size + 1):
            for tx in range(x0 // size, (x1 - 1) // size + 1):
                path = own_tile(self.patch.pyramid, level, tx % columns, ty)
                tile = self._decode(Image.open(path))
                if out is None:
                    out = np.empty((y1 - y0, x1 - x0, *tile.shape[2:]), tile.dtype)
                top, left = max(y0, ty * size), max(x0, tx * size)
                bottom, right = min(y1, (ty + 1) * size), min(x1, (tx + 1) * size)
                out[top - y0 : bottom - y0, left - x0 : right - x0] = tile[
                    top - ty * size : bottom - ty * size,
                    left - tx * size : right - tx * size,
                ]
        assert out is not None
        return out

    def _box(
        self, level: int, x0: int, y0: int, x1: int, y1: int
    ) -> tuple[float, float, float, float]:
        """A pixel window of ``level`` on this grid."""
        scale = 1 << (level - self.patch.base_level)
        return (
            x0 / scale - self.left,
            y0 / scale - self.top,
            x1 / scale - self.left,
            y1 / scale - self.top,
        )

    def map_tile(self, level: int, tile_x: int, tile_y: int) -> np.ndarray:
        """A tile the rasters do not touch: the map, enlarged."""
        size = config.TILE_SIZE
        x0, y0 = tile_x * size, tile_y * size
        box = self._box(level, x0, y0, x0 + size, y0 + size)
        return _resized(self.plain, box, (size, size), self.smooth)

    def block(
        self, level: int, tile_x: int, tile_y: int, across: int, down: int
    ) -> np.ndarray:
        """The tiles of ``level`` from ``(tile_x, tile_y)``, ``across`` by
        ``down``, as one array."""
        size = config.TILE_SIZE
        x0, y0 = tile_x * size, tile_y * size
        x1, y1 = x0 + across * size, y0 + down * size
        box = self._box(level, x0, y0, x1, y1)
        shape = (x1 - x0, y1 - y0)
        plain = _resized(self.plain, box, shape)
        weight = _resized(self.weight, box, shape)
        if not weight.any():
            return plain
        # A later raster over an earlier one, where it has data.
        ratio = np.ones(weight.shape, dtype=np.float32)
        usable = np.zeros(weight.shape, dtype=bool)
        for index, coarse in enumerate(self.held):
            fine = self.patch.fine(index, level, y0, y1, x0, x1)
            low = _resized(coarse, box, shape)
            here = np.isfinite(fine) & (low > 0)
            np.divide(fine, low, out=ratio, where=here)
            usable |= here
        np.clip(ratio, *config.TILE_SHARPEN_RANGE, out=ratio)
        sharp = tiles.apply_detail(_resized(self.soft, box, shape), ratio)
        alpha = np.where(usable, weight, 0.0)[..., None]
        return np.rint(plain * (1.0 - alpha) + sharp * alpha).astype(np.uint8)


class _HeightGround(_Ground):
    """The ground of a height patch: the pyramid's heights in km, and for each
    raster how far the pyramid stands above it at the scale of the blur."""

    smooth = True

    def _take(
        self, index: int, plain: np.ndarray, fine: np.ndarray, here: np.ndarray
    ) -> None:
        sigma = self.patch.sigma
        # The difference is blurred, not each map: at the edge of a raster a
        # blur has ground on one side only, and on a slope that alone would
        # raise or sink the patch there.
        coverage = ndimage.gaussian_filter(here.astype(np.float32), sigma)
        apart = ndimage.gaussian_filter(np.where(here, plain - fine, 0.0), sigma)
        offset = np.zeros_like(fine)
        np.divide(apart, coverage, out=offset, where=coverage > 0.05)
        self.held.append(Image.fromarray(offset))

    def _keep(self, plain: np.ndarray) -> None:
        pass

    def _decode(self, tile: Image.Image) -> np.ndarray:
        coding = self.patch.coding
        assert coding is not None
        return coding.unpack(np.asarray(tile.convert("RGB")))

    def block(
        self, level: int, tile_x: int, tile_y: int, across: int, down: int
    ) -> np.ndarray:
        size = config.TILE_SIZE
        x0, y0 = tile_x * size, tile_y * size
        x1, y1 = x0 + across * size, y0 + down * size
        box = self._box(level, x0, y0, x1, y1)
        shape = (x1 - x0, y1 - y0)
        plain = _resized(self.plain, box, shape, smooth=True)
        weight = _resized(self.weight, box, shape)
        if not weight.any():
            return plain
        # A later raster over an earlier one. Two terrain models of one place
        # stand apart by what their blurs do not show, and a cut from one to
        # the other would be a step in the ground: each comes in gradually.
        top = max(y0 - _SEAM, 0)
        bottom = min(y1 + _SEAM, size << level)
        rows = slice(y0 - top, y1 - top)
        columns = slice(_SEAM, _SEAM + x1 - x0)
        sharp = plain.copy()
        for index, offset in enumerate(self.held):
            fine = self.patch.fine(index, level, top, bottom, x0 - _SEAM, x1 + _SEAM)
            here = np.isfinite(fine)
            if not here.any():
                continue
            share = _inside(here)[rows, columns]
            over = fine[rows, columns] + _resized(offset, box, shape) - sharp
            np.add(sharp, over * share, out=sharp, where=share > 0)
        return plain + (sharp - plain) * weight


class _Over:
    """What a patch draws over the pyramid's own tiles: its first level made
    one level coarser, as whole tiles of the pyramid's finest level. It is
    opaque where the rasters are: its tiles already fade into the map there,
    and a second fade would weaken the detail at the edge."""

    def __init__(self, patch: PatchBuilder, ground: _Ground) -> None:
        self.patch = patch
        size = config.TILE_SIZE
        x0, x1, y0, y1 = patch.tile_range(patch.base_level)
        # From an even tile to an odd one: whole tiles of the next level.
        x0, y0 = x0 - x0 % 2, y0 - y0 % 2
        self.x0, self.y0 = x0, y0
        shape = (((y1 | 1) - y0 + 1) * size, ((x1 | 1) - x0 + 1) * size)
        self.image = np.zeros((*shape, 3), dtype=np.uint8)
        self.alpha = np.zeros(shape, dtype=np.uint8)
        # The ground is on the same grid, and starts at a pixel of its own.
        weight = np.asarray(ground.weight)
        top, left = ground.top - y0 * size, ground.left - x0 * size
        rows = slice(max(top, 0), min(top + weight.shape[0], shape[0]))
        columns = slice(max(left, 0), min(left + weight.shape[1], shape[1]))
        inside = weight[
            rows.start - top : rows.stop - top,
            columns.start - left : columns.stop - left,
        ]
        self.alpha[rows, columns] = np.where(inside > 0, 255, 0)

    def take(self, x: int, y: int, values: np.ndarray) -> None:
        """Hold tile ``(x, y)`` of the patch's first level."""
        half = config.TILE_SIZE // 2
        top = y * half - self.y0 * config.TILE_SIZE
        left = x * half - self.x0 * config.TILE_SIZE
        self.image[top : top + half, left : left + half] = tiles._halve(values)

    def write(self, out_dir: Path) -> None:
        """One tile for each tile of the pyramid that the patch shows in."""
        size = config.TILE_SIZE
        image, alpha = self.image, self.alpha
        x0, y0 = self.x0, self.y0
        for level in range(
            self.patch.base_level, self.patch.base_level - self.patch.map_levels, -1
        ):
            for down in range(alpha.shape[0] // size):
                for right in range(alpha.shape[1] // size):
                    rows = slice(down * size, (down + 1) * size)
                    columns = slice(right * size, (right + 1) * size)
                    if not alpha[rows, columns].any():
                        continue
                    tile = np.dstack([image[rows, columns], alpha[rows, columns]])
                    folder = out_dir / str(level) / str(x0 + right)
                    folder.mkdir(parents=True, exist_ok=True)
                    Image.fromarray(tile).save(
                        folder / f"{y0 + down}.webp",
                        "webp",
                        **config.TILE_LOSSLESS_KWARGS,
                    )
            # Whole tiles of the next level, which may start a tile earlier.
            pad = (
                (y0 % 2 * size, (alpha.shape[0] // size + y0) % 2 * size),
                (x0 % 2 * size, (alpha.shape[1] // size + x0) % 2 * size),
            )
            if any(map(any, pad)):
                alpha = np.pad(alpha, pad)
                image = np.pad(image, (*pad, (0, 0)))
            image, alpha = _coarser(image, alpha)
            x0, y0 = x0 // 2, y0 // 2


def _polar(raster: Raster) -> tiles.PolarRegion:
    region = raster.pixels
    assert isinstance(region, tiles.PolarRegion)
    return region


def _coarser(image: np.ndarray, alpha: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """``image`` and its ``alpha`` at half the size. Each pixel counts by its
    alpha: one that the patch does not draw has no colour to give."""
    out = np.zeros((image.shape[0] // 2, image.shape[1] // 2, 3), dtype=np.uint8)
    low = np.zeros(out.shape[:2], dtype=np.uint8)
    # In strips: the whole image as floats is several times its size.
    rows = 2 * config.TILE_SIZE
    for top in range(0, image.shape[0], rows):
        part = slice(top // 2, (top + rows) // 2)
        weight = alpha[top : top + rows].astype(np.float32)
        held = tiles._halve(image[top : top + rows] * weight[..., None])
        weight = tiles._halve(weight)
        np.divide(held, weight[..., None], out=held, where=weight[..., None] > 0)
        out[part] = np.rint(held)
        low[part] = np.rint(weight)
    return out, low


def _tiles_under(folder: Path) -> set[tuple[int, int, int]]:
    """Level, column and row of each tile under ``folder``."""
    return {
        (int(path.parts[-3]), int(path.parts[-2]), int(path.stem))
        for path in folder.glob("*/*/*.webp")
    }


def _lay(pyramid: Path, level: int, x: int, y: int) -> None:
    """Make tile ``(x, y)`` of one of the pyramid's own levels again: its own
    pixels, with what each patch draws over them."""
    name = Path(str(level), str(x), f"{y}.webp")
    shown, own = pyramid / name, pyramid / _OWN_DIR / name
    overs = sorted((pyramid / _OVER_DIR).glob(f"*/{name}"))
    if not overs:
        if own.exists():
            # As the pyramid built it, byte for byte.
            own.replace(shown)
            _drop_empty(own.parent, pyramid)
        return
    if not own.exists():
        own.parent.mkdir(parents=True, exist_ok=True)
        part = own.with_suffix(".part")
        shutil.copyfile(shown, part)
        part.replace(own)
    tile = np.asarray(Image.open(own).convert("RGB")).astype(np.float32)
    for over in overs:
        drawn = np.asarray(Image.open(over).convert("RGBA")).astype(np.float32)
        tile += (drawn[..., :3] - tile) * (drawn[..., 3:] / 255.0)
    # A reader never sees half a tile.
    part = shown.with_suffix(".part")
    Image.fromarray(np.rint(tile).astype(np.uint8)).save(
        part, "webp", **webp_kwargs(lossless=False)
    )
    part.replace(shown)


def _drop_empty(folder: Path, stop: Path) -> None:
    """Remove ``folder`` and the folders over it, up to ``stop``, while they
    are empty."""
    while folder != stop and not any(folder.iterdir()):
        folder.rmdir()
        folder = folder.parent


def _draw(pyramid: Path, patch_id: str, built: Path | None) -> None:
    """Change what patch ``patch_id`` draws over the pyramid's own tiles for
    the tiles under ``built``, or for nothing, and make each tile that either
    touches again."""
    over = pyramid / _OVER_DIR / patch_id
    touched = _tiles_under(over)
    shutil.rmtree(over, ignore_errors=True)
    if built is not None and built.exists():
        over.parent.mkdir(exist_ok=True)
        built.replace(over)
        touched |= _tiles_under(over)
    for level, x, y in sorted(touched):
        _lay(pyramid, level, x, y)
    if over.parent.exists():
        _drop_empty(over.parent, pyramid)


def put_in_place(built: Path, pyramid: Path, patch_id: str) -> None:
    """Move the tiles of a patch built aside into its pyramid, and draw the
    patch over the pyramid's own tiles."""
    _draw(pyramid, patch_id, built / _OVER_DIR)
    for level in built.iterdir():
        for column in level.iterdir():
            target = pyramid / level.name / column.name
            target.mkdir(parents=True, exist_ok=True)
            for tile in column.iterdir():
                tile.replace(target / tile.name)
            column.rmdir()
        level.rmdir()
    built.rmdir()


def remove(pyramid: Path, base_level: int, patch: dict) -> None:
    """Delete the tiles of a patch, as its descriptor entry states them, and
    give the pyramid its own tiles back."""
    _draw(pyramid, patch["id"], None)
    (x0, x1), (y0, y1) = patch["x"], patch["y"]
    for level in range(base_level + 1, patch["max_level"] + 1):
        shift = patch["max_level"] - level
        folder = pyramid / str(level)
        for x in range(x0 >> shift, (x1 >> shift) + 1):
            for y in range(y0 >> shift, (y1 >> shift) + 1):
                (folder / str(x) / f"{y}.webp").unlink(missing_ok=True)
            if (folder / str(x)).exists() and not any((folder / str(x)).iterdir()):
                (folder / str(x)).rmdir()
        if folder.exists() and not any(folder.iterdir()):
            folder.rmdir()
