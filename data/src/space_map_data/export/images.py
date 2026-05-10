"""Per-object image list + thumbnail/metadata generation for export.

Reads source images and their pre-decided license servability from the
``DOWNLOAD_DIR/commons/images/<filename>/`` layout, then writes an export-side bundle
for each servable image::

    EXPORT_DIR/v1/images/<filename>/s.<ext>     # 512px (webp/avif, or verbatim jpg)
    EXPORT_DIR/v1/images/<filename>/m.<ext>     # 1024px (when source is larger)
    EXPORT_DIR/v1/images/<filename>/xl.<ext>    # 4096px (when source is larger)
    EXPORT_DIR/v1/images/<filename>/metadata.json.gz

Size buckets and bucket extensions follow these rules:
- Passthrough sources (svg, webm) are copied verbatim to ``xl.<ext>``
  when under the 25 MiB Cloudflare Pages per-file cap. SVG is a vector
  that scales to any dimension; WebM is forward-compatible (the frontend
  doesn't render video in ``<img>`` today but the file is available for
  when it does).
- Unshippable formats (pdf, stl, djvu) are skipped entirely — nothing
  useful as a thumbnail and browsers can't render them as images.
- Animated sources (GIFs with multiple frames) are encoded as animated AVIF
  at every emitted bucket, preserving frames and timing.
- Non-animated lossy sources (jpg/jpeg) emit lossy webp for downscaled
  buckets and are copied verbatim at the resting bucket (re-encoding lossy
  just degrades further).
- Non-animated lossless sources (png, etc.) emit lossy webp at every bucket,
  including the resting bucket — one lossless→lossy re-encode is visually
  equivalent to encoding from the original and avoids shipping multi-MiB
  PNGs verbatim.
- The resting bucket is the first bucket whose target dim is ≥ the source's
  largest dim. Buckets above it are not emitted (no upscaling).

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
from PIL import Image, ImageFile, ImageSequence

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

# Wikimedia Commons is a curated, trusted source. Disable Pillow's
# decompression-bomb guard so legitimate large images (e.g. 180-megapixel
# logos on Commons) don't get dropped as "possible DoS".
Image.MAX_IMAGE_PIXELS = None

# Be permissive about mildly-malformed sources. Wikimedia Commons has a
# handful of JPGs with missing trailing bytes and PNGs with truncated
# chunks; rather than dropping them we accept the partial decode. Using
# setattr because the PIL stubs type this attribute as Literal[False].
setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", True)

logger = logging.getLogger(__name__)

_EXPORT_IMAGES_DIR = EXPORT_DIR / "v1" / "images"

# Lossy-source formats: stay verbatim at the resting bucket (re-encoding would
# just degrade further). Anything else we treat as lossless and re-encode to
# lossy webp, including at the resting bucket — one lossless→lossy step is
# visually equivalent to encoding from the original source and saves a lot of
# bytes (e.g. 36 MiB PNGs that fit under the xl bucket used to ship verbatim).
_LOSSY_EXTENSIONS = {".jpg", ".jpeg"}

# Formats served verbatim at the xl label without decoding. SVG is a
# vector (scales to any dimension). WebM is a video the frontend doesn't
# render in <img> today but is forward-compatible when video support lands.
# Size-capped at the Cloudflare Pages per-file limit so oversize sources
# still get dropped rather than breaking the deploy.
_PASSTHROUGH_EXTENSIONS = {".svg", ".webm"}
_PASSTHROUGH_MAX_BYTES = 25 * 1024 * 1024

# Formats we never ship: can't render in <img>, not useful as a thumbnail,
# and not worth shipping just to sit in the bundle.
_SKIP_EXTENSIONS = {".pdf", ".stl", ".djvu"}

# Bucket label → max dim (in pixels, on the longest side).
_BUCKETS: tuple[tuple[str, int], ...] = (
    ("s", 512),
    ("m", 1024),
    ("xl", 4096),
)

_ANIMATED_AVIF_QUALITY = 55
_ANIMATED_AVIF_SPEED = 6

# Formats where multiple frames mean "animation". PIL exposes is_animated /
# n_frames for other multi-frame formats too (MPO stereoscopic JPEGs, multi-
# page TIFFs), but those aren't real animation and trying to iterate their
# frames can fail with "No data found for frame".
_ANIMATED_FORMATS = {"GIF", "WEBP", "PNG"}

# Bump when the variant-emission rules change (new encoder, new bucket sizes,
# dropped/added formats). Existing bundles whose metadata.json.gz carries an
# older schema are wiped and regenerated on the next export.
_BUNDLE_SCHEMA = 3

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
        bundle = _ensure_bundle(filename)
    except Exception as exc:
        logger.error("Failed to build export bundle for %s: %s", filename, exc)
        return None
    if not bundle.get("variants"):
        return None

    entry: dict = {
        "file": filename,
        "source_url": f"https://commons.wikimedia.org/wiki/File:{quote(filename)}",
        "kind": kind,
        "variants": bundle["variants"],
    }
    if bundle.get("width") and bundle.get("height"):
        entry["width"] = bundle["width"]
        entry["height"] = bundle["height"]
    return entry


def _ensure_bundle(filename: str) -> dict:
    """Generate (if missing) and return the export bundle for an image.

    Returns a dict with ``variants`` (``{label: ext}`` of emitted size buckets)
    and, when the source is a raster format we decoded, ``width`` and ``height``
    (source pixel dimensions on the longest/shortest axes). Passthrough sources
    (SVG/WebM) and skipped formats may be missing dimensions.

    ``metadata.json.gz`` doubles as the completion marker: once it exists with
    a current ``schema`` the bundle is trusted and its embedded ``variants`` /
    dimensions are returned. Bundles written under an older schema are wiped
    and regenerated.
    """
    out_dir = _EXPORT_IMAGES_DIR / filename
    metadata_path = out_dir / "metadata.json.gz"

    with _file_lock(filename):
        if metadata_path.exists():
            existing = orjson.loads(gzip.decompress(metadata_path.read_bytes()))
            if existing.get("schema") == _BUNDLE_SCHEMA:
                return {
                    "variants": existing.get("variants") or {},
                    "width": existing.get("width"),
                    "height": existing.get("height"),
                }
            logger.info(
                "Regenerating stale image bundle %s (schema %s → %s)",
                filename,
                existing.get("schema"),
                _BUNDLE_SCHEMA,
            )
            _wipe_bundle_dir(out_dir)

        out_dir.mkdir(parents=True, exist_ok=True)
        variants, dims = _generate_variants(filename, out_dir)
        if variants:
            _write_trimmed_metadata(filename, out_dir, variants, dims)
        return {
            "variants": variants,
            "width": dims[0] if dims else None,
            "height": dims[1] if dims else None,
        }


def _wipe_bundle_dir(out_dir: Path) -> None:
    """Remove every regular file in the per-image bundle directory."""
    for entry in out_dir.iterdir():
        if entry.is_file() or entry.is_symlink():
            entry.unlink()


def _generate_variants(
    filename: str, out_dir: Path
) -> tuple[dict[str, str], tuple[int, int] | None]:
    """Write s/m/xl output files.

    Returns ``(variants, dims)`` where ``variants`` is the ``{label: ext}`` map
    of emitted buckets and ``dims`` is ``(width, height)`` of the decoded source
    raster — ``None`` for passthrough/skipped sources where we never opened a
    raster. Dimensions match the source, not the variant; PhotoSwipe/clients
    use them only for aspect ratio.
    """
    src = source_path(filename)
    src_ext = src.suffix.lower()

    if src_ext in _SKIP_EXTENSIONS:
        logger.debug("Skipping unshippable format %s: %s", src_ext, filename)
        return {}, None

    if src_ext in _PASSTHROUGH_EXTENSIONS:
        size = src.stat().st_size
        if size > _PASSTHROUGH_MAX_BYTES:
            logger.info(
                "Skipping oversize %s passthrough (%d bytes > %d): %s",
                src_ext,
                size,
                _PASSTHROUGH_MAX_BYTES,
                filename,
            )
            return {}, None
        ext = src_ext.lstrip(".")
        target = out_dir / f"xl.{ext}"
        if not target.exists():
            _atomic_copy(src, target)
        return {"xl": ext}, None

    try:
        img = Image.open(src)
        img.load()
    except Exception as exc:
        logger.warning("Skipping unreadable image %s: %s", filename, exc)
        return {}, None

    source_max = max(img.width, img.height)
    dims = (img.width, img.height)
    lossy_source = src_ext in _LOSSY_EXTENSIONS
    animated = (
        img.format in _ANIMATED_FORMATS
        and getattr(img, "is_animated", False)
        and getattr(img, "n_frames", 1) > 1
    )

    variants: dict[str, str] = {}
    for label, dim in _BUCKETS:
        out_stem = out_dir / label
        if dim < source_max:
            ext = "avif" if animated else "webp"
            target = out_stem.with_suffix(f".{ext}")
            if not target.exists():
                if animated:
                    _write_animated_avif(img, dim, target)
                else:
                    _write_webp(img, dim, target)
            variants[label] = ext
            continue

        # Resting bucket: source fits within this size. We stop after writing
        # it (no upscaled variants above).
        if animated:
            ext = "avif"
            target = out_stem.with_suffix(f".{ext}")
            if not target.exists():
                _write_animated_avif(img, dim, target)
        elif lossy_source:
            ext = src_ext.lstrip(".")
            target = out_stem.with_suffix(f".{ext}")
            if not target.exists():
                _atomic_copy(src, target)
        else:
            ext = "webp"
            target = out_stem.with_suffix(f".{ext}")
            if not target.exists():
                _write_webp(img, dim, target)
        variants[label] = ext
        break

    img.close()
    return variants, dims


def _output_exists(stem: Path, ext: str) -> bool:
    return stem.with_suffix(f".{ext}").exists()


def _write_webp(img: Image.Image, max_dim: int, target: Path) -> None:
    """Resize (preserving aspect) to ``max_dim`` on the longest side and save as lossy webp."""
    w, h = img.size
    if max_dim < max(w, h):
        scale = max_dim / max(w, h)
        resized = img.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS
        )
    else:
        resized = img

    to_save = resized.convert("RGBA") if resized.mode in ("P", "LA") else resized
    if to_save.mode == "RGBA":
        # Flatten transparency against black to avoid halo artifacts at low quality.
        to_save = to_save.convert("RGB")

    tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    to_save.save(tmp, "webp", quality=80)
    tmp.rename(target)

    if resized is not img:
        resized.close()


def _write_animated_avif(img: Image.Image, max_dim: int, target: Path) -> None:
    """Iterate frames of an animated image, resize each, save as animated AVIF."""
    frames: list[Image.Image] = []
    durations: list[int] = []
    for frame in ImageSequence.Iterator(img):
        f = frame.convert("RGBA")
        if max_dim < max(f.size):
            scale = max_dim / max(f.size)
            f = f.resize(
                (max(1, int(f.width * scale)), max(1, int(f.height * scale))),
                Image.Resampling.LANCZOS,
            )
        frames.append(f)
        durations.append(frame.info.get("duration", 100))

    tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    frames[0].save(
        tmp,
        "AVIF",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=img.info.get("loop", 0),
        quality=_ANIMATED_AVIF_QUALITY,
        speed=_ANIMATED_AVIF_SPEED,
    )
    tmp.rename(target)


def _atomic_copy(src: Path, dst: Path) -> None:
    """Copy ``src`` to ``dst`` via a temp file + rename. Atomic within a filesystem."""
    tmp = dst.with_name(f".{dst.name}.{uuid.uuid4().hex}.tmp")
    shutil.copyfile(src, tmp)
    tmp.rename(dst)


def _write_trimmed_metadata(
    filename: str,
    out_dir: Path,
    variants: dict[str, str],
    dims: tuple[int, int] | None,
) -> None:
    """Write the frontend-facing per-image metadata (gzipped JSON).

    Trimmed to the subset the frontend actually consumes:

    - ``variants``: ``{label: ext}`` map of emitted size buckets
    - ``width``/``height``: source pixel dimensions when known (omitted for
      passthrough sources that never went through PIL)
    - ``license``: ``{"name", "url"}`` from extmetadata LicenseShortName + LicenseUrl
    - ``artist``, ``description``: multilang-capable fields, restricted to
      supported locales (with bare strings passed through unchanged)
    - ``source_url``: Commons page URL (constructible client-side, but cheap
      to include here)
    """
    raw = orjson.loads(download_metadata_path(filename).read_bytes())
    em = (raw.get("imageinfo") or {}).get("extmetadata") or {}

    payload: dict = {
        "schema": _BUNDLE_SCHEMA,
        "source_url": f"https://commons.wikimedia.org/wiki/File:{quote(filename)}",
        "variants": variants,
    }
    if dims:
        payload["width"], payload["height"] = dims
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
