"""Notable surface features per body, attached to the object detail bundle.

Feeds the body's Features tab: a count plus top features to show before (or
without) the search backend, ranked the same way as the ``ft-`` type pages
so a feature sits consistently in both.
"""

import logging

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.nomenclature.notable import (
    feature_sitelinks,
    rank_notable_features,
)
from space_map_data.export.notable import notable_entries, notable_names
from space_map_data.export.objects.writer import ChunkObjectData
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.models.feature import Feature

logger = logging.getLogger(__name__)


def attach_notable_features(
    chunk: ChunkObjectData,
    nomenclature_by_body: dict[str, list[Feature]],
    wikidata_entities: WikidataEntityCache,
) -> None:
    """Inject ``feature_count`` + ``notable_features`` into each body's bundle.

    Mutates ``chunk`` in place (mirrors ``attach_notable_moons``), reusing the
    per-body feature lists the nomenclature tier already built.
    """
    attached = 0
    missing: list[str] = []
    for body_id, features in nomenclature_by_body.items():
        global_data = chunk.global_data.get(body_id)
        if global_data is None:
            missing.append(body_id)
            continue
        members = rank_notable_features(
            [(feature_sitelinks(f, wikidata_entities), f) for f in features]
        )
        entries = notable_entries(members, wikidata_entities)
        global_data["feature_count"] = len(features)
        global_data["notable_features"] = entries
        for lang in LANGUAGES:
            localized = chunk.localized_data.get(lang, {}).get(body_id)
            if localized is None:
                continue
            names = notable_names(members, entries, lang, wikidata_entities)
            if names:
                localized["notable_feature_names"] = names
        attached += 1
    if missing:
        logger.warning(
            "%d body/bodies have nomenclature but no object bundle; no Features "
            "tab for them: %s",
            len(missing),
            ", ".join(sorted(missing)),
        )
    logger.info("Attached notable surface features to %d bodies", attached)
