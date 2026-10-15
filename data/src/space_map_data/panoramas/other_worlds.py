"""Curated planetary sphere previews with explicit geometry and reuse terms."""

import argparse
import json
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from PIL import Image
from scipy import ndimage

from space_map_data.download.common import load_config

from .pipeline import fetch, sha256, write_json
from .releases import refresh_catalog
from .strip_spheres import project_strip

LPI = "https://www.lpi.usra.edu/resources/apollopanoramas/"
ESA_TERMS = (
    "https://www.esa.int/ESA_Multimedia/"
    "Terms_and_conditions_of_use_of_images_and_videos_available_on_the_esa_website"
)
ALSJ_COORDS = "https://apollojournals.org/alsj/alsjcoords.html"
NASA_POLICY = "https://www.nasa.gov/nasa-brand-center/images-and-media/"
NSSDCA = "https://web.archive.org/web/2024/https://nssdc.gsfc.nasa.gov/nmc/"
LPI_VENUS = "https://www.flickr.com/photos/lunarandplanetaryinstitute/4089158361/"
ESA_IMAGES = "https://www.esa.int/var/esa/storage/images/esa_multimedia/images/"
LANDING_RECORD = "published landing site, as the probe's own landing record carries it"
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
        "method": LANDING_RECORD,
    },
    "venera14-lpi": {
        "latitude": -13.25,
        "longitude": 310.0,
        "uncertainty_m": None,
        "source_url": NSSDCA + "spacecraft/display.action?id=1981-110D",
        "method": LANDING_RECORD,
    },
    "philae-civa": {
        "latitude": -8.04,
        "longitude": -1.60,
        "uncertainty_m": None,
        "source_url": "https://arxiv.org/abs/2008.03180",
        "method": "Abydos in the Cheops frame: Ulamec et al. (2017), as Hoang et al. (2020) cite it",
    },
}
for view in ("15km", "pia08113", "2km", "400m"):
    SITES[f"huygens-{view}"] = {
        "latitude": -10.25,
        "longitude": 167.68,
        "uncertainty_m": None,
        "source_url": "https://science.nasa.gov/mission/cassini/huygens-probe/",
        "method": "published landing site; each view was taken above it during descent",
    }
# Landing sites as the probe events record them, which follow the LROC images
# of the craft.
SURVEYORS = {
    1: ("1966-06-02", "1967-01-07", -2.4745, -43.3398, 0.135, "surveyor-1-panorama-1"),
    3: ("1967-04-20", "1967-05-04", -3.01239, -23.42157, 0.058, "surveyor-3-panorama"),
    5: ("1967-09-11", "1967-12-17", 1.4551, 23.1943, 0.057, "surveyor-5-1"),
    6: ("1967-11-10", "1967-12-14", 0.4742, -1.4275, 0.097, "surveyor-6-panorama"),
    7: (
        "1968-01-10",
        "1968-02-21",
        -40.9812,
        -11.5127,
        0.061,
        "surveyor-7-panorama-1-1",
    ),
}
for number, (_, _, latitude, longitude, _, _) in SURVEYORS.items():
    SITES[f"surveyor{number}-stooke"] = {
        "latitude": latitude,
        "longitude": longitude,
        "uncertainty_m": None,
        "source_url": None,
        "method": LANDING_RECORD,
    }


def venera_lpi(
    number: int,
    date: str,
    commons_path: str,
    crop: list[float],
    experiment: str,
    *papers: str,
) -> dict:
    """One Venera camera scan of the LPI composite, through its Commons crop.
    Both landers carried the same cameras, so the scans share their geometry."""
    name = commons_path.rsplit("/", 1)[1]
    return {
        "id": f"venera{number}-lpi",
        "collection": "venus",
        "body": "venus",
        "mission": f"venera{number}",
        "instrument": "Scanning telephotometer",
        "title": f"Venera {number} · Grayscale surface scan",
        "capture_time": date,
        "selected_url": "https://upload.wikimedia.org/wikipedia/commons/"
        + commons_path,
        "source_pages": [
            LPI_VENUS,
            f"https://commons.wikimedia.org/wiki/File:{name}",
            *papers,
            NSSDCA + f"experiment/display.action?id={experiment}",
        ],
        "credit": f"Venera {number} / Soviet space program; Stephen Paul Meszaros for NASA; Lunar and Planetary Institute; crop by 4throck (CC BY 2.0). Further cropped and reprojected by Space Map.",
        "reuse": {
            "status": "allowed-with-credit",
            "policy_url": "https://creativecommons.org/licenses/by/2.0/",
            "note": "CC BY 2.0 · Surfaces of Mars and Venus · LPI / Stephen Paul Meszaros; cropped and reprojected.",
        },
        "mapping": "tilted_scan",
        "vertical_degrees": 37,
        "color": "grayscale; not colorized",
        "crop_fraction": crop,
        "geometry_note": "Nominal 180° × 37° angular scan, rotated downward 50°, as NSSDCA states for the Venera 13 and 14 cameras. Print crop and scan registration are approximate; not calibrated. Scan sweep is not level-world horizontal coverage.",
        "initial_view": {"yaw": 0, "pitch": -45},
    }


def huygens_poster_b(
    altitude: str, label: str, metres: int, rows: tuple[int, int]
) -> dict:
    """One panel of the DISR team's Poster B: a Mercator view at one altitude.

    Each panel runs past one turn. Its two South labels are 2400 px apart, and
    so are the repeats at its ends, so the crop between them is one turn that
    starts at south.
    """
    return {
        "id": f"huygens-{altitude}",
        "collection": "titan",
        "body": "titan",
        "mission": "huygens",
        "instrument": "DISR",
        "title": f"Huygens · Descent from {label} (not a surface view)",
        "capture_time": "2005-01-14",
        "observation_type": "descent",
        "observer_altitude_m": metres,
        "source_file": "huygens-poster-b.jpg",
        "selected_url": ESA_IMAGES
        + "2006/05/mercator_projections_of_huygens_s_view_at_different_altitudes/9769740-3-eng-GB/Mercator_projections_of_Huygens_s_view_at_different_altitudes.jpg",
        "source_pages": [
            "https://www.esa.int/ESA_Multimedia/Images/2006/05/Mercator_projections_of_Huygens_s_view_at_different_altitudes",
            "https://atmos.nmsu.edu/PDS/data/hpdisr_0001/DATA/HIGHER_LEVEL_DATA/POSTERS/POSTER_B.JPG",
        ],
        "credit": "©ESA/NASA/JPL/University of Arizona",
        "reuse": {
            "status": "educational-editorial-informational-only",
            "policy_url": ESA_TERMS,
            "note": "ESA Standard Licence; not a general commercial-use licence. Retain all joint credits.",
        },
        "mapping": "mercator",
        "horizon_fraction": 0.0,
        "start_azimuth_deg": 180,
        "crop_fraction": [311 / 2900, rows[0] / 3700, 2711 / 2900, rows[1] / 3700],
        "geometry_note": "Published Mercator projection; one turn between the panel's South labels, which its repeating ends confirm. Top row assumed horizon. Descent mosaic, not a single surface camera position.",
    }


PRODUCTS: list[dict[str, Any]] = [
    venera_lpi(
        13,
        "1982-03-01",
        "7/74/Surface_of_Venus_from_Venera_13.jpg",
        [76 / 2048, 94 / 553, 1975 / 2048, 478 / 553],
        "1981-106D-01",
        "https://www.lpi.usra.edu/meetings/lpsc1983/pdf/1123.pdf",
    ),
    venera_lpi(
        14,
        "1982-03-05",
        "2/21/Venera_14_surface_image.jpg",
        [78 / 2185, 123 / 622, 2092 / 2185, 545 / 622],
        "1981-110D-01",
    ),
    huygens_poster_b("15km", "15 km", 15000, (835, 1760)),
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
    huygens_poster_b("2km", "2 km", 2000, (1785, 2710)),
    huygens_poster_b("400m", "400 m", 400, (2735, 3660)),
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
# The six CIVA-P cameras look out 60° apart. Camera 7 is camera 6's stereo
# twin, so it adds nothing to the ring. ESA's panorama sets the frames out
# clockwise in camera order with their tops outward, so a camera's azimuth
# grows with its number. The ring has no north; camera 4, the sunlit cliff,
# is put where the viewer first looks.
CIVA_FRAMES = {
    1: "15540083-1-eng-GB/CIVA_camera_1_view.jpg",
    2: "15540119-1-eng-GB/CIVA_camera_2_view.jpg",
    3: "15540264-1-eng-GB/CIVA_camera_3_view.jpg",
    4: "15540298-1-eng-GB/CIVA_camera_4_view.jpg",
    5: "15540332-1-eng-GB/CIVA_camera_5_view.png",
    6: "15540366-1-eng-GB/CIVA_camera_6_view.jpg",
}
PRODUCTS.append(
    {
        "id": "philae-civa",
        "collection": "67p",
        "body": "67p",
        "mission": "philae",
        "instrument": "CIVA-P",
        "title": "Philae · Abydos · CIVA panorama",
        "capture_time": "2014-11-13T06:13:53Z",
        "capture_stop_time": "2014-11-13T06:14:54Z",
        "capture_precision": "second",
        "capture_date_basis": "the frame names of the ESA archive data set RL-C-CIVA-3-FSS-V1.0 state 06:13:53 to 06:14:54 UTC; ESA's pages give the day",
        "capture_date_source_url": "https://www.esa.int/ESA_Multimedia/Images/2015/07/CIVA_camera_4_view",
        "observation_type": "surface",
        "frames": [
            {
                "camera": camera,
                "azimuth_deg": (camera - 4) % 6 * 60,
                "url": ESA_IMAGES + f"2015/07/civa_camera_{camera}_view/{path}",
            }
            for camera, path in CIVA_FRAMES.items()
        ],
        "selected_url": ESA_IMAGES + "2015/07/civa_camera_4_view/" + CIVA_FRAMES[4],
        "source_pages": [
            *(
                f"https://www.esa.int/ESA_Multimedia/Images/2015/07/CIVA_camera_{camera}_view"
                for camera in CIVA_FRAMES
            ),
            "https://www.esa.int/ESA_Multimedia/Images/2014/11/Comet_panoramic_lander_orientation",
        ],
        "credit": "ESA/Rosetta/Philae/CIVA",
        "reuse": {
            "status": "educational-editorial-informational-only",
            "policy_url": ESA_TERMS,
            "note": "ESA Standard Licence; not a general commercial-use licence. Retain all joint credits.",
        },
        "color": "grayscale; not colorized",
        "mapping": "camera_ring",
        "horizontal_degrees": 70,
        "geometry_note": "Six cameras 60° apart, each a 70° square field (CIVA instrument description), approximated as rectilinear frames; each direction is drawn from the camera that faces it most nearly. Lens distortion, camera tilt and the lander's attitude are uncalibrated; camera-relative sphere, not a level horizon. ESA processed each frame on its own, so brightness steps at the seams. Black pixels retained as real shadows.",
        "initial_view": {"yaw": 0, "pitch": 0},
    }
)
for number, (landed, ended, _, _, horizon, slug) in SURVEYORS.items():
    page = f"https://www.planetary.org/space-images/{slug}"
    PRODUCTS.append(
        {
            "id": f"surveyor{number}-stooke",
            "collection": "moon",
            "body": "moon",
            "mission": f"surveyor{number}",
            "instrument": "Television camera",
            "title": f"Surveyor {number} · Landing site",
            "capture_time": landed,
            "capture_stop_time": ended,
            "capture_precision": "mission",
            "capture_date_basis": "the mosaic states no dates; its frames fall between the landing and the last transmission",
            "selected_url": "https://planetary.s3.amazonaws.com/web/assets/pictures/"
            f"20190123_stooke_pan_lunar_surveyor_{number}.jpg",
            "source_pages": [page],
            "credit": "NASA / Philip Stooke, University of Western Ontario",
            "reuse": {
                "status": "allowed-with-credit",
                "policy_url": NASA_POLICY,
                "credit_source_url": page,
            },
            "color": "grayscale; not colorized",
            "horizon_fraction": horizon,
            "mapping": "cylindrical",
            "empty": "border",
            "left_edge_deg": 180,
            "geometry_note": "Hand-assembled mosaic, reconstructed by Philip Stooke. Assumed 360° sweep and cylindrical scale; horizon at the top of the imaged ground, which the camera's tilt bends. Spacecraft structure at both ends; angular bounds and north uncalibrated.",
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


def project_perspective(source, horizontal=60, width=4096, yaw=0):
    """Place a rectilinear camera frame on a sphere without inventing
    surroundings. `yaw`: the azimuth the camera looks along, in degrees."""
    if width < 256 or width % 2 or not 0 < horizontal < 180:
        raise ValueError("Invalid sphere width or perspective field of view")
    pixels = np.asarray(source.convert("RGB"))
    height, columns = pixels.shape[:2]
    focal = columns / (2 * np.tan(np.deg2rad(horizontal) / 2))
    elevation = np.pi / 2 - (np.arange(width // 2) + 0.5) * 2 * np.pi / width
    azimuth = (np.arange(width) + 0.5) * 2 * np.pi / width - np.deg2rad(yaw)
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


def project_ring(frames, horizontal, width=4096):
    """Several rectilinear cameras around one point, given as (yaw, frame).
    Where their fields overlap, the camera that faces a direction most nearly
    draws it."""
    height = width // 2
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    nearest = np.full((height, width), -2.0)
    azimuth = (np.arange(width) + 0.5) * 360 / width
    for yaw, source in frames:
        sphere, _ = project_perspective(source, horizontal, width, yaw)
        pixels = np.asarray(sphere)
        facing = np.broadcast_to(np.cos(np.deg2rad(azimuth - yaw)), (height, width))
        take = (pixels[:, :, 3] > 0) & (facing > nearest)
        rgba[take] = pixels[take]
        nearest[take] = facing[take]
    elevation = np.pi / 2 - (np.arange(height) + 0.5) * np.pi / height
    weights = np.cos(elevation)[:, None]
    percent = float(((rgba[:, :, 3] > 0) * weights).sum() / (width * weights.sum()))
    return Image.fromarray(rgba), percent * 100


def project_tilted_scan(source, width=4096, tilt_deg=50, vertical_deg=37):
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
    sy = (0.5 - scan_el / np.deg2rad(vertical_deg)) * height
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


def project_mercator(source, width=4096, start_azimuth=0):
    """Invert Mercator with a top-edge horizon and one full azimuth turn whose
    left edge looks along `start_azimuth`."""
    if width < 256 or width % 2:
        raise ValueError("Sphere width must be even and at least 256")
    pixels = np.asarray(source.convert("RGB"))
    height, columns = pixels.shape[:2]
    elevation = np.pi / 2 - (np.arange(width // 2) + 0.5) * 2 * np.pi / width
    sy = -columns / (2 * np.pi) * np.arcsinh(np.tan(elevation))
    sx = ((np.arange(width) + 0.5) / width * 360 - start_azimuth) % 360 / 360 * columns
    rgb = pixels[
        np.clip(sy, 0, height - 1).astype(int)[:, None], sx.astype(int)[None, :]
    ]
    valid = np.broadcast_to(((sy >= 0) & (sy < height))[:, None], (width // 2, width))
    weights = np.cos(elevation)[:, None]
    percent = float((valid * weights).sum() / (width * weights.sum()) * 100)
    return Image.fromarray(np.dstack((rgb, valid.astype(np.uint8) * 255))), percent


def border_black(source, threshold=8):
    """The near-black pixels that reach the edge of the image: sky and the
    sectors never imaged. Dark ground inside the picture is shadow."""
    dark = np.asarray(source.convert("L")) <= threshold
    labels, _ = ndimage.label(dark)
    edge = np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1]))
    return np.isin(labels, np.unique(edge[edge > 0]))


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


# The mappings that draw a sphere from a stated left-edge azimuth, and so may
# claim a north.
TURNABLE = frozenset({"mercator", "cylindrical"})


def ring_preview(frames):
    """The frames as a grid two rows high, in the order of their azimuths: a
    picture shaped for a card, where six in a row would be a sliver."""
    ordered = [frame for _, frame in sorted(frames, key=lambda f: f[0])]
    columns = -(-len(ordered) // 2)
    preview = Image.new("RGB", (512 * columns, 1024))
    for index, frame in enumerate(ordered):
        row, column = divmod(index, columns)
        preview.paste(frame.resize((512, 512)), (512 * column, 512 * row))
    return preview


def fetched(client, url: str, path: Path, offline: bool) -> Path:
    if offline and not path.is_file():
        raise FileNotFoundError(path)
    if not offline:
        fetch(client, url, path)
    return path


def single_source(client, root: Path, product: dict, offline: bool):
    """The image a product is projected from, and what it was made from.
    Panels of one poster share its file."""
    name = product.get("source_file", product["id"] + ".jpg")
    path = fetched(client, product["selected_url"], root / name, offline)
    checksum = sha256(path)
    with Image.open(path) as master:
        dimensions = master.size
        rendition = crop_single_turn(master, product.get("sweep_crop"), checksum)
        rendition_dimensions = rendition.size
        rendition.thumbnail((8192, 8192), Image.Resampling.LANCZOS)
        source = rendition.convert("RGB")
    if crop := product.get("crop_fraction"):
        source = source.crop(
            tuple(round(v * source.size[i % 2]) for i, v in enumerate(crop))
        )
    return source, {
        "source_width": dimensions[0],
        "source_height": dimensions[1],
        "source_sha256": checksum,
        "rendition_source_width": rendition_dimensions[0],
        "rendition_source_height": rendition_dimensions[1],
    }


def ring_frames(client, root: Path, product: dict, offline: bool):
    """A ring product's cameras as (yaw, frame), and what each came from."""
    frames, facts = [], []
    for frame in product["frames"]:
        name = f"camera-{frame['camera']}{Path(frame['url']).suffix}"
        path = fetched(client, frame["url"], root / product["id"] / name, offline)
        with Image.open(path) as image:
            facts.append(
                {
                    **frame,
                    "width": image.width,
                    "height": image.height,
                    "sha256": sha256(path),
                }
            )
            frames.append((frame["azimuth_deg"], image.convert("RGB")))
    return frames, {"frames": facts}


def process(root, output, *, offline=False, collections=None):
    catalogs = {}
    # Official masters exceed Pillow's default pixel limit; this allowlist is bounded.
    Image.MAX_IMAGE_PIXELS = 200_000_000
    with httpx.Client(
        follow_redirects=True,
        timeout=90,
        # Wikimedia refuses a User-Agent that gives no way to reach its sender.
        # An offline build reads no config, which a fresh checkout lacks.
        headers={}
        if offline
        else {"User-Agent": load_config()["download"]["user_agent"]},
    ) as client:
        for product in PRODUCTS:
            identity, collection = product["id"], product["collection"]
            if collections is not None and collection not in collections:
                continue
            target = output / collection / identity
            target.mkdir(parents=True, exist_ok=True)
            heading = product.get("start_azimuth_deg")
            if heading is not None and product["mapping"] not in TURNABLE:
                raise ValueError(f"{identity}: a {product['mapping']} cannot be turned")
            horizontal = 360
            if product["mapping"] == "camera_ring":
                frames, facts = ring_frames(client, root, product, offline)
                preview = ring_preview(frames)
                sphere, percent = project_ring(frames, product["horizontal_degrees"])
            else:
                source, facts = single_source(client, root, product, offline)
                preview = source.copy()
                if product["mapping"] == "perspective":
                    horizontal = product["horizontal_degrees"]
                    sphere, percent = project_perspective(source, horizontal)
                elif product["mapping"] == "tilted_scan":
                    sphere, percent, horizontal = project_tilted_scan(
                        source, vertical_deg=product["vertical_degrees"]
                    )
                elif product["mapping"] == "mercator":
                    sphere, percent = project_mercator(
                        source, start_azimuth=heading or 0
                    )
                else:
                    sphere, percent = project_strip(
                        source,
                        360,
                        product["horizon_fraction"],
                        # Without a heading the viewer opens on 0°, so a
                        # strip whose ends are the spacecraft is drawn with
                        # them behind it.
                        start_azimuth=product.get("left_edge_deg", 0)
                        if heading is None
                        else heading,
                        empty=border_black(source)
                        if product.get("empty") == "border"
                        else None,
                    )
            preview.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
            preview.save(target / "preview.webp", quality=90)
            sphere.save(target / "sphere.webp", lossless=True)
            metadata = {
                **product,
                "schema_version": 2,
                **facts,
                "preview": "preview.webp",
                "image": "sphere.webp",
                "projection": "equirectangular",
                "geometry_status": "estimated",
                # The sphere is rendered north-first where the source names a
                # direction; elsewhere its azimuth is the source's own.
                "orientation_status": "unknown"
                if heading is None
                else "caption-aligned",
                "north_azimuth_offset_deg": None if heading is None else 0,
                "width": sphere.width,
                "height": sphere.height,
                "body_id": BODY_IDS.get(collection),
                "position": site_position(identity),
                "position_status": "published landing site"
                if identity in SITES
                else "no published surface coordinates",
                "color": product.get("color", "source-processed color; not recolored"),
                "render_status": "approximate immersive preview; not calibrated",
                "processing": "Downsampled, optionally cropped, reprojected; no synthetic fill. Near-black pixels of cylindrical strips masked, which may also remove shadows; for the Surveyor mosaics only those that reach the edge of the image.",
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
