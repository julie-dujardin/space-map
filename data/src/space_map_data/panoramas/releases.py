"""Inventory and cache official color mosaics without inventing projection bounds."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
from typing import Any
import re
import shutil
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup
import httpx
import numpy as np
from PIL import Image

from .pipeline import fetch, sha256, write_json

logger = logging.getLogger(__name__)
API = "https://mastcamz.asu.edu/wp-json/wp/v2/"
POLICY = "https://mastcamz.asu.edu/mastcam-zs-landscape-mosaic-collection/"
FULL_POLICY = "https://mastcamz.asu.edu/mastcam-zs-360-panorama-collection/"
ASSET_HOSTS = {"mastcamz.asu.edu", "mcz-images.sese.asu.edu"}


def plain(html):
    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)


def unknown_coverage(horizontal=None):
    return {
        "horizontal_degrees": horizontal,
        "horizontal_percent": horizontal / 3.6 if horizontal is not None else None,
        "sphere_percent": None,
        "method": "published horizontal extent; vertical bounds and valid-pixel mask pending"
        if horizontal is not None
        else "projection bounds not yet verified",
    }


def mastcam_assets(post):
    """Retain variants as alternatives, not extra street-view locations."""
    soup = BeautifulSoup(post["content"]["rendered"], "html.parser")
    title = plain(post["title"]["rendered"])
    groups = {}
    for link in soup.find_all("a", href=True):
        url = str(link["href"])
        parsed = urlsplit(url)
        name = unquote(Path(parsed.path).name)
        if parsed.hostname not in ASSET_HOSTS or Path(name).suffix.lower() not in {
            ".png",
            ".jpg",
            ".jpeg",
            ".tif",
            ".tiff",
        }:
            continue
        # Only documented RGB filters and cylindrical color products are admitted.
        match = re.search(
            r"(CZCAM_SOL\d+_ZCAM\d+_Z\d+)_([LR]0)_(NN|EE)_SCI_CYL_(.+)_(\d{2})\.(png|jpe?g|tiff?)$",
            name,
            re.I,
        )
        if not match:
            legacy = re.fullmatch(
                r"(Mastcam-Z_360_.+_Sols?\d+[\d_-]*)_([LR]0)_(natural|enhanced)(?:_(?:half|2x))?\.(png|jpe?g|tiff?)",
                name,
                re.I,
            )
            if not legacy:
                continue
            prefix, eye, color_name, extension = legacy.groups()
            color = "NN" if color_name.lower() == "natural" else "EE"
            target, revision = "360", "0"
        else:
            prefix, eye, color, target, revision, extension = match.groups()
        key = f"{prefix}_{target}".lower()
        if key not in groups:
            sol_match = re.search(r"SOLs?(\d+)", prefix, re.I)
            assert sol_match is not None
            sol = int(sol_match[1])
            groups[key] = {
                "id": "perseverance-mastcamz-" + key,
                "mission": "perseverance",
                "instrument": "Mastcam-Z",
                "sol": sol,
                "title": title,
                "target": target,
                "sequence": prefix,
                "capture_time": None,
                "publication_time": post["date"],
                "position": None,
                "position_status": "requires exact sequence/site-drive association",
                "projection": "cylindrical",
                "projection_bounds": None,
                "coverage": unknown_coverage(360 if target == "360" else None),
                "color": "natural",
                "credit": "NASA/JPL-Caltech/ASU/MSSS",
                "reuse": {
                    "status": "allowed-with-credit",
                    "policy_url": FULL_POLICY if target == "360" else POLICY,
                },
                "source_pages": [post["link"]],
                "variants": [],
            }
        groups[key]["variants"].append(
            {
                "url": url,
                "eye": eye.upper(),
                "color": color.upper(),
                "revision": int(revision),
                "format": extension.lower(),
            }
        )
    return list(groups.values())


def discover_mastcam(client, root, *, refresh=False):
    cache = root / "mastcamz" / "metadata"
    fetch(client, POLICY, cache / "reuse-policy.html", refresh=refresh)
    fetch(client, FULL_POLICY, cache / "360-policy.html", refresh=refresh)
    taxonomy = json.loads(
        fetch(
            client,
            API + "gallery?per_page=100",
            cache / "taxonomy.json",
            refresh=refresh,
        ).read_text()
    )
    gallery_id = next(
        row["id"] for row in taxonomy if row["slug"] == "panoramas-mosaics"
    )
    products, unsupported, post_count = {}, [], 0
    collection_post = {
        "link": FULL_POLICY,
        "date": None,
        "title": {"rendered": "Mastcam-Z 360 panorama collection"},
        "content": {"rendered": (cache / "360-policy.html").read_text()},
    }
    for asset in mastcam_assets(collection_post):
        products[asset["id"]] = asset
    page = 1
    while True:
        url = API + f"gallery_item?gallery={gallery_id}&per_page=100&page={page}"
        rows = json.loads(
            fetch(
                client, url, cache / f"page-{page:04}.json", refresh=refresh
            ).read_text()
        )
        post_count += len(rows)
        for post in rows:
            assets = mastcam_assets(post)
            if not assets:
                unsupported.append(
                    {
                        "url": post["link"],
                        "title": plain(post["title"]["rendered"]),
                        "reason": "no supported cylindrical RGB asset filename",
                    }
                )
            for asset in assets:
                key = asset["id"]
                if key in products:
                    products[key]["variants"].extend(asset["variants"])
                    products[key]["source_pages"].extend(asset["source_pages"])
                    if "collection" in products[key]["title"].lower():
                        products[key]["title"] = asset["title"]
                else:
                    products[key] = asset
        logger.info(
            "Mastcam-Z page %s: %s posts, %s RGB mosaics",
            page,
            post_count,
            len(products),
        )
        if len(rows) < 100:
            break
        page += 1
    for product in products.values():
        product["source_pages"] = sorted(set(product["source_pages"]))
        product["variants"] = list({v["url"]: v for v in product["variants"]}.values())
        if re.search(r"360\D*panorama", product["title"], re.I):
            product["coverage"] = unknown_coverage(360)
        product["variants"].sort(
            key=lambda v: (
                v["color"] != "NN",
                v["eye"] != "L0",
                -v["revision"],
                v["format"] != "png",
            )
        )
        product["selected_url"] = product["variants"][0]["url"]
        product["color"] = (
            "natural" if product["variants"][0]["color"] == "NN" else "enhanced"
        )
    inventory = {
        "schema_version": 2,
        "collection": "mastcamz",
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "discovery_complete": True,
        "source_post_count": post_count,
        "scope": "all public Mastcam-Z panoramas/mosaics gallery pages; supported RGB cylindrical filenames",
        "products": sorted(products.values(), key=lambda p: (p["sol"], p["id"])),
        "unresolved_posts": unsupported,
        "policy_sha256": sha256(cache / "reuse-policy.html"),
    }
    write_json(root / "mastcamz" / "inventory.json", inventory)
    return inventory


def timeline_select(products, *, years=2):
    """Keep endpoints and curated events alongside the regular sampling cadence."""
    if years < 1:
        raise ValueError("Timeline interval must be positive")
    dated, undated = [], []
    for product in products:
        if not product.get("capture_time"):
            undated.append({**product, "timeline_reason": "capture date needs review"})
            continue
        stamp = datetime.fromisoformat(product["capture_time"].replace("Z", "+00:00"))
        dated.append((stamp, product))
    dated.sort(key=lambda row: (row[0], row[1]["id"]))
    chosen = {}
    if dated:
        for reason, (_, item) in zip(("first", "last"), (dated[0], dated[-1])):
            chosen.setdefault(item["id"], {**item, "timeline_reasons": []})[
                "timeline_reasons"
            ].append(reason)
        anchor = dated[0][0]
        next_year = anchor.year + years
        for stamp, item in dated:
            reasons = list(item.get("interesting_reasons", []))
            if stamp >= anchor.replace(
                year=min(next_year, 9999), day=min(anchor.day, 28)
            ):
                reasons.append(f"{years}-year interval")
                next_year = stamp.year + years
            if reasons:
                chosen.setdefault(item["id"], {**item, "timeline_reasons": []})[
                    "timeline_reasons"
                ].extend(reasons)
    return sorted(chosen.values(), key=lambda p: (p["capture_time"], p["id"])), undated


def download_releases(client, root, collection, *, limit=None):
    directory = root / collection
    inventory = json.loads((directory / "inventory.json").read_text())
    state_path = directory / "downloads.json"
    state: dict[str, Any] = (
        json.loads(state_path.read_text())
        if state_path.exists()
        else {"schema_version": 2, "products": {}}
    )
    count = 0
    by_url = {row["url"]: row for row in state["products"].values()}
    for product in inventory["products"]:
        if limit is not None and count >= limit:
            break
        identity = product["id"]
        previous = state["products"].get(
            identity, by_url.get(product["selected_url"], {})
        )
        if (
            previous.get("status") == "downloaded"
            and previous.get("url") == product["selected_url"]
        ):
            path = directory / previous["path"]
            if path.exists() and sha256(path) == previous["sha256"]:
                state["products"][identity] = previous
                continue
        if shutil.disk_usage(directory).free < 20 * 1024**3:
            raise OSError(
                "Stopping before disk free space falls below 20 GiB; rerun to resume"
            )
        url = product["selected_url"]
        suffix = Path(urlsplit(url).path).suffix.lower()
        path = (
            directory
            / "images"
            / (hashlib.sha256(url.encode()).hexdigest()[:24] + suffix)
        )
        try:
            fetch(client, url, path, refresh=path.exists())
            # Headers are enough to record native size without decoding gigapixel rasters.
            with Image.open(path) as image:
                width, height = image.size
                mode = image.mode
            record = {
                "status": "downloaded",
                "url": url,
                "path": str(path.relative_to(directory)),
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
                "width": width,
                "height": height,
                "mode": mode,
            }
        except (httpx.HTTPError, OSError, ValueError) as error:
            record = {"status": "failed", "url": url, "error": str(error)}
            logger.warning("Download failed: %s: %s", identity, error)
        state["products"][identity] = record
        write_json(state_path, state)
        count += 1
        logger.info("%s: %s (%s new attempts)", collection, identity, count)
    write_json(state_path, state)
    return state


def refresh_catalog(output, collection):
    path = output / collection / "catalog.json"
    if not path.exists():
        return
    catalog = json.loads(path.read_text())
    for entry in catalog["panoramas"]:
        metadata = json.loads((output / entry["metadata"]).read_text())
        entry.update(
            {
                key: metadata.get(key)
                for key in (
                    "mission",
                    "instrument",
                    "position",
                    "coverage",
                    "color",
                    "capture_time",
                    "source_width",
                    "source_height",
                )
            }
        )
        entry["sphere_ready"] = bool(metadata.get("image"))
        entry["map_ready"] = bool(
            metadata.get("image")
            and metadata.get("position")
            and metadata.get("grid_geometry_status") != "estimated"
            and metadata.get("geometry_status") != "estimated"
        )
    write_json(path, catalog)


def process_releases(root, output, collection):
    directory = root / collection
    inventory = json.loads((directory / "inventory.json").read_text())
    state = json.loads((directory / "downloads.json").read_text())
    entries, review = [], []
    for product in inventory["products"]:
        record = state["products"].get(product["id"], {})
        if record.get("status") != "downloaded":
            continue
        source = directory / record["path"]
        if sha256(source) != record["sha256"]:
            raise ValueError(f"Source checksum mismatch: {source}")
        target = output / collection / product["id"]
        target.mkdir(parents=True, exist_ok=True)
        previous_path = target / "metadata.json"
        previous = (
            json.loads(previous_path.read_text()) if previous_path.exists() else {}
        )
        if (
            not (target / "preview.webp").exists()
            or previous.get("source_sha256") != record["sha256"]
        ):
            with Image.open(source) as image:
                image.draft("RGB", (2048, 1024))
                image.thumbnail((2048, 1024))
                image.convert("RGB").save(target / "preview.webp", quality=90)
        with Image.open(target / "preview.webp") as image:
            sample = image.convert("RGB")
            sample.thumbnail((96, 96))
            chromatic = float(
                (np.ptp(np.asarray(sample).astype(np.int16), axis=2) > 8).mean()
            )
        if chromatic < 0.01:
            review.append(
                {
                    "id": product["id"],
                    "reason": "monochrome-like raster excluded from color catalog",
                    "chromatic_fraction": chromatic,
                }
            )
            continue
        metadata = {
            **product,
            "schema_version": 2,
            "source_width": record["width"],
            "source_height": record["height"],
            "source_sha256": record["sha256"],
            "preview": "preview.webp",
            "render_status": "flat-preview-only; angular bounds unverified",
            "chromatic_fraction": chromatic,
        }
        write_json(target / "metadata.json", metadata)
        entries.append(
            {
                "id": product["id"],
                "sol": product["sol"],
                "title": product["title"],
                "metadata": str((target / "metadata.json").relative_to(output)),
                "preview": str((target / "preview.webp").relative_to(output)),
            }
        )
    write_json(
        output / collection / "catalog.json",
        {"schema_version": 2, "panoramas": entries},
    )
    refresh_catalog(output, collection)
    write_json(output / collection / "processing-audit.json", {"review": review})
    return entries


def cli():
    parser = argparse.ArgumentParser(
        description="Cache official preprocessed color panoramas, including partial mosaics"
    )
    parser.add_argument("stage", choices=["discover", "download", "process", "all"])
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--limit",
        type=int,
        help="Optional new download attempts per invocation; discovery is always complete",
    )
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument(
        "--collections",
        nargs="+",
        choices=[
            "mastcamz",
            "pancam",
            "curiosity",
            "spirit",
            "opportunity",
            "insight",
            "phoenix",
            "pathfinder",
        ],
        default=["mastcamz"],
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("Limit must be positive")
    if args.stage in {"process", "all"} and args.output_dir is None:
        parser.error("--output-dir is required for processing")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # Official full-resolution releases routinely exceed Pillow's generic web-image cap.
    Image.MAX_IMAGE_PIXELS = None
    with httpx.Client(
        follow_redirects=True, timeout=120, transport=httpx.HTTPTransport(retries=3)
    ) as client:
        for collection in args.collections:
            if args.stage in {"discover", "all"}:
                if collection == "mastcamz":
                    discover_mastcam(client, args.source_dir, refresh=args.refresh)
                elif collection == "pancam":
                    from .pancam import discover_pancam

                    discover_pancam(client, args.source_dir, refresh=args.refresh)
                else:
                    from .nasa_releases import discover_nasa

                    discover_nasa(
                        client, args.source_dir, collection, refresh=args.refresh
                    )
            if args.stage in {"download", "all"}:
                download_releases(client, args.source_dir, collection, limit=args.limit)
            if args.stage in {"process", "all"}:
                process_releases(args.source_dir, args.output_dir, collection)


if __name__ == "__main__":
    cli()
