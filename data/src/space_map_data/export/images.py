"""Per-object image list + thumbnail/metadata generation for export.

Reads source images and their pre-decided license servability from
``IMAGES_DIR/<filename>/``, then writes an export bundle per servable image::

    EXPORT_DIR/v1/images/<filename>/s.<ext>     # 512px
    EXPORT_DIR/v1/images/<filename>/m.<ext>     # 1024px (when source is larger)
    EXPORT_DIR/v1/images/<filename>/xl.<ext>    # 4096px (when source is larger)
    EXPORT_DIR/v1/images/<filename>/metadata.json.gz   # completion marker, not deployed
    EXPORT_DIR/v1/images/<filename>/sidecar.json.gz    # only when EXIF can't carry

SVG/WebM pass through verbatim under the Cloudflare Pages 25 MiB cap; pdf/stl/
djvu are skipped (unrenderable as images); animated sources re-encode to
animated AVIF at every bucket; lossy JPEGs stay verbatim at their resting
bucket (re-encoding would just degrade further) except when EXIF-rotated,
since their pixels must be baked upright; everything else re-encodes to lossy
webp even at the resting bucket, since one lossless→lossy step is visually
equivalent and avoids shipping multi-MiB PNGs verbatim. The resting bucket is
the smallest one at least as large as the source; nothing above it is emitted.

Frontend-facing metadata rides inside every raster variant as an EXIF
ImageDescription, so the deploy doesn't spend a file slot per image on a
sidecar; bundles that can't embed (passthrough, oversize, fake-extension)
get a deployed ``sidecar.json.gz`` fallback instead. ``metadata.json.gz``
carries the full payload and doubles as the completion marker.
"""

import gzip
import json
import logging
import re
import shutil
import threading
import uuid
from collections import deque
from collections.abc import Callable, Iterable
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

import orjson
from PIL import Image, ImageFile, ImageOps, ImageSequence
from PIL.ExifTags import Base as ExifBase

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

# Stay verbatim at the resting bucket; everything else re-encodes to lossy
# webp there too, since a lossless→lossy step is visually equivalent and
# avoids shipping multi-MiB PNGs verbatim.
_LOSSY_EXTENSIONS = {".jpg", ".jpeg"}

# Served verbatim at the xl label without decoding. Size-capped at the
# Cloudflare Pages per-file limit so oversize sources are dropped rather
# than breaking the deploy.
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

# Formats where multiple frames mean "animation". Other multi-frame formats
# (MPO stereoscopic JPEGs, multi-page TIFFs) aren't real animation, and
# iterating their frames can fail with "No data found for frame".
_ANIMATED_FORMATS = {"GIF", "WEBP", "PNG"}

# Bump when the variant-emission rules change (new encoder, new bucket sizes,
# dropped/added formats) OR the metadata payload gains/drops fields. Existing
# bundles whose metadata.json.gz carries an older schema are wiped and
# regenerated on the next export.
_BUNDLE_SCHEMA = 6

# Embedded-metadata envelope: EXIF ImageDescription =
# "SPACEMAP-META:v1:<byte-len>:<json>". ensure_ascii keeps byte offsets equal
# to character offsets so the client can byte-scan for the sentinel instead
# of parsing EXIF. Cap keeps the blob under the JPEG APP1 segment limit.
_META_SENTINEL = "SPACEMAP-META:v1:"
_EMBED_MAX_BYTES = 60_000

# P571 inception precision codes we accept. Wikidata uses the WikibaseTime
# precision enum: 11=day, 10=month, 9=year, lower=decade/century/millennium
# etc. Anything coarser than year isn't useful for an image creation date.
_TIME_PRECISION_DAY = 11
_TIME_PRECISION_MONTH = 10
_TIME_PRECISION_YEAR = 9

# Matches a leading date in extmetadata DateTimeOriginal: "2009-10-05",
# "2012-09-23 16:26:36", "1999". The trailing time (if any) is dropped.
_DATETIME_ORIGINAL_RE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?")

# Per-filename locks so two chunk-writer threads never race on the same
# image, while different files stay free to parallelize.
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

    Renders the pre-computed selection from ``OBJECT_IMAGES_PATH``; discovery
    and scoring happen at ingest time. Returns ``None`` when the cache has no
    entries for ``object_id``.
    """
    return _collect_images_from_cache(object_id, _object_images_cache)


def collect_feature_images(feature_id: int | str) -> list[dict] | None:
    """Build the ``images`` array for a single IAU nomenclature feature.

    Same shape as :func:`collect_object_images` but keyed by ``feature_id``
    and may include ``kind: 'locator'`` entries for P242 locator maps.
    """
    return _collect_images_from_cache(str(feature_id), _feature_images_cache)


def collect_group_images(slug: str) -> list[dict] | None:
    """Build the ``images`` array for a single group (constellation, ...).

    Same shape as :func:`collect_object_images` but keyed by ``Group.slug``.
    """
    return _collect_images_from_cache(slug, _group_images_cache)


def collect_topic_images(object_id: str, topic: str) -> list[dict] | None:
    """Build one topic shelf for a body — its atmosphere or its interior.

    Pictures from the article *about* that aspect, not of the body: the same
    arrangement as ``collect_ring_images``, from one shared cache.
    """
    return _collect_images_from_cache(f"{topic}:{object_id}", _topic_images_cache)


def collect_ring_images(body_id: str) -> list[dict] | None:
    """Build the ``ring_images`` array for one ringed body.

    Pictures of the ring system, not of the planet wearing it — a separate
    selection from the body's own ``images`` (see ``RING_IMAGES_PATH``).
    """
    return _collect_images_from_cache(body_id, _ring_images_cache)


def _collect_images_from_cache(
    key: str,
    cache_loader: Callable[[], dict[str, list[dict]]],
) -> list[dict] | None:
    """Shared body of ``collect_object_images`` / ``collect_feature_images``."""
    selections = cache_loader().get(key) or []
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


def _feature_images_cache() -> dict[str, list[dict]]:
    """Lazy-load and cache ``feature_images.json`` for the export run."""
    global _FEATURE_IMAGES_CACHE
    if _FEATURE_IMAGES_CACHE is None:
        from space_map_data.ingest.providers.image_selection import (
            read_feature_images,
        )

        _FEATURE_IMAGES_CACHE = read_feature_images()
        if not _FEATURE_IMAGES_CACHE:
            logger.warning(
                "feature_images.json missing or empty — run `space-map-ingest "
                "--targets images` first; export will emit no feature images"
            )
    return _FEATURE_IMAGES_CACHE


def _group_images_cache() -> dict[str, list[dict]]:
    """Lazy-load and cache ``group_images.json`` for the export run."""
    global _GROUP_IMAGES_CACHE
    if _GROUP_IMAGES_CACHE is None:
        from space_map_data.ingest.providers.image_selection import (
            read_group_images,
        )

        _GROUP_IMAGES_CACHE = read_group_images()
        if not _GROUP_IMAGES_CACHE:
            logger.warning(
                "group_images.json missing or empty — run `space-map-ingest "
                "--targets images` first; export will emit no group images"
            )
    return _GROUP_IMAGES_CACHE


def _topic_images_cache() -> dict[str, list[dict]]:
    """Lazy-load and cache ``topic_images.json`` for the export run."""
    global _TOPIC_IMAGES_CACHE
    if _TOPIC_IMAGES_CACHE is None:
        from space_map_data.ingest.providers.image_selection import (
            read_topic_images,
        )

        _TOPIC_IMAGES_CACHE = read_topic_images()
        if not _TOPIC_IMAGES_CACHE:
            logger.warning(
                "topic_images.json missing or empty — run `space-map-ingest "
                "--targets images` first; export will emit no topic galleries"
            )
    return _TOPIC_IMAGES_CACHE


def _ring_images_cache() -> dict[str, list[dict]]:
    """Lazy-load and cache ``ring_images.json`` for the export run."""
    global _RING_IMAGES_CACHE
    if _RING_IMAGES_CACHE is None:
        from space_map_data.ingest.providers.image_selection import (
            read_ring_images,
        )

        _RING_IMAGES_CACHE = read_ring_images()
        if not _RING_IMAGES_CACHE:
            logger.warning(
                "ring_images.json missing or empty — run `space-map-ingest "
                "--targets images` first; the Rings tabs will open on the chart"
            )
    return _RING_IMAGES_CACHE


_OBJECT_IMAGES_CACHE: dict[str, list[dict]] | None = None
_FEATURE_IMAGES_CACHE: dict[str, list[dict]] | None = None
_GROUP_IMAGES_CACHE: dict[str, list[dict]] | None = None
_RING_IMAGES_CACHE: dict[str, list[dict]] | None = None
_TOPIC_IMAGES_CACHE: dict[str, list[dict]] | None = None


# Smallest variant first — buckets ascend left-to-right in the export.
_THUMB_LABEL_ORDER = ("s", "m", "xl")


def pick_thumbnail(images: list[dict] | None) -> dict[str, str] | None:
    """Pick a card thumbnail from an export ``images`` array.

    Prefers the first ``kind: photo`` entry (locators/logos are less useful at
    32-48px) and returns its smallest available variant as
    ``{file, label, ext}``. Returns ``None`` when no entry has a renderable
    variant.
    """
    if not images:
        return None
    chosen = (
        next((img for img in images if img.get("kind") == "photo"), None) or images[0]
    )
    file = chosen.get("file")
    variants = chosen.get("variants") or {}
    if not isinstance(file, str) or not variants:
        return None
    for label in _THUMB_LABEL_ORDER:
        ext = variants.get(label)
        if ext:
            return {"file": file, "label": label, "ext": ext}
    return None


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
        "attr": _attribution_tier((bundle.get("license") or {}).get("name")),
    }
    titles = image_titles(_image_description(filename))
    _IMAGE_TITLES[filename] = titles
    title = _base_title(titles)
    # Nothing gained by shipping what the client derives from the filename anyway.
    if title and title.casefold() != _filename_label(filename).casefold():
        entry["title"] = title
    if bundle.get("width") and bundle.get("height"):
        entry["width"] = bundle["width"]
        entry["height"] = bundle["height"]
    return entry


def _image_description(filename: str) -> str | dict[str, str] | None:
    """The Commons description a picture's title is cut from.

    Read from the download metadata, not the export bundle: adding a field to
    the bundle marker would mean a schema bump and a full regeneration.
    """
    return _viewer_payload(filename).get("description")


def _filename_label(filename: str) -> str:
    """What the client shows without a title: the filename, de-slugged.
    Mirrors ``imageLabel`` in the frontend's ``fetch/objects/images.ts``."""
    return re.sub(r"\.[^.]+$", "", filename).replace("_", " ")


def _ensure_bundle(filename: str) -> dict:
    """Generate (if missing) and return the export bundle for an image.

    ``metadata.json.gz`` doubles as the completion marker: once it exists
    with a current ``schema`` the bundle is trusted as-is. Bundles written
    under an older schema are wiped and regenerated.
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
                    "license": existing.get("license"),
                }
            logger.info(
                "Regenerating stale image bundle %s (schema %s → %s)",
                filename,
                existing.get("schema"),
                _BUNDLE_SCHEMA,
            )
            _wipe_bundle_dir(out_dir)

        out_dir.mkdir(parents=True, exist_ok=True)
        payload = _viewer_payload(filename)
        exif = _exif_blob(filename, payload)
        variants, dims, embedded = _generate_variants(filename, out_dir, exif)
        if variants:
            if not embedded:
                _write_json_gz(out_dir / "sidecar.json.gz", payload)
            _write_marker_metadata(out_dir, payload, variants, dims)
        return {
            "variants": variants,
            "width": dims[0] if dims else None,
            "height": dims[1] if dims else None,
            "license": payload.get("license"),
        }


def _wipe_bundle_dir(out_dir: Path) -> None:
    """Remove every regular file in the per-image bundle directory."""
    for entry in out_dir.iterdir():
        if entry.is_file() or entry.is_symlink():
            entry.unlink()


def _generate_variants(
    filename: str, out_dir: Path, exif: bytes | None
) -> tuple[dict[str, str], tuple[int, int] | None, bool]:
    """Write s/m/xl output files.

    Returns ``(variants, dims, embedded)``. ``dims`` is ``None`` for
    passthrough/skipped sources where no raster was ever opened; ``embedded``
    tells the caller whether every variant carries the EXIF blob, or a
    sidecar fallback is needed.
    """
    src = source_path(filename)
    src_ext = src.suffix.lower()

    if src_ext in _SKIP_EXTENSIONS:
        logger.debug("Skipping unshippable format %s: %s", src_ext, filename)
        return {}, None, False

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
            return {}, None, False
        ext = src_ext.lstrip(".")
        target = out_dir / f"xl.{ext}"
        if not target.exists():
            _atomic_copy(src, target)
        return {"xl": ext}, None, False

    try:
        img = Image.open(src)
        img.load()
    except Exception as exc:
        logger.warning("Skipping unreadable image %s: %s", filename, exc)
        return {}, None, False

    animated = (
        img.format in _ANIMATED_FORMATS
        and getattr(img, "is_animated", False)
        and getattr(img, "n_frames", 1) > 1
    )

    # Bake EXIF orientation into the pixels: re-encoded variants carry only
    # our synthetic EXIF (no Orientation tag), and exported width/height must
    # describe the image as displayed.
    orientation = img.getexif().get(ExifBase.Orientation, 1)
    transposed = orientation != 1 and not animated
    if orientation != 1 and animated:
        logger.warning(
            "Ignoring EXIF orientation %s on animated source: %s",
            orientation,
            filename,
        )
    if transposed:
        upright = ImageOps.exif_transpose(img)
        img.close()
        img = upright

    source_max = max(img.width, img.height)
    dims = (img.width, img.height)
    # A transposed JPEG can't ship verbatim (stored pixels are rotated), so it
    # takes the lossless→webp resting path instead.
    lossy_source = src_ext in _LOSSY_EXTENSIONS and not transposed

    variants: dict[str, str] = {}
    embedded = exif is not None
    for label, dim in _BUCKETS:
        out_stem = out_dir / label
        if dim < source_max:
            ext = "avif" if animated else "webp"
            target = out_stem.with_suffix(f".{ext}")
            if not target.exists():
                if animated:
                    _write_animated_avif(img, dim, target, exif)
                else:
                    _write_webp(img, dim, target, exif)
            variants[label] = ext
            continue

        # Resting bucket: source fits within this size. We stop after writing
        # it (no upscaled variants above).
        if animated:
            ext = "avif"
            target = out_stem.with_suffix(f".{ext}")
            if not target.exists():
                _write_animated_avif(img, dim, target, exif)
        elif lossy_source:
            ext = src_ext.lstrip(".")
            target = out_stem.with_suffix(f".{ext}")
            # A ``.jpg`` source can decode as some other format (extension
            # lies); only a real JPEG stream can take the APP1 insert.
            jpeg_exif = exif if img.format in ("JPEG", "MPO") else None
            if not target.exists():
                if jpeg_exif is not None:
                    _copy_jpeg_with_exif(src, target, jpeg_exif)
                else:
                    _atomic_copy(src, target)
            embedded = embedded and jpeg_exif is not None
        else:
            ext = "webp"
            target = out_stem.with_suffix(f".{ext}")
            if not target.exists():
                _write_webp(img, dim, target, exif)
        variants[label] = ext
        break

    img.close()
    return variants, dims, embedded


def _write_webp(
    img: Image.Image, max_dim: int, target: Path, exif: bytes | None
) -> None:
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
    to_save.save(tmp, "webp", quality=80, **({"exif": exif} if exif else {}))
    tmp.rename(target)

    if resized is not img:
        resized.close()


def _write_animated_avif(
    img: Image.Image, max_dim: int, target: Path, exif: bytes | None
) -> None:
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
        **({"exif": exif} if exif else {}),
    )
    tmp.rename(target)


def _atomic_copy(src: Path, dst: Path) -> None:
    """Copy ``src`` to ``dst`` via a temp file + rename. Atomic within a filesystem."""
    tmp = dst.with_name(f".{dst.name}.{uuid.uuid4().hex}.tmp")
    shutil.copyfile(src, tmp)
    tmp.rename(dst)


def _copy_jpeg_with_exif(src: Path, dst: Path, exif: bytes) -> None:
    """Copy a JPEG verbatim except for an inserted APP1 EXIF segment.

    Image data is untouched — only the metadata segment is spliced in after
    SOI, ahead of any pre-existing APP segments. Callers must ensure ``src``
    is a real JPEG stream.
    """
    data = src.read_bytes()
    segment = b"\xff\xe1" + (len(exif) + 2).to_bytes(2, "big") + exif
    tmp = dst.with_name(f".{dst.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_bytes(data[:2] + segment + data[2:])
    tmp.rename(dst)


def _viewer_payload(filename: str) -> dict:
    """Build the frontend-facing per-image metadata.

    ``artist``/``description`` aggregate across the derivative tree per
    locale, so e.g. a French derivative's caption fills a gap in the English
    original. ``date`` and ``depicts`` take the chosen file's value outright
    if it has one, falling back to the tree only when it doesn't (derivatives
    can have different framing, so these aren't merged). ``license`` stays
    tied to the chosen file alone: it describes the bytes actually served.
    """
    base = read_download_metadata(filename) or {}
    base_em = (base.get("imageinfo") or {}).get("extmetadata") or {}

    payload: dict = {
        "source_url": f"https://commons.wikimedia.org/wiki/File:{quote(filename)}",
    }
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
    return payload


def _exif_blob(filename: str, payload: dict) -> bytes | None:
    """Encode the viewer payload as sentinel-wrapped EXIF bytes.

    Returns None (→ sidecar fallback) when the blob would overflow a JPEG
    APP1 segment.
    """
    body = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    exif = Image.Exif()
    exif[ExifBase.ImageDescription] = f"{_META_SENTINEL}{len(body)}:{body}"
    blob = exif.tobytes()
    if len(blob) > _EMBED_MAX_BYTES:
        logger.info(
            "Metadata too large to embed (%d bytes) — sidecar fallback: %s",
            len(blob),
            filename,
        )
        return None
    return blob


def _write_json_gz(target: Path, payload: dict) -> None:
    """Write gzipped JSON via a temp file + rename."""
    tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_bytes(gzip.compress(orjson.dumps(payload)))
    tmp.rename(target)


def _write_marker_metadata(
    out_dir: Path,
    payload: dict,
    variants: dict[str, str],
    dims: tuple[int, int] | None,
) -> None:
    """Write metadata.json.gz, the completion marker. Written last so a
    crash never leaves a marked-but-incomplete bundle."""
    full: dict = {"schema": _BUNDLE_SCHEMA, "variants": variants, **payload}
    if dims:
        full["width"], full["height"] = dims
    _write_json_gz(out_dir / "metadata.json.gz", full)


def _aggregate_tree_metadata(
    filename: str, base_meta: dict
) -> tuple[
    str | dict[str, str] | None,
    str | dict[str, str] | None,
    str | None,
    list[str],
]:
    """Walk the derivative tree once and aggregate the fields we export.

    Returns ``(artist, description, date, depicts)``, chosen-file values
    taking precedence. BFS from the chosen file means closer derivatives are
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
    """Best-available creation date, ISO-truncated to known precision.

    Prefers SDC P571 (structured time + precision) over extmetadata's
    free-form ``DateTimeOriginal``, so a year-only inception isn't dressed
    up as a fake day.
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
    """Truncate a Wikibase time (``+2009-10-05T00:00:00Z``) to its declared
    precision. Anything coarser than year is dropped — "circa the 2000s"
    isn't a useful creation date."""
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
    """Default to ``base``; fill missing dict locales from ``fallback``. A
    bare-string ``fallback`` against a dict ``base`` is ignored — splatting
    it across all locales would lose the locale tagging."""
    if base is None:
        return fallback
    if fallback is None or isinstance(base, str):
        return base
    if isinstance(fallback, str):
        return base
    merged = dict(fallback)
    merged.update(base)
    return merged


# Attribution tiers for the social-card image picker. NC/ND/fair-use never
# reach here (dropped at download). ``free`` keywords must stay precise: a
# false positive would serve a credit-requiring image with no credit.
_FREE_LICENSE_KEYWORDS = (
    "cc0",
    "public domain",
    "pd-",
    "pd ",
    "no restrictions",
    "copyrighted free use",
)
_CREDIT_LICENSE_KEYWORDS = (
    "cc by",
    "cc-by",
    "attribution",
    "godl",
    "kogl",
    "ogl",
    "fal",
    "free art",
)


def _attribution_tier(license_name: str | None) -> str:
    """Classify a LicenseShortName by what crediting it demands.

    ``free`` needs no credit, ``credit`` is usable with a front-loaded text
    attribution, ``other`` (copyleft software licenses, unknowns) can't be
    honoured within a social card.
    """
    if not license_name:
        return "other"
    lower = license_name.lower()
    if any(kw in lower for kw in _FREE_LICENSE_KEYWORDS):
        return "free"
    if any(kw in lower for kw in _CREDIT_LICENSE_KEYWORDS):
        return "credit"
    return "other"


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


class _HTMLTextExtractor(HTMLParser):
    """Collect text nodes, turning <br> and block tags into newlines."""

    _BLOCK = {"p", "div", "li", "tr", "ul", "ol", "table", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._BLOCK:
            self._parts.append("\n")

    def text(self) -> str:
        # Collapse non-newline whitespace runs, cap consecutive blank lines.
        joined = "".join(self._parts)
        collapsed = re.sub(r"[^\S\n]+", " ", joined)
        return re.sub(r"\n{2,}", "\n\n", collapsed).strip()


def _strip_html(value: str) -> str:
    """Reduce attacker-editable Commons HTML to plain text (defense in depth
    alongside the client's inert parse)."""
    if "<" not in value:
        return value
    parser = _HTMLTextExtractor()
    parser.feed(value)
    parser.close()
    return parser.text()


# A tile label, not a caption: past this a description is prose about the
# picture rather than a name for it, and the filename reads better than a
# truncated paragraph. Two lines at the tile's font size.
MAX_TITLE_CHARS = 110

# filename -> {lang: title}, filled as bundles are rendered and read back when
# the localized bundles are built. Titles only, not payloads: the export holds
# tens of thousands of images at once.
_IMAGE_TITLES: dict[str, dict[str, str]] = {}


def image_titles(description: str | dict[str, str] | None) -> dict[str, str]:
    """Per-language tile titles from a Commons description.

    Takes the first line, and only when it's already label-shaped — there's
    no way to cut a long description that doesn't read as a truncation.
    """
    if not description:
        return {}
    by_lang = (
        description if isinstance(description, dict) else {LANGUAGES[0]: description}
    )
    out: dict[str, str] = {}
    for lang, text in by_lang.items():
        first_line = _strip_html(text).strip().split("\n", 1)[0].strip()
        if first_line and len(first_line) <= MAX_TITLE_CHARS:
            out[lang] = first_line
    return out


def _base_title(titles: dict[str, str]) -> str | None:
    """The title the global entry carries: the base language, else whichever
    single language Commons happened to describe the picture in."""
    return titles.get(LANGUAGES[0]) or next(iter(titles.values()), None)


def localized_image_titles(files: Iterable[str], lang: str) -> dict[str, str]:
    """Title overrides for one language, keyed by filename.

    Only where the language has a title of its own that differs from the one
    already in the global entry — the same shape (and the same reason) as the
    notable-member name overrides.
    """
    out: dict[str, str] = {}
    for filename in files:
        titles = _IMAGE_TITLES.get(canonical_filename(filename))
        if not titles:
            continue
        title = titles.get(lang)
        if title and title != _base_title(titles):
            out[filename] = title
    return out


def _locale_field(field: dict | None) -> str | dict[str, str] | None:
    """Normalize a Commons multilang-or-string extmetadata field.

    - Bare strings pass through unchanged (no locale structure in the source).
    - Multilang dicts are restricted to supported locales; ``_type`` is dropped.
    - HTML markup is stripped to plain text (the fields carry Commons HTML).
    - Empty results collapse to None.
    """
    if not field:
        return None
    value = field.get("value")
    if isinstance(value, str):
        s = _strip_html(value).strip()
        return s or None
    if isinstance(value, dict):
        trimmed = {}
        for k, v in value.items():
            if k not in LANGUAGES or not isinstance(v, str):
                continue
            stripped = _strip_html(v).strip()
            if stripped:
                trimmed[k] = stripped
        return trimmed or None
    return None


def prune_image_bundles() -> None:
    """Delete bundle dirs for images no longer referenced by any selection.

    The bundle writers only ever add, so selection changes (image replaced,
    object dropped, exclusion added) would otherwise leave orphans forever.
    "Referenced" is the union of *every* selection cache, not just the ones a
    page loads first — a ring/topic-only picture is referenced just as much.
    Skipped with a warning when every cache is empty, since that means
    ingest hasn't run rather than nothing being referenced.
    """
    keep: set[str] = set()
    for cache_loader in (
        _object_images_cache,
        _feature_images_cache,
        _group_images_cache,
        _ring_images_cache,
        _topic_images_cache,
    ):
        for entries in cache_loader().values():
            for entry in entries:
                keep.add(canonical_filename(entry["file"]))
    if not keep:
        logger.warning("All image selection caches empty — skipping bundle prune")
        return

    if not _EXPORT_IMAGES_DIR.exists():
        return
    deleted = 0
    for d in _EXPORT_IMAGES_DIR.iterdir():
        if not d.is_dir() or d.name in keep:
            continue
        logger.debug("Pruning orphan image bundle: %s", d.name)
        shutil.rmtree(d)
        deleted += 1
    if deleted:
        logger.info("Pruned %d orphan image bundles", deleted)


def clear_export_cache() -> None:
    """Reset per-export caches. For tests that monkeypatch paths."""
    global \
        _OBJECT_IMAGES_CACHE, \
        _FEATURE_IMAGES_CACHE, \
        _GROUP_IMAGES_CACHE, \
        _RING_IMAGES_CACHE, \
        _TOPIC_IMAGES_CACHE
    _OBJECT_IMAGES_CACHE = None
    _FEATURE_IMAGES_CACHE = None
    _GROUP_IMAGES_CACHE = None
    _RING_IMAGES_CACHE = None
    _TOPIC_IMAGES_CACHE = None
    with _FILE_LOCKS_GUARD:
        _FILE_LOCKS.clear()


__all__ = [
    "collect_object_images",
    "collect_feature_images",
    "collect_group_images",
    "pick_thumbnail",
    "prune_image_bundles",
    "clear_export_cache",
    "DOWNLOADS_IMAGES_DIR",
]
