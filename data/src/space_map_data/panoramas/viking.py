"""Build sphere textures from the Viking Lander panorama mosaics.

The imaging team assembled the lander frames into cylindrical mosaics and the
archive kept them in VICAR form. Each one states where its first pixel points
and how wide a pixel is, which is all the geometry a sphere needs.

The azimuth is measured in the lander's own frame. Nothing in the label ties
that frame to north, so these panoramas are placed and dated but claim no
heading, and the viewer draws none.
"""

import argparse
from datetime import date, timedelta
import json
import logging
from pathlib import Path
import re
import shutil

import httpx
from PIL import Image

from .labels import Mosaic
from .missions import FRAME
from .pipeline import (
    POLICY,
    coordinate_grid_remains,
    coverage,
    fetch,
    read_header,
    read_pixels,
    reusable,
    sha256,
    sphere_texture,
    write_json,
    BUILD_VERSION,
)

logger = logging.getLogger(__name__)

ARCHIVE = "https://planetarydata.jpl.nasa.gov/img/data/viking/viking_lander/viking/"
# Each directory holds one processing of the mosaics; all of them are cylindrical.
DIRECTORIES = ("dnm_vic", "dnr_vic", "dns_vic", "fnm_vic", "fns_vic")
COLLECTION = "viking"
# A label long enough to hold every LAB line the archive writes; the header
# states its own length, so this only has to be an upper bound.
LABEL_PREFIX_BYTES = 16384

# Stated in the volume's own mission catalogue, which gives west longitude as
# the Viking era did. Both convert into the Chryse and Utopia basins the IAU
# gazetteer places at 319.69 and 117.52 degrees east.
CATALOG = ARCHIVE.replace("viking/viking/", "viking/vl_0001/catalog/mission.cat")
LANDERS = {
    1: {"latitude": 22.480, "west_longitude": 47.968, "naif": -327},
    2: {"latitude": 47.967, "west_longitude": 225.737, "naif": -330},
}
# Mars sols since landing are what the labels count, so the date each one falls
# on is reckoned from the landing and checked against the day of year beside it.
LANDED = {1: ("1976-07-20", 202), 2: ("1976-09-03", 247)}
SOL_SECONDS = 88775.244


def vicar_field(header: str, key: str) -> str | None:
    found = re.search(rf"\b{key}=('([^']*)'|\S+)", header)
    return (found[2] if found[2] is not None else found[1]) if found else None


def vicar_number(header: str, key: str) -> int:
    found = vicar_field(header, key)
    if found is None:
        raise ValueError(f"VICAR header states no {key}")
    return int(found)


def annotations(header: str) -> str:
    """The numbered comment lines the imaging team wrote the geometry into."""
    return " ".join(value for _, value in re.findall(r"LAB(\d\d)='([^']*)'", header))


def read_vicar(header: str) -> tuple[Mosaic, dict]:
    """The mosaic a VICAR header describes, and who took it when."""
    if vicar_field(header, "FORMAT") != "BYTE" or vicar_field(header, "ORG") != "BSQ":
        raise ValueError("Unsupported VICAR raster layout")
    text = annotations(header)
    pointing = re.search(
        r"MARS LOCAL\s+AZIMUTH/ELEVATION OF PIXEL\(1,1\)\s*=\s*"
        r"(-?[\d.]+)\s*/\s*(-?[\d.]+)",
        text,
    )
    degrees = re.search(r"SCALE\s*=\s*([\d.]+)\s*DEG/PIXEL", text)
    who = re.search(r"VIKING LANDER (\d)\s+CAMERA (\d)", text)
    when = re.search(r"LLD/T\s+(\d+)/[\d:]+.*?EVENT D/GMT\s+(\d+)/", text)
    if pointing is None or degrees is None:
        raise ValueError("Label states no pointing for the first pixel")
    if who is None:
        raise ValueError("Label names no lander and camera")
    if when is None:
        raise ValueError("Label states no capture sol")
    scale = 1 / float(degrees[1])
    elevation = float(pointing[2])
    mosaic = Mosaic(
        product_id="",
        sol=int(when[1]),
        site=0,
        drive=0,
        start_time="",
        stop_time="",
        width=vicar_number(header, "NS"),
        height=vicar_number(header, "NL"),
        bands=vicar_number(header, "NB"),
        dtype="u1",
        offset=vicar_number(header, "LBLSIZE"),
        azimuth=float(pointing[1]) % 360,
        scale_x=scale,
        scale_y=scale,
        # Line 1 points at `elevation`, and every line below it one pixel lower.
        zero_line=1 + elevation * scale,
        frame="LANDER_FRAME",
        # Mosaic canvas the frames never covered is left at zero, which the
        # stated range of real data sits well above.
        missing=(0.0,),
    )
    return mosaic, {"lander": int(who[1]), "camera": int(who[2]), "doy": int(when[2])}


def capture_date(lander: int, sol: int, doy: int) -> str:
    """The Earth date a lander sol fell on, checked against the label's own.

    The label counts sols since landing and, separately, the day of the year
    the data came down. Deriving the first and finding the second is what says
    the sol was read correctly.
    """
    landing, landing_doy = LANDED[lander]
    start = date.fromisoformat(landing)
    found = start + timedelta(seconds=sol * SOL_SECONDS)
    # The downlink day may be the sol's own or the one after it.
    if not 0 <= (doy - landing_doy) - (found - start).days <= 1:
        raise ValueError(f"Sol {sol} and day of year {doy} disagree")
    return found.isoformat()


def position(lander: int) -> dict:
    site = LANDERS[lander]
    return {
        **FRAME,
        "latitude": site["latitude"],
        "longitude": (360 - site["west_longitude"]) % 360,
        "elevation_m": None,
        "elevation_datum": None,
        "method": "published landing site, west longitude as the volume states it",
        "reference_point": "lander",
        "uncertainty_m": None,
        "source_url": CATALOG,
    }


def listing(client: httpx.Client, directory: str, cache: Path, *, refresh=False):
    page = fetch(
        client, ARCHIVE + directory + "/", cache / f"{directory}.html", refresh=refresh
    )
    return sorted(set(re.findall(r'href="([A-Za-z0-9_\-.]+\.vic)"', page.read_text())))


def download(client: httpx.Client, source_dir: Path, *, refresh=False) -> list[dict]:
    """Fetch every archived mosaic whose label states its pointing."""
    root = source_dir / COLLECTION
    root.mkdir(parents=True, exist_ok=True)
    accepted, rejected = [], []
    for directory in DIRECTORIES:
        for name in listing(client, directory, root / "listings", refresh=refresh):
            url = f"{ARCHIVE}{directory}/{name}"
            try:
                image = fetch(client, url, root / "images" / name, refresh=refresh)
                with image.open("rb") as stream:
                    header = stream.read(LABEL_PREFIX_BYTES).decode("latin-1")
                mosaic, who = read_vicar(header)
                mosaic.product_id = Path(name).stem
                mosaic.start_time = capture_date(who["lander"], mosaic.sol, who["doy"])
                mosaic.stop_time = mosaic.start_time
                mosaic.validate()
            except (ValueError, KeyError, httpx.HTTPStatusError) as error:
                rejected.append({"url": url, "reason": str(error)})
                logger.warning("Rejected %s: %s", name, error)
                continue
            accepted.append(
                {
                    "id": f"viking{who['lander']}-{mosaic.product_id}",
                    "mission": f"viking{who['lander']}",
                    "instrument": f"Facsimile camera {who['camera']}",
                    "mosaic": vars(mosaic).copy(),
                    "position": position(who["lander"]),
                    "image": str(image.relative_to(root)),
                    "image_url": url,
                    "image_sha256": sha256(image),
                }
            )
    if not accepted:
        raise ValueError("No supported Viking Lander mosaics found")
    write_json(
        root / "selection.json",
        {
            "schema_version": 1,
            "complete": True,
            "products": accepted,
            "rejected": rejected,
        },
    )
    logger.info(
        "viking: %s mosaics selected, %s rejected", len(accepted), len(rejected)
    )
    return accepted


def build_product(root: Path, output_dir: Path, product: dict, width: int) -> dict:
    mosaic = Mosaic(**product["mosaic"])
    mosaic.validate()
    image = root / product["image"]
    rgba, tone = read_pixels(image, mosaic)
    texture = sphere_texture(rgba, mosaic, width)
    directory = output_dir / COLLECTION / product["id"]
    directory.mkdir(parents=True, exist_ok=True)
    texture.save(directory / "panorama.webp", quality=90, method=4)
    preview = Image.fromarray(rgba)
    preview.thumbnail((1536, 768), Image.Resampling.LANCZOS)
    preview.save(directory / "preview.webp", quality=85)
    metadata = {
        "schema_version": 1,
        "build_version": BUILD_VERSION,
        "id": product["id"],
        "body": "mars",
        "body_id": "naif-499",
        "mission": product["mission"],
        "instrument": product["instrument"],
        "sol": mosaic.sol,
        "start_time": mosaic.start_time,
        "stop_time": mosaic.stop_time,
        "position": product["position"],
        "position_status": "published landing site",
        "projection": "equirectangular",
        "width": width,
        "height": width // 2,
        "hfov_deg": 360,
        "vfov_deg": 180,
        # The lander frame is referenced to the spacecraft, and nothing in the
        # label ties it to north, so no heading may be claimed.
        "north_azimuth_offset_deg": None,
        "pixel_convention": (
            "pixel centers; left edge is the frame's zero azimuth; clockwise; "
            "top edge +90 degrees"
        ),
        "source_coverage": {
            "hfov_deg": min(360, mosaic.width / mosaic.scale_x),
            "azimuth_start_deg": mosaic.azimuth,
            "elevation_max_deg": (mosaic.zero_line - 0.5) / mosaic.scale_y,
            "elevation_min_deg": (mosaic.zero_line - mosaic.height - 0.5)
            / mosaic.scale_y,
            "frame": mosaic.frame,
            "frame_is_north_referenced": False,
            "holes": "alpha=0; no synthetic sky or ground",
        },
        "coverage": {
            **coverage(texture, mosaic),
            "includes_source_grid": coordinate_grid_remains(read_header(image, mosaic)),
        },
        "color": "grayscale",
        "source_width": mosaic.width,
        "source_height": mosaic.height,
        "image": "panorama.webp",
        "preview": "preview.webp",
        "tone_mapping": tone,
        "quality_notes": [
            "Azimuth is measured in the lander frame; nothing ties it to north.",
            "Mosaic seams and near-lander parallax are retained.",
        ],
        "credit": "Courtesy NASA/JPL-Caltech",
        "reuse_policy_url": POLICY,
        "sources": {
            "image_url": product["image_url"],
            "image_sha256": product["image_sha256"],
        },
        "output_sha256": sha256(directory / "panorama.webp"),
    }
    write_json(directory / "metadata.json", metadata)
    logger.info(
        "Processed %s (%.1f%% sphere coverage)",
        product["id"],
        metadata["coverage"]["sphere_percent"],
    )
    return {
        "id": metadata["id"],
        "sol": metadata["sol"],
        "sphere_ready": True,
        "map_ready": True,
        "color": metadata["color"],
        "position": metadata["position"],
        "metadata": str((directory / "metadata.json").relative_to(output_dir)),
    }


def process(source_dir: Path, output_dir: Path, *, width=4096, rebuild=False):
    root = source_dir / COLLECTION
    selection = json.loads((root / "selection.json").read_text())
    entries, rejected, kept = [], [], 0
    for product in selection["products"]:
        directory = output_dir / COLLECTION / product["id"]
        built = directory / "metadata.json"
        if built.is_file():
            metadata = json.loads(built.read_text())
            if not rebuild and reusable(metadata, width):
                entries.append(
                    {
                        "id": metadata["id"],
                        "sol": metadata.get("sol"),
                        "sphere_ready": True,
                        "map_ready": True,
                        "color": metadata["color"],
                        "position": metadata["position"],
                        "metadata": str(built.relative_to(output_dir)),
                    }
                )
                kept += 1
                continue
            shutil.rmtree(directory)
        if sha256(root / product["image"]) != product["image_sha256"]:
            raise ValueError(f"Cached image checksum mismatch: {product['id']}")
        try:
            entries.append(build_product(root, output_dir, product, width))
        except (ValueError, KeyError, OSError) as error:
            rejected.append({"id": product["id"], "reason": str(error)})
            logger.warning("Rejected %s: %s", product["id"], error)
    write_json(
        output_dir / COLLECTION / "catalog.json",
        {
            "schema_version": 1,
            "body": "mars",
            "source_complete": bool(selection.get("complete")),
            "panoramas": entries,
        },
    )
    write_json(output_dir / COLLECTION / "processing-rejected.json", rejected)
    logger.info(
        "viking: %s panoramas (%s already built), %s rejected",
        len(entries),
        kept,
        len(rejected),
    )
    return entries


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("download", "process", "all"))
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--width", type=int, default=4096)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.stage in ("download", "all"):
        with httpx.Client(
            follow_redirects=True, timeout=300, transport=httpx.HTTPTransport(retries=3)
        ) as client:
            download(client, args.source_dir, refresh=args.refresh)
    if args.stage in ("process", "all"):
        process(
            args.source_dir, args.output_dir, width=args.width, rebuild=args.rebuild
        )


if __name__ == "__main__":
    cli()
