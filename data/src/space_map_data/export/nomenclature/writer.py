"""Build and write IAU planetary nomenclature export files.

Two files per body with features:

    nomenclature/positions/{body_id}.bin.gz   — SMNF-format binary
    nomenclature/__global__/{body_id}.json.gz — IAU canonical metadata

Features missing the matched ``object_id`` (unmatched targets during ingest),
``center_lat``/``center_lon``, or ``feature_type_code`` are dropped with a
single aggregate log line — they can't be rendered.
"""

import gzip
import logging
from pathlib import Path

import orjson
from sqlalchemy.orm import Session

from space_map_data.export.nomenclature.format import (
    pack_header,
    pack_record,
    quantize_lon_e7,
)
from space_map_data.export.position.format import quantize_deg
from space_map_data.models.feature import Feature

logger = logging.getLogger(__name__)


def build_nomenclature(
    session: Session,
) -> dict[str, tuple[bytes, dict[str, dict]]]:
    """Group features by parent body and produce (positions, global_dict) per body."""
    rows = (
        session.query(Feature)
        .filter(Feature.object_id.isnot(None))
        .order_by(Feature.object_id, Feature.feature_id)
        .all()
    )

    skipped_no_position = 0
    skipped_no_type = 0
    by_body: dict[str, list[Feature]] = {}
    for f in rows:
        if f.center_lat is None or f.center_lon is None:
            skipped_no_position += 1
            continue
        if not f.feature_type_code:
            skipped_no_type += 1
            continue
        assert f.object_id is not None  # SQL filter guarantees this
        by_body.setdefault(f.object_id, []).append(f)

    unmatched = session.query(Feature).filter(Feature.object_id.is_(None)).count()
    if unmatched:
        logger.info(
            "Skipped %d nomenclature features with no matched object", unmatched
        )
    if skipped_no_position:
        logger.info(
            "Skipped %d nomenclature features missing lat/lon", skipped_no_position
        )
    if skipped_no_type:
        logger.info(
            "Skipped %d nomenclature features missing type code", skipped_no_type
        )

    return {
        body_id: (_build_positions(feats), _build_global(feats))
        for body_id, feats in by_body.items()
    }


def _build_positions(features: list[Feature]) -> bytes:
    """Pack pre-filtered features into the SMNF binary layout."""
    parts = [pack_header(len(features))]
    for f in features:
        # Invariants from build_nomenclature's filter pass.
        assert f.center_lat is not None
        assert f.center_lon is not None
        assert f.feature_type_code is not None
        diameter_km = f.diameter or 0.0
        parts.append(
            pack_record(
                feature_id=f.feature_id,
                center_lat_e7=quantize_deg(f.center_lat),
                center_lon_e7=quantize_lon_e7(f.center_lon),
                diameter_m=max(0, int(round(diameter_km * 1000.0))),
                type_code=f.feature_type_code,
            )
        )
    return b"".join(parts)


def _build_global(features: list[Feature]) -> dict[str, dict]:
    """Per-feature canonical IAU metadata, keyed by string feature_id."""
    out: dict[str, dict] = {}
    for f in features:
        entry: dict = {"name": f.unicode_name or f.name}
        if f.approval_date:
            entry["approval_date"] = f.approval_date.isoformat()
        if f.origin:
            entry["origin"] = f.origin
        if f.parent_feature_id is not None:
            entry["parent_feature_id"] = f.parent_feature_id
        out[str(f.feature_id)] = entry
    return out


def write_nomenclature_files(
    out_dir: Path, payload: dict[str, tuple[bytes, dict[str, dict]]]
) -> None:
    """Dump positions and global JSON files for every body in *payload*."""
    if not payload:
        logger.info("No nomenclature features to export")
        return

    positions_dir = out_dir / "nomenclature" / "positions"
    global_dir = out_dir / "nomenclature" / "__global__"
    positions_dir.mkdir(parents=True, exist_ok=True)
    global_dir.mkdir(parents=True, exist_ok=True)

    total_features = 0
    for body_id, (positions_bytes, global_dict) in payload.items():
        (positions_dir / f"{body_id}.bin.gz").write_bytes(
            gzip.compress(positions_bytes)
        )
        (global_dir / f"{body_id}.json.gz").write_bytes(
            gzip.compress(orjson.dumps(global_dict))
        )
        total_features += len(global_dict)

    logger.info(
        "Wrote nomenclature for %d bodies (%d features total)",
        len(payload),
        total_features,
    )
