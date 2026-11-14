"""Render an equirectangular water mask from coastline, lake and river vectors.

The output is a grey cylindrical map with land at 0 and water at 255. It is
written twice: in full as a tiled TIFF for the tile pyramid, where it becomes
the alpha of the colour tiles, and reduced as a PNG for the whole-globe tiers.

Three layers stack. Each one only adds water:

* OSM coastline water polygons: every ocean, sea and tidal water body, also
  shallow banks (the Bahamas, the Florida shelf) that a bathymetry threshold
  reads as land.
* HydroLAKES: 1.4 M lake and reservoir polygons down to 10 ha.
* HydroRIVERS: river centrelines, stroked at the width that their mean
  discharge gives. Only reaches that are wide enough to resolve leave a mark.

The mask is drawn supersampled and box-averaged down, so a texel holds the
fraction of its area under water. A lake or river narrower than a texel keeps
a partial value.

The supersampled globe does not fit in memory, so it is drawn in bands of
rows. Each band draws only the features whose bounding box reaches it.
"""

import itertools
import logging
import math
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import numpy as np
import shapefile
import tifffile
from PIL import Image, ImageDraw

log = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = None

# The grid of the Blue Marble 500 m maps, so a mask texel is a colour texel.
OUT_WIDTH = 86400
OUT_HEIGHT = 43200
# 17 coverage levels per output texel.
SUPERSAMPLE = 4
# Output rows per band, and the side of a TIFF tile. A band's canvas is
# 86400·480·4² bytes, 663 MB.
BAND_ROWS = 480
# The tier PNG is this many times narrower than the full mask.
TIER_REDUCTION = 4

EARTH_MERIDIAN_M = 40_007_863.0

# Bankfull width from mean discharge, w ≈ COEF·Q^EXP (Q in m³/s, w in m), the
# usual hydraulic-geometry form. COEF puts the main stems at their measured
# widths: Amazon ≈ 4.6 km, Congo ≈ 2 km, Mississippi ≈ 1.3 km.
RIVER_WIDTH_COEF = 10.0
RIVER_WIDTH_EXP = 0.5
# A 1 px stroke would draw a thinner reach several times too wide.
RIVER_MIN_WIDTH_PX = 0.5
RIVER_DISCHARGE_FIELD = "DIS_AV_CMS"

# Records whose boxes are read at a time.
_BOX_CHUNK = 1 << 18


# A polygon ring or polyline part, as pyshp gives it.
Ring = shapefile.PointsT


@dataclass(frozen=True)
class Canvas:
    """The supersampled pixels of one band: ``width`` × ``height`` for the
    whole globe, from row ``top``."""

    width: int
    height: int
    top: int

    def project(self, ring: Ring) -> list[tuple[float, float]]:
        """Lon/lat degrees to pixels, east-positive with -180° at the left edge."""
        sx, sy = self.width / 360.0, self.height / 180.0
        # Pillow truncates a row towards zero. Floored here, a band draws the
        # same rows as the whole canvas.
        return [
            ((point[0] + 180.0) * sx, math.floor((90.0 - point[1]) * sy) - self.top)
            for point in ring
        ]


@dataclass
class _Features:
    """The records of one layer and the bands that each one reaches."""

    reader: shapefile.Reader
    ids: np.ndarray
    first: np.ndarray
    last: np.ndarray
    # Stroke width in supersampled pixels, for rivers.
    widths: np.ndarray | None = None

    def in_band(self, band: int) -> np.ndarray:
        pick = (self.first <= band) & (self.last >= band)
        return np.flatnonzero(pick)


def _ring_is_outer(ring: Ring) -> bool:
    """True for an outer ring. Shapefiles wind those clockwise (negative
    shoelace) and holes the other way."""
    area = 0.0
    for start, end in zip(ring, list(ring[1:]) + [ring[0]]):
        area += start[0] * end[1] - end[0] * start[1]
    return area < 0.0


def _record_boxes(path: Path) -> np.ndarray:
    """West, south, east, north of each record of a polygon or polyline
    shapefile, as (N, 4). NaN for a null record. Read from the record headers
    without the points."""
    index = np.fromfile(path.with_suffix(".shx"), dtype=">i4", offset=100)
    # Offsets are in 16-bit words. A record has an 8-byte header, then its
    # type as int32 and its box as four doubles.
    starts = index[0::2].astype(np.int64) * 2 + 8
    shp = np.memmap(path, dtype=np.uint8, mode="r")
    boxes = np.empty((starts.size, 4))
    for lo in range(0, starts.size, _BOX_CHUNK):
        part = starts[lo : lo + _BOX_CHUNK]
        # A null record has only its type: the last one can end the file.
        raw = shp[np.minimum(part[:, None] + np.arange(36), shp.size - 1)]
        kind = raw[:, :4].copy().view("<i4").ravel()
        box = raw[:, 4:].copy().view("<f8")
        box[kind == 0] = np.nan
        boxes[lo : lo + part.size] = box
    return boxes


def _band_range(
    boxes: np.ndarray, pad_px: np.ndarray | float, height: int, band_rows: int
) -> tuple[np.ndarray, np.ndarray]:
    """First and last band of each box, ``pad_px`` output pixels wider."""
    top = (90.0 - boxes[:, 3]) / 180.0 * height - pad_px
    bottom = (90.0 - boxes[:, 1]) / 180.0 * height + pad_px
    first = np.clip(np.floor(top / band_rows), 0, None).astype(np.int32)
    last = np.floor(bottom / band_rows).astype(np.int32)
    return first, last


def _drawable(boxes: np.ndarray) -> np.ndarray:
    """Records with a box that does not span ±180°. A shape with parts on both
    sides would be drawn across the whole map."""
    return np.isfinite(boxes).all(axis=1) & (boxes[:, 2] - boxes[:, 0] <= 180.0)


def _polygons(path: Path, height: int, band_rows: int) -> _Features:
    boxes = _record_boxes(path)
    (ids,) = np.nonzero(_drawable(boxes))
    first, last = _band_range(boxes[ids], 1.0, height, band_rows)
    return _Features(shapefile.Reader(str(path)), ids, first, last)


def _rivers(path: Path, height: int, band_rows: int) -> _Features:
    reader = shapefile.Reader(str(path))
    discharge = np.zeros(len(reader))
    for i, record in enumerate(reader.iterRecords([RIVER_DISCHARGE_FIELD])):
        if record is not None:
            discharge[i] = cast(float, record[0])
    # The rows of the canvas span half a meridian.
    metres_per_px = EARTH_MERIDIAN_M / 2 / (height * SUPERSAMPLE)
    widths = RIVER_WIDTH_COEF * discharge**RIVER_WIDTH_EXP / metres_per_px
    boxes = _record_boxes(path)
    (ids,) = np.nonzero(_drawable(boxes) & (widths >= RIVER_MIN_WIDTH_PX))
    pad = widths[ids] / SUPERSAMPLE / 2 + 1.0
    first, last = _band_range(boxes[ids], pad, height, band_rows)
    log.info("rivers: %d of %d reaches wide enough to resolve", ids.size, len(reader))
    return _Features(reader, ids, first, last, widths[ids])


def _draw_polygons(
    draw: ImageDraw.ImageDraw, canvas: Canvas, layer: _Features, picks: np.ndarray
) -> None:
    """Fill each polygon with water, then cut its holes back out.

    Holes are cut per feature: within a layer the features do not overlap, so
    only a feature with the same hole can cover one again.
    """
    for i in layer.ids[picks].tolist():
        shape = layer.reader.shape(i)
        if shape is None:
            continue
        bounds = [*shape.parts, len(shape.points)]
        outers, holes = [], []
        for start, end in itertools.pairwise(bounds):
            ring = shape.points[start:end]
            if len(ring) >= 3:
                (outers if _ring_is_outer(ring) else holes).append(canvas.project(ring))
        for ring in outers:
            draw.polygon(ring, fill=255)
        for ring in holes:
            draw.polygon(ring, fill=0)


def _draw_rivers(
    draw: ImageDraw.ImageDraw, canvas: Canvas, layer: _Features, picks: np.ndarray
) -> None:
    """Stroke each river centreline at its width."""
    assert layer.widths is not None
    for i, width_px in zip(layer.ids[picks].tolist(), layer.widths[picks].tolist()):
        shape = layer.reader.shape(i)
        if shape is None:
            continue
        bounds = [*shape.parts, len(shape.points)]
        for start, end in itertools.pairwise(bounds):
            if end - start >= 2:
                draw.line(
                    canvas.project(shape.points[start:end]),
                    fill=255,
                    width=max(1, round(width_px)),
                    joint="curve",
                )


def _reduce(pixels: np.ndarray, factor: int) -> np.ndarray:
    """Mean of each ``factor``² block, rounded."""
    rows, columns = pixels.shape[0] // factor, pixels.shape[1] // factor
    blocks = pixels.reshape(rows, factor, columns, factor)
    total = blocks.sum(axis=(1, 3), dtype=np.uint32)
    block = factor * factor
    return ((total + block // 2) // block).astype(np.uint8)


def _bands(
    layers: Sequence[_Features], width: int, height: int, band_rows: int
) -> Iterator[np.ndarray]:
    """The mask, one band of output rows at a time."""
    canvas_width = width * SUPERSAMPLE
    count = -(-height // band_rows)
    ocean, lakes, rivers = layers
    started = time.monotonic()
    for band in range(count):
        rows = min(band_rows, height - band * band_rows)
        canvas = Canvas(
            canvas_width, height * SUPERSAMPLE, band * band_rows * SUPERSAMPLE
        )
        image = Image.new("L", (canvas_width, rows * SUPERSAMPLE), 0)
        draw = ImageDraw.Draw(image)
        _draw_polygons(draw, canvas, ocean, ocean.in_band(band))
        _draw_polygons(draw, canvas, lakes, lakes.in_band(band))
        _draw_rivers(draw, canvas, rivers, rivers.in_band(band))
        yield _reduce(np.asarray(image), SUPERSAMPLE)
        if (band + 1) % 10 == 0 or band + 1 == count:
            log.info(
                "water mask: band %d of %d, %.0f s",
                band + 1,
                count,
                time.monotonic() - started,
            )


def render_water_mask(
    *,
    ocean: Path,
    lakes: Path,
    rivers: Path,
    tiles_path: Path,
    tier_path: Path,
    width: int = OUT_WIDTH,
    height: int = OUT_HEIGHT,
    band_rows: int = BAND_ROWS,
) -> None:
    """Rasterise the three vector layers into the full mask and the tier mask."""
    log.info(
        "Rasterising water mask at %d×%d, %d× supersampled", width, height, SUPERSAMPLE
    )
    layers = (
        _polygons(ocean, height, band_rows),
        _polygons(lakes, height, band_rows),
        _rivers(rivers, height, band_rows),
    )
    tier = np.empty((height // TIER_REDUCTION, width // TIER_REDUCTION), np.uint8)

    def tiles() -> Iterator[np.ndarray]:
        for band, rows in enumerate(_bands(layers, width, height, band_rows)):
            top = band * band_rows // TIER_REDUCTION
            tier[top : top + rows.shape[0] // TIER_REDUCTION] = _reduce(
                rows, TIER_REDUCTION
            )
            padded = np.zeros((band_rows, width), np.uint8)
            padded[: rows.shape[0]] = rows
            for x in range(0, width, band_rows):
                tile = np.zeros((band_rows, band_rows), np.uint8)
                part = padded[:, x : x + band_rows]
                tile[:, : part.shape[1]] = part
                yield tile

    tiles_path.parent.mkdir(parents=True, exist_ok=True)
    # Each file is named once whole, so a stopped run leaves no cut-off file.
    partial = tiles_path.with_name(f".{tiles_path.name}")
    tifffile.imwrite(
        partial,
        data=tiles(),
        shape=(height, width),
        dtype=np.uint8,
        tile=(band_rows, band_rows),
        compression="zlib",
        photometric="minisblack",
    )
    partial.replace(tiles_path)
    partial = tier_path.with_name(f".{tier_path.name}")
    Image.fromarray(tier).save(partial)
    partial.replace(tier_path)
    log.info("Wrote %s (%d×%d) and %s", tiles_path.name, width, height, tier_path.name)
