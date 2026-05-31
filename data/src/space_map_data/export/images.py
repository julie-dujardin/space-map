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
import re
import shutil
import threading
import uuid
from collections import deque
from pathlib import Path
from urllib.parse import quote

import orjson
from PIL import Image, ImageFile, ImageSequence

from space_map_data.constants.providers import LANGUAGES
from space_map_data.utils.commons_images import (
    IMAGES_DIR as DOWNLOADS_IMAGES_DIR,
    canonical_filename,
    is_excluded,
    is_servable_on_disk,
    read_download_metadata,
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
# dropped/added formats) OR the metadata payload gains/drops fields. Existing
# bundles whose metadata.json.gz carries an older schema are wiped and
# regenerated on the next export.
_BUNDLE_SCHEMA = 4

# P571 inception precision codes we accept. Wikidata uses the WikibaseTime
# precision enum: 11=day, 10=month, 9=year, lower=decade/century/millennium
# etc. Anything coarser than year isn't useful for an image creation date.
_TIME_PRECISION_DAY = 11
_TIME_PRECISION_MONTH = 10
_TIME_PRECISION_YEAR = 9

# Matches a leading date in extmetadata DateTimeOriginal: "2009-10-05",
# "2012-09-23 16:26:36", "1999". The trailing time (if any) is dropped.
_DATETIME_ORIGINAL_RE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?")

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


def collect_object_images(object_id: str) -> list[dict] | None:
    """Build the ``images`` array for a single object's global JSON.

    Reads the pre-computed selection from
    ``DOWNLOAD_DIR/commons/object_images.json`` (written by the
    ``image_selection`` ingest provider) and turns each entry into an
    export bundle with thumbnails. Discovery, derivative-tree expansion,
    and best-of-tree scoring all happen at ingest time — this function
    just renders.

    Returns ``None`` when the cache has no entries for ``object_id`` (or
    has not been generated). Excluded-prefix names, missing source bytes,
    and non-servable licenses are filtered defensively.
    """
    selections = _object_images_cache().get(object_id) or []
    out: list[dict] = []
    for entry in selections:
        name = canonical_filename(entry["file"])
        if is_excluded(name):
            logger.debug("Skipping excluded-prefix image: %s", name)
            continue
        bundle_entry = _make_entry(name, entry.get("kind", "photo"))
        if bundle_entry:
            out.append(bundle_entry)
    return out or None


def _object_images_cache() -> dict[str, list[dict]]:
    """Lazy-load and cache ``object_images.json`` for the export run."""
    global _OBJECT_IMAGES_CACHE
    if _OBJECT_IMAGES_CACHE is None:
        # Imported here to avoid pulling the ingest package at module load
        # (export is otherwise independent of ingest).
        from space_map_data.ingest.providers.image_selection import (
            read_object_images,
        )

        _OBJECT_IMAGES_CACHE = read_object_images()
        if not _OBJECT_IMAGES_CACHE:
            logger.warning(
                "object_images.json missing or empty — run `space-map-ingest "
                "--targets images` first; export will emit no images"
            )
    return _OBJECT_IMAGES_CACHE


_OBJECT_IMAGES_CACHE: dict[str, list[dict]] | None = None


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
      supported locales (with bare strings passed through unchanged). Both
      are aggregated across the chosen file's derivative tree — the chosen
      file's value is the default, and tree members fill in missing entries
      (per-locale for multilang dicts), so a French derivative's French
      description survives when the English original lacked one.
    - ``date``: ISO-truncated creation date (``YYYY-MM-DD`` / ``YYYY-MM`` /
      ``YYYY``). Prefers SDC P571 ``inception`` (truncated by precision) and
      falls back to extmetadata ``DateTimeOriginal`` text. Tree-aggregated
      with chosen-file priority.
    - ``depicts``: list of Wikidata QIDs from SDC P180. Tree-aggregated only
      when the chosen file has no depicts of its own — derivatives can have
      different framing, so we don't merge.
    - ``source_url``: Commons page URL (constructible client-side, but cheap
      to include here)

    License stays tied to the chosen file: it describes the bytes we
    actually serve, so a derivative's license can't substitute.
    """
    base = read_download_metadata(filename) or {}
    base_em = (base.get("imageinfo") or {}).get("extmetadata") or {}

    payload: dict = {
        "schema": _BUNDLE_SCHEMA,
        "source_url": f"https://commons.wikimedia.org/wiki/File:{quote(filename)}",
        "variants": variants,
    }
    if dims:
        payload["width"], payload["height"] = dims
    license_block = _license_block(base_em)
    if license_block:
        payload["license"] = license_block

    artist, description, date, depicts = _aggregate_tree_metadata(filename, base)
    if artist:
        payload["artist"] = artist
    if description:
        payload["description"] = description
    if date:
        payload["date"] = date
    if depicts:
        payload["depicts"] = depicts

    target = out_dir / "metadata.json.gz"
    tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_bytes(gzip.compress(orjson.dumps(payload)))
    tmp.rename(target)


def _aggregate_tree_metadata(
    filename: str, base_meta: dict
) -> tuple[
    str | dict[str, str] | None,
    str | dict[str, str] | None,
    str | None,
    list[str],
]:
    """Walk the derivative tree once and aggregate the fields we export.

    Returns ``(artist, description, date, depicts)``. Chosen-file values
    take precedence; tree members reachable via ``derived_from`` /
    ``other_versions`` provide fallbacks. ``artist`` and ``description``
    fall back per-locale on multilang dicts; ``date`` and ``depicts`` use
    whole-value fallback (the chosen file wins outright if it has any
    value at all). BFS from the chosen file means closer derivatives are
    visited first and win the fallback race over distant ones.
    """
    artist: str | dict[str, str] | None = None
    description: str | dict[str, str] | None = None
    date: str | None = None
    depicts: list[str] = []
    for idx, name in enumerate(_walk_tree(filename)):
        meta = base_meta if idx == 0 else read_download_metadata(name)
        if not meta:
            continue
        em = (meta.get("imageinfo") or {}).get("extmetadata") or {}
        artist = _merge_locale_field(
            artist, _locale_field(em.get("Artist") or em.get("Credit"))
        )
        description = _merge_locale_field(
            description, _locale_field(em.get("ImageDescription"))
        )
        if date is None:
            date = _extract_date(meta, em)
        if not depicts:
            depicts = _extract_depicts(meta)
    return artist, description, date, depicts


def _extract_date(meta: dict, em: dict) -> str | None:
    """Best-available creation date for an image, ISO-truncated to known precision.

    Prefers SDC P571 (structured time + precision) so we don't dress up a
    year-only inception as a fake day. Falls back to extmetadata
    ``DateTimeOriginal``, which is free-form text but usually starts with a
    parseable ISO-ish date.
    """
    for stmt in _sdc_statements(meta, "P571"):
        snak = stmt.get("mainsnak") or {}
        if snak.get("snaktype") != "value":
            continue
        value = (snak.get("datavalue") or {}).get("value") or {}
        time_str = value.get("time")
        precision = value.get("precision")
        if not isinstance(time_str, str) or not isinstance(precision, int):
            continue
        truncated = _truncate_wikibase_time(time_str, precision)
        if truncated:
            return truncated
    raw = (em.get("DateTimeOriginal") or {}).get("value")
    if isinstance(raw, str):
        match = _DATETIME_ORIGINAL_RE.match(raw.strip())
        if match:
            year, month, day = match.groups()
            if day:
                return f"{year}-{month}-{day}"
            if month:
                return f"{year}-{month}"
            return year
    return None


def _truncate_wikibase_time(time_str: str, precision: int) -> str | None:
    """Truncate a Wikibase time string to its declared precision.

    Wikibase times look like ``+2009-10-05T00:00:00Z`` (negative leading
    sign for BCE). A day-precision stamp gives ``"2009-10-05"``,
    month-precision ``"2009-10"``, year-precision ``"2009"``. Anything
    coarser than year (decade/century/...) we drop — for image creation
    dates "circa the 2000s" isn't a useful signal.
    """
    if not time_str.startswith(("+", "-")):
        return None
    sign = "" if time_str[0] == "+" else "-"
    body = time_str[1:]
    head = body.split("T", 1)[0]  # YYYY-MM-DD
    parts = head.split("-")
    if len(parts) != 3:
        return None
    year, month, day = parts
    if precision >= _TIME_PRECISION_DAY:
        return f"{sign}{year}-{month}-{day}"
    if precision == _TIME_PRECISION_MONTH:
        return f"{sign}{year}-{month}"
    if precision == _TIME_PRECISION_YEAR:
        return f"{sign}{year}"
    return None


def _extract_depicts(meta: dict) -> list[str]:
    """Wikidata QIDs from SDC P180 statements (deduplicated, deprecated dropped)."""
    out: list[str] = []
    seen: set[str] = set()
    for stmt in _sdc_statements(meta, "P180"):
        if stmt.get("rank") == "deprecated":
            continue
        snak = stmt.get("mainsnak") or {}
        if snak.get("snaktype") != "value":
            continue
        value = (snak.get("datavalue") or {}).get("value") or {}
        qid = value.get("id")
        if isinstance(qid, str) and qid not in seen:
            seen.add(qid)
            out.append(qid)
    return out


def _sdc_statements(meta: dict, pid: str) -> list[dict]:
    """Look up an SDC statement list by property id, returning ``[]`` if absent."""
    sdc = meta.get("sdc") or {}
    return (sdc.get("statements") or {}).get(pid) or []


def _walk_tree(filename: str) -> list[str]:
    """BFS over ``derived_from`` / ``other_versions`` starting at ``filename``.

    Returns the BFS order with ``filename`` first. Missing tree members
    (no metadata.json on disk) are silently skipped, but their already-
    queued neighbours still get visited.
    """
    seen: set[str] = set()
    order: list[str] = []
    queue: deque[str] = deque([filename])
    while queue:
        node = queue.popleft()
        if node in seen:
            continue
        seen.add(node)
        order.append(node)
        meta = read_download_metadata(node)
        if not meta:
            continue
        related = list(meta.get("derived_from") or ()) + list(
            meta.get("other_versions") or ()
        )
        for nb in related:
            if nb not in seen:
                queue.append(nb)
    return order


def _merge_locale_field(
    base: str | dict[str, str] | None,
    fallback: str | dict[str, str] | None,
) -> str | dict[str, str] | None:
    """Default to ``base``; fill missing dict locales from ``fallback``.

    - ``base`` None → use ``fallback`` outright.
    - ``base`` is a bare string → keep it (no per-locale info to merge into).
    - ``base`` is a dict → merge per-locale, base entries winning. A
      bare-string ``fallback`` against a dict base is ignored (we'd lose
      the locale tagging if we tried to splat it across all locales).
    """
    if base is None:
        return fallback
    if fallback is None or isinstance(base, str):
        return base
    if isinstance(fallback, str):
        return base
    merged = dict(fallback)
    merged.update(base)
    return merged


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
    """Reset per-export caches. For tests that monkeypatch paths."""
    global _OBJECT_IMAGES_CACHE
    _OBJECT_IMAGES_CACHE = None
    with _FILE_LOCKS_GUARD:
        _FILE_LOCKS.clear()


__all__ = [
    "collect_object_images",
    "clear_export_cache",
    "DOWNLOADS_IMAGES_DIR",
]
