"""Per-object image list + thumbnail/metadata generation for export.

Reads source images and their pre-decided license servability from the new
``DOWNLOAD_DIR/images/<filename>/`` layout, then writes an export-side bundle
for each servable image::

    EXPORT_DIR/v1/images/<filename>/s.<ext>     # 512px webp or verbatim source
    EXPORT_DIR/v1/images/<filename>/m.<ext>     # 1024px (when source is larger)
    EXPORT_DIR/v1/images/<filename>/xl.<ext>    # 4096px (when source is larger)
    EXPORT_DIR/v1/images/<filename>/metadata.json.gz

Size buckets and bucket extensions follow these rules:
- For every bucket `T` strictly smaller than `max(source_width, source_height)`,
  emit a webp downscaled to `T`.
- At most one bucket is "the resting place" — the first bucket whose target
  dim is ≥ the source's largest dim. It carries the source verbatim (same
  extension, no downscale) unless the source is a lossless format and the
  bucket's target exactly matches `max(w, h)`, in which case we convert to
  lossless webp (smaller file, no quality loss).
- Buckets above the resting place are not emitted (no upscaling).

``metadata.json.gz`` embeds the ``variants`` map (``{label: ext}``) alongside
the license/artist/description fields and doubles as the completion marker —
no separate variants.json is written.
"""

import gzip
import logging
import shutil
import threading
import uuid
from pathlib import Path
from urllib.parse import quote

import orjson
from PIL import Image

from space_map_data.constants.providers import LANGUAGES
from space_map_data.utils.commons_images import (
    IMAGES_DIR as DOWNLOADS_IMAGES_DIR,
    canonical_filename,
    download_metadata_path,
    is_excluded,
    is_servable_on_disk,
    source_path,
)
from space_map_data.utils.paths import EXPORT_DIR

logger = logging.getLogger(__name__)

_EXPORT_IMAGES_DIR = EXPORT_DIR / "v1" / "images"

# Lossy-source formats: stay verbatim at the resting bucket (re-encoding would
# just degrade further). Anything else we treat as lossless and re-encode to
# webp when it exactly fills a bucket, since lossless webp usually beats the
# source on size with zero quality cost.
_LOSSY_EXTENSIONS = {".jpg", ".jpeg"}

# Bucket label → max dim (in pixels, on the longest side).
_BUCKETS: tuple[tuple[str, int], ...] = (
    ("s", 512),
    ("m", 1024),
    ("xl", 4096),
)

# Per-filename locks so two chunk-writer threads never race on the same image.
# Serializes work on a single file (lock held across PIL save + rename) while
# leaving different files free to parallelize. The lock dict's own mutations
# are protected by ``_FILE_LOCKS_GUARD``.
_FILE_LOCKS: dict[str, threading.Lock] = {}
_FILE_LOCKS_GUARD = threading.Lock()


def _file_lock(filename: str) -> threading.Lock:
    with _FILE_LOCKS_GUARD:
        lock = _FILE_LOCKS.get(filename)
        if lock is None:
            lock = threading.Lock()
            _FILE_LOCKS[filename] = lock
        return lock


def collect_object_images(
    extracted: dict,
    wiki_image_filenames: list[str],
) -> list[dict] | None:
    """Build the ``images`` array for a single object's global JSON.

    Collects images from:
    - Wikidata P18 (``extracted["image"]``) — kind=photo
    - Wikipedia pageimages from all languages — kind=photo
    - Wikidata P154 (``extracted["logo_image"]``) — kind=logo

    Deduplicates by canonical (underscore-form) filename, filters out images
    whose license isn't servable (decided at download time), and as a side
    effect ensures the per-image thumbnail/metadata bundle exists under
    ``EXPORT_DIR/v1/images/<filename>/``. Returns ``None`` if no images
    qualify.
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
    name = canonical_filename(filename)
    if name in seen:
        return
    seen.add(name)
    if is_excluded(name):
        logger.debug("Skipping excluded-prefix image: %s", name)
        return
    entry = _make_entry(name, kind)
    if entry:
        images.append(entry)


def _make_entry(filename: str, kind: str) -> dict | None:
    """Ensure the export bundle exists, then return a global-object-data entry."""
    if not source_path(filename).exists():
        logger.info("Dropping image (source missing): %s", filename)
        return None
    if not is_servable_on_disk(filename):
        return None  # already logged at download time and/or in ensure_bundle

    try:
        variants = _ensure_bundle(filename)
    except Exception as exc:
        logger.error("Failed to build export bundle for %s: %s", filename, exc)
        return None
    if not variants:
        return None

    return {
        "file": filename,
        "source_url": f"https://commons.wikimedia.org/wiki/File:{quote(filename)}",
        "kind": kind,
        "variants": variants,
    }


def _ensure_bundle(filename: str) -> dict[str, str]:
    """Generate (if missing) and return the export bundle for an image.

    Returns a ``{label: extension}`` map describing the emitted variants
    (without a leading dot — e.g. ``{"s": "webp", "m": "webp", "xl": "jpg"}``).
    ``metadata.json.gz`` doubles as the completion marker: once it exists the
    bundle is trusted and its embedded ``variants`` block is returned. Wipe
    the per-image directory to force regeneration after schema changes.
    """
    out_dir = _EXPORT_IMAGES_DIR / filename
    metadata_path = out_dir / "metadata.json.gz"

    with _file_lock(filename):
        if metadata_path.exists():
            existing = orjson.loads(gzip.decompress(metadata_path.read_bytes()))
            return existing.get("variants") or {}

        out_dir.mkdir(parents=True, exist_ok=True)
        variants = _generate_variants(filename, out_dir)
        if variants:
            _write_trimmed_metadata(filename, out_dir, variants)
        return variants


def _generate_variants(filename: str, out_dir: Path) -> dict[str, str]:
    """Write s/m/xl output files. Returns the {label: ext} map emitted."""
    src = source_path(filename)
    src_ext = src.suffix.lower()

    try:
        img = Image.open(src)
        img.load()
    except Exception as exc:
        logger.warning("Skipping unreadable image %s: %s", filename, exc)
        return {}

    source_max = max(img.width, img.height)
    lossy = src_ext in _LOSSY_EXTENSIONS

    variants: dict[str, str] = {}
    for label, dim in _BUCKETS:
        out_stem = out_dir / label
        if dim < source_max:
            ext = "webp"
            if not _output_exists(out_stem, ext):
                _write_webp(img, dim, out_stem.with_suffix(f".{ext}"))
            variants[label] = ext
            continue

        # Resting bucket: source fits within this size. We stop after writing
        # it (no upscaled variants above).
        if lossy or dim != source_max:
            ext = src_ext.lstrip(".")
            target = out_stem.with_suffix(f".{ext}")
            if not target.exists():
                _atomic_copy(src, target)
        else:
            ext = "webp"
            target = out_stem.with_suffix(f".{ext}")
            if not target.exists():
                _write_webp(img, dim, target, lossless=True)
        variants[label] = ext
        break

    img.close()
    return variants


def _output_exists(stem: Path, ext: str) -> bool:
    return stem.with_suffix(f".{ext}").exists()


def _write_webp(
    img: Image.Image, max_dim: int, target: Path, *, lossless: bool = False
) -> None:
    """Resize (preserving aspect) to ``max_dim`` on the longest side and save as webp."""
    w, h = img.size
    if max_dim < max(w, h):
        scale = max_dim / max(w, h)
        resized = img.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS
        )
    else:
        resized = img

    to_save = resized.convert("RGBA") if resized.mode in ("P", "LA") else resized
    if to_save.mode == "RGBA" and not lossless:
        # Flatten transparency against black for lossy webp to avoid
        # halo artifacts at low quality.
        to_save = to_save.convert("RGB")

    tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    kwargs = {"lossless": True, "method": 6} if lossless else {"quality": 80}
    to_save.save(tmp, "webp", **kwargs)
    tmp.rename(target)

    if resized is not img:
        resized.close()


def _atomic_copy(src: Path, dst: Path) -> None:
    """Copy ``src`` to ``dst`` via a temp file + rename. Atomic within a filesystem."""
    tmp = dst.with_name(f".{dst.name}.{uuid.uuid4().hex}.tmp")
    shutil.copyfile(src, tmp)
    tmp.rename(dst)


def _write_trimmed_metadata(
    filename: str, out_dir: Path, variants: dict[str, str]
) -> None:
    """Write the frontend-facing per-image metadata (gzipped JSON).

    Trimmed to the subset the frontend actually consumes:

    - ``variants``: ``{label: ext}`` map of emitted size buckets
    - ``license``: ``{"name", "url"}`` from extmetadata LicenseShortName + LicenseUrl
    - ``artist``, ``description``: multilang-capable fields, restricted to
      supported locales (with bare strings passed through unchanged)
    - ``source_url``: Commons page URL (constructible client-side, but cheap
      to include here)
    """
    raw = orjson.loads(download_metadata_path(filename).read_bytes())
    em = (raw.get("imageinfo") or {}).get("extmetadata") or {}

    payload: dict = {
        "source_url": f"https://commons.wikimedia.org/wiki/File:{quote(filename)}",
        "variants": variants,
    }
    license_block = _license_block(em)
    if license_block:
        payload["license"] = license_block
    artist = _locale_field(em.get("Artist") or em.get("Credit"))
    if artist:
        payload["artist"] = artist
    description = _locale_field(em.get("ImageDescription"))
    if description:
        payload["description"] = description

    target = out_dir / "metadata.json.gz"
    tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_bytes(gzip.compress(orjson.dumps(payload)))
    tmp.rename(target)


def _license_block(em: dict) -> dict | None:
    """Extract ``{name, url}`` from extmetadata, dropping empty values."""
    name = (em.get("LicenseShortName") or {}).get("value")
    url = (em.get("LicenseUrl") or {}).get("value")
    out: dict = {}
    if isinstance(name, str) and name.strip():
        out["name"] = name.strip()
    if isinstance(url, str) and url.strip():
        out["url"] = url.strip()
    return out or None


def _locale_field(field: dict | None) -> str | dict[str, str] | None:
    """Normalize a Commons multilang-or-string extmetadata field.

    - Bare strings pass through unchanged (no locale structure in the source).
    - Multilang dicts are restricted to supported locales; ``_type`` is dropped.
    - Empty results collapse to None.
    """
    if not field:
        return None
    value = field.get("value")
    if isinstance(value, str):
        s = value.strip()
        return s or None
    if isinstance(value, dict):
        trimmed = {
            k: v.strip()
            for k, v in value.items()
            if k in LANGUAGES and isinstance(v, str) and v.strip()
        }
        return trimmed or None
    return None


def clear_export_cache() -> None:
    """Reset the per-filename lock registry. For tests that monkeypatch paths."""
    with _FILE_LOCKS_GUARD:
        _FILE_LOCKS.clear()


# --- Sanity helpers for tests / migration --------------------------------


def export_image_dir(filename: str) -> Path:
    """Directory under EXPORT_DIR/v1/images/ that holds variants+metadata for a file."""
    return _EXPORT_IMAGES_DIR / filename


def downloaded_source_exists(filename: str) -> bool:
    """Convenience wrapper for ``source_path(filename).exists()``."""
    return source_path(filename).exists()


__all__ = [
    "collect_object_images",
    "clear_export_cache",
    "export_image_dir",
    "downloaded_source_exists",
    "DOWNLOADS_IMAGES_DIR",
]
