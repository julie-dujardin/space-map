"""Scrape per-texture source metadata from USGS / NASA pages.

Iterates the per-body entries in the texture manifests
(`constants/manifests/textures/`), fetches the `source:` page for each, parses
the structured fields the site publishes, and writes one JSON per entry to
`textures/source_metadata/{file_stem}.json`.

The goal is troubleshooting-friendly provenance, not something the export
pipeline consumes directly. A human (or a follow-up auto-fill step) then copies
the relevant bits — a compact `attribution:` line — back into the manifest.

Supported sites:
- USGS Astrogeology Science Center (`astrogeology.usgs.gov/search/map/...`)
  — structured `<dt>/<dd>` table with authors, abstract, credits, mission,
  instrument, latitude/longitude extent, etc.
- NASA Photojournal (`science.nasa.gov/photojournal/...`) — labeled block
  with Credits / Target / Mission / Instrument / Description and JSON-LD.
- NASA Scientific Visualization Studio (`svs.gsfc.nasa.gov/<id>/...`) —
  fetched via the studio's JSON API at `svs.gsfc.nasa.gov/api/<id>` (much
  cleaner than scraping the page) for title, description, credits, dates,
  funding sources, keywords, and the downloadable media listing.
- NASA Earth Observatory (`science.nasa.gov/earth/earth-observatory/...`) —
  loose prose; meta description + main article body.

Other hosts (bjj.mmedia.is, stevealbers.net, deviantart, lpi.usra.edu, etc.)
are left alone — their `attribution:` has already been hand-curated from the
page content the user provided.
"""

import json
import logging
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from space_map_data.constants.manifests.textures import MANIFESTS_DIR, load_entries
from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader
from space_map_data.utils.paths import DERIVED_TEXTURES_DIR, SOURCES_TEXTURES_DIR

logger = logging.getLogger(__name__)

SOURCE_METADATA_DIR = DERIVED_TEXTURES_DIR / "source-metadata"
HTML_CACHE_DIR = SOURCE_METADATA_DIR / "html"
PARSED_DIR = SOURCE_METADATA_DIR / "parsed"

REQUEST_DELAY_SECONDS = 3.0


# ------------------------------------------------------------------ helpers --


def _dt_dd_pairs(soup: BeautifulSoup) -> dict[str, str]:
    """Extract <dt>/<dd> pairs into a dict. USGS pages use this heavily."""
    out: dict[str, str] = {}
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if not dd:
            continue
        label = dt.get_text(" ", strip=True)
        value = dd.get_text(" ", strip=True)
        if label and value:
            out[label] = value
    return out


def _clean_main_text(soup: BeautifulSoup, selector: str = "main") -> str:
    """Return visible text from the main content area, stripping nav/scripts/etc."""
    main = soup.select_one(selector) or soup.find("article") or soup.body
    if not isinstance(main, Tag):
        return ""
    for node in main(["script", "style", "nav", "footer", "aside", "iframe"]):
        node.decompose()
    return main.get_text("\n", strip=True)


def _meta(soup: BeautifulSoup, name: str) -> str | None:
    tag = soup.find("meta", attrs={"name": name}) or soup.find(
        "meta", attrs={"property": name}
    )
    if isinstance(tag, Tag):
        content = tag.get("content")
        if isinstance(content, str):
            return content.strip()
    return None


_MOJIBAKE_MARKERS = ("Â", "Ã", "â€")


def _fix_mojibake_deep(obj: object) -> object:
    """Apply _fix_mojibake to every string inside a nested dict/list structure."""
    if isinstance(obj, str):
        return _fix_mojibake(obj)
    if isinstance(obj, list):
        return [_fix_mojibake_deep(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _fix_mojibake_deep(v) for k, v in obj.items()}
    return obj


def _fix_mojibake_dict(d: dict) -> dict:
    """Typed wrapper around _fix_mojibake_deep for dict-valued parser results."""
    fixed = _fix_mojibake_deep(d)
    assert isinstance(fixed, dict)
    return fixed


def _fix_mojibake(text: str | None) -> str | None:
    """Reverse UTF-8-as-latin-1 double-encoding when we can detect it.

    Some source pages (notably USGS Astrogeology) serve `°` as `Â°` etc. —
    their bytes are UTF-8 content mis-decoded as latin-1 then re-encoded as
    UTF-8. Running the inverse restores the intended characters.
    """
    if text is None or not any(m in text for m in _MOJIBAKE_MARKERS):
        return text
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _json_ld_objects(soup: BeautifulSoup) -> list[dict]:
    """Parse all application/ld+json blocks, handling @graph lists."""
    out: list[dict] = []
    for s in soup.find_all("script", type="application/ld+json"):
        if not s.string:
            continue
        try:
            data = json.loads(s.string)
        except json.JSONDecodeError:
            logger.debug("Skipping malformed JSON-LD block")
            continue
        if isinstance(data, dict):
            if "@graph" in data and isinstance(data["@graph"], list):
                out.extend(x for x in data["@graph"] if isinstance(x, dict))
            else:
                out.append(data)
        elif isinstance(data, list):
            out.extend(x for x in data if isinstance(x, dict))
    return out


# --------------------------------------------------------------- USGS parser -


def _parse_usgs(html: str, url: str) -> dict:
    """Parse an astrogeology.usgs.gov /search/map/<id> page.

    Fields (when present):
    title, description, abstract, purpose, credits, authors, publisher,
    mission, instrument, mission_names, target, date, edition,
    access_constraints, use_constraints, format, native_env, theme,
    source_title, source_online_linkage, bbox (min/max lat/lon),
    supplemental_information, online_file_link.
    """
    soup = BeautifulSoup(html, "html.parser")
    pairs = _dt_dd_pairs(soup)

    title_tag = soup.find("h1") or soup.find("title")
    title = title_tag.get_text(" ", strip=True) if title_tag else None

    meta_desc = _meta(soup, "description")
    # Abstract on the page is the authoritative long-form description.
    abstract = pairs.get("Abstract")
    purpose = pairs.get("Purpose")

    authors_raw = pairs.get("Primary Authors")
    authors = [a.strip() for a in authors_raw.split(",")] if authors_raw else []

    def _multi(key: str) -> list[str]:
        v = pairs.get(key)
        if not v:
            return []
        parts = re.split(r",\s*", v)
        return [p for p in (p.strip() for p in parts) if p]

    bbox = None
    if all(
        k in pairs
        for k in (
            "Minimum Latitude",
            "Maximum Latitude",
            "Minimum Longitude",
            "Maximum Longitude",
        )
    ):
        try:
            bbox = {
                "min_lat": float(pairs["Minimum Latitude"]),
                "max_lat": float(pairs["Maximum Latitude"]),
                "min_lon": float(pairs["Minimum Longitude"]),
                "max_lon": float(pairs["Maximum Longitude"]),
            }
        except ValueError:
            pass

    publisher = pairs.get("Publisher")
    originator = pairs.get("Originators")
    mission = pairs.get("Mission Names")
    # USGS pages sometimes put the canonical NASA-style credit chain in
    # "Primary Authors" (e.g. "NASA/JPL-Caltech/UCLA/MPS/DLR/IDA" for Vesta).
    # When it looks like a credit chain, prefer it verbatim. Otherwise fall
    # back to a "Courtesy <publisher>. Data: <originator> (<mission>)." line
    # built from the other structured fields.
    slash_credit = authors_raw if authors_raw and authors_raw.count("/") >= 2 else None
    if slash_credit:
        attribution = slash_credit
    else:
        credit_pieces = []
        if publisher:
            credit_pieces.append(f"Courtesy {publisher}")
        if originator or mission:
            data_line = []
            if originator:
                data_line.append(originator)
            if mission:
                data_line.append(f"({mission})")
            credit_pieces.append("Data: " + " ".join(data_line))
        attribution = ". ".join(credit_pieces) + "." if credit_pieces else None

    result = {
        "source_url": url,
        "site": "usgs_astrogeology",
        "title": title,
        "description_meta": meta_desc,
        "abstract": abstract,
        "purpose": purpose,
        "authors": authors,
        "publisher": publisher,
        "originators": originator,
        "mission_names": _multi("Mission Names"),
        "instrument_names": _multi("Instrument Names"),
        "target": pairs.get("Target"),
        "format": pairs.get("Format"),
        "edition": pairs.get("Edition"),
        "access_constraints": pairs.get("Access Constraints"),
        "use_constraints": pairs.get("Use Constraints"),
        "native_environment": pairs.get("Native Data Set Environment"),
        "theme": pairs.get("Astrogeology Theme"),
        "source_title": pairs.get("Source Title"),
        "source_online_linkage": pairs.get("Source Online Linkage"),
        "supplemental_information": pairs.get("Supplemental Information"),
        "online_file_link": pairs.get("Online File Link"),
        "file_size": pairs.get("External File Size"),
        "process_description": pairs.get("Process Description"),
        "completeness_report": pairs.get("Completeness Report"),
        "logical_consistency": pairs.get("Logical Consistency"),
        "update_frequency": pairs.get("Update Frequency"),
        "progress": pairs.get("Progress"),
        "bbox": bbox,
        "attribution_guess": attribution,
    }
    return _fix_mojibake_dict(result)


# -------------------------------------------------- NASA Photojournal parser -

_NASA_PJ_LABEL_KEYS = {
    "Credits": "credits",
    "Image Addition Date": "image_addition_date",
    "Target": "target",
    "Is a satellite of": "satellite_of",
    "Mission(s)": "missions",
    "Mission": "missions",
    "Spacecraft(s)": "spacecraft",
    "Spacecraft": "spacecraft",
    "Instrument(s)": "instruments",
    "Instrument": "instruments",
    "Product Size": "product_size",
    "Produced By": "produced_by",
}


def _parse_label_block(lines: list[str], stop_sections: set[str]) -> dict[str, str]:
    """Walk a list of text lines and group label-colon-followed-by-value pairs.

    The NASA Photojournal body renders each field as:
        <p>Label:</p><p>Value</p>
    which flattens to two consecutive lines, label ending in ':'. Each value is
    treated as a single line.

    `stop_sections` terminates the block *once we've started collecting*, so
    unrelated headings above the first label (breadcrumbs, navigation bars) are
    ignored.
    """
    out: dict[str, str] = {}
    started = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if started and stripped in stop_sections:
            break
        if stripped.endswith(":") and i + 1 < len(lines):
            key = stripped[:-1].strip()
            value = lines[i + 1].strip()
            if value and value not in stop_sections and not value.endswith(":"):
                out[key] = value
                started = True
    return out


def _parse_nasa_photojournal(html: str, url: str) -> dict:
    """Parse a science.nasa.gov/photojournal/<slug>/ page."""
    soup = BeautifulSoup(html, "html.parser")

    title_tag = soup.find("h1") or soup.find("title")
    title = title_tag.get_text(" ", strip=True) if title_tag else None

    meta_desc = _meta(soup, "description")

    # JSON-LD carries page-poster names and dates/keywords. The "author" field
    # there is the NASA staffer who uploaded the page, NOT the image credit —
    # we track it as `page_authors` to make that distinction obvious. The real
    # image credit lives in the "Credits:" label block.
    jsonld = _json_ld_objects(soup)
    article = next((o for o in jsonld if o.get("@type") == "NewsArticle"), None)
    page_authors: list[str] = []
    keywords: list[str] = []
    date_created = None
    date_modified = None
    if article:
        raw_authors = article.get("author") or []
        if isinstance(raw_authors, list):
            page_authors = [
                a["name"] if isinstance(a, dict) and "name" in a else str(a)
                for a in raw_authors
            ]
        elif isinstance(raw_authors, dict):
            page_authors = [raw_authors.get("name", "")]
        kw = article.get("keywords")
        if isinstance(kw, list):
            keywords = [str(k) for k in kw]
        date_created = article.get("dateCreated")
        date_modified = article.get("dateModified")

    main_text = _clean_main_text(soup)
    lines = [ln for ln in main_text.split("\n") if ln.strip()]
    photojournal_stops = {
        "Downloads",
        "Description",
        "Keep Exploring",
        "Discover More Topics",
        "Photojournal",
        "Feedback",
        "Photojournal Navigation",
    }
    labels = _parse_label_block(lines, photojournal_stops)

    # The freeform "Description" section is a big block of text after the
    # "Description" label — capture everything up to the next section marker.
    description = None
    for idx, ln in enumerate(lines):
        if ln.strip() == "Description":
            # Accumulate lines until a known next-section anchor.
            collected: list[str] = []
            stop_markers = {
                "Keep Exploring",
                "Discover More Topics",
                "Photojournal",
                "Feedback",
            }
            for follower in lines[idx + 1 :]:
                if any(follower.startswith(m) for m in stop_markers):
                    break
                collected.append(follower)
            description = "\n".join(collected).strip() or None
            break

    def _field(key: str) -> str | None:
        for k, mapped in _NASA_PJ_LABEL_KEYS.items():
            if mapped == key and k in labels:
                return labels[k]
        return None

    credits = _field("credits")
    attribution = credits or None  # photojournal credits are short & self-contained

    return {
        "source_url": url,
        "site": "nasa_photojournal",
        "title": title,
        "description_meta": meta_desc,
        "description": description,
        "credits": credits,
        "target": _field("target"),
        "satellite_of": _field("satellite_of"),
        "missions": _field("missions"),
        "spacecraft": _field("spacecraft"),
        "instruments": _field("instruments"),
        "image_addition_date": _field("image_addition_date"),
        "produced_by": _field("produced_by"),
        "product_size": _field("product_size"),
        "page_authors": page_authors,
        "keywords": keywords,
        "date_created": date_created,
        "date_modified": date_modified,
        "attribution_guess": attribution,
    }


# ----------------------------------------------------------- NASA SVS parser -

_SVS_PATH_ID_RE = re.compile(r"^/(\d+)(?:/|$)")


def _svs_id_from_url(url: str) -> str | None:
    """Extract the numeric visualization id from an svs.gsfc.nasa.gov page URL."""
    m = _SVS_PATH_ID_RE.match(urlparse(url).path)
    return m.group(1) if m else None


def _svs_api_url(svs_id: str) -> str:
    return f"https://svs.gsfc.nasa.gov/api/{svs_id}"


def _svs_people(entries: object) -> list[str]:
    """Flatten an SVS credit list of `{name, employer}` dicts into "Name (Employer)" strings."""
    if not isinstance(entries, list):
        return []
    out: list[str] = []
    for raw in entries:
        if not isinstance(raw, dict):
            continue
        p = cast(dict[str, object], raw)
        name = str(p.get("name") or "").strip()
        employer = str(p.get("employer") or "").strip()
        if not name:
            continue
        out.append(f"{name} ({employer})" if employer else name)
    return out


def _parse_nasa_svs(data: dict, url: str) -> dict:
    """Parse a payload from the svs.gsfc.nasa.gov/api/<id> JSON endpoint.

    The API exposes everything the HTML page renders as structured fields:
    title, description, release/update timestamps, role-keyed credits, mission
    and funding tags, keywords, and per-media-group download listings. We pull
    a normalized subset suitable for attribution + provenance display.
    """
    svs_id = (
        str(data.get("id")) if data.get("id") is not None else _svs_id_from_url(url)
    )

    main_credits = data.get("main_credits") or {}
    visualizations_by = _svs_people(main_credits.get("Visualizations by"))

    credits_by_role: dict[str, list[str]] = {}
    for entry in data.get("credits") or []:
        if not isinstance(entry, dict):
            continue
        role = (entry.get("role") or "").strip()
        people = _svs_people(entry.get("people"))
        if role and people:
            credits_by_role[role] = people

    description = data.get("description")
    if isinstance(description, str):
        # API descriptions sometimes list download filenames after a "||" sep.
        # Drop those — they're a flattened table of contents, not prose.
        description = description.split("||", 1)[0].strip() or None

    # Each media group lists one or more files at varying resolutions.
    media_files: list[dict] = []
    for group in data.get("media_groups") or []:
        if not isinstance(group, dict):
            continue
        for item in group.get("items") or []:
            if not isinstance(item, dict):
                continue
            inst = (
                item.get("instance") if isinstance(item.get("instance"), dict) else item
            )
            filename = inst.get("filename")
            if not filename:
                continue
            media_files.append(
                {
                    "filename": filename,
                    "url": inst.get("url"),
                    "width": inst.get("width"),
                    "height": inst.get("height"),
                    "media_type": inst.get("media_type"),
                }
            )

    attribution = None
    if visualizations_by:
        attribution = (
            "NASA's Goddard Space Flight Center Scientific Visualization Studio "
            f"— visualizations by {', '.join(visualizations_by)}."
        )

    return {
        "source_url": url,
        "api_url": _svs_api_url(svs_id) if svs_id else None,
        "site": "nasa_svs",
        "svs_id": svs_id,
        "title": data.get("title"),
        "description": description,
        "visualizations_by": visualizations_by,
        "credits_by_role": credits_by_role,
        "released": data.get("release_date"),
        "last_updated": data.get("update_date"),
        "missions": data.get("missions") or [],
        "funding_sources": data.get("funding_sources") or [],
        "keywords": data.get("keywords") or [],
        "media_files": media_files,
        "attribution_guess": attribution,
    }


# ------------------------------------------- NASA Earth Observatory parser --


def _parse_nasa_earth_observatory(html: str, url: str) -> dict:
    """Parse a science.nasa.gov/earth/earth-observatory/<slug>/ page.

    These are prose articles — we pull meta description, main body text, and
    a conservative default attribution.
    """
    soup = BeautifulSoup(html, "html.parser")

    title_tag = soup.find("h1") or soup.find("title")
    title = title_tag.get_text(" ", strip=True) if title_tag else None

    meta_desc = _meta(soup, "description")

    jsonld = _json_ld_objects(soup)
    article = next((o for o in jsonld if o.get("@type") == "NewsArticle"), None)
    authors: list[str] = []
    if article:
        raw_authors = article.get("author") or []
        if isinstance(raw_authors, list):
            authors = [
                a["name"] if isinstance(a, dict) and "name" in a else str(a)
                for a in raw_authors
            ]

    body_text = _clean_main_text(soup)
    body_lines = [ln for ln in body_text.split("\n") if ln.strip()]
    # Breadcrumbs / nav / section headings at the top of the body are all short
    # (<80 chars). Drop them to reach the first prose paragraph.
    first_prose = next((i for i, ln in enumerate(body_lines) if len(ln) > 80), 0)
    description = "\n".join(body_lines[first_prose : first_prose + 12]).strip()
    description = description[:3000] or None

    # JSON-LD often lists "NASA Earth Observatory" itself as the author —
    # dedupe against the site name so we don't render "… — NASA Earth Observatory."
    _SITE = "NASA Earth Observatory"
    people = [a for a in authors if a and a != _SITE]
    attribution = _SITE + (" — " + ", ".join(people) if people else "") + "."

    return {
        "source_url": url,
        "site": "nasa_earth_observatory",
        "title": title,
        "description_meta": meta_desc,
        "description": description,
        "authors": authors,
        "attribution_guess": attribution,
    }


# ------------------------------------------------------- dispatch / download -

_HTML_PARSERS = {
    "usgs_astrogeology": _parse_usgs,
    "nasa_photojournal": _parse_nasa_photojournal,
    "nasa_earth_observatory": _parse_nasa_earth_observatory,
}

_ALL_SITES = {*_HTML_PARSERS.keys(), "nasa_svs"}


def _site_for(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    path = urlparse(url).path.lower()
    if host == "astrogeology.usgs.gov" or host.endswith(".astrogeology.usgs.gov"):
        return "usgs_astrogeology"
    if host == "svs.gsfc.nasa.gov":
        return "nasa_svs"
    if host == "science.nasa.gov":
        if path.startswith("/photojournal/"):
            return "nasa_photojournal"
        if path.startswith("/earth/"):
            return "nasa_earth_observatory"
    return None


def _file_stem(file_name: str) -> str:
    return Path(file_name).stem


class TextureSourcesDownloader(Downloader):
    name = PROVIDERS.TEXTURE_SOURCES

    def __init__(self, client: httpx.Client) -> None:
        # Skip the base class mkdir — we live under textures/, not a dedicated provider dir.
        self.client = client
        self.out_dir = SOURCE_METADATA_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)
        HTML_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        PARSED_DIR.mkdir(parents=True, exist_ok=True)

    def _fetch_text(self, url: str, cache_path: Path, *, force: bool) -> str:
        if cache_path.exists() and not force:
            return cache_path.read_text(encoding="utf-8")
        logger.info("GET %s", url)
        resp = self.client.get(url)
        resp.raise_for_status()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(resp.text, encoding="utf-8")
        time.sleep(REQUEST_DELAY_SECONDS)
        return resp.text

    def download(
        self,
        limit: int | None = None,
        *,
        force: bool = False,
        **kwargs: object,
    ) -> None:
        entries = load_entries(SOURCES_TEXTURES_DIR)
        if limit is not None:
            entries = entries[:limit]

        wrote = 0
        skipped_unsupported = 0
        errors = 0

        for entry in entries:
            source_url = entry.get("source")
            file_name = entry.get("file")
            if not source_url or not file_name:
                continue
            site = _site_for(source_url)
            if site is None:
                logger.debug("No parser for %s — skipping", source_url)
                skipped_unsupported += 1
                continue

            stem = _file_stem(file_name)
            out_json = PARSED_DIR / f"{stem}.json"
            if out_json.exists() and not force:
                logger.debug("Already parsed: %s", out_json.name)
                continue

            try:
                parsed = self._fetch_and_parse(site, source_url, stem, force=force)
            except Exception:
                logger.exception("Failed to fetch/parse %s (%s)", source_url, site)
                errors += 1
                continue

            parsed["fetched_at"] = datetime.now(UTC).isoformat()
            parsed["entry_body"] = entry.get("body")
            parsed["entry_file"] = file_name
            out_json.write_text(
                json.dumps(parsed, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            wrote += 1

        logger.info(
            "texture_sources: wrote %d, skipped %d (no parser), %d errors",
            wrote,
            skipped_unsupported,
            errors,
        )
        self._save_metadata(
            url=str(MANIFESTS_DIR),
            record_count=wrote,
            complete=True,
            parser_sites=sorted(_ALL_SITES),
        )

    def _fetch_and_parse(
        self, site: str, source_url: str, stem: str, *, force: bool
    ) -> dict:
        """Dispatch fetch + parse per site. SVS uses its JSON API; others scrape HTML."""
        if site == "nasa_svs":
            svs_id = _svs_id_from_url(source_url)
            if not svs_id:
                raise ValueError(f"could not extract SVS id from {source_url}")
            api_url = _svs_api_url(svs_id)
            cache_path = HTML_CACHE_DIR / f"{stem}.api.json"
            payload = self._fetch_text(api_url, cache_path, force=force)
            return _parse_nasa_svs(json.loads(payload), source_url)

        cache_path = HTML_CACHE_DIR / f"{stem}.html"
        html = self._fetch_text(source_url, cache_path, force=force)
        return _HTML_PARSERS[site](html, source_url)

    def is_complete(self, limit: int | None) -> bool:
        # Always re-run; cheap since HTML is cached and per-entry JSONs are
        # skipped when they exist. `force=True` forces a full re-scrape.
        return False
