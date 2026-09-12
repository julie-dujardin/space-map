"""Render an equirectangular water mask from coastline, lake and river vectors.

Output is a grayscale cylindrical map with land at 0 and water at 255,
consumed by the ``cylindrical_specular`` texture entry as a roughness mask.

Three layers stack, each only ever adding water:

* OSM coastline water polygons — every ocean, sea and tidal water body,
  including shallow banks (the Bahamas, the Florida shelf) that a bathymetry
  threshold reads as land.
* HydroLAKES — 1.4 M lake and reservoir polygons down to 10 ha.
* HydroRIVERS — river centrelines, stroked at the width their mean discharge
  implies, so only reaches wide enough to resolve leave a mark.

The mask is drawn oversampled and box-averaged down, so a texel carries the
*fraction* of its area under water rather than a hard in/out decision: a lake
or river narrower than a texel survives as a partial value instead of
vanishing or blooming to full width.
"""

import logging
import time
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import numpy as np
import shapefile
from PIL import Image, ImageDraw

log = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = None

# Matches the GEBCO-derived mask this replaced; the high tier caps at 16383 px
# so this leaves a little headroom to downsample into every tier.
OUT_WIDTH = 21600
OUT_HEIGHT = 10800
# Draw at 4x in each axis, giving 17 coverage levels per output texel. Peak
# memory is the supersampled canvas alone: 21600·10800·4² = 3.7 GiB.
SUPERSAMPLE = 4

EARTH_MERIDIAN_M = 40_007_863.0

# Bankfull width from mean discharge, w ≈ COEF·Q^EXP (Q in m³/s, w in m) — the
# usual hydraulic-geometry form. COEF is set so the main stems land on their
# measured widths: Amazon ≈ 4.6 km, Congo ≈ 2 km, Mississippi ≈ 1.3 km.
RIVER_WIDTH_COEF = 10.0
RIVER_WIDTH_EXP = 0.5
# Reaches thinner than half a supersampled pixel are dropped rather than
# stroked at the 1 px floor, which would draw them several times too wide.
RIVER_MIN_WIDTH_PX = 0.5
RIVER_DISCHARGE_FIELD = "DIS_AV_CMS"

# Output rows per downsample block — bounds the uint32 accumulator.
_DOWNSAMPLE_BLOCK_ROWS = 256


# A polygon ring or polyline part, as pyshp hands it over.
Ring = shapefile.PointsT


def _ring_is_outer(ring: Ring) -> bool:
    """True for an outer ring — shapefiles wind those clockwise (negative shoelace) and holes the other way."""
    area = 0.0
    for start, end in zip(ring, list(ring[1:]) + [ring[0]]):
        area += start[0] * end[1] - end[0] * start[1]
    return area < 0.0


def _project(ring: Ring, width: int, height: int) -> list[tuple[float, float]]:
    """Lon/lat degrees → pixel coordinates, east-positive with -180° at the left edge."""
    return [
        ((point[0] + 180.0) / 360.0 * width, (90.0 - point[1]) / 180.0 * height)
        for point in ring
    ]


def _wraps_antimeridian(bbox: Sequence[float]) -> bool:
    """True for a shape whose parts sit on both sides of ±180°, which would smear across the map."""
    return bbox[2] - bbox[0] > 180.0


def _draw_polygons(
    draw: ImageDraw.ImageDraw, size: tuple[int, int], path: Path, label: str
) -> int:
    """Fill every polygon in a shapefile with water, punching its holes back out.

    Holes are punched per feature rather than in a second pass over the whole
    layer: within each layer the features tile rather than overlap, so a hole
    can only ever be re-cut by a feature that carries the same hole.
    """
    reader = shapefile.Reader(str(path))
    started = time.monotonic()
    drawn = 0
    for shape in reader.iterShapes():
        if shape is None or not shape.points or _wraps_antimeridian(shape.bbox):
            continue
        bounds = list(shape.parts) + [len(shape.points)]
        outers, holes = [], []
        for start, end in zip(bounds, bounds[1:]):
            ring = shape.points[start:end]
            if len(ring) < 3:
                continue
            (outers if _ring_is_outer(ring) else holes).append(_project(ring, *size))
        for ring in outers:
            draw.polygon(ring, fill=255)
        for ring in holes:
            draw.polygon(ring, fill=0)
        drawn += 1
    log.info("%s: %d polygons in %.0f s", label, drawn, time.monotonic() - started)
    return drawn


def _draw_rivers(
    draw: ImageDraw.ImageDraw, size: tuple[int, int], path: Path, metres_per_px: float
) -> int:
    """Stroke river centrelines at their discharge-implied width."""
    reader = shapefile.Reader(str(path))
    started = time.monotonic()
    drawn = 0
    for reach in reader.iterShapeRecords(fields=[RIVER_DISCHARGE_FIELD]):
        shape, record = reach.shape, reach.record
        if shape is None or record is None:
            continue
        # pyshp types a record value as any dbf type; this field is numeric.
        discharge = cast(float, record[0])
        width_px = RIVER_WIDTH_COEF * discharge**RIVER_WIDTH_EXP / metres_per_px
        if width_px < RIVER_MIN_WIDTH_PX:
            continue
        if not shape.points or _wraps_antimeridian(shape.bbox):
            continue
        bounds = list(shape.parts) + [len(shape.points)]
        for start, end in zip(bounds, bounds[1:]):
            if end - start < 2:
                continue
            draw.line(
                _project(shape.points[start:end], *size),
                fill=255,
                width=max(1, round(width_px)),
                joint="curve",
            )
        drawn += 1
    log.info(
        "rivers: %d of %d reaches wide enough to resolve, in %.0f s",
        drawn,
        len(reader),
        time.monotonic() - started,
    )
    return drawn


def _box_downsample(canvas: Image.Image) -> Image.Image:
    """Average each SUPERSAMPLE² block down to one texel of water fraction."""
    supersampled = np.asarray(canvas)
    out = np.empty((OUT_HEIGHT, OUT_WIDTH), np.uint8)
    block = SUPERSAMPLE * SUPERSAMPLE
    for y in range(0, OUT_HEIGHT, _DOWNSAMPLE_BLOCK_ROWS):
        rows = min(_DOWNSAMPLE_BLOCK_ROWS, OUT_HEIGHT - y)
        window = supersampled[y * SUPERSAMPLE : (y + rows) * SUPERSAMPLE].reshape(
            rows, SUPERSAMPLE, OUT_WIDTH, SUPERSAMPLE
        )
        totals = window.sum(axis=(1, 3), dtype=np.uint32)
        out[y : y + rows] = ((totals + block // 2) // block).astype(np.uint8)
    return Image.fromarray(out)


def render_water_mask(
    *, ocean: Path, lakes: Path, rivers: Path, out_path: Path
) -> Image.Image:
    """Rasterise the three vector layers into the output mask and save it."""
    width, height = OUT_WIDTH * SUPERSAMPLE, OUT_HEIGHT * SUPERSAMPLE
    log.info(
        "Rasterising water mask at %d×%d (%.1f GiB)",
        width,
        height,
        width * height / 2**30,
    )
    canvas = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(canvas)

    _draw_polygons(draw, (width, height), ocean, "ocean")
    _draw_polygons(draw, (width, height), lakes, "lakes")
    _draw_rivers(draw, (width, height), rivers, EARTH_MERIDIAN_M / height)

    mask = _box_downsample(canvas)
    del draw, canvas
    out_path.parent.mkdir(parents=True, exist_ok=True)
    mask.save(out_path)
    log.info("Wrote %s (%d×%d)", out_path.name, OUT_WIDTH, OUT_HEIGHT)
    return mask
