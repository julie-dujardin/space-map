"""Collect and resolve image metadata for object export."""

import html
import logging
import re
from urllib.parse import quote

import orjson

from space_map_data.utils.paths import EXPORT_DIR

logger = logging.getLogger(__name__)

_IMAGES_DIR = EXPORT_DIR / "v1" / "images"
_THUMB_DIR = _IMAGES_DIR / "thumb"
_FULL_DIR = _IMAGES_DIR / "full"
_METADATA_DIR = _IMAGES_DIR / "metadata"

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

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def collect_object_images(
    extracted: dict,
    wiki_image_filenames: list[str],
) -> list[dict] | None:
    """Build the ``images`` array for a single object's global JSON.

    Collects images from:
    - Wikidata P18 (``extracted["image"]``) — kind=photo
    - Wikipedia pageimages from all languages — kind=photo
    - Wikidata P154 (``extracted["logo_image"]``) — kind=logo

    Deduplicates by canonical (underscore-form) filename, checks the image is
    present on disk, and filters out entries whose Commons metadata license is
    unknown or non-redistributable. Each returned entry also carries the
    attribution fields (``artist``, ``license``, ``license_url``) needed to
    display the image responsibly.

    Returns None if no images qualify.
    """
    seen: set[str] = set()
    images: list[dict] = []

    for filename in extracted.get("image", []):
        _try_add(images, seen, filename, "photo")
    for filename in wiki_image_filenames:
        _try_add(images, seen, filename, "photo")
    for filename in extracted.get("logo_image", []):
        _try_add(images, seen, filename, "logo")

    return images or None


def _try_add(images: list[dict], seen: set[str], filename: str, kind: str) -> None:
    """Canonicalize, dedupe, and append a qualifying image entry."""
    canonical = filename.replace(" ", "_")
    if canonical in seen:
        return
    seen.add(canonical)
    entry = _make_entry(canonical, kind)
    if entry:
        images.append(entry)


def _make_entry(filename: str, kind: str) -> dict | None:
    """Create an image metadata entry if the file passes all export gates."""
    if not (_THUMB_DIR / filename).exists() and not (_FULL_DIR / filename).exists():
        logger.info("Dropping image (not on disk): %s", filename)
        return None

    attribution = _load_attribution(filename)
    if attribution is None:
        return None  # reason already logged

    return {
        "file": filename,
        "source_url": f"https://commons.wikimedia.org/wiki/File:{quote(filename)}",
        "kind": kind,
        **attribution,
    }


def _load_attribution(filename: str) -> dict | None:
    """Load metadata, enforce license policy, and return attribution fields.

    Returns ``None`` if the image must be dropped (missing/corrupt metadata, or
    the license fails our acceptance rules). Otherwise returns a dict with
    ``license``, ``license_url``, and ``artist`` (any of which may be missing
    from the source, but ``license`` is always present).
    """
    meta_path = _METADATA_DIR / f"{filename}.json"
    if not meta_path.exists():
        logger.info("Dropping image (no Commons metadata): %s", filename)
        return None

    try:
        meta = orjson.loads(meta_path.read_bytes())
    except orjson.JSONDecodeError:
        logger.warning("Dropping image (corrupt metadata): %s", filename)
        return None

    em = (meta.get("imageinfo") or {}).get("extmetadata") or {}

    license_tag = _pick_license(em, filename)
    if license_tag is None:
        return None

    attribution: dict = {"license": license_tag}
    license_url = _plain_str(em.get("LicenseUrl"))
    if license_url:
        attribution["license_url"] = license_url
    artist = _plain_text(em.get("Artist")) or _plain_text(em.get("Credit"))
    if artist:
        attribution["artist"] = artist
    return attribution


def _pick_license(em: dict, filename: str) -> str | None:
    """Return the license tag to attribute under, or None to drop.

    For multi-licensed images (``LicenseShortName`` contains ``" or "``) we
    prefer a non-GFDL tag — serving a CC side avoids the GFDL-specific
    obligation to ship the full license text.
    """
    short_value = _plain_str(em.get("LicenseShortName"))
    if not short_value:
        logger.info("Dropping image (no LicenseShortName): %s", filename)
        return None

    tags = [t.strip() for t in short_value.split(" or ") if t.strip()]
    acceptable = [t for t in tags if _is_acceptable(t)]
    if not acceptable:
        logger.info(
            "Dropping image (unacceptable license %r): %s", short_value, filename
        )
        return None

    non_gfdl = [t for t in acceptable if "gfdl" not in t.lower()]
    if not non_gfdl:
        logger.info("Dropping image (GFDL-only license %r): %s", short_value, filename)
        return None
    return non_gfdl[0]


def _is_acceptable(short_name: str) -> bool:
    """True if a single LicenseShortName tag is one we're willing to serve."""
    lower = short_name.lower()
    return not any(kw in lower for kw in _DENIED_LICENSE_KEYWORDS)


def _plain_str(field: dict | None) -> str | None:
    """Return the plain string value of a non-HTML extmetadata field."""
    if not isinstance(field, dict):
        return None
    value = field.get("value")
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _plain_text(field: dict | None) -> str | None:
    """Return HTML-stripped, entity-decoded text from an extmetadata field.

    Handles the string form and the multilang ``{"_type": "lang", "en": ...}``
    form the Commons API returns when ``iiextmetadatamultilang=1`` is set.
    """
    if not isinstance(field, dict):
        return None
    value = field.get("value")
    if isinstance(value, dict):
        # Prefer English; otherwise pick any language entry.
        value = value.get("en") or next(
            (v for k, v in value.items() if k != "_type" and isinstance(v, str)),
            None,
        )
    if not isinstance(value, str):
        return None
    text = html.unescape(_HTML_TAG_RE.sub("", value))
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text or None
