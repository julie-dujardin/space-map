"""IAU nomenclature stats for feature-type (``ft-``) group pages.

One page per 2-letter IAU descriptor code: how many features of that kind
exist, which bodies carry them, the largest example, and when the IAU approved
the names. Members are surface features, so they route to
``/b/<body>/f/<feature_id>`` rather than focusing an object.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from space_map_data.constants.categories import SURFACE_FEATURES_SLUG
from space_map_data.constants.nomenclature.families import FEATURE_FAMILY_CODES
from space_map_data.constants.nomenclature.feature_types import (
    FEATURE_TYPE_SLUGS,
    FEATURE_TYPES,
)
from space_map_data.export.nomenclature.notable import (
    feature_sitelinks,
    rank_notable_features,
)
from space_map_data.export.nomenclature.writer import renderable_feature_filter
from space_map_data.export.notable import NotableObject
from space_map_data.export.objects.wikidata_claims import make_feature_entityref
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.models.feature import Feature
from space_map_data.models.object.main import Object

logger = logging.getLogger(__name__)

# Etymology rows on the meta page. The IAU records 360 distinct origins; the
# tail is one-offs, and every group page pays for this bundle.
TOP_ORIGINS = 60


def _families(member_counts: dict[str, int]) -> list[dict]:
    """Landform families with their type slugs, most-populated type first.

    Families keep the constants' narrative order. Unused types (and so empty
    families) are dropped — they carry no chip in ``child_groups`` either, so
    the frontend would have no name to render.
    """
    out: list[dict] = []
    for family, codes in FEATURE_FAMILY_CODES.items():
        slugs = sorted(
            (
                slug
                for code in codes
                if member_counts.get(slug := FEATURE_TYPE_SLUGS[code], 0) > 0
            ),
            key=lambda slug: (-member_counts[slug], slug),
        )
        if slugs:
            out.append(
                {
                    "key": family,
                    "n": sum(member_counts[slug] for slug in slugs),
                    "types": slugs,
                }
            )
    return out


@dataclass
class FeatureTypeStats:
    """Per-type roll-up consumed by the ft- group bundle.

    The Surface Features meta category rides the same struct for its own page;
    ``type_count`` / ``families`` / ``naming_origins`` are meta-only.
    """

    feature_count: int = 0
    body_count: int = 0
    # Meta node only: how many types have at least one feature (= its chips).
    type_count: int = 0
    # Meta node only: landform families, in the constants' narrative order —
    # [{key, n, types: [ft- slug, most features first]}].
    families: list[dict] = field(default_factory=list)
    # Meta node only: name-etymology tally, most-named first: [{name, n}].
    naming_origins: list[dict] = field(default_factory=list)
    # Bar-chart rows, most features first: {name, primary_type, primary_id, n}.
    bodies: list[dict] = field(default_factory=list)
    # Biggest named example, as an EntityRef + its diameter.
    largest: dict | None = None
    first_approval: str | None = None  # ISO date
    last_approval: str | None = None
    approval_histogram: dict[int, int] = field(default_factory=dict)
    # Chart-row body id -> Wikidata QID, so the bundle can localize row labels.
    body_qids: dict[str, str] = field(default_factory=dict)


@dataclass
class FeatureTypeGroups:
    """Everything the group tier needs for the ft- pages."""

    stats: dict[str, FeatureTypeStats] = field(default_factory=dict)
    member_counts: dict[str, int] = field(default_factory=dict)
    notable_members: dict[str, list[NotableObject]] = field(default_factory=dict)


def build_feature_type_groups(
    session: Session, wikidata_entities: WikidataEntityCache
) -> FeatureTypeGroups:
    """Stats + notable members for every ft- page, keyed by group slug."""
    by_code: dict[str, list[tuple[int, Feature]]] = defaultdict(list)
    unknown_codes: dict[str, int] = defaultdict(int)
    origins: dict[str, int] = defaultdict(int)
    for f in session.query(Feature).filter(*renderable_feature_filter()).all():
        assert f.feature_type_code is not None  # SQL filter guarantees this
        if f.feature_type_code not in FEATURE_TYPES:
            unknown_codes[f.feature_type_code] += 1
            continue
        by_code[f.feature_type_code].append(
            (feature_sitelinks(f, wikidata_entities), f)
        )
        if f.ethnicity:
            origins[f.ethnicity] += 1
    if unknown_codes:
        logger.warning(
            "Skipped features with codes missing from FEATURE_TYPES: %s",
            ", ".join(f"{c}={n}" for c, n in sorted(unknown_codes.items())),
        )

    body_ids = {f.object_id for entries in by_code.values() for _, f in entries}
    bodies = {
        object_id: (name, qid)
        for object_id, name, qid in session.query(
            Object.id, Object.name, Object.wikidata_qid
        ).filter(Object.id.in_(body_ids))
    }

    out = FeatureTypeGroups()
    empty: list[str] = []
    all_approvals: dict[int, int] = defaultdict(int)
    for code in FEATURE_TYPES:
        slug = FEATURE_TYPE_SLUGS[code]
        entries = by_code.get(code, [])
        if not entries:
            # Defined by the IAU but unused in the current gazetteer; the page
            # still exists (Wikidata description + IAU definition), just empty.
            empty.append(code)
            out.stats[slug] = FeatureTypeStats()
            out.member_counts[slug] = 0
            continue

        per_body: dict[str, int] = defaultdict(int)
        histogram: dict[int, int] = defaultdict(int)
        approvals: list[str] = []
        largest: Feature | None = None
        for _, f in entries:
            assert f.object_id is not None  # SQL filter guarantees this
            per_body[f.object_id] += 1
            if f.approval_date:
                histogram[f.approval_date.year] += 1
                all_approvals[f.approval_date.year] += 1
                approvals.append(f.approval_date.isoformat())
            if f.diameter and (largest is None or f.diameter > (largest.diameter or 0)):
                largest = f

        top_bodies = sorted(per_body.items(), key=lambda kv: (-kv[1], kv[0]))
        largest_ref = None
        if largest is not None:
            assert largest.object_id is not None
            largest_ref = make_feature_entityref(
                largest.object_id, largest.feature_id, largest.name
            ).to_dict()
            largest_ref["diameter_km"] = largest.diameter

        out.stats[slug] = FeatureTypeStats(
            feature_count=len(entries),
            body_count=len(per_body),
            bodies=[
                {
                    "name": bodies[object_id][0],
                    "primary_type": "object",
                    "primary_id": object_id,
                    "n": n,
                }
                for object_id, n in top_bodies
            ],
            largest=largest_ref,
            first_approval=min(approvals) if approvals else None,
            last_approval=max(approvals) if approvals else None,
            approval_histogram=dict(sorted(histogram.items())),
            body_qids={
                object_id: qid
                for object_id, _ in top_bodies
                if (qid := bodies[object_id][1])
            },
        )
        out.member_counts[slug] = len(entries)
        out.notable_members[slug] = rank_notable_features(entries)

    # The meta category's own page: stat cards, family grouping for its 57
    # chips, whole-gazetteer naming timeline + etymology chart. Deliberately
    # absent from ``member_counts``: the category tier sums that map for its
    # member total. No first/last approval — three stat cards is the row.
    ranked_origins = sorted(origins.items(), key=lambda kv: (-kv[1], kv[0]))
    out.stats[SURFACE_FEATURES_SLUG] = FeatureTypeStats(
        feature_count=sum(out.member_counts.values()),
        body_count=len(body_ids),
        type_count=len(FEATURE_TYPES) - len(empty),
        families=_families(out.member_counts),
        naming_origins=[
            {"name": name, "n": n} for name, n in ranked_origins[:TOP_ORIGINS]
        ],
        approval_histogram=dict(sorted(all_approvals.items())),
    )
    if len(ranked_origins) > TOP_ORIGINS:
        dropped = sum(n for _, n in ranked_origins[TOP_ORIGINS:])
        logger.info(
            "Naming origins: kept the top %d of %d (%d features in the %d-origin "
            "tail are not charted)",
            TOP_ORIGINS,
            len(ranked_origins),
            dropped,
            len(ranked_origins) - TOP_ORIGINS,
        )

    logger.info(
        "Feature-type group pages: %d types (%d with no features: %s), %d features "
        "on %d bodies",
        len(FEATURE_TYPES),
        len(empty),
        ", ".join(empty) if empty else "[]",
        sum(out.member_counts.values()),
        len(body_ids),
    )
    return out
