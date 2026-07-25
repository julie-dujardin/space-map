"""Build and write IAU planetary nomenclature export files.

Marker tier (loaded eagerly when a body's surface comes into view):

    nomenclature/positions/{body_id}.bin.gz       — SMNF-format binary
    nomenclature/labels/{lang}/{body_id}.txt.gz   — \\n-separated label per
                                                    feature, ordered to match
                                                    the positions binary. Each
                                                    line is the Wikidata label
                                                    in ``lang`` when present,
                                                    falling back to ``Feature.name``.

Details tier (lazy, fetched on drawer open, hash-bucketed):

    nomenclature/details/__global__/{bucket}.json.gz   — feature image manifest,
                                                         physical-quantity claims,
                                                         wikidata cross-link,
                                                         approval_date, origin,
                                                         parent_feature, …
    nomenclature/details/{lang}/{bucket}.json.gz       — localized description,
                                                         named_after / instance_of
                                                         refs, wiki summary, …

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
import re
from pathlib import Path

import orjson
from sqlalchemy.orm import Session

from urllib.parse import quote

from space_map_data.constants.providers import LANGUAGES
from space_map_data.constants.nomenclature.quadrangles import QUADRANGLE_QIDS
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
    EntityRef,
    FocusResolver,
    make_feature_entityref,
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
from space_map_data.models.object import Object


# Wikidata claim keys folded into the unified ``inside_of`` list:
# P706 (located_on_physical_feature) and P361 (part_of). P276
# (`location`) is dropped for now — almost all values are IAU
# quadrangles, which the dedicated ``quadrangle`` field handles once
# their QIDs are matched upstream; until then we'd be shipping noise.
INSIDE_OF_CLAIM_KEYS: tuple[str, ...] = ("located_on_physical_feature", "part_of")

# Claim keys handled by the inside_of builder — these are skipped in the
# regular per-claim EntityRef loop so they don't get re-emitted.
_SPATIAL_CLAIM_KEYS: frozenset[str] = frozenset(
    {"location", "located_on_physical_feature", "part_of"}
)

# Bbox area threshold (in deg² × cos(midlat) proxy) below which a feature
# is considered too small to act as a useful spatial container. Filters
# out point-like features that happen to carry a tiny bbox.
_MIN_CONTAINER_BBOX_AREA = 0.01

# Feature-type codes that are inherently 1D (linear) or point-like and
# shouldn't act as spatial containers — "X is inside a cliff/ridge/chain"
# reads wrong in the sidebar even when the bbox math happens to fit.
_NON_CONTAINER_TYPES: frozenset[str] = frozenset(
    {
        # Linear / 1D features
        "AR",
        "CA",
        "DO",
        "FE",
        "LI",
        "PR",
        "RI",
        "RU",
        "SC",
        "SE",
        "SU",
        "VI",
        # Point features (landing sites, single boulders, single eruptive centers)
        "ER",
        "LF",
        "SA",
        "ST",
    }
)

# TODO(data-quality): some features — notably AL-type albedo regions like
# Adiri on Titan — carry a degenerate bbox (min == max == center) and
# diameter=0 from the IAU XML. Without size info the "container must be
# bigger" guard can't fire, so they get spuriously placed inside small
# overlapping features. Needs a Wikidata-claim radius fallback at ingest
# time, or per-feature size overrides for known-bad entries. Re-export
# afterwards.

logger = logging.getLogger(__name__)


# Drops a trailing '.' even when it sits before closing quote(s)/paren(s)
# — IAU origin strings ship with a sentence-final period that reads as
# clutter in the UI, including in nested cases like `(…Armínski.)`.
_TRAILING_ORIGIN_DOT_RE = re.compile(r"\.(?=[)\]\"'»”]*$)")


# Target average members per bundle. Global entries are mostly small
# (quadrangle + parent_feature + occasional wikidata claims), localized
# entries carry text. K is tuned to land post-gzip bundle size around
# the target 200–300 KiB so the frontend keeps file count low.
K_GLOBAL = 10000
K_LOCALIZED = 1100


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


def renderable_feature_filter() -> tuple:
    """SQL filter for features that reach the export (and so the frontend/search).

    Shared with the feature-type group tier so a group's member count can't
    drift from the set the map and search index actually carry.
    """
    return (
        Feature.object_id.isnot(None),
        Feature.center_lat.isnot(None),
        Feature.center_lon.isnot(None),
        Feature.feature_type_code.isnot(None),
        Feature.feature_type_code != "",
    )


def build_nomenclature(session: Session) -> dict[str, list[Feature]]:
    """Group renderable features by parent body, in stable feature_id order.

    The same ordered list drives the positions binary and the per-language
    label files — line i of every labels file refers to record i of the
    positions binary. ``test_nomenclature_writer`` pins that invariant.
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

    return by_body


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


def _build_labels(
    features: list[Feature],
    lang: str,
    wikidata_entities: WikidataEntityCache,
) -> bytes:
    """Pack one line per feature: Wikidata label in *lang*, else IAU ``name``.

    Order matches :func:`_build_positions`, by contract — frontend joins by
    index (positions[i] ↔ label_lines[i]).
    """
    lines: list[str] = []
    for f in features:
        label = f.name
        if f.wikidata_qid:
            wd = wikidata_entities.get_feature_entity(f.wikidata_qid)
            if wd is not None:
                wd_label = wd["labels"].get(lang)
                if wd_label:
                    label = wd_label
        lines.append(label)
    return "\n".join(lines).encode("utf-8")


def write_nomenclature_positions(
    out_dir: Path, by_body: dict[str, list[Feature]]
) -> None:
    """Dump the SMNF positions binary for every body in *by_body*."""
    if not by_body:
        logger.info("No nomenclature features to export")
        return

    positions_dir = out_dir / "nomenclature" / "positions"
    positions_dir.mkdir(parents=True, exist_ok=True)
    total_features = 0
    for body_id, feats in by_body.items():
        (positions_dir / f"{body_id}.bin.gz").write_bytes(
            gzip.compress(_build_positions(feats))
        )
        total_features += len(feats)
    logger.info(
        "Wrote nomenclature positions for %d bodies (%d features total)",
        len(by_body),
        total_features,
    )


def write_nomenclature_labels(
    out_dir: Path,
    by_body: dict[str, list[Feature]],
    wikidata_entities: WikidataEntityCache,
) -> None:
    """Dump one ``labels/{lang}/{body_id}.txt.gz`` per (lang, body)."""
    if not by_body:
        return
    labels_root = out_dir / "nomenclature" / "labels"
    for lang in LANGUAGES:
        lang_dir = labels_root / lang
        lang_dir.mkdir(parents=True, exist_ok=True)
        for body_id, feats in by_body.items():
            (lang_dir / f"{body_id}.txt.gz").write_bytes(
                gzip.compress(_build_labels(feats, lang, wikidata_entities))
            )
    logger.info(
        "Wrote nomenclature labels for %d bodies × %d languages",
        len(by_body),
        len(LANGUAGES),
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
    *,
    body_filter: str | None = None,
    body_radii_km: dict[str, float] | None = None,
    trace_sources: dict[int, dict[str, set[int]]] | None = None,
) -> FeatureDetailData:
    """Build the details tier for every IAU feature with extractable enrichment.

    Source set: features with ``object_id`` set plus at least one of: a
    Wikidata QID (claim extraction), images in the feature-image cache,
    IAU quadrangle assignment, an IAU satellite-feature link, or any
    derived spatial relationship. Features with none of those still get
    their lean marker entry, just no details bundle entry.

    ``body_radii_km`` enables circle (center+diameter) containment in
    addition to the bbox check; missing bodies fall back to bbox-only.
    ``trace_sources`` collects per-feature attribution
    (``{feature_id: {source_key: {container_fid, …}}}``) when supplied —
    diagnostics-only, the production export passes ``None``.
    """
    out = FeatureDetailData()

    rows_q = session.query(Feature).filter(Feature.object_id.isnot(None))
    if body_filter is not None:
        rows_q = rows_q.filter(Feature.object_id == body_filter)
    rows = rows_q.order_by(Feature.object_id, Feature.feature_id).all()

    focus_resolver, feature_qid_to_id_per_body, name_lookup_per_body = (
        _build_focus_indices(session, rows)
    )
    container_candidates_per_body = _container_candidates_per_body(rows)

    # Cache Wikidata extraction (used twice: inside_of pre-pass + per-feature build)
    extracted_by_feature: dict[int, dict] = {}
    wd_by_feature: dict[int, WikidataEntity | None] = {}
    for f in rows:
        wd = wikidata_entities.get_feature_entity(f.wikidata_qid)
        wd_by_feature[f.feature_id] = wd
        if f.wikidata_qid and wd:
            try:
                extracted_by_feature[f.feature_id] = extract_feature_claims(
                    wd["claims"],
                    qid=f.wikidata_qid,
                    wikidata_entities=wikidata_entities,
                )
            except Exception as exc:
                logger.error(
                    "Error extracting claims for feature %d (%s): %s",
                    f.feature_id,
                    f.wikidata_qid,
                    exc,
                )

    # Same-body feature ids each feature is inside (Wikidata-resolved +
    # bbox-derived, dedup'd against parent_feature_id). Powers both the
    # per-feature inside_of list and the inverse `contains` index.
    inside_feature_ids: dict[int, set[int]] = {}
    sat_index: dict[tuple[str, int], set[int]] = {}
    contains_index: dict[tuple[str, int], set[int]] = {}

    for f in rows:
        assert f.object_id is not None

        if f.parent_feature_id is not None:
            sat_index.setdefault((f.object_id, f.parent_feature_id), set()).add(
                f.feature_id
            )

        extracted = extracted_by_feature.get(f.feature_id, {})
        per_body_qid_map = feature_qid_to_id_per_body.get(f.object_id, {})
        traces: dict[str, set[int]] | None = None
        if trace_sources is not None:
            traces = {}
            trace_sources[f.feature_id] = traces

        same_body_inside: set[int] = set()
        for key in INSIDE_OF_CLAIM_KEYS:
            for qid in extracted.get(key, []):
                tgt = per_body_qid_map.get(qid)
                if tgt is not None and tgt != f.feature_id:
                    same_body_inside.add(tgt)
                    if traces is not None:
                        traces.setdefault(key, set()).add(tgt)

        # SF children inherit their spatial placement through the
        # parent_feature link — running bbox/radius would double-count
        # them in every ancestor's contains list. Wikidata-declared
        # edges still flow through (above) since those are explicit.
        if f.parent_feature_id is None:
            spatial = _spatial_inside_of(
                f,
                container_candidates_per_body.get(f.object_id, []),
                body_radii_km.get(f.object_id) if body_radii_km else None,
            )
            for fid, source in spatial:
                same_body_inside.add(fid)
                if traces is not None:
                    traces.setdefault(source, set()).add(fid)

        if f.parent_feature_id is not None:
            # Belt-and-suspenders: a Wikidata edge to F's SF parent
            # belongs in `parent_feature`, not echoed here.
            same_body_inside.discard(f.parent_feature_id)

        inside_feature_ids[f.feature_id] = same_body_inside

        for parent_fid in same_body_inside:
            contains_index.setdefault((f.object_id, parent_fid), set()).add(
                f.feature_id
            )

    # IAU SF naming hierarchy wins over spatial containment when a child
    # could be in both — keeps satellite_features and contains disjoint.
    for parent_key, sf_set in sat_index.items():
        if parent_key in contains_index:
            contains_index[parent_key] -= sf_set

    skipped_no_enrichment = 0
    for f in rows:
        assert f.object_id is not None  # SQL filter
        extracted = extracted_by_feature.get(f.feature_id, {})
        wd = wd_by_feature[f.feature_id]
        images = collect_feature_images(f.feature_id)
        has_quadrangle = bool(f.quad_code and f.quad_name)

        has_iau_meta = bool(f.approval_date or f.origin)
        if (
            not images
            and not extracted
            and not f.wikidata_qid
            and not has_quadrangle
            and f.parent_feature_id is None
            and not has_iau_meta
        ):
            skipped_no_enrichment += 1
            continue

        global_entry = _build_detail_global(
            f, extracted, images, units, wikidata_entities, name_lookup_per_body
        )
        bucket_key = feature_bucket_key(f.object_id, f.feature_id)
        if global_entry:
            out.global_data[bucket_key] = global_entry

        # Localized may have content (quadrangle, inside_of) even without a
        # feature-level Wikidata entry — quadrangle just needs the seeded
        # referenced/ payload; inside_of also has bbox/radius contributions.
        wiki_summaries = (
            load_wikipedia_summaries_for_qid(f.wikidata_qid) if f.wikidata_qid else {}
        )
        body_names = name_lookup_per_body.get(f.object_id, {})
        inside_ids = inside_feature_ids.get(f.feature_id, set())
        for lang in LANGUAGES:
            lang_entry = _build_detail_localized(
                f,
                lang,
                wd,
                extracted,
                wikidata_entities,
                wiki_summaries.get(lang),
                focus_resolver,
                inside_ids,
                body_names,
            )
            if lang_entry:
                out.localized_data[lang][bucket_key] = lang_entry

    if skipped_no_enrichment:
        logger.info(
            "Skipped %d features with no detail-tier enrichment (no QID, no images, "
            "no quadrangle, no SF parent)",
            skipped_no_enrichment,
        )

    _attach_inverse_lists(out, "satellite_features", sat_index, name_lookup_per_body)
    _attach_inverse_lists(out, "contains", contains_index, name_lookup_per_body)
    return out


def _build_focus_indices(
    session: Session,
    rows: list[Feature],
) -> tuple[FocusResolver, dict[str, dict[str, int]], dict[str, dict[int, str]]]:
    """Build QID→body and per-body QID→feature maps used by focus resolution.

    Also returns a per-body ``feature_id → name`` lookup, used downstream
    when attaching inverse lists and building same-body EntityRefs.
    """
    body_q = session.query(Object.id, Object.name, Object.wikidata_qid).filter(
        Object.wikidata_qid.isnot(None)
    )
    body_by_qid: dict[str, tuple[str, str | None]] = {}
    for object_id, name, qid in body_q:
        body_by_qid.setdefault(qid, (object_id, name))

    feature_qid_to_id_per_body: dict[str, dict[str, int]] = {}
    feature_by_qid_per_body: dict[str, dict[str, tuple[int, str]]] = {}
    name_lookup_per_body: dict[str, dict[int, str]] = {}
    for f in rows:
        assert f.object_id is not None
        canonical = f.unicode_name or f.name
        name_lookup_per_body.setdefault(f.object_id, {})[f.feature_id] = canonical
        if f.wikidata_qid:
            feature_qid_to_id_per_body.setdefault(f.object_id, {})[f.wikidata_qid] = (
                f.feature_id
            )
            feature_by_qid_per_body.setdefault(f.object_id, {})[f.wikidata_qid] = (
                f.feature_id,
                canonical,
            )

    return (
        FocusResolver(body_by_qid, feature_by_qid_per_body),
        feature_qid_to_id_per_body,
        name_lookup_per_body,
    )


def _attach_inverse_lists(
    out: FeatureDetailData,
    field: str,
    index: dict[tuple[str, int], set[int]],
    name_lookup_per_body: dict[str, dict[int, str]],
) -> None:
    """Attach a sorted EntityRef[] list under ``field`` to each parent's global entry.

    Parents without other enrichment but with children get a minimal
    global entry created here so the list still ships.
    """
    for (body_id, parent_fid), child_set in index.items():
        names = name_lookup_per_body.get(body_id, {})
        sorted_children = sorted(
            (cid for cid in child_set if cid in names),
            key=lambda cid: names[cid],
        )
        if not sorted_children:
            continue
        parent_key = feature_bucket_key(body_id, parent_fid)
        entry = out.global_data.setdefault(parent_key, {})
        entry[field] = [
            make_feature_entityref(body_id, cid, names[cid]).to_dict()
            for cid in sorted_children
        ]


# -- Spatial containment (bbox + radius) -------------------------------------


def _container_candidates_per_body(rows: list[Feature]) -> dict[str, list[Feature]]:
    """Group features that could act as containers (bbox OR center+diameter).

    Tiny bbox-only features are filtered out (sub-degree placeholders),
    as are 1D/point feature types — see ``_NON_CONTAINER_TYPES``.
    """
    out: dict[str, list[Feature]] = {}
    for f in rows:
        if f.feature_type_code in _NON_CONTAINER_TYPES:
            continue
        has_bbox = (
            f.min_lat is not None
            and f.max_lat is not None
            and f.min_lon is not None
            and f.max_lon is not None
            and _bbox_area(f.min_lat, f.max_lat, f.min_lon, f.max_lon)
            >= _MIN_CONTAINER_BBOX_AREA
        )
        has_circle = (
            f.center_lat is not None
            and f.center_lon is not None
            and f.diameter is not None
            and f.diameter > 0.0
        )
        if has_bbox or has_circle:
            assert f.object_id is not None
            out.setdefault(f.object_id, []).append(f)
    return out


def _bbox_contains(
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    p_lat: float,
    p_lon: float,
) -> bool:
    """Point-in-rectangle on a sphere; ``lon_min > lon_max`` means antimeridian-crossing."""
    if not (lat_min <= p_lat <= lat_max):
        return False
    if lon_min <= lon_max:
        return lon_min <= p_lon <= lon_max
    return p_lon >= lon_min or p_lon <= lon_max


def _bbox_area(lat_min: float, lat_max: float, lon_min: float, lon_max: float) -> float:
    """Rough deg² with cosine-of-midlat correction — good enough for ranking."""
    lat_span = lat_max - lat_min
    if lon_min <= lon_max:
        lon_span = lon_max - lon_min
    else:
        lon_span = (360.0 - lon_min) + lon_max
    midlat = (lat_min + lat_max) / 2.0
    return lat_span * lon_span * math.cos(math.radians(midlat))


def _haversine_km(
    lat1: float, lon1: float, lat2: float, lon2: float, radius_km: float
) -> float:
    """Great-circle distance between two lat/lon points on a sphere of *radius_km*."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    )
    return 2.0 * radius_km * math.asin(min(1.0, math.sqrt(a)))


def _circle_area_deg2(diameter_km: float, body_radius_km: float) -> float:
    """Approximate area of a feature's circular footprint, in deg² on its body."""
    angular_r_deg = (diameter_km / 2.0) / body_radius_km * (180.0 / math.pi)
    return math.pi * angular_r_deg * angular_r_deg


def _container_metrics(
    c: Feature, body_radius_km: float | None
) -> tuple[float, bool] | None:
    """Return ``(area_deg2, is_bbox)`` for a candidate container, or None if unusable.

    Bbox wins when present (more precise than a circle approximation);
    falls back to (center, diameter) when only the circle is available.
    """
    if (
        c.min_lat is not None
        and c.max_lat is not None
        and c.min_lon is not None
        and c.max_lon is not None
    ):
        return _bbox_area(c.min_lat, c.max_lat, c.min_lon, c.max_lon), True
    if (
        body_radius_km is not None
        and c.center_lat is not None
        and c.center_lon is not None
        and c.diameter is not None
        and c.diameter > 0.0
    ):
        return _circle_area_deg2(c.diameter, body_radius_km), False
    return None


def _spatial_inside_of(
    feature: Feature,
    candidates: list[Feature],
    body_radius_km: float | None,
) -> list[tuple[int, str]]:
    """Containers whose bbox/circle contains ``feature.center``, with source tag.

    Same-type candidates collapse to the smallest (most precise). When
    the feature itself has bbox or circle, candidates must be strictly
    larger — keeps a small bright spot from claiming a giant region as
    its parent just because both happen to overlap.
    Returns ``[(feature_id, "bbox" | "radius"), …]``.
    """
    if feature.center_lat is None or feature.center_lon is None:
        return []

    feature_area: float | None = None
    if (
        feature.min_lat is not None
        and feature.max_lat is not None
        and feature.min_lon is not None
        and feature.max_lon is not None
    ):
        feature_area = _bbox_area(
            feature.min_lat, feature.max_lat, feature.min_lon, feature.max_lon
        )
    elif (
        body_radius_km is not None
        and feature.diameter is not None
        and feature.diameter > 0.0
    ):
        feature_area = _circle_area_deg2(feature.diameter, body_radius_km)

    best_by_type: dict[str, tuple[int, float, str]] = {}
    for c in candidates:
        if c.feature_id == feature.feature_id:
            continue
        metrics = _container_metrics(c, body_radius_km)
        if metrics is None:
            continue
        c_area, c_has_bbox = metrics
        if feature_area is not None and c_area <= feature_area:
            continue

        if c_has_bbox:
            assert c.min_lat is not None
            assert c.max_lat is not None
            assert c.min_lon is not None
            assert c.max_lon is not None
            inside = _bbox_contains(
                c.min_lat,
                c.max_lat,
                c.min_lon,
                c.max_lon,
                feature.center_lat,
                feature.center_lon,
            )
            source = "bbox"
        else:
            assert c.center_lat is not None
            assert c.center_lon is not None
            assert c.diameter is not None
            assert body_radius_km is not None
            d_km = _haversine_km(
                c.center_lat,
                c.center_lon,
                feature.center_lat,
                feature.center_lon,
                body_radius_km,
            )
            inside = d_km <= c.diameter / 2.0
            source = "radius"

        if not inside:
            continue

        type_code = c.feature_type_code or ""
        prev = best_by_type.get(type_code)
        if prev is None or c_area < prev[1]:
            best_by_type[type_code] = (c.feature_id, c_area, source)
    return [(fid, src) for fid, _, src in best_by_type.values()]


def _build_detail_global(
    feature: Feature,
    extracted: dict,
    images: list[dict] | None,
    units: UnitConverter,
    wikidata_entities: WikidataEntityCache,
    name_lookup_per_body: dict[str, dict[int, str]],
) -> dict:
    """Build the per-language-independent payload for one feature."""
    data: dict = {}
    if feature.approval_date:
        data["approval_date"] = feature.approval_date.isoformat()
    if feature.origin:
        data["origin"] = _TRAILING_ORIGIN_DOT_RE.sub("", feature.origin)
    if feature.wikidata_qid:
        data["wikidata_qid"] = feature.wikidata_qid
        # Prominence key: ranks features notable-first in search member lists
        # (a feature-type page lists Tycho before a bigger anonymous crater).
        wd = wikidata_entities.get_feature_entity(feature.wikidata_qid)
        if wd and wd["sitelinks"]:
            data["sitelinks_count"] = len(wd["sitelinks"])
    if feature.parent_feature_id is not None:
        assert feature.object_id is not None
        parent_name = name_lookup_per_body.get(feature.object_id, {}).get(
            feature.parent_feature_id
        )
        if parent_name is not None:
            data["parent_feature"] = make_feature_entityref(
                feature.object_id, feature.parent_feature_id, parent_name
            ).to_dict()
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
    wd: WikidataEntity | None,
    extracted: dict,
    wikidata_entities: WikidataEntityCache,
    wiki_summary: WikipediaSummary | None,
    focus_resolver: FocusResolver,
    inside_feature_ids: set[int],
    body_name_lookup: dict[int, str],
) -> dict:
    """Build the per-language payload for one feature."""
    data: dict = {}
    if wd is not None:
        desc = wd["descriptions"].get(lang)
        if desc:
            data["description"] = desc
        aliases = wd["aliases"].get(lang)
        if aliases:
            data["aliases"] = aliases

        for claim in FEATURE_ENTITY_REF_CLAIMS:
            if claim.key in _SPATIAL_CLAIM_KEYS or claim.key not in extracted:
                continue
            if claim.multiple:
                refs = [
                    r.to_dict()
                    for qid in extracted[claim.key]
                    if (r := resolve_entity_ref(qid, lang, wikidata_entities))
                ]
                if refs:
                    data[claim.key] = refs
            else:
                ref = resolve_entity_ref(extracted[claim.key], lang, wikidata_entities)
                if ref:
                    data[claim.key] = ref.to_dict()

    inside_of = _build_inside_of(
        feature,
        lang,
        extracted,
        wikidata_entities,
        focus_resolver,
        inside_feature_ids,
        body_name_lookup,
    )
    if inside_of:
        data["inside_of"] = inside_of

    if feature.quad_code and feature.quad_name:
        assert feature.object_id is not None
        wiki_url: str | None = None
        quad_qid = QUADRANGLE_QIDS.get((feature.object_id, feature.quad_code))
        if quad_qid is not None:
            quad_wd = wikidata_entities.get_referenced(quad_qid)
            if quad_wd:
                title = quad_wd["sitelinks"].get(lang)
                if title:
                    wiki_url = f"https://{lang}.wikipedia.org/wiki/{quote(title)}"
        data["quadrangle"] = EntityRef(
            name=feature.quad_name,
            short_name=feature.quad_code,
            wikipedia=wiki_url,
        ).to_dict()

    if wiki_summary is not None:
        data["wikipedia"] = wiki_summary.to_dict()

    return data


def _build_inside_of(
    feature: Feature,
    lang: str,
    extracted: dict,
    wikidata_entities: WikidataEntityCache,
    focus_resolver: FocusResolver,
    inside_feature_ids: set[int],
    body_name_lookup: dict[int, str],
) -> list[dict]:
    """Merge Wikidata (P706/P361) + bbox-derived containers into one EntityRef[].

    Wikidata refs may resolve to bodies, features, or unmapped concepts;
    bbox-derived refs always target same-body features. Dedup is keyed by
    (primary/secondary id, name) so duplicate sources collapse cleanly.
    The IAU SF parent is excluded — that lives in ``parent_feature``.
    """
    assert feature.object_id is not None
    refs: list[dict] = []
    seen: set[tuple[str | None, str | None, str | None, str | None, str]] = set()
    parent_fid_str = (
        str(feature.parent_feature_id)
        if feature.parent_feature_id is not None
        else None
    )

    def _add(ref: EntityRef) -> None:
        if (
            ref.secondary_type == "feature"
            and parent_fid_str is not None
            and ref.secondary_id == parent_fid_str
        ):
            return
        key = (
            ref.primary_type,
            ref.primary_id,
            ref.secondary_type,
            ref.secondary_id,
            ref.name,
        )
        if key in seen:
            return
        seen.add(key)
        refs.append(ref.to_dict())

    for claim_key in INSIDE_OF_CLAIM_KEYS:
        for qid in extracted.get(claim_key, []):
            ref = resolve_entity_ref(
                qid,
                lang,
                wikidata_entities,
                focus_resolver=focus_resolver,
                focus_body_id=feature.object_id,
            )
            if ref is not None:
                _add(ref)

    for fid in sorted(inside_feature_ids, key=lambda i: body_name_lookup.get(i, "")):
        name = body_name_lookup.get(fid)
        if name is None:
            continue
        _add(make_feature_entityref(feature.object_id, fid, name))

    return refs


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
