"""Surface-features search index.

Source files (per body):

    v1/nomenclature/positions/{body_id}.bin.gz   — SMNF binary
    v1/nomenclature/labels/{lang}/{body_id}.txt.gz — one label per record,
                                                     ordered to match positions
    v1/nomenclature/details/{lang}/{bucket}.json.gz — per-language details
                                                      (description, aliases, …)

One document per feature, all language variants on the same document.
"""

import gzip
import json
import logging
import struct
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from space_map_data.constants.nomenclature.quadrangle_grid import quadrangle_for
from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.images import pick_thumbnail
from space_map_data.export.nomenclature.quadrangles import load_quadrangles
from space_map_data.export.nomenclature.format import (
    HEADER_SIZE,
    MAGIC,
    RECORD_SIZE,
)

from .base import feature_pk

logger = logging.getLogger(__name__)


_RECORD_STRUCT = struct.Struct("<IiII2sBB")


def _read_positions(path: Path) -> list[tuple[int, float, float, int, str]]:
    """Decode an SMNF file into ``(feature_id, lat, lon, diameter_m, type_code)`` tuples."""
    data = gzip.decompress(path.read_bytes())
    magic, version, _, _, count, _ = struct.unpack("<4sHBBII", data[:HEADER_SIZE])
    if magic != MAGIC:
        raise ValueError(f"Bad SMNF magic in {path}: {magic!r}")
    out: list[tuple[int, float, float, int, str]] = []
    for i in range(count):
        off = HEADER_SIZE + i * RECORD_SIZE
        fid, lat_e7, lon_e7, dia_m, tc, _, _ = _RECORD_STRUCT.unpack(
            data[off : off + RECORD_SIZE]
        )
        type_code = tc.rstrip(b"\x00").decode("ascii", errors="replace")
        out.append((fid, lat_e7 / 1e7, lon_e7 / 1e7, dia_m, type_code))
    return out


def _read_labels(path: Path, expected: int) -> list[str]:
    """Decode a labels file; pads/trims to ``expected`` lines so a mismatch is loud."""
    lines = gzip.decompress(path.read_bytes()).decode("utf-8").split("\n")
    if len(lines) != expected:
        logger.warning(
            "Label count mismatch in %s: got %d, expected %d (will align by index)",
            path,
            len(lines),
            expected,
        )
        if len(lines) < expected:
            lines = lines + [""] * (expected - len(lines))
        else:
            lines = lines[:expected]
    return lines


def _load_localized_details(
    export_dir: Path,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Return ``{lang: {bucket_key: detail_entry}}`` from the details tier.

    Localized bundles are small (~15 buckets per lang, hundreds of KiB each),
    so we slurp them into RAM and join against the streamed features below.
    Detail entries are missing for features without any enrichment — that's
    fine, they just won't carry a description.
    """
    details_root = export_dir / "v1" / "nomenclature" / "details"
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for lang in LANGUAGES:
        lang_dir = details_root / lang
        if not lang_dir.exists():
            out[lang] = {}
            continue
        merged: dict[str, dict[str, Any]] = {}
        for bundle in sorted(lang_dir.glob("*.json.gz")):
            merged.update(json.loads(gzip.decompress(bundle.read_bytes())))
        out[lang] = merged
        logger.info("Loaded %d feature detail entries for %s", len(merged), lang)
    return out


def _load_global_details(export_dir: Path) -> dict[str, dict[str, Any]]:
    """Return ``{bucket_key: global_entry}`` from the details tier.

    Carries the ``images`` array used to pick search-card thumbnails.
    """
    global_dir = export_dir / "v1" / "nomenclature" / "details" / "__global__"
    if not global_dir.exists():
        return {}
    merged: dict[str, dict[str, Any]] = {}
    for bundle in sorted(global_dir.glob("*.json.gz")):
        merged.update(json.loads(gzip.decompress(bundle.read_bytes())))
    logger.info("Loaded %d feature global detail entries", len(merged))
    return merged


def build_feature_documents(export_dir: Path) -> Iterator[dict[str, Any]]:
    positions_dir = export_dir / "v1" / "nomenclature" / "positions"
    labels_root = export_dir / "v1" / "nomenclature" / "labels"
    if not positions_dir.exists():
        logger.warning(
            "No nomenclature positions at %s — nothing to index", positions_dir
        )
        return

    details_by_lang = _load_localized_details(export_dir)
    global_details = _load_global_details(export_dir)
    # Quadrangle membership is geometric; `overrides` carries the few features
    # the gazetteer files against the neighbouring cell (see quadrangles.py).
    quad_overrides = {
        body: data.get("overrides") or {}
        for body, data in load_quadrangles(export_dir).items()
    }
    body_files = sorted(positions_dir.glob("*.bin.gz"))
    logger.info("Indexing features from %d bodies", len(body_files))

    total = 0
    unparsed_dates = 0
    for body_path in body_files:
        body_id = body_path.name.removesuffix(".bin.gz")
        records = _read_positions(body_path)
        if not records:
            continue

        labels_by_lang: dict[str, list[str]] = {}
        for lang in LANGUAGES:
            label_path = labels_root / lang / f"{body_id}.txt.gz"
            if not label_path.exists():
                logger.warning(
                    "Missing labels file %s — body will have no %s names",
                    label_path,
                    lang,
                )
                labels_by_lang[lang] = [""] * len(records)
                continue
            labels_by_lang[lang] = _read_labels(label_path, len(records))

        for i, (fid, lat, lon, dia_m, type_code) in enumerate(records):
            # Canonical name = English label (writer falls back to IAU
            # `Feature.name` when no Wikidata label exists, so en is always
            # non-empty for a renderable feature).
            canonical = labels_by_lang["en"][i]
            doc: dict[str, Any] = {
                "id": feature_pk(body_id, fid),
                "kind": "feature",
                "name": canonical,
                # Feature-specific fields nest under `feature`; the natural
                # body_id + feature_id ride along for frontend routing.
                "feature": {
                    "feature_id": fid,
                    "body_id": body_id,
                    "type": type_code,
                    "center_lat": round(lat, 4),
                    "center_lon": round(lon, 4),
                },
            }
            if dia_m:
                doc["diameter_km"] = round(dia_m / 1000.0, 3)
            quad = quad_overrides.get(body_id, {}).get(str(fid)) or quadrangle_for(
                body_id, lat, lon
            )
            if quad:
                doc["feature"]["quad"] = quad
            # Detail-tier bundles use ``{body}:{fid}`` as the key — mirrors
            # ``feature_bucket_key`` in the nomenclature writer.
            detail_key = f"{body_id}:{fid}"
            detail_global = global_details.get(detail_key) or {}
            thumb = pick_thumbnail(detail_global.get("images"))
            if thumb:
                doc["thumbnail"] = thumb
            # Prominence ranking key, shared with objects/groups — ranks a
            # feature-type page's member list notable-first.
            if sitelinks := detail_global.get("sitelinks_count"):
                doc["sitelinks_count"] = sitelinks
            # IAU approval year — the naming-date range filter. Kept as a bare
            # year (the gazetteer's own precision is the year for older names).
            approval = detail_global.get("approval_date")
            if approval:
                year = approval[:4]
                if year.isdigit():
                    doc["feature"]["named"] = int(year)
                else:
                    unparsed_dates += 1
            for lang in LANGUAGES:
                label = labels_by_lang[lang][i]
                if label:
                    doc[f"name_{lang}"] = label
                desc = (details_by_lang[lang].get(detail_key) or {}).get("description")
                if desc:
                    doc[f"description_{lang}"] = desc
            yield doc
            total += 1

    if unparsed_dates:
        logger.warning(
            "%d feature(s) had an unparseable approval_date — no naming year indexed",
            unparsed_dates,
        )
    logger.info("Built %d feature documents", total)
