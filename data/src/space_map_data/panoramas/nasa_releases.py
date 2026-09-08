"""Discover official rover color releases and curated lander timeline frames."""

import json
import logging
import re
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from .pipeline import POLICY, fetch, write_json
from .releases import unknown_coverage

logger = logging.getLogger(__name__)
API = "https://images-api.nasa.gov/"
INSTRUMENTS = {
    "curiosity": ("Mastcam", "mastcam", "mast camera"),
    "spirit": ("Pancam", "pancam", "panoramic camera"),
    "opportunity": ("Pancam", "pancam", "panoramic camera"),
}
TRUSTED_CREDITS = {
    "NASA/JPL-Caltech/University of Arizona/Texas A&M University",
    "NASA/JPL-Caltech/Cornell Univ./Arizona State Univ.",
    "NASA/JPL-Caltech/Cornell University",
    "NASA/JPL-Caltech/Cornell/Arizona State Univ.",
    "NASA/JPL/Cornell/Texas A&M",
    "NASA/JPL/Texas A&M/Cornell",
    "NASA/JPL-Caltech/Cornell/USGS/ASU",
    "NASA/JPL-Caltech/Malin Space Science Systems",
    "NASA/JPL-Caltech/MSSS/ASU",
    "NASA/JPL-Caltech",
    "NASA/JPL",
    "NASA/JPL-Caltech/MSSS",
    "NASA/JPL-Caltech/ASU",
    "NASA/JPL-Caltech/ASU/MSSS",
    "NASA/JPL/Cornell",
    "NASA/JPL-Caltech/Cornell",
    "NASA/JPL/Cornell/ASU",
    "NASA/JPL-Caltech/Cornell/ASU",
    "NASA/JPL-Caltech/University of Arizona",
    "NASA/JPL/University of Arizona",
    "NASA/JPL-Caltech/Texas A&M/Cornell",
}

# Capture dates come from the captions, not the image library's publication field.
INSIGHT = {
    "PIA23140": {
        "capture_time": "2018-12-09",
        "instrument": "IDC",
        "sol": 14,
        "projection": "unknown",
        "coverage": {
            "horizontal_degrees": 290,
            "horizontal_percent": 290 / 360 * 100,
            "sphere_percent": None,
            "method": "NASA caption; vertical bounds unknown",
        },
        "interesting_reasons": ["290-degree Homestead Hollow landing-site panorama"],
    },
    "PIA22829": {
        "capture_time": "2018-11-26",
        "instrument": "ICC",
        "interesting_reasons": ["first surface image; dust cover still on"],
    },
    "PIA22876": {
        "capture_time": "2018-12-06",
        "instrument": "IDC",
        "interesting_reasons": ["first full selfie; clean solar panels"],
    },
    "PIA23203": {
        "capture_time": "2019-03-01",
        "capture_stop_time": "2019-04-30",
        "capture_date_precision": "month range",
        "instrument": "IDC",
        "interesting_reasons": ["second selfie; visible dust accumulation"],
    },
    "PIA25287": {
        "capture_time": "2022-04-24",
        "instrument": "IDC",
        "interesting_reasons": ["final selfie; dusty solar panels"],
    },
    "PIA25680": {
        "capture_time": "2022-12-11",
        "instrument": "ICC",
        "interesting_reasons": [
            "one of the last published surface images; not verified as the final exposure"
        ],
    },
}

HEROES = {"phoenix": ("PIA13804", "SSI"), "pathfinder": ("PIA01466", "IMP")}

CURATED_MASTCAM = (
    (
        "PIA23623",
        "curiositys-18-billion-pixel-panorama",
        "PIA23623_hires.tif",
        "2019-11-24",
        "2019-12-01",
        None,
    ),
    (
        "PIA26696",
        "curiosity-captures-a-360-degree-view-at-nevado-sajama",
        "PIA26696_figA.png",
        "2025-11-09",
        "2025-12-07",
        4714,
    ),
)


def curated_mastcam(client, cache, *, refresh=False):
    products = []
    for identity, slug, filename, start, stop, sol in CURATED_MASTCAM:
        page = f"https://science.nasa.gov/photojournal/{slug}/"
        html = fetch(
            client, page, cache / f"{identity}-photojournal.html", refresh=refresh
        ).read_text()
        soup = BeautifulSoup(html, "html.parser")
        credit = "NASA/JPL-Caltech/MSSS"
        if credit not in soup.get_text():
            raise ValueError(f"Curated credit changed: {page}")
        urls = [
            href
            for a in soup.select("a[href]")
            if isinstance(href := a.get("href"), str)
            and filename in href
            and href.startswith("https://assets.science.nasa.gov/")
        ]
        heading = soup.h1
        if not urls or heading is None:
            raise ValueError(f"Curated master missing: {page}")
        # The original asset bypasses the website's thumbnail transformation.
        original = urls[0].split("?", 1)[0].replace("/dynamicimage/assets/", "/assets/")
        products.append(
            {
                "id": f"curiosity-{identity.lower()}",
                "mission": "curiosity",
                "instrument": "Mastcam",
                "sol": sol,
                "title": heading.get_text(strip=True),
                "capture_time": start,
                "capture_stop_time": stop,
                "position": None,
                "position_status": "caption/localization association pending",
                "projection": "unknown",
                "projection_bounds": None,
                "coverage": {
                    **unknown_coverage(),
                    "horizontal_degrees": 360,
                    "horizontal_percent": 100,
                    "method": "published full-360 description; vertical bounds unknown",
                },
                "color": "source-processed color",
                "credit": credit,
                "reuse": {
                    "status": "allowed-with-credit",
                    "policy_url": POLICY,
                    "credit_source_url": page,
                },
                "source_pages": [page],
                "selected_url": original,
                "variants": [{"url": original}],
            }
        )
    return products


def rover_in_caption(description):
    introduction = description[:2000]
    matches = re.findall(
        r"\brover\s+(curiosity|spirit|opportunity)\b|\b(curiosity|spirit|opportunity)(?:\s+Mars)?\s+rover\b|\bNASA['’]s\s+(Curiosity|Spirit|Opportunity)\b",
        introduction,
        re.I,
    )
    missions = {value.lower() for pair in matches for value in pair if value}
    return next(iter(missions)) if len(missions) == 1 else None


def search(client, cache, query, *, refresh=False):
    rows, page = [], 1
    while True:
        url = (
            API
            + "search?"
            + urlencode(
                {"q": query, "media_type": "image", "page_size": 100, "page": page}
            )
        )
        name = query.replace(" ", "-") + f"-{page}.json"
        data = json.loads(
            fetch(client, url, cache / name, refresh=refresh).read_text()
        )["collection"]
        rows.extend(data["items"])
        if not any(link.get("rel") == "next" for link in data.get("links", [])):
            return rows
        page += 1


def discover_nasa(client, root, mission, *, refresh=False):
    directory = root / mission
    cache = directory / "metadata"
    try:
        fetch(client, POLICY, cache / "reuse-policy.html", refresh=refresh)
    except httpx.HTTPStatusError as error:
        if error.response.status_code != 403:
            raise
        write_json(
            cache / "reuse-policy-review.json",
            {
                "url": POLICY,
                "reviewed_date": "2026-09-07",
                "review_method": "official policy read through browser; direct HTTP cache returned 403",
                "conditions": "credit NASA/JPL-Caltech; no endorsement; exclude separately copyrighted third-party material",
            },
        )
    queries = [f"{mission} {term}" for term in ("panorama", "mosaic", "360")]
    if mission == "insight":
        queries = list(INSIGHT)
    elif mission in HEROES:
        queries = [HEROES[mission][0]]
    items = {}
    for query in queries:
        for item in search(client, cache, query, refresh=refresh):
            data = item["data"][0]
            items[data["nasa_id"]] = item
    products, rejected = [], []
    for identity, item in sorted(items.items()):
        data = item["data"][0]
        description = data.get("description", "")
        text = (data["title"] + " " + description).lower()
        reason = None
        if not identity.startswith("PIA") or data.get("center") != "JPL":
            reason = "not a JPL Photojournal release"
        elif mission == "insight":
            if identity not in INSIGHT:
                reason = "not a curated timeline frame"
        elif mission in HEROES:
            if identity != HEROES[mission][0]:
                reason = "not a curated lander panorama"
        elif rover_in_caption(description) != mission:
            reason = "rover identity not established in caption introduction"
        elif any(
            term in description[:800].lower()
            for term in (
                "space simulation chamber",
                "microscopic imager",
                "navigation camera",
                "pair of images",
                "side-by-side",
            )
        ):
            reason = "test, mixed-camera or comparison product requires review"
        elif mission != "curiosity" and not re.search(r"\b(colou?rs?|rgb)\b", text):
            reason = "caption does not establish color"
        elif mission not in text or not any(
            term in text for term in INSTRUMENTS[mission][1:]
        ):
            reason = "mission/color instrument not established by caption"
        elif any(
            term in data["title"].lower()
            for term in (
                "anaglyph",
                "stereo",
                "polar",
                "vertical",
                "map",
                "simulat",
                "artist",
            )
        ):
            reason = "not a single-eye landscape color product"
        elif "black-and-white" in text and not any(
            term in text
            for term in (
                "true color",
                "true-color",
                "natural color",
                "false-color",
                "false color",
            )
        ):
            reason = "color not established"
        if reason:
            rejected.append({"id": identity, "reason": reason})
            continue
        metadata_url = f"https://images-assets.nasa.gov/image/{identity}/metadata.json"
        metadata = json.loads(
            fetch(
                client, metadata_url, cache / f"{identity}-credit.json", refresh=refresh
            ).read_text()
        )
        credit = metadata.get("AVAIL:SecondaryCreator", "").strip()
        if credit not in TRUSTED_CREDITS:
            rejected.append(
                {
                    "id": identity,
                    "reason": "credit requires reuse review",
                    "credit": credit,
                }
            )
            continue
        asset_url = API + "asset/" + identity
        assets = json.loads(
            fetch(
                client, asset_url, cache / f"{identity}-assets.json", refresh=refresh
            ).read_text()
        )["collection"]["items"]
        originals = [
            a["href"]
            for a in assets
            if a["href"]
            .lower()
            .endswith(
                ("~orig.jpg", "~orig.jpeg", "~orig.png", "~orig.tif", "~orig.tiff")
            )
        ]
        if not originals:
            rejected.append({"id": identity, "reason": "no original raster in library"})
            continue
        product = {
            "id": f"{mission}-{identity.lower()}",
            "mission": mission,
            "instrument": "IDC"
            if mission == "insight"
            else HEROES[mission][1]
            if mission in HEROES
            else INSTRUMENTS[mission][0],
            "sol": None,
            "title": data["title"],
            "description": description,
            "capture_time": None,
            "publication_time": data.get("date_created"),
            "position": None,
            "position_status": "caption/localization association pending",
            "projection": "unknown",
            "projection_bounds": None,
            "coverage": unknown_coverage(),
            "color": "source-processed; natural/false-color classification pending",
            "credit": credit,
            "reuse": {
                "status": "allowed-with-credit",
                "policy_url": POLICY,
                "credit_source_url": metadata_url,
            },
            "source_pages": [f"https://photojournal.jpl.nasa.gov/catalog/{identity}"],
            "selected_url": originals[0],
            "variants": [{"url": url} for url in originals],
        }
        if mission == "insight":
            product["projection"] = "unrectified still/selfie"
            product.update(INSIGHT[identity])
        products.append(product)
        logger.info("%s release: %s", mission, identity)
    if mission == "curiosity":
        curated = curated_mastcam(client, cache, refresh=refresh)
        replacements = {p["id"] for p in curated}
        products = [p for p in products if p["id"] not in replacements] + curated
    result = {
        "schema_version": 2,
        "collection": mission,
        "discovery_complete": True,
        "scope": "all result pages of the recorded NASA library queries; not an exhaustive PDS mission inventory",
        "queries": queries,
        "products": products,
        "rejected": rejected,
    }
    if mission == "insight":
        from .releases import timeline_select

        result["products"], result["undated"] = timeline_select(products)
        result["timeline"] = {
            "interval_years": 2,
            "endpoints": "first/last in curated source set",
            "mission_last_exposure_verified": False,
        }
    write_json(directory / "inventory.json", result)
    return result
