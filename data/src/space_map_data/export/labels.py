"""Write element_labels/<lang>.json files and load Wikidata entities."""

import json
import logging
from pathlib import Path
from typing import TypedDict

from space_map_data.download.providers.wikipedia import LANGUAGES
from space_map_data.models.object import Object
from space_map_data.utils.paths import DOWNLOAD_DIR

logger = logging.getLogger(__name__)


class WikidataEntity(TypedDict):
    labels: dict[str, str]  # lang → name
    descriptions: dict[str, str]  # lang → short description
    aliases: dict[str, list[str]]  # lang → alternative names
    claims: dict  # raw claims from entity JSON
    sitelinks: dict[str, str]  # lang → Wikipedia article title


def load_wikidata_entities() -> dict[str, WikidataEntity]:
    """Load Wikidata entities into {qid: WikidataEntity} dict."""
    entities_dir = DOWNLOAD_DIR / "wikidata" / "entities"
    if not entities_dir.exists():
        logger.info("No wikidata entities found, labels will use object names only")
        return {}

    result: dict[str, WikidataEntity] = {}
    for entity_file in entities_dir.glob("Q*.json"):
        qid = entity_file.stem
        try:
            entity = json.loads(entity_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue

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


def _extract_lang_values(data: dict) -> dict[str, str]:
    """Extract {lang: value} from Wikidata labels/descriptions format."""
    result: dict[str, str] = {}
    for lang_code, obj in data.items():
        if isinstance(obj, dict) and "value" in obj:
            result[lang_code] = obj["value"]
        elif isinstance(obj, str):
            result[lang_code] = obj
    return result


def _extract_lang_aliases(data: object) -> dict[str, list[str]]:
    """Extract {lang: [alias, ...]} from Wikidata aliases format."""
    if not isinstance(data, dict):
        return {}
    result: dict[str, list[str]] = {}
    for lang_code, alias_list in data.items():
        if isinstance(alias_list, list):
            values = [
                a["value"] for a in alias_list if isinstance(a, dict) and "value" in a
            ]
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


def write_labels(
    objects: list[Object],
    out_dir: Path,
    wikidata_entities: dict[str, WikidataEntity],
) -> None:
    """Write per-language label JSON files.

    Each file maps eid (string) → localized name.
    Fallback chain: Wikidata label (target lang) → Wikidata label (en) → object.name.
    """
    labels_dir = out_dir / "element_labels"
    labels_dir.mkdir(parents=True, exist_ok=True)

    for lang in LANGUAGES:
        labels: dict[str, str] = {}
        for eid, obj in enumerate(objects):
            name = resolve_name(obj, lang, wikidata_entities)
            if name:
                labels[str(eid)] = name

        out_file = labels_dir / f"{lang}.json"
        out_file.write_text(json.dumps(labels, ensure_ascii=False))
        logger.info("Wrote %d labels to %s", len(labels), out_file.name)


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
