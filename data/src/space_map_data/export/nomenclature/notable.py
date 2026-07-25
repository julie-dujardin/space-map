"""Prominence ranking for surface features.

Shared by the ``ft-`` type pages and each body's own Features tab so both list
the same features in the same order.
"""

from space_map_data.export.notable import NotableObject
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.models.feature import Feature

# Members shown in a notable strip before the paginated list takes over.
NOTABLE_FEATURES = 20


def feature_sitelinks(feature: Feature, wikidata_entities: WikidataEntityCache) -> int:
    if not feature.wikidata_qid:
        return 0
    wd = wikidata_entities.get_feature_entity(feature.wikidata_qid)
    return len(wd["sitelinks"]) if wd else 0


def rank_notable_features(
    features: list[tuple[int, Feature]], limit: int = NOTABLE_FEATURES
) -> list[NotableObject]:
    """Top features from ``(sitelinks, feature)`` pairs, most prominent first.

    Prominence is the feature's own Wikidata sitelink count (Tycho over a
    bigger but anonymous crater), with diameter as the tiebreaker — and as the
    only signal for the ~44% of features with no Wikidata item.
    """
    ranked = sorted(
        features, key=lambda e: (-e[0], -(e[1].diameter or 0.0), e[1].feature_id)
    )
    return [
        NotableObject(
            object_id=f.object_id or "",
            wikidata_qid=f.wikidata_qid,
            fallback_name=f.name,
            diameter_km=f.diameter or None,
            first_obs=f.approval_date.isoformat() if f.approval_date else None,
            feature_id=f.feature_id,
            sitelinks_count=sitelinks or None,
        )
        for sitelinks, f in ranked[:limit]
    ]
