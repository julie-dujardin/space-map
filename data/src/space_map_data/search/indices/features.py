"""Surface-features search index.

Source files (per body):

    v1/nomenclature/positions/{body_id}.bin.gz   — SMNF binary
    v1/nomenclature/labels/{lang}/{body_id}.txt.gz — one label per record,
                                                     ordered to match positions

One document per feature, all language variants on the same document.
"""

import gzip
import logging
import struct
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.nomenclature.format import (
    HEADER_SIZE,
    MAGIC,
    RECORD_SIZE,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Index:
    uid: str
    primary_key: str
    settings: dict[str, Any]

    def build_documents(self, export_dir: Path) -> Iterator[dict[str, Any]]:
        raise NotImplementedError


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


def _build_feature_documents(export_dir: Path) -> Iterator[dict[str, Any]]:
    positions_dir = export_dir / "v1" / "nomenclature" / "positions"
    labels_root = export_dir / "v1" / "nomenclature" / "labels"
    if not positions_dir.exists():
        logger.warning(
            "No nomenclature positions at %s — nothing to index", positions_dir
        )
        return

    body_files = sorted(positions_dir.glob("*.bin.gz"))
    logger.info("Indexing features from %d bodies", len(body_files))

    total = 0
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
                # Meili primary keys only allow [a-zA-Z0-9_-]; the `:`
                # separator used elsewhere in the export isn't legal here,
                # so feature_id rides as a numeric suffix after `_`.
                "id": f"{body_id}_{fid}",
                "feature_id": fid,
                "body_id": body_id,
                "name": canonical,
                "feature_type": type_code,
                "center_lat": round(lat, 4),
                "center_lon": round(lon, 4),
            }
            if dia_m:
                doc["diameter_km"] = round(dia_m / 1000.0, 3)
            for lang in LANGUAGES:
                label = labels_by_lang[lang][i]
                if label:
                    doc[f"name_{lang}"] = label
            yield doc
            total += 1

    logger.info("Built %d feature documents", total)


def _features_settings() -> dict[str, Any]:
    name_fields = ["name"] + [f"name_{lang}" for lang in LANGUAGES]
    return {
        "searchableAttributes": name_fields,
        "filterableAttributes": ["body_id", "feature_type"],
        "sortableAttributes": ["diameter_km"],
        "localizedAttributes": [
            {"locales": [lang], "attributePatterns": [f"name_{lang}"]}
            for lang in LANGUAGES
        ],
        # Prefer larger features when relevancy is otherwise tied — Olympus
        # Mons should beat any 1km crater that happens to share part of the name.
        "rankingRules": [
            "words",
            "typo",
            "proximity",
            "attribute",
            "sort",
            "exactness",
            "diameter_km:desc",
        ],
    }


class FeaturesIndex(Index):
    def build_documents(self, export_dir: Path) -> Iterator[dict[str, Any]]:
        return _build_feature_documents(export_dir)


FEATURES_INDEX = FeaturesIndex(
    uid="features",
    primary_key="id",
    settings=_features_settings(),
)
