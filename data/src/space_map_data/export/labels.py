"""Write element_labels/<lang>.json files."""

import json
import logging
from pathlib import Path

from space_map_data.download.providers.wikipedia import LANGUAGES
from space_map_data.models.object import Object
from space_map_data.utils.paths import DOWNLOAD_DIR

logger = logging.getLogger(__name__)


def write_labels(objects: list[Object], out_dir: Path) -> None:
    """Write per-language label JSON files.

    Each file maps eid (string) → localized name.
    Fallback chain: Wikidata label (target lang) → Wikidata label (en) → object.name.
    """
    labels_dir = out_dir / "element_labels"
    labels_dir.mkdir(parents=True, exist_ok=True)

    # Build QID → labels lookup from wikidata entities (if available)
    qid_labels = _load_wikidata_labels()

    for lang in LANGUAGES:
        labels: dict[str, str] = {}
        for eid, obj in enumerate(objects):
            name = _resolve_name(obj, lang, qid_labels)
            if name:
                labels[str(eid)] = name

        out_file = labels_dir / f"{lang}.json"
        out_file.write_text(json.dumps(labels, ensure_ascii=False))
        logger.info("Wrote %d labels to %s", len(labels), out_file.name)


def _load_wikidata_labels() -> dict[str, dict[str, str]]:
    """Load Wikidata entity labels into {qid: {lang: label}} dict."""
    entities_dir = DOWNLOAD_DIR / "wikidata" / "entities"
    if not entities_dir.exists():
        logger.info("No wikidata entities found, labels will use object names only")
        return {}

    result: dict[str, dict[str, str]] = {}
    for entity_file in entities_dir.glob("Q*.json"):
        qid = entity_file.stem
        try:
            entity = json.loads(entity_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        labels_data = entity.get("labels", {})
        lang_map: dict[str, str] = {}
        for lang_code, label_obj in labels_data.items():
            if isinstance(label_obj, dict) and "value" in label_obj:
                lang_map[lang_code] = label_obj["value"]
            elif isinstance(label_obj, str):
                lang_map[lang_code] = label_obj
        if lang_map:
            result[qid] = lang_map

    logger.info("Loaded labels for %d Wikidata entities", len(result))
    return result


def _resolve_name(
    obj: Object,
    lang: str,
    qid_labels: dict[str, dict[str, str]],
) -> str | None:
    """Resolve the best available name for an object in a given language."""
    if obj.wikidata_qid and obj.wikidata_qid in qid_labels:
        labels = qid_labels[obj.wikidata_qid]
        # Try target language first, then English fallback
        if lang in labels:
            return labels[lang]
        if "en" in labels:
            return labels["en"]

    return obj.name
