"""Inventory both official Pancam galleries, including small color mosaics."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import logging
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
import httpx

from .pipeline import POLICY, fetch, write_json
from .releases import unknown_coverage

logger = logging.getLogger(__name__)
BASE = "https://pancam.sese.asu.edu/"


def gallery_pages(html, *, full=False):
    soup = BeautifulSoup(html, "html.parser")
    columns = soup.find_all("td", width="50%")
    if len(columns) != 2:
        raise ValueError("Pancam mission-column layout changed")
    result = []
    for mission, column in zip(("spirit", "opportunity"), columns):
        for link in column.find_all("a", href=True):
            href = str(link["href"])
            if not re.fullmatch(r"[\w-]+\.html", href):
                continue
            context = link.find_parent("p")
            caption = context.get_text(" ", strip=True) if context else ""
            result.append(
                {
                    "mission": mission,
                    "url": urljoin(BASE, href),
                    "caption": caption,
                    "full": full,
                }
            )
    return result


def color_assets(html, descriptor):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    if not re.search(r"NASA\s*/\s*JPL", text):
        return []
    variants = []
    introduction = text.split("Image credit:", 1)[0]
    primary_color = bool(
        re.search(
            r"(?:true|false|natural)[ -]colou?r|colou?r (?:image|mosaic)",
            introduction,
            re.I,
        )
    )
    primary_stem = None
    for link in soup.find_all("a", href=True):
        url = urljoin(BASE, str(link["href"]))
        parsed = urlsplit(url)
        name = Path(parsed.path).name.lower()
        if parsed.hostname != "pancam.sese.asu.edu" or not name.endswith(
            (".jpg", ".png", ".tif", ".tiff")
        ):
            continue
        context = link.parent.get_text(" ", strip=True).lower() if link.parent else ""
        if any(
            term in name
            for term in ("ana", "stereo", "polar", "vert", "_vp", "thumb", "mono")
        ):
            continue
        if re.search(r"(?:^|_)(?:traverse|map|dem)(?:_|\.)", name):
            continue
        if primary_stem is None:
            primary_stem = Path(name).stem
        if not (
            re.search(r"[lr][1-7]{3}", name)
            or any(
                word in name
                for word in ("atc", "false", "natural", "enhanced", "truecolor")
            )
            or re.search(r"(?:true|false|natural|enhanced)\s*colou?r", context)
            or (primary_color and Path(name).stem == primary_stem)
        ):
            continue
        variants.append(
            {
                "url": url,
                "color": "approximate-true"
                if "atc" in name or "natural" in name
                else "source-color-composite",
                "format": Path(name).suffix[1:],
            }
        )
    if not variants:
        return []
    variants.sort(
        key=lambda v: (
            v["color"] != "approximate-true",
            v["format"] not in {"jpg", "png"},
            "cyl" not in v["url"].lower(),
        )
    )
    groups = {}
    for variant in variants:
        stem = Path(urlsplit(variant["url"]).path).stem.lower()
        family = re.sub(
            r"(?:_[lr][1-7]{3}(?:atc\d*|f)?|_(?:atc|false|natural|enhanced|truecolor))(?=_|$)",
            "",
            stem,
        )
        groups.setdefault(family, []).append(variant)
    width = re.search(
        r"(?:approximately\s+)?(\d+(?:\.\d+)?)\s*(?:degrees?|°)[ -]+wide", text, re.I
    )
    declared = re.search(
        r"(?:spans?|covers?)\s+(\d+(?:\.\d+)?)\s*(?:degrees?|°)|(\d+(?:\.\d+)?)[ -]*(?:degrees?|°)[, -]+(?:(?:false.color|true.color|color|high.resolution)[ -]+)?(?:view|panorama|mosaic|image|vista)",
        introduction,
        re.I,
    )
    products = []
    for family, alternatives in groups.items():
        identity = descriptor["mission"] + "-pancam-" + family
        sol = (
            re.search(r"\bSols?\s+(\d+)", descriptor["caption"], re.I)
            if len(groups) == 1
            else re.search(r"(?:sol)?(\d+)[ab]_", family, re.I)
        )
        horizontal = None
        if declared and (len(groups) == 1 or "cyl" in family):
            horizontal = float(declared[1] or declared[2])
        elif len(groups) == 1 and width:
            horizontal = float(width[1])
        products.append(
            {
                "id": identity,
                "mission": descriptor["mission"],
                "instrument": "Pancam",
                "sol": int(sol[1]) if sol else None,
                "title": descriptor["mission"].title()
                + " · "
                + (descriptor["caption"] if len(groups) == 1 else family),
                "capture_time": None,
                "capture_date_caption": descriptor["caption"],
                "publication_time": None,
                "position": None,
                "position_status": "requires rover localization association",
                "projection": "unverified landscape projection",
                "projection_bounds": None,
                "coverage": unknown_coverage(horizontal),
                "color": alternatives[0]["color"],
                "credit": "NASA/JPL/Cornell/Arizona State University",
                "reuse": {
                    "status": "allowed-with-credit",
                    "policy_url": POLICY,
                    "credit_source_url": descriptor["url"],
                },
                "source_pages": [descriptor["url"]],
                "source_caption": text,
                "selected_url": alternatives[0]["url"],
                "variants": alternatives,
                "scene_deduplication": "color/format variants grouped; overlapping crops may remain",
            }
        )
    return products


def discover_pancam(client, root, *, refresh=False):
    directory = root / "pancam"
    cache = directory / "metadata"
    descriptors = {}
    for name, full in (("panoramas", True), ("mosaics", False)):
        html = fetch(
            client, BASE + name + ".html", cache / (name + ".html"), refresh=refresh
        ).read_text()
        for descriptor in gallery_pages(html, full=full):
            descriptors.setdefault(descriptor["url"], descriptor)
    products, rejected, checked = {}, [], 0

    def inspect(descriptor):
        url = descriptor["url"]
        name = hashlib.sha256(url.encode()).hexdigest()[:24] + ".html"
        try:
            html = fetch(client, url, cache / name, refresh=refresh).read_text()
            assets = color_assets(html, descriptor)
            return assets, None if assets else {
                "url": url,
                "reason": "no supported color landscape variant; inspect for alternate naming or monochrome-only data",
            }
        except (httpx.HTTPError, OSError, ValueError) as error:
            return [], {"url": url, "reason": str(error)}

    def checkpoint(complete):
        write_json(
            directory / "inventory.json",
            {
                "schema_version": 2,
                "collection": "pancam",
                "discovery_complete": complete,
                "scope": "all linked pages in the official full and partial Pancam galleries; supported color filename/context patterns",
                "candidate_page_count": len(descriptors),
                "checked_page_count": checked,
                "products": list(products.values()),
                "rejected": rejected,
            },
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        for count, (assets, rejection) in enumerate(
            pool.map(inspect, descriptors.values()), 1
        ):
            for asset in assets:
                products.setdefault(asset["id"], asset)
            checked = count
            if rejection:
                rejected.append(rejection)
            if count % 25 == 0:
                checkpoint(False)
                logger.info(
                    "Pancam: %s/%s pages checked, %s color mosaics",
                    count,
                    len(descriptors),
                    len(products),
                )
    checkpoint(True)
