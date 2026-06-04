"""Build and write IAU planetary nomenclature export files.

Marker tier (loaded eagerly when a body's surface comes into view):

    nomenclature/positions/{body_id}.bin.gz       — SMNF-format binary
    nomenclature/__global__/{body_id}.json.gz     — lean IAU canonical metadata
                                                    (name, approval_date,
                                                    origin, parent_feature_id)

Details tier (lazy, fetched on drawer open, hash-bucketed):

    nomenclature/details/__global__/{bucket}.json.gz   — feature image manifest,
                                                         physical-quantity claims,
                                                         wikidata cross-link, …
    nomenclature/details/{lang}/{bucket}.json.gz       — localized name override,
                                                         description, named_after /
                                                         instance_of refs, wiki
                                                         summary, …

Bucket key = ``f"{object_id}:{feature_id}"`` so features on the same body
cluster — fetching one feature's details warms the bundle for its siblings.
Bucket count = ``ceil(total_features / K)`` with K=100 (global) / K=200
(localized), mirroring the objects pipeline.

Features missing the matched ``object_id`` (unmatched targets during ingest),
``center_lat``/``center_lon``, or ``feature_type_code`` are dropped from the
marker tier with a single aggregate log line — they can't be rendered.
"""

import gzip
import hashlib
import logging
import math
from pathlib import Path

import orjson
from sqlalchemy.orm import Session

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.images import collect_feature_images
from space_map_data.export.nomenclature.format import (
    pack_header,
    pack_record,
    quantize_lon_e7,
)
from space_map_data.export.nomenclature.wikidata_claims import (
    FEATURE_ENTITY_REF_CLAIMS,
    FEATURE_GLOBAL_CLAIMS,
    extract_feature_claims,
)
from space_map_data.export.objects.wikidata_claims import (
    resolve_entity_ref,
    resolve_unit,
)
from space_map_data.export.objects.wikipedia import (
    WikipediaSummary,
    load_wikipedia_summaries_for_qid,
)
from space_map_data.export.position.format import quantize_deg
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.wikidata import WikidataEntity, WikidataEntityCache
from space_map_data.models.feature import Feature

logger = logging.getLogger(__name__)


# Target average members per bundle, mirroring the objects writer. Bucket
# count = ceil(total / K) so the per-bundle size stays roughly constant as
# the dataset grows.
K_GLOBAL = 100
K_LOCALIZED = 200


def hash_bucket(key: str, n_buckets: int) -> int:
    """Deterministic bucket from a string key. Mirrors the objects-writer impl.

    Lifted (not imported) to keep the two writers' bucket math independently
    reviewable and to avoid an objects→nomenclature coupling that'd reverse
    the natural module dependency order.
    """
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:4], "big") % n_buckets


def feature_bucket_key(object_id: str, feature_id: int) -> str:
    """``object_id:feature_id`` — frontend reproduces this from the body URL."""
    return f"{object_id}:{feature_id}"


def build_nomenclature(
    session: Session,
) -> dict[str, tuple[bytes, dict[str, dict]]]:
    """Group features by parent body and produce (positions, global_dict) per body.

    The ``global_dict`` here is the lean marker payload (name / approval_date /
    origin / parent_feature_id). Richer per-feature data ships separately via
    :func:`build_feature_details`.
    """
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


# ---------------------------------------------------------------------------
# Details tier
# ---------------------------------------------------------------------------


class FeatureDetailData:
    """Per-feature global + localized dicts assembled by :func:`build_feature_details`.

    Mirrors ``ChunkObjectData`` but keys on the bucket key
    ``f"{object_id}:{feature_id}"`` directly to keep the bucket math trivial
    when bundles get written.
    """

    __slots__ = ("global_data", "localized_data")

    def __init__(self) -> None:
        self.global_data: dict[str, dict] = {}
        self.localized_data: dict[str, dict[str, dict]] = {
            lang: {} for lang in LANGUAGES
        }


def build_feature_details(
    session: Session,
    wikidata_entities: WikidataEntityCache,
    units: UnitConverter,
) -> FeatureDetailData:
    """Build the details tier for every IAU feature with extractable enrichment.

    Source set: every Feature with ``object_id`` set (so the bucket key has a
    body) and either a Wikidata QID (claim extraction) or images in the
    feature-image cache. Features with neither don't get a details entry —
    the lean marker file is all the frontend will fetch for them.
    """
    out = FeatureDetailData()
    rows = (
        session.query(Feature)
        .filter(Feature.object_id.isnot(None))
        .order_by(Feature.object_id, Feature.feature_id)
        .all()
    )

    skipped_no_enrichment = 0
    for f in rows:
        assert f.object_id is not None  # SQL filter
        feature_qid = f.wikidata_qid
        wd = wikidata_entities.get_feature_entity(feature_qid)

        extracted: dict = {}
        if feature_qid and wd:
            try:
                extracted = extract_feature_claims(
                    wd["claims"], qid=feature_qid, wikidata_entities=wikidata_entities
                )
            except Exception as exc:
                logger.error(
                    "Error extracting claims for feature %d (%s): %s",
                    f.feature_id,
                    feature_qid,
                    exc,
                )

        images = collect_feature_images(f.feature_id)

        # Skip features that have neither images nor extractable claims —
        # there's nothing for the details bundle to carry.
        if not images and not extracted and not feature_qid:
            skipped_no_enrichment += 1
            continue

        global_entry = _build_detail_global(
            f, extracted, images, units, wikidata_entities
        )
        bucket_key = feature_bucket_key(f.object_id, f.feature_id)
        out.global_data[bucket_key] = global_entry

        if wd:
            wiki_summaries = (
                load_wikipedia_summaries_for_qid(feature_qid) if feature_qid else {}
            )
            for lang in LANGUAGES:
                lang_entry = _build_detail_localized(
                    f,
                    lang,
                    wd,
                    extracted,
                    wikidata_entities,
                    wiki_summaries.get(lang),
                )
                if lang_entry:
                    out.localized_data[lang][bucket_key] = lang_entry

    if skipped_no_enrichment:
        logger.info(
            "Skipped %d features with no detail-tier enrichment (no QID, no images)",
            skipped_no_enrichment,
        )
    return out


def _build_detail_global(
    feature: Feature,
    extracted: dict,
    images: list[dict] | None,
    units: UnitConverter,
    wikidata_entities: WikidataEntityCache,
) -> dict:
    """Build the per-language-independent payload for one feature."""
    data: dict = {}
    if feature.wikidata_qid:
        data["wikidata_qid"] = feature.wikidata_qid
    if images:
        data["images"] = images
    if extracted:
        wikidata_section: dict = {}
        for claim in FEATURE_GLOBAL_CLAIMS:
            if claim.key not in extracted:
                continue
            val = extracted[claim.key]
            if isinstance(val, dict) and "unit" in val:
                converted = units.convert(float(val["value"]), val["unit"])
                if converted is not None:
                    val = converted
                else:
                    resolved = resolve_unit(val["unit"], wikidata_entities)
                    if resolved:
                        units.used_units.add(resolved)
                        val = {**val, "unit": resolved}
            wikidata_section[claim.key] = val
        if wikidata_section:
            data["wikidata"] = wikidata_section
    return data


def _build_detail_localized(
    feature: Feature,
    lang: str,
    wd: WikidataEntity,
    extracted: dict,
    wikidata_entities: WikidataEntityCache,
    wiki_summary: WikipediaSummary | None,
) -> dict:
    """Build the per-language payload for one feature."""
    data: dict = {}
    labels = wd["labels"]
    canonical = feature.unicode_name or feature.name
    # Only ship a localized name when it actually differs from the IAU
    # canonical form — the marker file already carries `name`, no point
    # double-shipping identical strings.
    if lang in labels and labels[lang] != canonical:
        data["name"] = labels[lang]

    desc = wd["descriptions"].get(lang)
    if desc:
        data["description"] = desc
    aliases = wd["aliases"].get(lang)
    if aliases:
        data["aliases"] = aliases

    for claim in FEATURE_ENTITY_REF_CLAIMS:
        if claim.key not in extracted:
            continue
        if claim.multiple:
            refs = [
                r
                for qid in extracted[claim.key]
                if (r := resolve_entity_ref(qid, lang, wikidata_entities))
            ]
            if refs:
                data[claim.key] = refs
        else:
            ref = resolve_entity_ref(extracted[claim.key], lang, wikidata_entities)
            if ref:
                data[claim.key] = ref

    if wiki_summary is not None:
        data["wikipedia"] = wiki_summary.to_dict()

    return data


def write_feature_detail_bundles(
    out_dir: Path,
    details: FeatureDetailData,
) -> dict[str, int]:
    """Hash-bucket per-feature dicts and write one gzipped JSON per bucket.

    Returns ``{"global": N, lang: N, ...}`` for publication in
    ``metadata.json`` so the frontend can compute the bucket id from a
    ``(body_id, feature_id)`` pair. A tier with zero entries gets ``N=0``
    and no directory.
    """
    bundle_ns: dict[str, int] = {}

    global_data = details.global_data
    n_global = max(1, math.ceil(len(global_data) / K_GLOBAL)) if global_data else 0
    bundle_ns["global"] = n_global
    if n_global:
        _write_hashed_bundles(
            out_dir / "nomenclature" / "details" / "__global__",
            global_data,
            n_global,
        )

    for lang in LANGUAGES:
        by_key = details.localized_data.get(lang, {})
        n_lang = max(1, math.ceil(len(by_key) / K_LOCALIZED)) if by_key else 0
        bundle_ns[lang] = n_lang
        if n_lang:
            _write_hashed_bundles(
                out_dir / "nomenclature" / "details" / lang,
                by_key,
                n_lang,
            )

    logger.info(
        "Wrote feature detail bundles: global N=%d (%d features), langs: %s",
        n_global,
        len(global_data),
        ", ".join(
            f"{lang}={bundle_ns[lang]}({len(details.localized_data.get(lang, {}))})"
            for lang in LANGUAGES
        ),
    )
    return bundle_ns


def _write_hashed_bundles(
    dir_path: Path, by_key: dict[str, dict], n_buckets: int
) -> None:
    """Group by ``hash(key) % n_buckets`` and write one gzipped JSON per bucket."""
    buckets: dict[int, dict[str, dict]] = {}
    for key, data in by_key.items():
        buckets.setdefault(hash_bucket(key, n_buckets), {})[key] = data
    dir_path.mkdir(parents=True, exist_ok=True)
    for bucket, entries in buckets.items():
        (dir_path / f"{bucket}.json.gz").write_bytes(
            gzip.compress(orjson.dumps(entries))
        )
