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
    chunk_entities: dict[str, WikidataEntity | None],
) -> None:
    """Write a single label JSON file for one language and chunk.

    Fallback chain: Wikidata label (target lang) → Wikidata label (en) → object.name.
    """
    labels = []
    for obj in objects:
        # Name: prefer localized name, else english name (handled by resolve_name), else provider name or primary designation or provisional designation
        # In practice, this covers everything.
        name = (
            (
                resolve_name(obj, lang, chunk_entities.get(obj.wikidata_qid))
                if obj.wikidata_qid
                else None
            )
            or obj.name
            or obj.sbdb_mcp_designation
            or obj.provisional_designation
        )
        if not name:
            logger.warning("No name found for object %s (id=%s)", obj, obj.id)
            name = ""
        labels.append(name)

    out_file.write_text("\n".join(labels))
    named = sum(1 for label in labels if label)
    logger.info("Wrote %d/%d labels to %s", named, len(labels), out_file)
