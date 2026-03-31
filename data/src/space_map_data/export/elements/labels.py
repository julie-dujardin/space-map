"""Write element_labels/<lang>.json files."""

import logging
from pathlib import Path

from space_map_data.export.wikidata import WikidataEntity, resolve_name
from space_map_data.models.object import Object

logger = logging.getLogger(__name__)


def write_labels(
    objects: list[Object],
    out_file: Path,
    lang: str,
    wikidata_entities: dict[str, WikidataEntity],
) -> None:
    """Write a single label JSON file for one language and chunk.

    Fallback chain: Wikidata label (target lang) → Wikidata label (en) → object.name.
    """
    labels = []
    for obj in objects:
        name = resolve_name(obj, lang, wikidata_entities)
        labels.append(name or "")

    out_file.write_text("\n".join(labels))
    named = sum(1 for label in labels if label)
    logger.info("Wrote %d/%d labels to %s", named, len(labels), out_file)
