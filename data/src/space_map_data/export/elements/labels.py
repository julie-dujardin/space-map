"""Write element_labels/<lang>.json files."""

import json
import logging
from pathlib import Path

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.wikidata import WikidataEntity, resolve_name
from space_map_data.models.object import Object

logger = logging.getLogger(__name__)


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
