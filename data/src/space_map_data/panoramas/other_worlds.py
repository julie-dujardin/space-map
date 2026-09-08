"""Curated planetary sphere previews with explicit geometry and reuse terms."""

import argparse
import json
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from PIL import Image

from .pipeline import fetch, sha256, write_json
from .releases import refresh_catalog
from .strip_spheres import project_strip

LPI = "https://www.lpi.usra.edu/resources/apollopanoramas/"
ESA_TERMS = (
    "https://www.esa.int/ESA_Multimedia/"
    "Terms_and_conditions_of_use_of_images_and_videos_available_on_the_esa_website"
)
PRODUCTS: list[dict[str, Any]] = [
    {
        "id": "venera13-lpi",
        "collection": "venus",
        "body": "venus",
        "mission": "venera13",
        "instrument": "Scanning telephotometer",
        "title": "Venera 13 · Grayscale surface scan",
        "capture_time": "1982-03-01",
        "selected_url": "https://upload.wikimedia.org/wikipedia/commons/7/74/Surface_of_Venus_from_Venera_13.jpg",
        "source_pages": [
            "https://www.flickr.com/photos/lunarandplanetaryinstitute/4089158361/",
            "https://commons.wikimedia.org/wiki/File:Surface_of_Venus_from_Venera_13.jpg",
            "https://www.lpi.usra.edu/meetings/lpsc1983/pdf/1123.pdf",
        ],
        "credit": "Venera 13 / Soviet space program; Stephen Paul Meszaros for NASA; Lunar and Planetary Institute; crop by 4throck (CC BY 2.0). Further cropped and reprojected by Space Map.",
        "reuse": {
            "status": "allowed-with-credit",
            "policy_url": "https://creativecommons.org/licenses/by/2.0/",
            "note": "CC BY 2.0 · Surfaces of Mars and Venus · LPI / Stephen Paul Meszaros; cropped and reprojected.",
        },
        "mapping": "tilted_scan",
        "color": "grayscale; not colorized",
        "crop_fraction": [76 / 2048, 94 / 553, 1975 / 2048, 478 / 553],
        "geometry_note": "Nominal 180° × 40° angular scan, rotated downward 50° following Garvin et al. (1983). Print crop and scan registration are approximate; not calibrated. Scan sweep is not level-world horizontal coverage.",
        "initial_view": {"yaw": 0, "pitch": -45},
    },
    {
        "id": "apollo16-station1",
        "collection": "moon",
        "body": "moon",
        "mission": "apollo16",
        "instrument": "Hasselblad",
        "title": "Apollo 16 · Station 1",
        "capture_time": None,
        "selected_url": LPI + "images/print/original/JSC2012e052598.jpg",
        "source_pages": [LPI + "pans/?pan=JSC2012e052598", LPI + "about/"],
        "credit": "NASA/JSC; panorama by Warren Harold",
        "reuse": {"status": "allowed-with-credit", "policy_url": LPI + "about/"},
        "horizon_fraction": 0.13,
        "mapping": "cylindrical",
        "geometry_note": "Assumed 360° sweep and cylindrical scale; visual horizon estimate, not calibrated.",
    },
    {
        "id": "apollo17-landing",
        "collection": "moon",
        "body": "moon",
        "mission": "apollo17",
        "instrument": "Hasselblad",
        "title": "Apollo 17 · Landing site",
        "capture_time": None,
        "selected_url": LPI + "images/print/original/JSC2007e045384.jpg",
        "source_pages": [LPI + "pans/?pan=JSC2007e045384", LPI + "about/"],
        "credit": "NASA/JSC; panorama by Warren Harold",
        "reuse": {"status": "allowed-with-credit", "policy_url": LPI + "about/"},
        "horizon_fraction": 0.45,
        "mapping": "cylindrical",
        "geometry_note": "Assumed 360° sweep and cylindrical scale; visual horizon estimate, not calibrated.",
    },
    {
        "id": "huygens-pia08113",
        "collection": "titan",
        "body": "titan",
        "mission": "huygens",
        "instrument": "DISR",
        "title": "Huygens · Descent from 10 km (not a surface view)",
        "capture_time": "2005-01-14",
        "observation_type": "descent",
        "observer_altitude_m": 10000,
        "selected_url": "https://assets.science.nasa.gov/content/dam/science/psd/photojournal/pia/pia08/pia08113/PIA08113.jpg",
        "source_pages": [
            "https://science.nasa.gov/photojournal/mercator-projection-of-huygenss-view/",
            "https://www.esa.int/ESA_Multimedia/Images/2006/05/Mercator_projection_of_Huygens_s_view",
        ],
        "credit": "©ESA/NASA/JPL/University of Arizona",
        "reuse": {
            "status": "educational-editorial-informational-only",
            "policy_url": ESA_TERMS,
            "note": "ESA Standard Licence; not a general commercial-use licence. Retain all joint credits.",
        },
        "mapping": "mercator",
        "horizon_fraction": 0.0,
        "crop_fraction": [1 / 18, 0, 17 / 18, 1],
        "geometry_note": "Published Mercator projection; approximate south-to-south crop from annotated figure; top row assumed horizon. Descent mosaic, not a single surface camera position.",
    },
]


def project_tilted_scan(source, width=4096, tilt_deg=50):
    if width < 256 or width % 2 or not -90 <= tilt_deg <= 90:
        raise ValueError("Invalid sphere dimensions or tilt")
    pixels = np.asarray(source.convert("RGB"))
    height, columns = pixels.shape[:2]
    elevation = np.pi / 2 - (np.arange(width // 2) + 0.5) * 2 * np.pi / width
    azimuth = (np.arange(width) + 0.5) * 2 * np.pi / width
    x = np.cos(elevation)[:, None] * np.sin(azimuth)[None, :]
    y = np.sin(elevation)[:, None]
    z = np.cos(elevation)[:, None] * np.cos(azimuth)[None, :]
    tilt = np.deg2rad(tilt_deg)
    # Undo scanner tilt before looking up angular samples; a level strip bends the horizon.
    local_y = np.cos(tilt) * y + np.sin(tilt) * z
    local_z = -np.sin(tilt) * y + np.cos(tilt) * z
    scan_az = np.arctan2(x, local_z)
    scan_el = np.arcsin(np.clip(local_y, -1, 1))
    sx = (scan_az / np.pi + 0.5) * columns
    sy = (0.5 - scan_el / np.deg2rad(40)) * height
    valid = (sx >= 0) & (sx < columns) & (sy >= 0) & (sy < height)
    rgb = pixels[
        np.clip(sy, 0, height - 1).astype(int), np.clip(sx, 0, columns - 1).astype(int)
    ]
    rgb[~valid] = 0
    weights = np.cos(elevation)[:, None]
    percent = float((valid * weights).sum() / (width * weights.sum()) * 100)
    horizontal = float(valid.any(axis=0).sum() / width * 360)
    return (
        Image.fromarray(np.dstack((rgb, valid.astype(np.uint8) * 255))),
        percent,
        horizontal,
    )


def project_mercator(source, width=4096):
    """Invert Mercator with a top-edge horizon and one full azimuth turn."""
    if width < 256 or width % 2:
        raise ValueError("Sphere width must be even and at least 256")
    pixels = np.asarray(source.convert("RGB"))
    height, columns = pixels.shape[:2]
    elevation = np.pi / 2 - (np.arange(width // 2) + 0.5) * 2 * np.pi / width
    sy = -columns / (2 * np.pi) * np.arcsinh(np.tan(elevation))
    sx = (np.arange(width) + 0.5) / width * columns
    rgb = pixels[
        np.clip(sy, 0, height - 1).astype(int)[:, None], sx.astype(int)[None, :]
    ]
    valid = np.broadcast_to(((sy >= 0) & (sy < height))[:, None], (width // 2, width))
    weights = np.cos(elevation)[:, None]
    percent = float((valid * weights).sum() / (width * weights.sum()) * 100)
    return Image.fromarray(np.dstack((rgb, valid.astype(np.uint8) * 255))), percent


def process(root, output, *, offline=False):
    catalogs = {}
    # Official masters exceed Pillow's default pixel limit; this allowlist is bounded.
    Image.MAX_IMAGE_PIXELS = 200_000_000
    with httpx.Client(
        follow_redirects=True,
        timeout=90,
        headers={"User-Agent": "SpaceMapPanoramas/0.1 (offline imagery research)"},
    ) as client:
        for product in PRODUCTS:
            identity, collection = product["id"], product["collection"]
            source_path = root / (identity + ".jpg")
            if offline and not source_path.is_file():
                raise FileNotFoundError(source_path)
            if not offline:
                fetch(client, product["selected_url"], source_path)
            target = output / collection / identity
            target.mkdir(parents=True, exist_ok=True)
            with Image.open(source_path) as master:
                dimensions = master.size
                master.thumbnail((8192, 8192), Image.Resampling.LANCZOS)
                source = master.convert("RGB")
            if crop := product.get("crop_fraction"):
                source = source.crop(
                    tuple(round(v * source.size[i % 2]) for i, v in enumerate(crop))
                )
            preview = source.copy()
            preview.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
            preview.save(target / "preview.webp", quality=90)
            horizontal = 360
            if product["mapping"] == "tilted_scan":
                sphere, percent, horizontal = project_tilted_scan(source)
            elif product["mapping"] == "mercator":
                sphere, percent = project_mercator(source)
            else:
                sphere, percent = project_strip(
                    source, 360, product["horizon_fraction"]
                )
            sphere.save(target / "sphere.webp", lossless=True)
            metadata = {
                **product,
                "schema_version": 2,
                "source_width": dimensions[0],
                "source_height": dimensions[1],
                "source_sha256": sha256(source_path),
                "preview": "preview.webp",
                "image": "sphere.webp",
                "projection": "equirectangular",
                "geometry_status": "estimated",
                "orientation_status": "unknown",
                "north_azimuth_offset": None,
                "position": None,
                "color": product.get("color", "source-processed color; not recolored"),
                "render_status": "approximate immersive preview; not calibrated",
                "processing": "Downsampled, optionally cropped, reprojected; no synthetic fill. Apollo near-black pixels masked (may also remove shadows).",
                "coverage": {
                    "horizontal_degrees": None,
                    "horizontal_percent": None,
                    "estimated_horizontal_degrees": horizontal,
                    "estimated_horizontal_percent": horizontal / 360 * 100,
                    "sphere_percent": None,
                    "estimated_sphere_percent": percent,
                    "method": product["geometry_note"],
                },
                "initial_view": product.get(
                    "initial_view",
                    {
                        "yaw": 180,
                        "pitch": -20 if collection == "titan" else -8,
                    },
                ),
            }
            write_json(target / "metadata.json", metadata)
            catalogs.setdefault(collection, []).append(
                {
                    "id": identity,
                    "title": product["title"],
                    "metadata": f"{collection}/{identity}/metadata.json",
                }
            )
            print(f"{identity}: approximate sphere {percent:.1f}%", flush=True)
    for collection, entries in catalogs.items():
        path = output / collection / "catalog.json"
        catalog = json.loads(path.read_text()) if path.exists() else {"panoramas": []}
        identities = {entry["id"] for entry in entries}
        catalog["panoramas"] = [
            entry for entry in catalog["panoramas"] if entry["id"] not in identities
        ] + entries
        write_json(path, catalog)
        refresh_catalog(output, collection)
    write_json(
        root / "review.json",
        {
            "venus": {
                "status": "grayscale-preview-available",
                "reason": "LPI CC BY 2.0 grayscale scan admitted with approximate tilted-scanner geometry; color rights still unresolved.",
                "candidates": [
                    "https://www.lpi.usra.edu/publications/slidesets/venus/slide_3.html",
                    "https://www.esa.int/ESA_Multimedia/Images/2007/11/Surface_of_Venus_by_Venera_13",
                ],
                "excluded": "ESA-hosted color Venera credits a non-ESA rights holder.",
            }
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    process(args.source_dir, args.output_dir, offline=args.offline)


if __name__ == "__main__":
    main()
