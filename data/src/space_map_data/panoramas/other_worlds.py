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
ALSJ_COORDS = "https://apollojournals.org/alsj/alsjcoords.html"
BODY_IDS = {
    "moon": "naif-301",
    "venus": "naif-299",
    "titan": "naif-606",
    "67p": "spkid-1000012",
}
# Where each panorama was taken. An Apollo pan shot away from the lander is
# placed at the lander with the traverse distance as its uncertainty: the
# journal maps the stations against local landmarks, not against coordinates.
SITES: dict[str, dict[str, Any]] = {
    "apollo11-landing": {"latitude": 0.67409, "longitude": 23.47298},
    "apollo12-landing": {"latitude": -3.01381, "longitude": 336.58070},
    "apollo14-landing": {"latitude": -3.64544, "longitude": 342.52861},
    "apollo15-landing": {"latitude": 26.13224, "longitude": 3.63400},
    "apollo15-station9a": {
        "latitude": 26.13224,
        "longitude": 3.63400,
        "uncertainty_m": 3500,
        "note": "Lunar Module; Station 9A is along Hadley Rille, not at the lander",
    },
    "apollo16-station1": {
        "latitude": -8.97341,
        "longitude": 15.49859,
        "uncertainty_m": 1400,
        "note": "Lunar Module; Station 1 is at Flag Crater, not at the lander",
    },
    "apollo17-landing": {"latitude": 20.18809, "longitude": 30.77475},
    "venera13-lpi": {
        "latitude": -7.5,
        "longitude": 303.0,
        "uncertainty_m": None,
        "source_url": None,
        "method": "published landing site, as the probe's own landing record carries it",
    },
    "huygens-pia08113": {
        "latitude": -10.25,
        "longitude": 167.68,
        "uncertainty_m": None,
        "source_url": "https://science.nasa.gov/mission/cassini/huygens-probe/",
        "method": "published landing site; the mosaic was taken from about 10 km above it during descent",
    },
}
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


# Frame sequences distinguish capture dates from panorama publication dates.
APOLLO = [
    (
        "apollo11-landing",
        11,
        "JSC2007e045375",
        "Landing site",
        "1969-07-21",
        "AS11-40-5881–5891",
        "110:31:47",
        0.10,
    ),
    (
        "apollo12-landing",
        12,
        "JSC2007e045376",
        "Landing site",
        "1969-11-19",
        "AS12-47-6982–7006",
        "118:33:10",
        0.51,
    ),
    (
        "apollo14-landing",
        14,
        "JSC2007e045377",
        "Landing site",
        "1971-02-05",
        "AS14-66-9271–9290",
        "114:53:34",
        0.47,
    ),
    (
        "apollo15-station9a",
        15,
        "JSC2007e045378",
        "Station 9A · Hadley Rille",
        "1971-08-02",
        "AS15-82-11110–11127",
        "165:21:14",
        0.40,
    ),
    (
        "apollo15-landing",
        15,
        "JSC2007e045379",
        "Landing site · EVA 2",
        "1971-08-01",
        "AS15-87-11805–11824",
        "147:27:12",
        0.42,
    ),
    (
        "apollo16-station1",
        16,
        "JSC2012e052598",
        "Station 1",
        "1972-04-21",
        "AS16-114-18415–18432, excluding 18427",
        "124:02:08",
        0.13,
    ),
    (
        "apollo17-landing",
        17,
        "JSC2007e045384",
        "Landing site · EVA 1",
        "1972-12-12",
        "AS17-147-22493–22521",
        "117:45:40",
        0.45,
    ),
]
SWEEP_CROPS = json.loads(
    Path(__file__).with_name("apollo_sweep_crops.json").read_text()
)
for identity, mission, image_id, title, date, frames, met, horizon in APOLLO:
    PRODUCTS.append(
        {
            "id": identity,
            "collection": "moon",
            "body": "moon",
            "mission": f"apollo{mission}",
            "instrument": "Hasselblad",
            "title": f"Apollo {mission} · {title}",
            "capture_time": date,
            "capture_precision": "day",
            "capture_date_basis": "UTC calendar day of the frame sequence in the Apollo Lunar Surface Journal; MET identifies the activity, not individual shutter times",
            "capture_activity_met": met,
            "capture_date_source_url": f"https://apollojournals.org/alsj/a{mission}/images{mission}.html",
            "source_frames": frames,
            "selected_url": LPI + f"images/print/original/{image_id}.jpg",
            "source_pages": [
                LPI + f"pans/?pan={image_id}",
                LPI + "about/",
                f"https://apollojournals.org/alsj/a{mission}/images{mission}.html",
            ],
            "credit": "NASA/JSC; panorama by Warren Harold",
            "reuse": {"status": "allowed-with-credit", "policy_url": LPI + "about/"},
            "color": "source-processed Hasselblad imagery; not recolored",
            "horizon_fraction": horizon,
            "sweep_crop": SWEEP_CROPS.get(identity),
            "mapping": "cylindrical",
            "geometry_note": "Assumed 360° sweep and cylindrical scale; visual horizon estimate. Angular bounds and north uncalibrated; source seams and flares retained.",
        }
    )
    if identity in SWEEP_CROPS:
        PRODUCTS[-1]["geometry_note"] = (
            "Repeated end terrain removed using a reviewed one-turn crop. "
            "Cylindrical scale and horizon remain approximate; north and source seam alignment uncalibrated."
        )
PRODUCTS.append(
    {
        "id": "philae-civa4",
        "collection": "67p",
        "body": "67p",
        "mission": "philae",
        "instrument": "CIVA-P camera 4",
        "title": "Philae · Abydos · CIVA camera 4",
        "capture_time": "2014-11-13",
        "capture_precision": "day",
        "observation_type": "surface",
        "selected_url": "https://www.esa.int/var/esa/storage/images/esa_multimedia/images/2015/07/civa_camera_4_view/15540298-1-eng-GB/CIVA_camera_4_view.jpg",
        "source_pages": [
            "https://www.esa.int/ESA_Multimedia/Images/2015/07/CIVA_camera_4_view",
            "https://www.ias.u-psud.fr/en/content/first-image-comet-churyumov-gerasimenko-civa-camera-rosettas-philae-lander",
        ],
        "credit": "ESA/Rosetta/Philae/CIVA",
        "reuse": {
            "status": "educational-editorial-informational-only",
            "policy_url": ESA_TERMS,
            "note": "ESA Standard Licence; not a general commercial-use licence. Retain all joint credits.",
        },
        "color": "grayscale; not colorized",
        "mapping": "perspective",
        "horizontal_degrees": 60,
        "geometry_note": "Nominal 60° CIVA field of view, approximated as a rectilinear square frame. Lens distortion and lander attitude uncalibrated; camera-relative sphere, not a level horizon. Black pixels retained as real shadows.",
        "initial_view": {"yaw": 0, "pitch": 0},
    }
)


def site_position(identity: str) -> dict | None:
    """The product's map position in the export's own shape, or None."""
    site = SITES.get(identity)
    if site is None:
        return None
    return {
        "latitude": site["latitude"],
        "longitude": site["longitude"] % 360,
        "elevation_m": None,
        "latitude_type": "planetocentric",
        "longitude_direction": "east",
        "longitude_range": [0, 360],
        "reference_point": "landing site",
        "uncertainty_m": site.get("uncertainty_m"),
        "method": site.get(
            "method", "Apollo Lunar Surface Journal landing coordinates"
        ),
        "source_url": site.get("source_url", ALSJ_COORDS),
        "note": site.get("note"),
    }


def project_perspective(source, horizontal=60, width=4096):
    """Place a rectilinear camera frame on a sphere without inventing surroundings."""
    if width < 256 or width % 2 or not 0 < horizontal < 180:
        raise ValueError("Invalid sphere width or perspective field of view")
    pixels = np.asarray(source.convert("RGB"))
    height, columns = pixels.shape[:2]
    focal = columns / (2 * np.tan(np.deg2rad(horizontal) / 2))
    elevation = np.pi / 2 - (np.arange(width // 2) + 0.5) * 2 * np.pi / width
    azimuth = (np.arange(width) + 0.5) * 2 * np.pi / width
    z = np.cos(elevation)[:, None] * np.cos(azimuth)[None, :]
    x = np.cos(elevation)[:, None] * np.sin(azimuth)[None, :]
    y = np.sin(elevation)[:, None]
    sx = columns / 2 + focal * x / z
    sy = height / 2 - focal * y / z
    valid = (z > 0) & (sx >= 0) & (sx < columns) & (sy >= 0) & (sy < height)
    rgb = pixels[
        np.clip(sy, 0, height - 1).astype(int), np.clip(sx, 0, columns - 1).astype(int)
    ]
    weights = np.cos(elevation)[:, None]
    percent = float((valid * weights).sum() / (width * weights.sum()) * 100)
    return Image.fromarray(np.dstack((rgb, valid.astype(np.uint8) * 255))), percent


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


def crop_single_turn(master, specification, checksum):
    if specification is None:
        return master
    if (
        checksum != specification["source_sha256"]
        or list(master.size) != specification["source_size"]
    ):
        raise ValueError("Apollo overlap crop needs review for changed source")
    left, top, right, bottom = specification["bounds_px"]
    if not (0 <= left < right <= master.width and top == 0 and bottom == master.height):
        raise ValueError("Invalid single-turn crop bounds")
    return master.crop((left, top, right, bottom))


def process(root, output, *, offline=False, collections=None):
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
            if collections is not None and collection not in collections:
                continue
            source_path = root / (identity + ".jpg")
            if offline and not source_path.is_file():
                raise FileNotFoundError(source_path)
            if not offline:
                fetch(client, product["selected_url"], source_path)
            target = output / collection / identity
            target.mkdir(parents=True, exist_ok=True)
            checksum = sha256(source_path)
            with Image.open(source_path) as master:
                dimensions = master.size
                rendition = crop_single_turn(
                    master, product.get("sweep_crop"), checksum
                )
                rendition_dimensions = rendition.size
                rendition.thumbnail((8192, 8192), Image.Resampling.LANCZOS)
                source = rendition.convert("RGB")
            if crop := product.get("crop_fraction"):
                source = source.crop(
                    tuple(round(v * source.size[i % 2]) for i, v in enumerate(crop))
                )
            preview = source.copy()
            preview.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
            preview.save(target / "preview.webp", quality=90)
            horizontal = 360
            if product["mapping"] == "perspective":
                horizontal = product["horizontal_degrees"]
                sphere, percent = project_perspective(source, horizontal)
            elif product["mapping"] == "tilted_scan":
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
                "source_sha256": checksum,
                "rendition_source_width": rendition_dimensions[0],
                "rendition_source_height": rendition_dimensions[1],
                "preview": "preview.webp",
                "image": "sphere.webp",
                "projection": "equirectangular",
                "geometry_status": "estimated",
                "orientation_status": "unknown",
                "north_azimuth_offset_deg": None,
                "width": sphere.width,
                "height": sphere.height,
                "body_id": BODY_IDS.get(collection),
                "position": site_position(identity),
                "position_status": "published landing site"
                if identity in SITES
                else "no published surface coordinates",
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
    parser.add_argument(
        "--collections", nargs="+", choices=["moon", "venus", "titan", "67p"]
    )
    args = parser.parse_args()
    process(
        args.source_dir,
        args.output_dir,
        offline=args.offline,
        collections=args.collections,
    )


if __name__ == "__main__":
    main()
