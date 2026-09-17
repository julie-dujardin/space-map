"""Explicitly approximate immersive previews of curated official panorama strips."""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from .pipeline import write_json

# Bind visual estimates to reviewed masters so changed sources require review.
STRIPS = json.loads(Path(__file__).with_name("curated_strips.json").read_text())

# How a strip's heading was established, for the viewer to label and for
# `export/panoramas.py` to decide whether a field of view can be drawn.
ORIENTATION = {
    "published cardinal direction": "caption-aligned",
    "skyline match": "matched to an archival sphere",
}


def orientation_status(spec):
    """What the viewer may claim about which way a strip faces.

    A basis outside the table is a mistake in the hand-edited manifest, not an
    unoriented strip: silently reading it as unknown would drop a heading that
    was measured, and nothing downstream would say so.
    """
    if spec["start_azimuth_deg"] is None:
        return "unknown"
    basis = spec.get("start_azimuth_basis", "")
    if basis not in ORIENTATION:
        raise ValueError(
            f"{spec['id']}: start_azimuth_deg is set but its basis "
            f"{basis!r} is not one of {sorted(ORIENTATION)}"
        )
    return ORIENTATION[basis]


def project_strip(source, horizontal, horizon, width=4096, *, start_azimuth=0):
    if (
        not np.isfinite(start_azimuth)
        or not 0 < horizontal <= 360
        or not 0 <= horizon <= 1
    ):
        raise ValueError("Invalid strip bounds")
    if width < 256 or width % 2:
        raise ValueError("Sphere width must be even and at least 256")
    pixels = np.asarray(source.convert("RGB"))
    height, columns = pixels.shape[:2]
    scale = columns / np.deg2rad(horizontal)
    elevation = np.pi / 2 - (np.arange(width // 2) + 0.5) * 2 * np.pi / width
    # A cylindrical approximation preserves the strip's horizontal sweep.
    sy = horizon * height - scale * np.tan(elevation)
    azimuth = ((np.arange(width) + 0.5) / width * 360 - start_azimuth) % 360
    sx = azimuth / horizontal * columns
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


def render_curated(target, metadata, spec, *, width=4096):
    if metadata.get("source_sha256") != spec["source_sha256"]:
        raise ValueError(
            f"Curated geometry needs review for changed source: {spec['id']}"
        )
    horizontal = spec["horizontal_degrees"]
    heading = spec["start_azimuth_deg"]
    with Image.open(target / metadata["preview"]) as source:
        source_size = source.size
        sphere, percent = project_strip(
            source,
            horizontal,
            spec["horizon_fraction"],
            width,
            start_azimuth=heading or 0,
        )
    sphere.save(target / "sphere.webp", lossless=True)
    metadata.update(
        {
            "image": "sphere.webp",
            "projection": "equirectangular",
            "width": width,
            "height": width // 2,
            "hfov_deg": 360,
            "vfov_deg": 180,
            "geometry_status": "estimated",
            # The sphere is rendered north-first, so a known heading leaves
            # nothing for the viewer to correct.
            "north_azimuth_offset_deg": 0 if heading is not None else None,
            "orientation_status": orientation_status(spec),
            "capture_time": spec["capture_time"],
            "capture_stop_time": spec["capture_stop_time"],
            "capture_precision": "day",
            # Only where the caption omits it; the localizer prefers this.
            **(
                {
                    "sol": spec["capture_sol"],
                    "sol_basis": spec.get(
                        "capture_sol_basis",
                        "reviewed; capture date matched to the sol the "
                        "NASA raw-image archive dates the same way",
                    ),
                    "sol_source_url": spec["capture_sol_source_url"],
                }
                if spec.get("capture_sol")
                else {}
            ),
            "capture_date_source_url": spec.get(
                "capture_date_source_url", spec["source_url"]
            ),
            "render_status": "approximate immersive preview; not calibrated",
            "projection_bounds": {
                "start_azimuth_deg": heading,
                "horizontal_degrees": horizontal,
            },
            "geometry_evidence": {
                "source_url": spec["source_url"],
                "horizontal": spec.get(
                    "horizontal_basis", "reviewed product caption or instrument gallery"
                ),
                "horizontal_source_url": spec.get(
                    "horizontal_source_url", spec["source_url"]
                ),
                # A horizon read off the picture is a guess the viewer should be
                # told about; one solved against a calibrated sphere is not.
                "vertical": spec.get(
                    "horizon_basis",
                    "assumed cylindrical scale; visually estimated horizon",
                ),
                "horizon_evidence": spec.get("horizon_evidence"),
                "horizon_fraction": spec["horizon_fraction"],
                "heading": spec.get("start_azimuth_basis", "unknown")
                if heading is not None
                else "unknown",
                "heading_evidence": spec.get("start_azimuth_evidence"),
                "source_rendition": "flat preview, not full-resolution master",
                "source_width": source_size[0],
                "source_height": source_size[1],
                "source_sha256": spec["source_sha256"],
            },
            "coverage": {
                "horizontal_degrees": horizontal,
                "horizontal_percent": horizontal / 360 * 100,
                "sphere_percent": None,
                "estimated_sphere_percent": percent,
                "method": "published sweep; approximate cylindrical mapping and near-black missing-pixel mask",
            },
            "geometry_note": (
                "Horizon solved against archival spheres of the same stop; "
                "cylindrical scale assumed."
                if spec.get("horizon_evidence")
                else "Visually estimated horizon and cylindrical scale."
            )
            + " Source seams/blended sky retained. Near-black masking can"
            " remove real shadows.",
        }
    )
    metadata.pop("north_azimuth_offset", None)
    return metadata


def process(directory, *, collections=None, width=4096):
    from .releases import refresh_catalog

    count = 0
    for collection in sorted({s["collection"] for s in STRIPS}):
        if collections is not None and collection not in collections:
            continue
        catalog_path = directory / collection / "catalog.json"
        if not catalog_path.exists():
            continue
        active = {e["id"] for e in json.loads(catalog_path.read_text())["panoramas"]}
        for spec in STRIPS:
            if spec["collection"] != collection or spec["id"] not in active:
                continue
            target = directory / collection / spec["id"]
            path = target / "metadata.json"
            metadata = render_curated(
                target, json.loads(path.read_text()), spec, width=width
            )
            write_json(path, metadata)
            count += 1
        refresh_catalog(directory, collection)
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--collections", nargs="+")
    args = parser.parse_args()
    count = process(args.directory, collections=args.collections)
    print(f"Rendered {count} curated spheres")


if __name__ == "__main__":
    main()
