"""Patches: areas where a tile pyramid goes deeper than its finest level.

A landing site can have a mosaic a hundred times as sharp as the map of its
body. A patch holds it as the tiles of the levels past the pyramid's own, for
the ground the mosaic covers and no more.

A patch is built on the tiles of its pyramid. Their colour and their broad
tone stay, so a patch joins the map around it without a step. Everything
finer comes from the mosaic alone: the map's own detail may sit some pixels
from the mosaic's, and each feature would otherwise show twice.
"""

import logging
import math
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from . import config, tiles
from .encoding import webp_kwargs

log = logging.getLogger(__name__)

# Bumped when a change to the build changes the bytes of a patch's tiles.
RECIPE = 3
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
# Least broad brightness the detail of a calibrated raster is compared with,
# as a share of the raster's average. A shadow wider than the blur has almost
# none of its own: its noise would otherwise count as detail as strong as the
# ground's.
_SHADOW_FLOOR = 0.2


def _resized(
    values: np.ndarray, box: tuple[float, float, float, float], size: tuple[int, int]
) -> np.ndarray:
    """``box`` of ``values`` at ``size``: smooth for colour, linear for the
    slow fields a ratio is made of."""
    filter_ = (
        Image.Resampling.BICUBIC if values.ndim == 3 else Image.Resampling.BILINEAR
    )
    return np.asarray(Image.fromarray(values).resize(size, filter_, box=box))


def _region(raster: tiles.Layer) -> tiles.Region:
    pixels = raster.pixels
    assert isinstance(pixels, tiles.Region)
    return pixels


def _bounds(raster: tiles.Layer) -> tuple[float, float, float, float]:
    return _region(raster).bounds


def _parts(raster: tiles.Layer) -> tuple[tiles.Layer, tiles.Layer]:
    """A raster as two fields that can be resampled: its values with nothing
    where it has no data, and the share of data. A site mosaic is strips with
    gaps between them, and one missing pixel under a filter would otherwise
    take the whole output pixel with it."""
    to_values = raster.to_values
    assert to_values is not None

    def filled(raw: np.ndarray) -> np.ndarray:
        values = to_values(raw)
        return np.where(np.isfinite(values), values, np.float32(0.0))

    def share(raw: np.ndarray) -> np.ndarray:
        return np.isfinite(to_values(raw)).astype(np.float32)

    return (
        tiles.Layer(raster.pixels, raster.placement, to_values=filled),
        tiles.Layer(raster.pixels, raster.placement, to_values=share),
    )


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
    level.
    """

    def __init__(
        self,
        name: str,
        pyramid: Path,
        base_level: int,
        rasters: Sequence[tiles.Layer],
        out_dir: Path,
        sigma: float,
        max_level: int | None = None,
    ) -> None:
        self.name = name
        self.pyramid = pyramid
        self.base_level = base_level
        self.rasters = rasters
        self.out_dir = out_dir
        self.sigma = sigma
        # A raster away from the equator has wider pixels in longitude than in
        # latitude: the finer of the two decides.
        widest = max(max(raster.width, 2 * raster.height) for raster in rasters)
        self.level = tiles.finest_level(widest) if max_level is None else max_level
        self._parts = [_parts(raster) for raster in rasters]
        if self.level <= base_level:
            raise ValueError(f"{name}: no finer than level {base_level} of its map")
        edges = [_bounds(raster) for raster in rasters]
        self.west = min(edge[0] for edge in edges)
        self.east = max(edge[1] for edge in edges)
        self.north = max(edge[2] for edge in edges)
        self.south = min(edge[3] for edge in edges)
        self.stats = tiles.PyramidStats.empty(self.level)
        self._lock = threading.Lock()
        self._save_kwargs = webp_kwargs(lossless=False)
        # Level of the tile a block leaves, and of the tile a group leaves.
        self._block_level = max(self.level - _BLOCK_LEVELS, base_level + 1)
        self._group_level = max(self._block_level - _GROUP_LEVELS, base_level + 1)

    def tile_range(self, level: int) -> tuple[int, int, int, int]:
        """First and last column, then first and last row, of the tiles of
        ``level`` that the rasters touch."""
        columns, rows = 2 << level, 1 << level
        return (
            math.floor((self.west + 180.0) / 360.0 * columns),
            math.ceil((self.east + 180.0) / 360.0 * columns) - 1,
            math.floor((90.0 - self.north) / 180.0 * rows),
            math.ceil((90.0 - self.south) / 180.0 * rows) - 1,
        )

    def _touched(self, level: int, x: int, y: int) -> bool:
        x0, x1, y0, y1 = self.tile_range(level)
        return x0 <= x <= x1 and y0 <= y <= y1

    def build(self) -> tiles.PyramidStats:
        ground = _Ground(self)
        first = self.base_level + 1
        for level in range(first, self.level + 1):
            x0, x1, _, _ = self.tile_range(level)
            for x in range(x0, x1 + 1):
                (self.out_dir / str(level) / str(x)).mkdir(parents=True, exist_ok=True)
        x0, x1, y0, y1 = self.tile_range(first)
        with ThreadPoolExecutor(_WORKERS) as pool:
            for y in range(y0, y1 + 1):
                for x in range(x0, x1 + 1):
                    self._tile(pool, ground, first, x, y)
                log.info(
                    "%s: tile row %d of %d, %d tiles",
                    self.name,
                    y - y0 + 1,
                    y1 - y0 + 1,
                    sum(self.stats.tiles),
                )
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
        """Brightness of raster ``index`` over a pixel window of ``level``,
        NaN where less than half of a pixel has data. A window that takes
        many reads can share them out over ``pool``."""
        raster = self.rasters[index]
        filled, share = self._parts[index]
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
            total = filled.window(width, lat_edges, left, right)
            seen = share.window(width, lat_edges, left, right)
            held = out[top - y0 : bottom - y0, left - x0 : right - x0]
            np.divide(total, seen, out=held, where=seen > 0.5)

        list((pool.map if pool else map)(band, range(first, last, step)))
        return out

    def _tile(
        self, pool: ThreadPoolExecutor, ground: "_Ground", level: int, x: int, y: int
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

    def _block(self, ground: "_Ground", x: int, y: int) -> np.ndarray:
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
        bottom = min((y1 + 1) * half + reach, size << level)

        self.plain = self._map(level, self.top, bottom, self.left, right)
        sigma = patch.sigma
        # Each raster blurred on its own: two mosaics of one place differ in
        # brightness by their sun, and only what each shows within itself is
        # detail.
        self.lows = []
        seen = np.zeros(self.plain.shape[:2], dtype=bool)
        # The one read of the rasters from end to end.
        with ThreadPoolExecutor(_WORKERS) as pool:
            for index in range(len(patch.rasters)):
                fine = patch.fine(
                    index, level, self.top, bottom, self.left, right, pool
                )
                here = np.isfinite(fine)
                coverage = ndimage.gaussian_filter(here.astype(np.float32), sigma)
                coarse = ndimage.gaussian_filter(np.where(here, fine, 0.0), sigma)
                low = np.ones_like(fine)
                np.divide(coarse, coverage, out=low, where=coverage > 0.05)
                if _region(patch.rasters[index]).calibrated and here.any():
                    floor = _SHADOW_FLOOR * float(fine[here].mean())
                    np.maximum(low, floor, out=low)
                self.lows.append(low)
                seen |= here
        # Full weight one blur inside the rasters: at their edge the patch
        # fades into the map.
        inside = ndimage.distance_transform_edt(seen)
        self.weight = np.clip(inside / max(sigma, 1.0), 0.0, 1.0).astype(np.float32)
        self.soft = tiles.soften(self.plain, sigma)

    def _map(self, level: int, y0: int, y1: int, x0: int, x1: int) -> np.ndarray:
        """Pixels of the pyramid's own tiles; columns wrap around the globe."""
        size = config.TILE_SIZE
        columns = 2 << level
        out = np.empty((y1 - y0, x1 - x0, 3), dtype=np.uint8)
        for ty in range(y0 // size, (y1 - 1) // size + 1):
            for tx in range(x0 // size, (x1 - 1) // size + 1):
                path = self.patch.pyramid / str(level) / str(tx % columns)
                tile = np.asarray(Image.open(path / f"{ty}.webp").convert("RGB"))
                top, left = max(y0, ty * size), max(x0, tx * size)
                bottom, right = min(y1, (ty + 1) * size), min(x1, (tx + 1) * size)
                out[top - y0 : bottom - y0, left - x0 : right - x0] = tile[
                    top - ty * size : bottom - ty * size,
                    left - tx * size : right - tx * size,
                ]
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
        return _resized(self.plain, box, (size, size))

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
        for index, coarse in enumerate(self.lows):
            fine = self.patch.fine(index, level, y0, y1, x0, x1)
            low = _resized(coarse, box, shape)
            here = np.isfinite(fine) & (low > 0)
            np.divide(fine, low, out=ratio, where=here)
            usable |= here
        np.clip(ratio, *config.TILE_SHARPEN_RANGE, out=ratio)
        sharp = tiles.apply_detail(_resized(self.soft, box, shape), ratio)
        alpha = np.where(usable, weight, 0.0)[..., None]
        return np.rint(plain * (1.0 - alpha) + sharp * alpha).astype(np.uint8)


def put_in_place(built: Path, pyramid: Path) -> None:
    """Move the tiles of a patch built aside into its pyramid."""
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
    """Delete the tiles of a patch, as its descriptor entry states them."""
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
