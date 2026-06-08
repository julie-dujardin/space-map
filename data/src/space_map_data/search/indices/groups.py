"""Object-groups search index.

Source files:

    v1/groups/__global__/{bucket}.json.gz   — slug + type + member_count
    v1/groups/{lang}/{bucket}.json.gz       — per-language name/description

One document per group, all language variants on the same document. The
index is small (~hundreds of constellations), so we slurp every bundle.
"""

import gzip
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from space_map_data.constants.providers import LANGUAGES

from .features import Index, pick_thumbnail

logger = logging.getLogger(__name__)


def _load_bundles(
    groups_dir: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, dict[str, Any]]]]:
    """Return ``(global_by_slug, localized_by_lang_by_slug)`` from the export."""
    global_dir = groups_dir / "__global__"
    global_by_slug: dict[str, dict[str, Any]] = {}
    if global_dir.exists():
        for bundle in sorted(global_dir.glob("*.json.gz")):
            global_by_slug.update(json.loads(gzip.decompress(bundle.read_bytes())))

    localized: dict[str, dict[str, dict[str, Any]]] = {}
    for lang in LANGUAGES:
        lang_dir = groups_dir / lang
        merged: dict[str, dict[str, Any]] = {}
        if lang_dir.exists():
            for bundle in sorted(lang_dir.glob("*.json.gz")):
                merged.update(json.loads(gzip.decompress(bundle.read_bytes())))
        localized[lang] = merged
    return global_by_slug, localized


def _build_group_documents(export_dir: Path) -> Iterator[dict[str, Any]]:
    groups_dir = export_dir / "v1" / "groups"
    if not groups_dir.exists():
        logger.warning("No group bundles at %s — nothing to index", groups_dir)
        return

    global_by_slug, localized = _load_bundles(groups_dir)
    logger.info("Indexing %d groups", len(global_by_slug))

    for slug, g in global_by_slug.items():
        # Canonical name = English wikidata label, falling back to slug so
        # the doc is always renderable.
        canonical = (localized.get("en", {}).get(slug, {}) or {}).get("name") or slug
        doc: dict[str, Any] = {
            "slug": slug,
            "name": canonical,
            "type": g["type"],
            "applies_to": g["applies_to"],
            "member_count": g.get("member_count", 0),
        }
        thumb = pick_thumbnail(g.get("images"))
        if thumb:
            doc["thumbnail"] = thumb
        for lang in LANGUAGES:
            entry = localized[lang].get(slug)
            if not entry:
                continue
            name = entry.get("name")
            if name:
                doc[f"name_{lang}"] = name
            description = entry.get("description")
            if description:
                doc[f"description_{lang}"] = description
        yield doc


def _groups_settings() -> dict[str, Any]:
    name_fields = ["name"] + [f"name_{lang}" for lang in LANGUAGES]
    description_fields = [f"description_{lang}" for lang in LANGUAGES]
    return {
        # slug last so it's a fallback for users who type the URL form
        # ("starlink") when there's no localized name yet.
        "searchableAttributes": name_fields + description_fields + ["slug"],
        "filterableAttributes": ["type", "applies_to"],
        "sortableAttributes": ["member_count"],
        "localizedAttributes": [
            {
                "locales": [lang],
                "attributePatterns": [f"name_{lang}", f"description_{lang}"],
            }
            for lang in LANGUAGES
        ],
        # Bigger constellations break ties — Starlink beats a tiny operator
        # group when both fuzzy-match a partial query.
        "rankingRules": [
            "words",
            "typo",
            "proximity",
            "attribute",
            "sort",
            "exactness",
            "member_count:desc",
        ],
    }


class GroupsIndex(Index):
    def build_documents(self, export_dir: Path) -> Iterator[dict[str, Any]]:
        return _build_group_documents(export_dir)


GROUPS_INDEX = GroupsIndex(
    uid="groups",
    primary_key="slug",
    settings=_groups_settings(),
)
