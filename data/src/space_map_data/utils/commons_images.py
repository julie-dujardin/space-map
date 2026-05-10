"""Shared helpers for Commons-hosted image files.

Used by:
- download/providers/images/commons.py — decide what to download, write metadata
- ingest/providers/images.py — set ``Object.image_available``
- export/images.py — emit per-object image lists and generate thumbnails

The on-disk layout after download is::

    DOWNLOAD_DIR/commons/images/<filename>/source.<ext>    # the source image bytes
    DOWNLOAD_DIR/commons/images/<filename>/metadata.json   # Commons imageinfo + license_servable

``<filename>`` is the full canonical Commons filename (underscore form, including
extension) — it is the stable Commons identity.
"""

import json
import logging
from pathlib import Path
from urllib.parse import unquote, urlparse

import orjson

from space_map_data.constants.providers import LANGUAGES, PROVIDERS
from space_map_data.utils.paths import DOWNLOAD_DIR

logger = logging.getLogger(__name__)


IMAGES_DIR = DOWNLOAD_DIR / "commons" / "images"

_WIKIDATA_IMAGE_PIDS = ("P18", "P154")
# Auto-generated orbit diagrams on ru.wiki that flood the pageimages set.
EXCLUDED_FILENAME_PREFIXES = ("Орбита_астероида_", "Орбита_кометы_")

# License tags we refuse to serve. Matched case-insensitively as substrings of
# ``extmetadata.LicenseShortName`` (and of each segment of a multi-license
# "A or B or C" string).
_DENIED_LICENSE_KEYWORDS = (
    "fair use",
    "non-free",
    "all rights reserved",
    "cc by-nc",
    "cc-by-nc",
    "cc by-nd",
    "cc-by-nd",
)


def canonical_filename(filename: str) -> str:
    """Normalize a Commons filename to its MediaWiki canonical (underscore) form.

    MediaWiki treats spaces and underscores as equivalent in page titles and
    always stores the underscore form internally. Callers mix space-form (from
    Wikidata claim values) and underscore-form (from parsed URL paths), which
    would otherwise produce duplicate downloads/queries for the same file.
    """
    return filename.replace(" ", "_")


def is_excluded(filename: str) -> bool:
    """Skip-list check for known-noise filename prefixes."""
    return any(filename.startswith(p) for p in EXCLUDED_FILENAME_PREFIXES)


def image_dir(filename: str) -> Path:
    """Per-image directory under DOWNLOAD_DIR/commons/images/."""
    return IMAGES_DIR / filename


def source_path(filename: str) -> Path:
    """Downloaded source image path. Extension matches the Commons filename."""
    ext = Path(filename).suffix
    return image_dir(filename) / f"source{ext}"


def download_metadata_path(filename: str) -> Path:
    """Per-image Commons metadata JSON (raw API response + license_servable flag)."""
    return image_dir(filename) / "metadata.json"


def parse_upload_url(url: str) -> tuple[str, str] | None:
    """Return ``(repo, filename)`` from an ``upload.wikimedia.org`` URL, or None.

    ``repo`` is ``"commons"`` for Commons files and a wiki code (e.g. ``"ru"``)
    for files hosted locally on a specific wiki.
    """
    parts = urlparse(url).path.split("/")
    # path is like /wikipedia/<repo>/<hash>/<hash>/<filename>
    if len(parts) < 4 or parts[1] != "wikipedia":
        return None
    repo = parts[2]
    filename = unquote(parts[-1])
    if not filename:
        return None
    return repo, filename


def extract_wikidata_filenames(entity: dict) -> set[str]:
    """Extract unique Commons image filenames from P18 and P154 claims."""
    filenames: set[str] = set()
    claims = entity.get("claims", {})
    for pid in _WIKIDATA_IMAGE_PIDS:
        for stmt in claims.get(pid, []):
            if stmt.get("rank") == "deprecated":
                continue
            val = stmt.get("mainsnak", {}).get("datavalue", {}).get("value")
            if isinstance(val, str) and val:
                filenames.add(canonical_filename(val))
    return filenames


def collect_qid_commons_filenames(
    qid: str,
    wikidata_dir: Path | None = None,
    wiki_dir: Path | None = None,
) -> list[dict]:
    """Return the ordered, deduped list of Commons-hosted images for a QID.

    Each entry is ``{"filename": str, "kind": "photo"|"logo"}``. Order is
    Wikidata P18 (photo) → Wikipedia pageimages (photo) → Wikidata P154 (logo)
    so the "first image" stays stable as Wikipedia sources come and go.

    Non-Commons Wikipedia images and excluded-prefix filenames are filtered
    out here; callers see only servable candidates.
    """
    wikidata_dir = wikidata_dir or (DOWNLOAD_DIR / PROVIDERS.WIKIDATA / "objects")
    wiki_dir = wiki_dir or (DOWNLOAD_DIR / PROVIDERS.WIKIPEDIA)

    photo_from_wikidata: list[str] = []
    logo_from_wikidata: list[str] = []
    entity_path = wikidata_dir / f"{qid}.json"
    if entity_path.exists():
        try:
            entity = orjson.loads(entity_path.read_bytes())
        except orjson.JSONDecodeError:
            entity = None
        if entity:
            claims = entity.get("claims", {})
            for stmt in claims.get("P18", []):
                if stmt.get("rank") == "deprecated":
                    continue
                v = stmt.get("mainsnak", {}).get("datavalue", {}).get("value")
                if isinstance(v, str) and v:
                    photo_from_wikidata.append(canonical_filename(v))
            for stmt in claims.get("P154", []):
                if stmt.get("rank") == "deprecated":
                    continue
                v = stmt.get("mainsnak", {}).get("datavalue", {}).get("value")
                if isinstance(v, str) and v:
                    logo_from_wikidata.append(canonical_filename(v))

    photo_from_wikipedia: list[str] = []
    for lang in LANGUAGES:
        page_path = wiki_dir / lang / f"{qid}.json"
        if not page_path.exists():
            continue
        try:
            page = orjson.loads(page_path.read_bytes())
        except orjson.JSONDecodeError:
            continue
        if page.get("missing"):
            continue
        src = (page.get("original") or {}).get("source")
        if not src:
            continue
        parsed = parse_upload_url(src)
        if parsed is None:
            continue
        repo, filename = parsed
        if repo != "commons":
            continue
        photo_from_wikipedia.append(canonical_filename(filename))

    seen: set[str] = set()
    out: list[dict] = []
    for name in photo_from_wikidata + photo_from_wikipedia:
        if name in seen or is_excluded(name):
            continue
        seen.add(name)
        out.append({"filename": name, "kind": "photo"})
    for name in logo_from_wikidata:
        if name in seen or is_excluded(name):
            continue
        seen.add(name)
        out.append({"filename": name, "kind": "logo"})
    return out


def license_is_servable(extmetadata: dict) -> tuple[bool, str | None]:
    """Decide whether a Commons image's license allows us to serve it.

    Returns ``(servable, reason)`` where ``reason`` is non-None when rejected
    (used for log lines). The rules are the same as the legacy
    ``export/images._license_is_servable``:

    - LicenseShortName must exist and be a non-empty string
    - Each "A or B or C" segment is tested independently; at least one must
      pass ``_is_acceptable`` and NOT be GFDL-only. Multi-licensed
      ``CC BY-SA or GFDL`` images are fine because we can serve under the CC
      side and skip the GFDL license-text obligation.
    """
    short_value = (extmetadata.get("LicenseShortName") or {}).get("value")
    if not isinstance(short_value, str) or not short_value.strip():
        return False, "no LicenseShortName"

    tags = [t.strip() for t in short_value.split(" or ") if t.strip()]
    acceptable = [t for t in tags if _license_tag_is_acceptable(t)]
    if not acceptable:
        return False, f"unacceptable license {short_value!r}"
    non_gfdl = [t for t in acceptable if "gfdl" not in t.lower()]
    if not non_gfdl:
        return False, f"GFDL-only license {short_value!r}"
    return True, None


def _license_tag_is_acceptable(short_name: str) -> bool:
    """True if a single LicenseShortName tag is one we're willing to serve."""
    lower = short_name.lower()
    return not any(kw in lower for kw in _DENIED_LICENSE_KEYWORDS)


def read_download_metadata(filename: str) -> dict | None:
    """Read a downloaded image's metadata JSON, or None if missing/corrupt."""
    path = download_metadata_path(filename)
    if not path.exists():
        return None
    try:
        return orjson.loads(path.read_bytes())
    except orjson.JSONDecodeError:
        logger.warning("Corrupt download metadata: %s", path)
        return None


def is_servable_on_disk(filename: str) -> bool:
    """True when the downloaded metadata says the image's license is servable.

    Callers that also need the source bytes should check ``source_path`` too.
    """
    meta = read_download_metadata(filename)
    if not meta:
        return False
    return bool(meta.get("license_servable"))


def write_download_metadata(filename: str, payload: dict) -> None:
    """Persist the Commons metadata for a downloaded image (JSON, indented)."""
    path = download_metadata_path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
