"""Yaml / json plumbing: attribution lookup, skip semantics, frame ids."""

import json
import logging
import re
from pathlib import Path
from typing import Any, TypedDict, cast

from space_map_data.export.sidecar_io import mirror_path

from . import config
from .alignment import DEFAULT_ALIGNMENT, entry_alignment

log = logging.getLogger(__name__)

# Matches an export file from the cloud bundle: `{tier}_{YYYYMMDDHH}.webp`.
# Used to identify outputs whose source snapshot has vanished from disk so
# the bundle doesn't accumulate ghost frames on subsequent runs.
CLOUD_OUTPUT_RE = re.compile(r"^([a-z]+)_(\d{10})\.webp$")


def scraped_attribution(src_file_name: str) -> str | None:
    """Look up `attribution_guess` from the per-texture scraped source metadata.

    The `texture_sources` downloader writes one JSON per raw texture file
    (keyed by file stem) to `source_metadata/parsed/`. Returns None when no
    scrape exists for this file or the scrape has no attribution.
    """
    parsed = config.SOURCE_METADATA_PARSED_DIR / f"{Path(src_file_name).stem}.json"
    if not parsed.exists():
        return None
    try:
        data = json.loads(parsed.read_text())
    except (OSError, json.JSONDecodeError):
        log.warning("Failed to read scraped source metadata at %s", parsed)
        return None
    guess = data.get("attribution_guess")
    return guess if isinstance(guess, str) and guess.strip() else None


def refresh_metadata_from_yaml(out_dir: Path, entry: dict, src_file_name: str) -> None:
    """Update yaml-sourced fields on an existing metadata.json without re-exporting the image.

    Covers entries written before a field existed (e.g. `organisation`,
    `attribution`) and any later yaml edits. Leaves image-derived fields
    (`source_file`, `source_dimensions`, `processed_at`, `exports`) intact.
    Silently no-ops if the file is missing — nothing to refresh.
    """
    meta_path = mirror_path(out_dir / "metadata.json")
    if not meta_path.exists():
        return
    try:
        current = json.loads(meta_path.read_text())
    except (OSError, json.JSONDecodeError):
        log.warning("Failed to read existing metadata at %s", meta_path)
        return

    attribution = entry.get("attribution") or scraped_attribution(src_file_name)
    desired = {
        "id": entry["body"],
        "source": entry["source"],
        "organisation": entry["organisation"],
        "attribution": attribution,
        "description": entry.get("description"),
        "type": entry["type"],
    }
    # absolute_radius is a yaml flag, not image-derived, so refresh it without a
    # reprocess — else a cached displacement bundle keeps a stale/missing value
    # and the renderer mis-scales the body (treats radius as elevation).
    if entry.get("type") == "cylindrical_displacement":
        desired["absolute_radius"] = bool(entry.get("absolute_radius", False))
    if all(current.get(k) == v for k, v in desired.items()):
        return
    current.update(desired)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(current, indent=2))
    log.info("refreshed metadata from yaml: %s/metadata.json", out_dir.name)


def expand_entry_files(entry: dict) -> list[str]:
    """Resolve an entry's ``file`` field into the concrete raw filenames it covers.

    Single-frame entries return ``[entry["file"]]``. ``cylindrical_monthly``
    entries python-format ``{month:02d}`` (and the unpadded ``{month}``) for
    ``range(1, months+1)``.
    """
    if entry.get("type") == "cylindrical_monthly":
        months = entry.get("months", 12)
        return [entry["file"].format(month=m) for m in range(1, months + 1)]
    return [entry["file"]]


def stale_metadata_reason(existing: dict, entry: dict) -> str | None:
    """Return a reason string if on-disk metadata is structurally stale.

    Used by ``TextureProcessor._try_skip`` to force a reprocess when a monthly
    entry's shape (frame count / template) has diverged from the last export.
    Returns None for single-frame entries — their skip is driven by file
    existence and the per-export size cap. Cloud overlays don't flow through
    ``_try_skip`` (own snapshot-set comparison), so they aren't handled here.
    """
    type_ = entry.get("type")
    if type_ in (
        "cylindrical",
        "cylindrical_monthly",
        "cylindrical_specular",
        "cylindrical_night_lights",
        "cylindrical_displacement",
    ):
        cur_align = existing.get("alignment") or DEFAULT_ALIGNMENT
        if cur_align != entry_alignment(entry):
            return "alignment changed"
        # Single-frame source swap (e.g. body reassigned to a new map file):
        # alignment can match yet the pixels differ. Monthly uses a template
        # path, handled by its own shape check below.
        if (
            type_ != "cylindrical_monthly"
            and existing.get("source_file") != entry["file"]
        ):
            return "source file changed"
    if type_ == "cylindrical_monthly":
        if (
            existing.get("type") != type_
            or existing.get("frames") != entry.get("months", 12)
            or existing.get("source_file") != entry["file"]
        ):
            return "yaml entry shape changed"
    if type_ == "cubemap_skybox":
        if (
            existing.get("type") != type_
            or tuple(existing.get("faces") or ()) != config.SKYBOX_FACES
            or existing.get("tier_face_size") != config.SKYBOX_TIER_SIZES
        ):
            return "skybox entry shape changed"
    return None


def any_export_over_cap(out_dir: Path) -> bool:
    """True if any export recorded in metadata.json exceeds MAX_FILE_BYTES.

    Used to auto-reprocess stale bundles after the cap is tightened or a
    deploy fails upload. Walks the ``exports`` tree so it works on both the
    flat (``{tier: rec}``) and frame-nested (``{frame: {tier: rec}}``) shapes.
    Safe against corrupt/missing metadata: returns False (falls through to
    the normal skip path, which will write a fresh metadata via
    ``refresh_metadata_from_yaml`` if needed).
    """
    meta_path = mirror_path(out_dir / "metadata.json")
    if not meta_path.exists():
        return False
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, json.JSONDecodeError):
        return False

    class _MaybeSized(TypedDict, total=False):
        size_bytes: int

    def _walk(node: Any) -> bool:
        if not isinstance(node, dict):
            return False
        entry = cast("_MaybeSized", node)
        size = entry.get("size_bytes")
        if size is not None:
            return size > config.MAX_FILE_BYTES
        return any(_walk(v) for v in node.values())

    return _walk(meta.get("exports") or {})


def cloud_frame_id(path: Path) -> str | None:
    """Derive a sortable frame id from a date-partitioned snapshot path.

    ``yyyy/mm/dd/HH.png`` → ``YYYYMMDDHH``. Returns None if the path
    doesn't fit that layout (so the caller can warn instead of silently
    grouping unrelated snapshots).
    """
    try:
        rel = path.relative_to(config.EARTH_CLOUDS_DIR).with_suffix("")
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        return None
    yyyy, mm, dd, hh = parts
    return f"{yyyy}{mm}{dd}{hh}"
