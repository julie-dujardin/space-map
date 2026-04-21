"""Collect and resolve image metadata for object export."""

import logging
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

# Filename prefixes we intentionally skip at download time — auto-generated
# orbit diagrams from ru.wiki that aren't hosted on Commons. Mirrored here so
# references to them in Wikidata claims don't produce "not on disk" warnings
# every export run. Keep in sync with commons.py's download-side constant.
_EXCLUDED_IMAGE_PREFIXES = ("Орбита_астероида_", "Орбита_кометы_")


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
    unknown or non-redistributable. Attribution fields (artist, license,
    description, ...) are *not* emitted here — the per-image metadata JSON
    under ``images/metadata/`` is the single source of truth and the frontend
    loads it lazily when opening the image.

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
    if any(canonical.startswith(p) for p in _EXCLUDED_IMAGE_PREFIXES):
        logger.debug("Skipping excluded-prefix image: %s", canonical)
        return
    entry = _make_entry(canonical, kind)
    if entry:
        images.append(entry)


def _make_entry(filename: str, kind: str) -> dict | None:
    """Create an image metadata entry if the file passes all export gates."""
    if not (_THUMB_DIR / filename).exists() and not (_FULL_DIR / filename).exists():
        logger.info("Dropping image (not on disk): %s", filename)
        return None

    if not _license_is_servable(filename):
        return None  # reason already logged

    return {
        "file": filename,
        "source_url": f"https://commons.wikimedia.org/wiki/File:{quote(filename)}",
        "kind": kind,
    }


def _license_is_servable(filename: str) -> bool:
    """Check that the Commons metadata exists and carries an acceptable license.

    Short-circuits to False on missing / corrupt metadata or a disallowed /
    GFDL-only / empty ``LicenseShortName``. For multi-licensed images
    (``LicenseShortName`` contains ``" or "``) we prefer a non-GFDL tag —
    serving a CC side avoids the GFDL-specific obligation to ship the full
    license text.
    """
    meta_path = _METADATA_DIR / f"{filename}.json"
    if not meta_path.exists():
        logger.info("Dropping image (no Commons metadata): %s", filename)
        return False

    try:
        meta = orjson.loads(meta_path.read_bytes())
    except orjson.JSONDecodeError:
        logger.warning("Dropping image (corrupt metadata): %s", filename)
        return False

    em = (meta.get("imageinfo") or {}).get("extmetadata") or {}
    short_value = (em.get("LicenseShortName") or {}).get("value")
    if not isinstance(short_value, str) or not short_value.strip():
        logger.info("Dropping image (no LicenseShortName): %s", filename)
        return False

    tags = [t.strip() for t in short_value.split(" or ") if t.strip()]
    acceptable = [t for t in tags if _is_acceptable(t)]
    if not acceptable:
        logger.info(
            "Dropping image (unacceptable license %r): %s", short_value, filename
        )
        return False

    non_gfdl = [t for t in acceptable if "gfdl" not in t.lower()]
    if not non_gfdl:
        logger.info("Dropping image (GFDL-only license %r): %s", short_value, filename)
        return False
    return True


def _is_acceptable(short_name: str) -> bool:
    """True if a single LicenseShortName tag is one we're willing to serve."""
    lower = short_name.lower()
    return not any(kw in lower for kw in _DENIED_LICENSE_KEYWORDS)
