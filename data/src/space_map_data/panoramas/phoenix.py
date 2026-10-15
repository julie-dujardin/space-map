"""Build sphere textures from Phoenix's full-circle horizon panoramas.

The imaging team mosaicked the Surface Stereo Imager frames into cylindrical
products in the site frame, whose azimuth starts at north. Of the archive's
mosaics only five go all the way round at the horizon: the first ring of
sols 1-3 and the 56-frame horizon pans of sols 20, 54, 87 and 112, taken from
the same spot over the mission. The others are sky surveys, views of the deck
or ground tiers with gaps.
"""

import argparse
import json
import logging
from pathlib import Path
import re

import httpx
import numpy as np
from PIL import Image
from scipy import ndimage

from .labels import read_attached_pds3
from .missions import lander_position
from .pipeline import (
    BUILD_VERSION,
    LABEL_PREFIX_BYTES,
    coverage,
    fetch,
    fill_from_neighbours,
    label_text,
    raw_pixels,
    sha256,
    sphere_texture,
    tone_map,
    write_json,
)

logger = logging.getLogger(__name__)

ARCHIVE = "https://planetarydata.jpl.nasa.gov/img/data/phoenix/phxmos_0xxx/data/ssi/"
COLLECTION = "phoenix-mosaic"
PRODUCTS = (
    "sol001/s_001edn_cyl_sr10d28_r111m1.img",
    "sol020/s_020edn_cyl_sr129f8_r888m1.img",
    "sol054/s_054edn_cyl_sr161e8_r888m1.img",
    "sol087/s_087edn_cyl_sr1a368_r888m1.img",
    "sol112/s_112edn_cyl_sr1d068_r888m1.img",
)
CREDIT = "NASA/JPL-Caltech/University of Arizona/Texas A&M University"
POLICY = "https://www.jpl.nasa.gov/jpl-image-use-policy/"
# The coordinate overlay is drawn into the pixels: a grid across empty canvas,
# and azimuth and elevation numbers near the edges in black with a white
# outline. A saturated pixel reads the outline value too, so a number is only
# looked for in the edge band.
LABEL_VALUES = (1, 4096)
LABEL_MARGIN = 24
FILL_PASSES = 32


def read_pixels(path: Path, mosaic) -> tuple[np.ndarray, dict]:
    """Display pixels without the drawn coordinate overlay.

    Grid lines run over empty canvas, so they are left empty too. The numbers
    along the top and bottom sit in rows that are mostly canvas, so those rows
    are dropped. The ones on the left and right edges sit inside the image
    and are filled in from the pixels around them.
    """
    pixels, valid = raw_pixels(path, mosaic)
    drawn = np.isin(pixels[:, :, 0], LABEL_VALUES)
    grid = drawn & ndimage.binary_dilation(~valid, np.ones((3, 3), dtype=bool))
    valid &= ~grid
    labels = drawn & ~grid
    labels[LABEL_MARGIN:-LABEL_MARGIN, LABEL_MARGIN:-LABEL_MARGIN] = False
    rows = np.flatnonzero(labels.any(axis=1))
    top = rows[rows < LABEL_MARGIN]
    bottom = rows[rows >= mosaic.height - LABEL_MARGIN]
    if top.size:
        valid[: top.max() + 1] = False
        labels[: top.max() + 1] = False
    if bottom.size:
        valid[bottom.min() :] = False
        labels[bottom.min() :] = False
    pixels, valid = fill_from_neighbours(pixels, valid, labels, FILL_PASSES)
    return tone_map(pixels, valid, mosaic.bands)


def read_label(path: Path):
    """The mosaic an attached label describes. The label states no sol; the
    product name starts with it."""
    with path.open("rb") as stream:
        text = label_text(stream.read(LABEL_PREFIX_BYTES).decode("latin-1"))
    sol = re.match(r"s_(\d{3})", path.name)
    if sol is None:
        raise ValueError(f"No sol in product name: {path.name}")
    return read_attached_pds3(text, 0, int(sol[1]))


def download(client: httpx.Client, source_dir: Path, *, refresh=False) -> list[dict]:
    root = source_dir / COLLECTION
    products = []
    for name in PRODUCTS:
        url = ARCHIVE + name
        image = fetch(client, url, root / "images" / Path(name).name, refresh=refresh)
        mosaic = read_label(image)
        products.append(
            {
                "id": f"phoenix-{mosaic.product_id.lower()}",
                "mosaic": vars(mosaic).copy(),
                "image": str(image.relative_to(root)),
                "image_url": url,
                "image_sha256": sha256(image),
            }
        )
    write_json(
        root / "selection.json",
        {"schema_version": 1, "complete": True, "products": products},
    )
    logger.info("phoenix: %s mosaics selected", len(products))
    return products


def build_product(root: Path, output_dir: Path, product: dict, width: int) -> dict:
    image = root / product["image"]
    if sha256(image) != product["image_sha256"]:
        raise ValueError(f"Cached image checksum mismatch: {product['id']}")
    mosaic = read_label(image)
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
        "mission": "phoenix",
        "instrument": "SSI",
        "sol": mosaic.sol,
        "start_time": mosaic.start_time,
        "stop_time": mosaic.stop_time,
        "position": lander_position("phoenix"),
        "position_status": "published landing site",
        "projection": "equirectangular",
        "width": width,
        "height": width // 2,
        "hfov_deg": 360,
        "vfov_deg": 180,
        # The site frame is level and its azimuth starts at north.
        "north_azimuth_offset_deg": 0,
        "pixel_convention": "pixel centers; left edge north; clockwise; top edge +90 degrees",
        "source_coverage": {
            "hfov_deg": min(360, mosaic.width / mosaic.scale_x),
            "azimuth_start_deg": mosaic.azimuth,
            "elevation_max_deg": (mosaic.zero_line - 0.5) / mosaic.scale_y,
            "elevation_min_deg": (mosaic.zero_line - mosaic.height - 0.5)
            / mosaic.scale_y,
            "frame": mosaic.frame,
            "frame_is_north_referenced": True,
            "holes": "alpha=0; no synthetic sky or ground",
        },
        "coverage": {**coverage(texture, mosaic), "includes_source_grid": False},
        "color": "grayscale",
        "source_width": mosaic.width,
        "source_height": mosaic.height,
        "image": "panorama.webp",
        "preview": "preview.webp",
        "tone_mapping": tone,
        "quality_notes": [
            "The archive's coordinate numbers are removed: edge rows dropped, side numbers filled from the pixels around them.",
            "Mosaic seams and near-lander parallax are retained.",
        ],
        "credit": CREDIT,
        "reuse": {"status": "allowed-with-credit", "policy_url": POLICY},
        "selected_url": product["image_url"],
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


def process(source_dir: Path, output_dir: Path, *, width=4096) -> list[dict]:
    root = source_dir / COLLECTION
    selection = json.loads((root / "selection.json").read_text())
    entries = [
        build_product(root, output_dir, product, width)
        for product in selection["products"]
    ]
    write_json(
        output_dir / COLLECTION / "catalog.json",
        {
            "schema_version": 1,
            "body": "mars",
            "source_complete": True,
            "panoramas": entries,
        },
    )
    return entries


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("download", "process", "all"))
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--width", type=int, default=4096)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.stage in ("download", "all"):
        with httpx.Client(
            follow_redirects=True, timeout=300, transport=httpx.HTTPTransport(retries=3)
        ) as client:
            download(client, args.source_dir, refresh=args.refresh)
    if args.stage in ("process", "all"):
        process(args.source_dir, args.output_dir, width=args.width)


if __name__ == "__main__":
    cli()
