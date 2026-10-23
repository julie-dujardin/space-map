"""Site mosaics taken in a low Sun, with the shading of that Sun taken out.

The renderer lights the ground with its own Sun. A mosaic taken in a low Sun
holds the long shadows and the bright and dark slopes of that Sun. These then
show twice, or against the renderer's light at another time of day. Where a
terrain model of the site covers the mosaic, the shading of the mosaic's Sun
is found on the model and divided out. Ground that this Sun did not light
holds no picture of its own: it takes the corrected ground around it.

The label of a mosaic does not give its Sun: a mosaic joins images of many
passes. The Sun is the one whose shading on the model best matches the
mosaic's detail.

The copy keeps the label and the layout of its source, so it reads as the
source does.
"""

import logging
import math
import shutil
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from scipy import ndimage

from . import tiles
from .image_io import open_pds_image, read_pds_label
from .patches import fields

log = logging.getLogger(__name__)

# Bumped when a change to the build changes the bytes of a copy.
RECIPE = 5
# Grid the mosaic's Sun is fitted on, and that of the shadows its slopes cast,
# in metres. Finer grids cost much time for little.
_FIT_M = 20.0
_SHADOW_M = 5.0
# Scale below which the mosaic's brightness is compared with the shading. The
# broad tone of the ground is its own.
_DETAIL_M = 300.0
# Distance over which the correction comes in from the edge of the terrain
# models. Past them the mosaic keeps its shading, and a narrow band shows as
# a line. A later model comes in over the ones before it as slowly: an offset
# between two models would otherwise show as a slope.
_FEATHER_M = 300.0
_BLEND_M = 400.0
# Least shading divided out, as a share of that of flat ground. A slope darker
# than this, a cast shadow, and dark ground hold too little picture.
_FLOOR = 0.3
# Dark ground: darker than this share of the mosaic's typical brightness.
_DARK = 0.3
# Least match of a Sun found on the models. Below it, the models are too
# noisy or the mosaic too flat, and dividing by a wrong shading would print
# a false one.
_LEAST_MATCH = 0.6
# Scales in mosaic pixels from which hidden ground takes the ground around it,
# wider for a larger area: no edge shows where it starts.
_FILL_SIGMAS = (8.0, 32.0, 128.0)
# The same on the grid the Sun is fitted on, for ground hidden from wider
# around: a mountain's shadow can be kilometres long.
_BROAD_SIGMAS = (2.0, 8.0, 32.0, 128.0)
# Least share of known ground under a fill for it to count.
_FILL_LEAST = 0.02
# Most pixels of the grid of shadows, about 4 GB in the works. A site whose
# models lie far apart takes a coarser one.
_GRID_PIXELS = 50_000_000
# Mosaic pixels corrected at a time.
_BLOCK = 2048
# Blocks in the works at a time: each holds about 1 GB.
_WORKERS = 4


@dataclass(frozen=True)
class Light:
    """The mosaic's Sun, and how strongly its shading shows in the mosaic."""

    # Degrees from north, east positive.
    azimuth: float
    elevation: float
    # Correlation of the shading with the mosaic's detail.
    match: float
    # Power of the shading in the mosaic: 1 for a surface that scatters light
    # as Lambert's law states.
    gain: float


def copy_name(mosaic: str, key: str) -> str:
    """The file name of the copy of ``mosaic`` for ``key``."""
    path = Path(mosaic)
    return f"{path.stem}-{key}{path.suffix}"


def copy_of(name: str, mosaic: str) -> bool:
    """Whether the file ``name`` is a copy of ``mosaic``, for any key."""
    path = Path(mosaic)
    return name.startswith(f"{path.stem}-") and name.endswith(path.suffix)


def deshaded(
    mosaic: Path, terrain: Sequence[tiles.Layer], key: str, folder: Path
) -> Path:
    """The copy of ``mosaic`` with its Sun's shading taken out, made first if
    ``folder`` has none for ``key``."""
    out = folder / copy_name(mosaic.name, key)
    if out.exists():
        return out
    folder.mkdir(parents=True, exist_ok=True)
    # A stopped build leaves no file that reads as whole, and no part of one:
    # a copy is gigabytes.
    partial = out.with_name(out.name + ".partial")
    try:
        light = write(mosaic, terrain, partial)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    partial.rename(out)
    log.info(
        "deshaded %s: Sun at azimuth %.0f, %.1f up (match %.2f), gain %.2f",
        mosaic.name,
        light.azimuth,
        light.elevation,
        light.match,
        light.gain,
    )
    return out


def write(mosaic: Path, terrain: Sequence[tiles.Layer], out: Path) -> Light:
    """Write ``mosaic`` to ``out`` with its Sun's shading taken out where the
    ``terrain`` models cover it."""
    if mosaic.suffix.lower() != ".img":
        raise ValueError(f"{mosaic.name}: only PDS3 images are deshaded")
    source = open_pds_image(mosaic)
    assert isinstance(source, np.memmap)
    # Integer samples are stretched for viewing, and a corrected value has no
    # place in that stretch.
    if source.dtype.kind != "f":
        raise ValueError(f"{mosaic.name}: only calibrated samples are deshaded")
    radius_km = read_pds_label(mosaic).get("A_AXIS_RADIUS")
    if radius_km is None:
        raise ValueError(f"{mosaic.name}: the label gives no radius")
    radius_m = float(radius_km) * 1000.0
    layer = tiles.open_region_layer(mosaic)
    to_values = layer.to_values
    assert to_values is not None
    site = _Site(layer, terrain, radius_m)

    light, cast, typical = site.light()
    shutil.copyfile(mosaic, out)
    target = np.memmap(
        out, dtype=source.dtype, mode="r+", offset=source.offset, shape=source.shape
    )
    height, width = source.shape
    blocks = [
        (y, x)
        for y in range(0, height, _BLOCK)
        for x in range(0, width, _BLOCK)
        if site.covers(y, min(y + _BLOCK, height), x, min(x + _BLOCK, width))
    ]
    log.info("deshading %s: %d blocks", mosaic.name, len(blocks))

    def correct(block: tuple[int, int]) -> None:
        y, x = block
        y1, x1 = min(y + _BLOCK, height), min(x + _BLOCK, width)
        site.correct(source, target, to_values, (y, y1, x, x1), light, cast, typical)

    with ThreadPoolExecutor(_WORKERS) as pool:
        for done, _ in enumerate(pool.map(correct, blocks), 1):
            if done % 50 == 0:
                log.info(
                    "deshading %s: %d of %d blocks", mosaic.name, done, len(blocks)
                )
    target.flush()
    return light


class _Site:
    """A mosaic over the terrain models of its site, on the grids the Sun is
    found on."""

    def __init__(
        self, mosaic: tiles.Layer, terrain: Sequence[tiles.Layer], radius_m: float
    ) -> None:
        region = mosaic.pixels
        assert isinstance(region, tiles.Region)
        self.mosaic = mosaic
        self.terrain = [fields(model) for model in terrain]
        self.radius_m = radius_m
        self.rows, self.columns = region.shape
        west, east, north, south = region.bounds
        self.top = round((90.0 - north) / 180.0 * self.rows)
        self.left = round((west + 180.0) / 360.0 * self.columns)
        self.pixel_m = math.radians(180.0 / self.rows) * radius_m
        # The terrain models' ground on the mosaic, in degrees.
        boxes = []
        for model in terrain:
            assert isinstance(model.pixels, tiles.Region)
            boxes.append(model.pixels.bounds)
        self.area = (
            max(west, min(b[0] for b in boxes)),
            min(east, max(b[1] for b in boxes)),
            min(north, max(b[2] for b in boxes)),
            max(south, min(b[3] for b in boxes)),
        )
        if self.area[0] >= self.area[1] or self.area[3] >= self.area[2]:
            raise ValueError("no terrain model over the mosaic")
        self.cos_lat = math.cos(math.radians((self.area[2] + self.area[3]) / 2))

    def _level(self, metres: float) -> int:
        """The pyramid level whose pixel is closest to ``metres``."""
        around = 2 * math.pi * self.radius_m / tiles.level_width(0)
        return max(0, round(math.log2(around / metres)))

    def light(self) -> tuple[Light, _Grid, float]:
        """The mosaic's Sun, the shadows its slopes cast, and the mosaic's
        typical brightness."""
        fine = self._level(_SHADOW_M)
        while fine > 0 and self._pixels(fine) > _GRID_PIXELS:
            fine -= 1
        coarse = min(self._level(_FIT_M), fine)
        grid = self._grid(fine, 1 << (fine - coarse + 1))
        valid = np.isfinite(grid.image) & (grid.inside > 0.99)
        if valid.sum() < 1000:
            raise ValueError("too little of the mosaic over the terrain models")
        typical = float(np.median(grid.image[valid]))

        # A walk from a single start can end on a lesser peak of the match:
        # the whole sky is tried first, on a grid coarse enough to be quick.
        factor = 1 << (fine - coarse)
        rough = _scorer(grid.coarser(factor * 2), self.cos_lat)
        score = _scorer(grid.coarser(factor), self.cos_lat)
        _, azimuth, elevation = max(
            (rough(a, e), float(a), float(e))
            for a in range(0, 360, 15)
            for e in (5, 10, 15, 20, 30, 45, 60)
        )
        match = score(azimuth, elevation)
        for step in (8.0, 4.0, 2.0, 1.0):
            while True:
                tries = [
                    (azimuth + da, elevation + de)
                    for da, de in ((step, 0), (-step, 0), (0, step), (0, -step))
                    if 1.0 <= elevation + de <= 85.0
                ]
                best = max((score(a, e), a % 360.0, e) for a, e in tries)
                if best[0] <= match:
                    break
                match, azimuth, elevation = best
        if match < _LEAST_MATCH:
            raise ValueError(f"no Sun of the mosaic matches the models ({match:.2f})")

        shade = _cast_shadows(grid, self.cos_lat, azimuth, elevation)
        gain = _gain(grid, shade, self.cos_lat, azimuth, elevation, typical)
        light = Light(azimuth, elevation, match, gain)
        broad = _broad(
            grid.coarser(factor), shade, factor, self.cos_lat, light, typical
        )
        return (
            light,
            replace(grid, shade=shade, broad=broad, broad_factor=factor),
            typical,
        )

    def _pixels(self, level: int) -> float:
        """Pixels of the area at ``level``."""
        west, east, north, south = self.area
        per_degree = tiles.level_width(level) / 360.0
        return (east - west) * (north - south) * per_degree**2

    def _grid(self, level: int, multiple: int) -> _Grid:
        """The mosaic and the models over the area at ``level``, a whole number
        of ``multiple`` pixels a side."""
        width = tiles.level_width(level)
        rows = width // 2
        west, east, north, south = self.area
        y0 = math.floor((90.0 - north) / 180.0 * rows)
        y1 = math.ceil((90.0 - south) / 180.0 * rows)
        x0 = math.floor((west + 180.0) / 360.0 * width)
        x1 = math.ceil((east + 180.0) / 360.0 * width)
        y1 = y0 + -(-(y1 - y0) // multiple) * multiple
        x1 = x0 + -(-(x1 - x0) // multiple) * multiple
        edges = 90.0 - np.arange(y0, y1 + 1) * (180.0 / rows)
        both = fields(self.mosaic).window(width, edges, x0, x1)
        image = np.where(
            both[..., 1] > 0.5, both[..., 0] / np.maximum(both[..., 1], 1e-6), np.nan
        )
        step_m = math.radians(360.0 / width) * self.radius_m
        heights, inside = _heights(
            self.terrain, width, edges, x0, x1, step_m, step_m * self.cos_lat
        )
        return _Grid(image.astype(np.float32), heights, inside, step_m, y0, x0, width)

    def covers(self, y0: int, y1: int, x0: int, x1: int) -> bool:
        """Whether mosaic pixels ``y0:y1``, ``x0:x1`` reach the models."""
        north = 90.0 - (self.top + y0) / self.rows * 180.0
        south = 90.0 - (self.top + y1) / self.rows * 180.0
        west = (self.left + x0) / self.columns * 360.0 - 180.0
        east = (self.left + x1) / self.columns * 360.0 - 180.0
        a_west, a_east, a_north, a_south = self.area
        return west < a_east and a_west < east and south < a_north and a_south < north

    def correct(
        self,
        source: np.ndarray,
        target: np.ndarray,
        to_values: Callable[[np.ndarray], np.ndarray],
        block: tuple[int, int, int, int],
        light: Light,
        cast: _Grid,
        typical: float,
    ) -> None:
        """Take the shading out of one block of the mosaic."""
        b0, b1, c0, c1 = block
        height, width = source.shape
        # The columns of a mosaic are as far apart as its label's latitude of
        # true scale has them, not as the rows.
        lat = 90.0 - (self.top + (b0 + b1) / 2) / self.rows * 180.0
        step_x = (
            math.radians(360.0 / self.columns)
            * self.radius_m
            * math.cos(math.radians(lat))
        )
        # Read around the block as far as the widest fill and the widest blend
        # reach: a block would otherwise not match the one beside it.
        reach_m = max(_FEATHER_M, _BLEND_M)
        pad = 8 + max(
            4 * math.ceil(_FILL_SIGMAS[-1]),
            math.ceil(reach_m / min(self.pixel_m, step_x)),
        )
        r0, r1 = max(b0 - pad, 0), min(b1 + pad, height)
        q0, q1 = max(c0 - pad, 0), min(c1 + pad, width)
        raw = np.asarray(source[r0:r1, q0:q1])
        edges = 90.0 - (self.top + np.arange(r0, r1 + 1)) * (180.0 / self.rows)
        heights, inside = _heights(
            self.terrain,
            self.columns,
            edges,
            self.left + q0,
            self.left + q1,
            self.pixel_m,
            step_x,
        )
        if not (inside > 0.0).any():
            return
        image = to_values(raw)
        valid = np.isfinite(image)
        normals = _normals(heights, self.pixel_m, step_x)
        shading = _shading(normals, light.azimuth, light.elevation)
        del normals
        # Nearest, not smoothed: ground is in a shadow or not.
        lats = 90.0 - (self.top + np.arange(r0, r1) + 0.5) * (180.0 / self.rows)
        lons = (self.left + np.arange(q0, q1) + 0.5) * (360.0 / self.columns) - 180.0
        shadow = cast.nearest(lats, lons)
        # Dark ground, not dark pixels: one at a time they would leave the map
        # showing through as specks.
        soft = ndimage.uniform_filter(np.where(valid, image, typical), 5)
        dark = ndimage.binary_opening(soft < _DARK * typical, iterations=2)
        dark = ndimage.binary_dilation(dark, iterations=3)
        hidden = (shadow | (shading < _FLOOR) | dark) & (inside > 0.0)
        # Outlines of whole areas, not of the models' noise.
        hidden = ndimage.binary_opening(
            ndimage.binary_closing(hidden, iterations=3), iterations=2
        )
        hidden &= valid
        factor = np.maximum(shading, _FLOOR) ** (light.gain * inside)
        corrected = (image / factor).astype(np.float32)
        # Hidden ground takes only corrected ground: past the models a shadow
        # is as dark as the mosaic has it.
        result = np.where(hidden | ~valid | (inside == 0.0), np.nan, corrected)
        for sigma in _FILL_SIGMAS:
            known = np.isfinite(result)
            todo = hidden & ~known
            if not todo.any():
                break
            weight = ndimage.gaussian_filter(known.astype(np.float32), sigma)
            around = ndimage.gaussian_filter(np.where(known, result, 0.0), sigma)
            if sigma < _FILL_SIGMAS[-1]:
                take = todo & (weight > _FILL_LEAST)
                result[take] = around[take] / weight[take]
                continue
            # The widest fill leans on the site's broad brightness, which every
            # block shares: ground hidden from far around would otherwise take
            # each block's own, and the blocks would show.
            ys, xs = np.nonzero(todo)
            broad = cast.broad_at(lats[ys], lons[xs])
            result[todo] = (around[todo] + _FILL_LEAST * broad) / (
                weight[todo] + _FILL_LEAST
            )
        # Hidden ground comes in from the edge of the models as the correction
        # does: a shadow across the edge would otherwise end in a line there,
        # and the models' noisy edges would leave specks.
        result = np.where(hidden, inside * result + (1.0 - inside) * corrected, result)
        # Past the models, and where nothing was seen, the samples stay.
        changed = valid & (inside > 0.0)
        core = (slice(b0 - r0, b1 - r0), slice(c0 - q0, c1 - q0))
        target[b0:b1, c0:c1] = np.where(changed[core], result[core], raw[core])


@dataclass
class _Grid:
    """The mosaic, the models' heights in metres, and how far inside the
    models each pixel is, on a grid of a pyramid level. ``y0`` and ``x0`` are
    its first row and column on that level."""

    image: np.ndarray
    heights: np.ndarray
    inside: np.ndarray
    step_m: float
    y0: int
    x0: int
    width: int
    shade: np.ndarray | None = None
    # The corrected brightness filled everywhere, on a grid ``broad_factor``
    # times coarser.
    broad: np.ndarray | None = None
    broad_factor: int = 1

    def coarser(self, factor: int) -> _Grid:
        def mean(a: np.ndarray) -> np.ndarray:
            h, w = a.shape
            blocks = a.reshape(h // factor, factor, w // factor, factor)
            seen = np.isfinite(blocks)
            total = np.where(seen, blocks, 0.0).sum(axis=(1, 3))
            count = seen.sum(axis=(1, 3))
            return np.where(count > 0, total / np.maximum(count, 1), np.nan).astype(
                np.float32
            )

        h, w = self.inside.shape
        least = self.inside.reshape(h // factor, factor, w // factor, factor)
        return _Grid(
            mean(self.image),
            mean(self.heights),
            least.min(axis=(1, 3)),
            self.step_m * factor,
            self.y0 // factor,
            self.x0 // factor,
            self.width // factor,
        )

    def nearest(self, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
        """The shade of the grid's pixel under each latitude and longitude."""
        assert self.shade is not None
        rows = (90.0 - lats) / 180.0 * (self.width // 2)
        columns = (lons + 180.0) / 360.0 * self.width
        y = np.clip(rows.astype(int) - self.y0, 0, self.shade.shape[0] - 1)
        x = np.clip(columns.astype(int) - self.x0, 0, self.shade.shape[1] - 1)
        return self.shade[y[:, None], x[None, :]]

    def broad_at(self, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
        """The broad brightness at each latitude and longitude, smoothly."""
        assert self.broad is not None
        scale = self.broad_factor
        rows = ((90.0 - lats) / 180.0 * (self.width // 2) - self.y0) / scale - 0.5
        columns = ((lons + 180.0) / 360.0 * self.width - self.x0) / scale - 0.5
        return ndimage.map_coordinates(
            self.broad, [rows, columns], order=1, mode="nearest"
        )


def _heights(
    terrain: Sequence[tiles.Layer],
    width: int,
    edges: np.ndarray,
    x0: int,
    x1: int,
    step_y: float,
    step_x: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Metres on a grid whose rows and columns are ``step_y`` and ``step_x``
    metres apart, with each model faded in over the ones before it, and how
    far inside the models each pixel is, 0 to 1. ``terrain`` gives fields as
    ``patches.fields`` does."""
    heights = inside = None
    for model in terrain:
        both = model.window(width, edges, x0, x1)
        seen = both[..., 1] > 0.5
        metres = both[..., 0] / np.maximum(both[..., 1], 1e-6) * 1000.0
        # With no edge in the window, scipy measures from a corner past it.
        deep = (
            np.full(seen.shape, np.inf)
            if seen.all()
            else ndimage.distance_transform_edt(seen, sampling=(step_y, step_x))
        )
        here = np.clip(deep / _FEATHER_M, 0.0, 1.0)
        if heights is None or inside is None:
            heights, inside = np.where(seen, metres, np.nan), here
            continue
        blend = np.clip(deep / _BLEND_M, 0.0, 1.0)
        heights = np.where(
            seen,
            np.where(np.isnan(heights), metres, heights + blend * (metres - heights)),
            heights,
        )
        inside = np.maximum(inside, here)
    assert heights is not None and inside is not None
    gaps = np.isnan(heights)
    if gaps.all():
        return np.zeros(heights.shape, np.float32), np.zeros(heights.shape, np.float32)
    if gaps.any():
        # Past the models, the height of the nearest ground on them: a step
        # there would read as a cliff and cast a shadow.
        nearest = ndimage.distance_transform_edt(
            gaps, return_distances=False, return_indices=True
        )
        heights = heights[tuple(nearest)]
    return heights.astype(np.float32), inside.astype(np.float32)


def _normals(
    heights: np.ndarray, step_y: float, step_x: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """East, north and up parts of the ground's normal. Rows run south."""
    down, across = np.gradient(heights, step_y, step_x)
    norm = np.sqrt(across**2 + down**2 + 1.0)
    return -across / norm, down / norm, 1.0 / norm


def _shading(
    normals: tuple[np.ndarray, np.ndarray, np.ndarray], azimuth: float, elevation: float
) -> np.ndarray:
    """Lambert brightness of each slope over that of flat ground."""
    a, e = math.radians(azimuth), math.radians(elevation)
    east, north, up = math.cos(e) * math.sin(a), math.cos(e) * math.cos(a), math.sin(e)
    lit = normals[0] * east + normals[1] * north + normals[2] * up
    return np.maximum(lit, 0.0) / up


def _local_mean(values: np.ndarray, mask: np.ndarray, sigma: float) -> np.ndarray:
    weight = ndimage.gaussian_filter(mask.astype(np.float32), sigma)
    total = ndimage.gaussian_filter(
        np.where(mask, values, 0.0).astype(np.float32), sigma
    )
    return total / np.maximum(weight, 1e-3)


def _high_pass(values: np.ndarray, mask: np.ndarray, sigma: float) -> np.ndarray:
    return values - _local_mean(values, mask, sigma)


def _scorer(grid: _Grid, cos_lat: float) -> Callable[[float, float], float]:
    """How well the shading of a Sun matches the mosaic's detail on ``grid``."""
    valid = np.isfinite(grid.image) & (grid.inside > 0.99)
    normals = _normals(grid.heights, grid.step_m, grid.step_m * cos_lat)
    lit = valid & (grid.image > 0.35 * _local_mean(grid.image, valid, 8))
    sigma = _DETAIL_M / grid.step_m
    # The same for every Sun tried.
    weight = np.maximum(ndimage.gaussian_filter(lit.astype(np.float32), sigma), 1e-3)

    def high_pass(values: np.ndarray) -> np.ndarray:
        around = ndimage.gaussian_filter(np.where(lit, values, 0.0), sigma)
        return values - around / weight

    image = np.log(np.maximum(np.where(valid, grid.image, 1.0), 1e-4))
    detail = high_pass(image.astype(np.float32))

    def score(azimuth: float, elevation: float) -> float:
        shading = _shading(normals, azimuth, elevation)
        both = lit & (shading > 0.05)
        if both.sum() < 100:
            return -1.0
        shade_detail = high_pass(np.log(np.maximum(shading, 0.05)))
        # A shading that is the same in every Sun, as on a flat model, has
        # no correlation: NaN would stop the walk from ever ending.
        with np.errstate(invalid="ignore", divide="ignore"):
            match = float(np.corrcoef(detail[both], shade_detail[both])[0, 1])
        return match if math.isfinite(match) else -1.0

    return score


def _cast_shadows(
    grid: _Grid, cos_lat: float, azimuth: float, elevation: float
) -> np.ndarray:
    """Where the slopes of ``grid`` hide a Sun at ``azimuth``, ``elevation``
    up."""
    heights = grid.heights
    # Square pixels first: away from the equator, the columns of the grid are
    # closer together than its rows.
    square = ndimage.zoom(heights, (1.0, cos_lat), order=1)
    # Turned so that the light runs down the rows: one pass over them then
    # carries the horizon.
    turned = ndimage.rotate(
        square, azimuth, order=1, reshape=True, cval=np.nan, mode="constant"
    )
    drop = grid.step_m * math.tan(math.radians(elevation))
    horizon = np.full(turned.shape[1], -np.inf, np.float32)
    shade = np.zeros(turned.shape, bool)
    for row in range(turned.shape[0]):
        shade[row] = turned[row] < horizon
        horizon = np.fmax(horizon, turned[row]) - drop
    back = ndimage.rotate(shade.astype(np.uint8), -azimuth, order=0, reshape=True)
    oy = (back.shape[0] - square.shape[0]) // 2
    ox = (back.shape[1] - square.shape[1]) // 2
    shade = back[oy : oy + square.shape[0], ox : ox + square.shape[1]] > 0
    columns = (np.arange(heights.shape[1]) + 0.5) * square.shape[1] / heights.shape[1]
    return shade[:, np.minimum(columns.astype(int), square.shape[1] - 1)]


def _gain(
    grid: _Grid,
    cast: np.ndarray,
    cos_lat: float,
    azimuth: float,
    elevation: float,
    typical: float,
) -> float:
    """How strongly the shading shows in the mosaic, from the lit ground."""
    image = grid.image
    valid = np.isfinite(image) & (grid.inside > 0.99)
    shading = _shading(
        _normals(grid.heights, grid.step_m, grid.step_m * cos_lat), azimuth, elevation
    )
    hidden = (
        cast
        | (shading < _FLOOR)
        | ~valid
        | (image < 0.35 * _local_mean(image, valid, 20))
        | (image < 0.25 * typical)
    )
    sigma = _DETAIL_M / grid.step_m
    image = np.log(np.maximum(np.where(hidden, typical, image), 1e-4))
    detail = _high_pass(image, ~hidden, sigma)
    shade_detail = _high_pass(np.log(np.maximum(shading, _FLOOR)), ~hidden, sigma)
    lit = ~hidden
    if lit.sum() < 100:
        return 0.0
    slope = np.polyfit(shade_detail[lit], detail[lit], 1)[0]
    return float(np.clip(slope, 0.0, 1.0))


def _broad(
    grid: _Grid,
    shade: np.ndarray,
    factor: int,
    cos_lat: float,
    light: Light,
    typical: float,
) -> np.ndarray:
    """The corrected brightness of the site on ``grid``, filled everywhere.
    ``shade`` is on a grid ``factor`` times finer."""
    h, w = grid.image.shape
    shaded = shade.reshape(h, factor, w, factor).any(axis=(1, 3))
    normals = _normals(grid.heights, grid.step_m, grid.step_m * cos_lat)
    shading = _shading(normals, light.azimuth, light.elevation)
    image = grid.image
    hidden = (
        shaded
        | (shading < _FLOOR)
        | ~np.isfinite(image)
        | (image < _DARK * typical)
        | (grid.inside <= 0.0)
    )
    strength = np.maximum(shading, _FLOOR) ** (light.gain * grid.inside)
    result = np.where(hidden, np.nan, image / strength).astype(np.float32)
    for sigma in _BROAD_SIGMAS:
        known = np.isfinite(result)
        if known.all():
            break
        weight = ndimage.gaussian_filter(known.astype(np.float32), sigma)
        around = ndimage.gaussian_filter(np.where(known, result, 0.0), sigma)
        take = ~known & (weight > _FILL_LEAST)
        result[take] = around[take] / weight[take]
    rest = ~np.isfinite(result)
    if rest.any():
        result[rest] = np.nanmedian(result) if not rest.all() else typical
    return result
