"""Explicitly approximate immersive previews of curated official panorama strips."""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from .pipeline import write_json
from .releases import refresh_catalog

# These horizons are visual estimates, not camera calibration or true north.
STRIPS = {
    "curiosity-pia20840": (
        360,
        0.27,
        "https://science.nasa.gov/photojournal/rovers-panorama-taken-amid-murray-buttes-on-mars/",
    ),
    "curiosity-pia23623": (
        360,
        0.20,
        "https://science.nasa.gov/photojournal/curiositys-18-billion-pixel-panorama/",
    ),
    "curiosity-pia26696": (
        360,
        0.30,
        "https://science.nasa.gov/photojournal/curiosity-captures-a-360-degree-view-at-nevado-sajama/",
    ),
    "insight-pia23140": (
        290,
        0.22,
        "https://science.nasa.gov/photojournal/insight-sol-14-panorama-2/",
    ),
}


def project_strip(source, horizontal, horizon, width=4096):
    if not 0 < horizontal <= 360 or not 0 <= horizon <= 1:
        raise ValueError("Invalid strip bounds")
    if width < 256 or width % 2:
        raise ValueError("Sphere width must be even and at least 256")
    pixels = np.asarray(source.convert("RGB"))
    height, columns = pixels.shape[:2]
    scale = columns / np.deg2rad(horizontal)
    elevation = np.pi / 2 - (np.arange(width // 2) + 0.5) * 2 * np.pi / width
    # A cylindrical approximation preserves the strip's horizontal sweep.
    sy = horizon * height - scale * np.tan(elevation)
    sx = (np.arange(width) + 0.5) / width * 360 / horizontal * columns
    valid = (sy[:, None] >= 0) & (sy[:, None] < height) & (sx[None, :] < columns)
    rgb = pixels[
        np.clip(sy, 0, height - 1).astype(int)[:, None],
        np.clip(sx, 0, columns - 1).astype(int)[None, :],
    ]
    valid &= rgb.max(axis=2) > 8
    rgba = np.dstack((rgb, valid.astype(np.uint8) * 255))
    weights = np.cos(elevation)[:, None]
    fraction = float((valid * weights).sum() / (width * weights.sum()))
    return Image.fromarray(rgba), fraction * 100


def process(directory):
    count = 0
    for identity, (horizontal, horizon, evidence) in STRIPS.items():
        collection = identity.split("-", 1)[0]
        target = directory / collection / identity
        path = target / "metadata.json"
        if not path.exists():
            continue
        metadata = json.loads(path.read_text())
        with Image.open(target / metadata["preview"]) as source:
            sphere, percent = project_strip(source, horizontal, horizon)
        sphere.save(target / "sphere.webp", lossless=True)
        metadata.update(
            {
                "image": "sphere.webp",
                "projection": "equirectangular",
                "geometry_status": "estimated",
                "north_azimuth_offset": None,
                "orientation_status": "unknown",
                "render_status": "approximate immersive preview; not calibrated",
                "projection_bounds": {
                    "start_azimuth_deg": 0,
                    "horizontal_degrees": horizontal,
                },
                "geometry_evidence": {
                    "source_url": evidence,
                    "horizontal": "published caption",
                    "vertical": "assumed cylindrical scale; visually estimated horizon",
                    "horizon_fraction": horizon,
                    "source_rendition": "2048-pixel flat preview, not full-resolution master",
                },
                "coverage": {
                    "horizontal_degrees": horizontal,
                    "horizontal_percent": horizontal / 360 * 100,
                    "sphere_percent": None,
                    "estimated_sphere_percent": percent,
                    "method": "published sweep; approximate cylindrical mapping and near-black missing-pixel mask",
                },
            }
        )
        write_json(path, metadata)
        refresh_catalog(directory, collection)
        count += 1
        print(
            f"{identity}: {horizontal} degrees; estimated {percent:.1f}% sphere",
            flush=True,
        )
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    process(args.directory)


if __name__ == "__main__":
    main()
