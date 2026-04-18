"""Collect and resolve image metadata for object export."""

import logging
from urllib.parse import quote

from space_map_data.utils.paths import EXPORT_DIR

logger = logging.getLogger(__name__)

_IMAGES_DIR = EXPORT_DIR / "v1" / "images"


def collect_object_images(
    extracted: dict,
    wiki_image_filenames: list[str],
) -> list[dict] | None:
    """Build the ``images`` array for a single object's global JSON.

    Collects images from:
    - Wikidata P18 (``extracted["image"]``) — kind=photo
    - Wikipedia pageimages from all languages — kind=photo
    - Wikidata P154 (``extracted["logo_image"]``) — kind=logo

    Deduplicates by filename.  Only includes images whose thumbnail file
    exists on disk (downloaded by CommonsDownloader).

    Returns None if no images are available.
    """
    seen: set[str] = set()
    images: list[dict] = []

    # P18 images first (primary editorial choice)
    for filename in extracted.get("image", []):
        if filename in seen:
            continue
        seen.add(filename)
        entry = _make_entry(filename, "photo")
        if entry:
            images.append(entry)

    # Wikipedia pageimages from all languages (often same as P18, deduped)
    for filename in wiki_image_filenames:
        if filename in seen:
            continue
        seen.add(filename)
        entry = _make_entry(filename, "photo")
        if entry:
            images.append(entry)

    # P154 logos last
    for filename in extracted.get("logo_image", []):
        if filename in seen:
            continue
        seen.add(filename)
        entry = _make_entry(filename, "logo")
        if entry:
            images.append(entry)

    return images or None


def _make_entry(filename: str, kind: str) -> dict | None:
    """Create an image metadata entry if the thumbnail file exists on disk."""
    thumb_path = _IMAGES_DIR / "thumb" / filename
    if not thumb_path.exists():
        logger.debug("Image not found on disk: %s", filename)
        return None
    return {
        "file": f"images/thumb/{filename}",
        "source_url": f"https://commons.wikimedia.org/wiki/File:{quote(filename)}",
        "kind": kind,
    }
