"""Wikidata entity loading, types, and name resolution."""

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import TypedDict

from space_map_data.models.object import Object
from space_map_data.utils.paths import DOWNLOAD_DIR

logger = logging.getLogger(__name__)


class WikidataEntity(TypedDict):
    labels: dict[str, str]  # lang → name
    descriptions: dict[str, str]  # lang → short description
    aliases: dict[str, list[str]]  # lang → alternative names
    claims: dict  # raw claims from entity JSON
    sitelinks: dict[str, str]  # lang → Wikipedia article title


def load_json_dir(directory: Path, glob: str = "Q*.json") -> Iterator[tuple[str, dict]]:
    """Yield (stem, parsed_json) for each JSON file matching *glob* in *directory*.

    Skips files that fail to parse and logs an error for each.
    """
    if not directory.exists():
        return
    for path in directory.glob(glob):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load %s: %s", path, exc)
            continue
        yield path.stem, data


def load_wikidata_entities() -> dict[str, WikidataEntity]:
    """Load Wikidata entities into {qid: WikidataEntity} dict."""
    wikidata_dir = DOWNLOAD_DIR / "wikidata"
    entity_dirs = [wikidata_dir / d for d in ("entities", "referenced", "units")]
    if not any(d.exists() for d in entity_dirs):
        logger.info("No wikidata entities found, labels will use object names only")
        return {}

    result: dict[str, WikidataEntity] = {}
    for entity_dir in entity_dirs:
        for qid, entity in load_json_dir(entity_dir):
            labels = _extract_lang_values(entity.get("labels", {}))
            descriptions = _extract_lang_values(entity.get("descriptions", {}))
            aliases = _extract_lang_aliases(entity.get("aliases", {}))
            claims = entity.get("claims", {})
            sitelinks = _extract_sitelinks(entity.get("sitelinks", {}))

            if labels or descriptions or aliases or claims:
                result[qid] = WikidataEntity(
                    labels=labels,
                    descriptions=descriptions,
                    aliases=aliases,
                    claims=claims,
                    sitelinks=sitelinks,
                )

    logger.info("Loaded %d Wikidata entities", len(result))
    return result


def resolve_name(
    obj: Object,
    lang: str,
    wikidata_entities: dict[str, WikidataEntity],
) -> str | None:
    """Resolve the best available name for an object in a given language."""
    if obj.wikidata_qid and obj.wikidata_qid in wikidata_entities:
        labels = wikidata_entities[obj.wikidata_qid]["labels"]
        if lang in labels:
            return labels[lang]
        if "en" in labels:
            return labels["en"]

    return obj.name


def _extract_lang_values(data: dict) -> dict[str, str]:
    """Extract {lang: value} from Wikidata labels/descriptions format."""
    result: dict[str, str] = {}
    for lang_code, obj in data.items():
        if isinstance(obj, dict) and "value" in obj:
            result[lang_code] = obj["value"]
        elif isinstance(obj, str):
            result[lang_code] = obj
    return result


def _extract_lang_aliases(
    data: dict[str, list[dict[str, str]]],
) -> dict[str, list[str]]:
    """Extract {lang: [alias, ...]} from Wikidata aliases format."""
    result: dict[str, list[str]] = {}
    for lang_code, alias_list in data.items():
        values = [a["value"] for a in alias_list if "value" in a]
        if values:
            result[lang_code] = values
    return result


def _extract_sitelinks(data: dict) -> dict[str, str]:
    """Extract {lang: article_title} from Wikidata sitelinks."""
    result: dict[str, str] = {}
    for site_key, link in data.items():
        if site_key.endswith("wiki") and isinstance(link, dict) and "title" in link:
            lang = site_key[: -len("wiki")]
            if lang:  # skip "commonswiki" etc. where lang would be "commons"
                result[lang] = link["title"]
    return result
