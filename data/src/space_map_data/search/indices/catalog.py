"""Unified catalog search index.

A single Meili index over every searchable entity — objects, surface features,
and group/collection pages — discriminated by the root ``kind`` field. Shared
fields (name, descriptions, thumbnail, diameter_km, sitelinks_count) live at the
document root; per-kind fields nest under ``object`` / ``feature`` / ``group``
(see base.py for the primary-key scheme).

Cross-kind ranking leans on ``sitelinks_count`` (Wikidata prominence) as the
sole tiebreaker after relevance, so the planet Earth outranks earth-related
groups without a blanket "objects first" rule.
"""

from collections.abc import Iterator
from itertools import chain
from pathlib import Path
from typing import Any

from space_map_data.constants.providers import LANGUAGES

from .base import Index
from .features import build_feature_documents
from .groups import build_group_documents
from .objects import build_object_documents


def _catalog_settings() -> dict[str, Any]:
    name_fields = ["name"] + [f"name_{lang}" for lang in LANGUAGES]
    alias_fields = [f"object.aliases_{lang}" for lang in LANGUAGES]
    description_fields = [f"description_{lang}" for lang in LANGUAGES]
    return {
        # Order matters — earlier attributes outrank later ones via the
        # "attribute" rule: name > aliases/designations > description, with the
        # group slug last as a URL-form fallback ("starlink").
        "searchableAttributes": (
            name_fields
            + alias_fields
            + ["object.designations"]
            + description_fields
            + ["group.slug"]
        ),
        "filterableAttributes": [
            "kind",
            "object.type",
            "object.parent_id",
            "object.groups",
            "object.neo",
            "object.pha",
            "object.ops_status",
            "object.render_quality",
            "object.magnitude",
            "object.inception",
            "group.type",
            "group.applies_to",
            "group.member_count",
            "group.orbit_classes",
            "feature.body_id",
            "feature.type",
            "feature.named",
            "diameter_km",
        ],
        "sortableAttributes": [
            "sitelinks_count",
            "diameter_km",
            "name",
            "object.magnitude",
            "object.inception",
            "group.member_count",
        ],
        "localizedAttributes": [
            {
                "locales": [lang],
                "attributePatterns": [
                    f"name_{lang}",
                    f"object.aliases_{lang}",
                    f"description_{lang}",
                ],
            }
            for lang in LANGUAGES
        ],
        # Relevance first; Wikidata prominence breaks ties across kinds, so a
        # prominent body wins over a niche group without a hard kind rule.
        "rankingRules": [
            "words",
            "typo",
            "proximity",
            "attribute",
            "sort",
            "exactness",
            "sitelinks_count:desc",
        ],
        # `object.groups` carries hundreds of slugs (constellations/operators);
        # the default cap of 100 would truncate facet distributions.
        "faceting": {"maxValuesPerFacet": 1000},
    }


class CatalogIndex(Index):
    def build_documents(self, export_dir: Path) -> Iterator[dict[str, Any]]:
        return chain(
            build_object_documents(export_dir),
            build_feature_documents(export_dir),
            build_group_documents(export_dir),
        )


CATALOG_INDEX = CatalogIndex(
    uid="catalog",
    primary_key="id",
    settings=_catalog_settings(),
)
