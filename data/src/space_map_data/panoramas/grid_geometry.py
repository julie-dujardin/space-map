"""Recover approximate angular geometry from printed Mastcam-Z grids."""

import argparse
import csv
import io
from itertools import combinations
import json
import logging
from pathlib import Path
import re
import subprocess
import tempfile

import numpy as np
from PIL import Image, ImageOps

from .labels import Mosaic
from .pipeline import coverage, sphere_texture, write_json
from .releases import refresh_catalog


def grid_words(path):
    with Image.open(path) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.int16)
    height, width = rgb.shape[:2]
    white = (rgb.min(axis=2) > 140) & (np.ptp(rgb, axis=2) < 35)
    white[white.sum(axis=1) > width * 0.3] = False
    white[:, white.sum(axis=0) > height * 0.6] = False
    interior = np.ones_like(white)
    border = min(35, height // 4)
    interior[:border] = False
    interior[-border:] = False
    interior[:, :50] = False
    interior[:, -50:] = False
    white[interior] = False
    bitmap = Image.fromarray(np.where(white, 0, 255).astype(np.uint8))
    bitmap = ImageOps.expand(
        bitmap.resize((width * 3, height * 3)), border=30, fill=255
    )
    with tempfile.TemporaryDirectory(prefix="mars-grid-") as temporary:
        source = Path(temporary) / "grid.png"
        bitmap.save(source)
        result = subprocess.run(
            [
                "tesseract",
                str(source),
                "stdout",
                "--psm",
                "11",
                "-c",
                "tessedit_char_whitelist=0123456789.-",
                "tsv",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    words = []
    for row in csv.DictReader(io.StringIO(result.stdout), delimiter="\t"):
        if not re.fullmatch(r"-?\d{1,3}(?:\.\d+)?", row.get("text", "")):
            continue
        if float(row["conf"]) < 30:
            continue
        words.append(
            {
                "value": float(row["text"]),
                "x": (int(row["left"]) - 30) / 3,
                "y": (int(row["top"]) + int(row["height"]) - 30) / 3,
            }
        )
    return words, width, height


def fit_axis(points, extent, *, circular=False):
    if len(points) < 3:
        raise ValueError("Too few readable grid labels")
    points = np.asarray(sorted(points), dtype=float)
    best = None
    for first, second in combinations(points, 2):
        distance = second[0] - first[0]
        if distance < extent * 0.25:
            continue
        delta = (second[1] - first[1]) % 360 if circular else second[1] - first[1]
        slope = delta / distance
        if circular and not 0 < slope * extent <= 362:
            continue
        if not circular and not -180 <= slope * extent < 0:
            continue
        intercept = first[1] - slope * first[0]
        residual = points[:, 1] - (points[:, 0] * slope + intercept)
        if circular:
            residual = (residual + 180) % 360 - 180
        valid = np.abs(residual) < abs(slope) * 3
        score = int(valid.sum())
        if best is None or score > best[0]:
            best = score, valid, slope, intercept
    if best is None:
        raise ValueError("No consistent angular grid")
    score, valid, slope, intercept = best
    if (
        score < 3
        or len(np.unique(points[valid, 1])) < (4 if circular else 3)
        or score < len(points) * 0.75
        or np.ptp(points[valid, 0]) < extent * 0.5
    ):
        raise ValueError("Insufficient grid agreement or spatial span")
    observed = points[valid, 1]
    if circular:
        expected = points[valid, 0] * slope + intercept
        observed = expected + (observed - expected + 180) % 360 - 180
    slope, intercept = np.polyfit(points[valid, 0], observed, 1)
    return float(slope), float(intercept), score


def geometry(words, width, height):
    horizontal = [
        (w["x"], w["value"])
        for w in words
        if 50 < w["x"] < width - 50
        and (w["y"] < 35 or w["y"] > height - 20)
        and 0 <= w["value"] <= 360
    ]
    vertical = [
        (w["y"] + 2, w["value"])
        for w in words
        if (w["x"] < 30 or w["x"] > width - 35) and -90 <= w["value"] <= 90
    ]
    sx, azimuth, nx = fit_axis(horizontal, width, circular=True)
    sy, elevation, ny = fit_axis(vertical, height)
    if not 0.95 < abs(sx / sy) < 1.05:
        raise ValueError("Grid axes disagree on angular pixel scale")
    if elevation > 90 or elevation + height * sy < -90:
        raise ValueError("Grid extends beyond valid elevations")
    return Mosaic(
        "grid",
        0,
        0,
        0,
        "",
        "",
        width,
        height,
        3,
        "u1",
        0,
        azimuth % 360,
        1 / sx,
        -1 / sy,
        1 - elevation / sy,
        "SITE_FRAME",
        (),
    ), {
        "horizontal_labels": nx,
        "vertical_labels": ny,
        "read_labels": words,
        "minimum_label_agreement": 0.75,
        "minimum_axis_span_fraction": 0.5,
    }


def process_grid(directory, *, width=4096):
    metadata_path = directory / "metadata.json"
    metadata = json.loads(metadata_path.read_text())
    if metadata.get("projection") != "cylindrical" or metadata.get("target") == "360":
        return False
    preview = directory / metadata["preview"]
    try:
        words, source_width, source_height = grid_words(preview)
        mosaic, evidence = geometry(words, source_width, source_height)
        mosaic.validate()
    except (ValueError, subprocess.SubprocessError) as error:
        metadata["grid_geometry_status"] = str(error)
        write_json(metadata_path, metadata)
        return False
    with Image.open(preview) as source:
        rgb = np.asarray(source.convert("RGB"))
    # Exclude neutral grid marks conservatively; some real neutral pixels may also be masked.
    valid = np.ptp(rgb.astype(np.int16), axis=2) > 8
    rgba = np.dstack((rgb, valid.astype(np.uint8) * 255))
    texture = sphere_texture(rgba, mosaic, width)
    texture.save(directory / "panorama.webp", quality=90)
    metrics = coverage(texture, mosaic)
    metrics.update(
        {
            "method": "approximate OCR grid fit and conservative color mask on display preview",
            "includes_source_grid": True,
            "accuracy": "approximate; visually verify before map publication",
        }
    )
    metadata.update(
        {
            "image": "panorama.webp",
            "projection": "equirectangular",
            "width": width,
            "height": width // 2,
            "hfov_deg": 360,
            "vfov_deg": 180,
            "north_azimuth_offset_deg": 0,
            "coverage": metrics,
            "grid_geometry_status": "estimated",
            "grid_geometry_evidence": evidence,
            "projection_bounds": {
                "start_azimuth_deg": mosaic.azimuth,
                "elevation_top_deg": (mosaic.zero_line - 1) / mosaic.scale_y,
                "elevation_bottom_deg": (mosaic.zero_line - source_height)
                / mosaic.scale_y,
            },
            "render_status": "approximate sphere; grid-derived geometry, unverified map position",
            "rendition_source": {
                "image": metadata["preview"],
                "width": source_width,
                "height": source_height,
            },
            "start_time": metadata.get("capture_time") or "",
            "quality_notes": [
                "Geometry inferred from printed grid labels, not archival numeric labels.",
                "Sphere uses the local display preview; full-resolution original remains cached.",
                "Neutral pixels are conservatively masked to exclude grid text; coverage is approximate.",
            ],
        }
    )
    write_json(metadata_path, metadata)
    return True


def cli():
    parser = argparse.ArgumentParser(
        description="Estimate angular coverage from printed Mastcam-Z grids; requires tesseract"
    )
    parser.add_argument(
        "--directory", type=Path, required=True, help="Derived mastcamz directory"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    count, accepted = 0, 0
    for path in sorted(args.directory.glob("*/metadata.json")):
        accepted += process_grid(path.parent)
        count += 1
        if count % 25 == 0:
            logging.info(
                "Grid audit: %s images checked, %s new estimates", count, accepted
            )
    write_json(
        args.directory / "grid-audit.json",
        {
            "checked": count,
            "new_estimates": accepted,
            "method": "printed-grid OCR; approximate, not publication-approved",
        },
    )
    refresh_catalog(args.directory.parent, args.directory.name)


if __name__ == "__main__":
    cli()
