"""Write element label files (gzip-compressed)."""

import gzip
import logging
from pathlib import Path

from space_map_data.export.wikidata import WikidataEntity, resolve_name
from space_map_data.models.object import Object

logger = logging.getLogger(__name__)


_US = "\x1f"  # ASCII Unit Separator — delimiter between flag and name


def write_labels(
    objects: list[Object],
    out_file: Path,
    lang: str,
    chunk_entities: dict[str, WikidataEntity | None],
    flags: dict[str, int],
) -> None:
    """Write a single label file for one language and chunk.

    Format: one "{flag}{US}{name}" line per object, where US is ASCII Unit Separator (0x1F).
    Flag values: 0 = no object file, 1 = localized file, 2 = English fallback file.

    Name fallback chain (for map display): Wikidata label (target lang) → Wikidata label (en) → object.name.
    """
    lines = []
    for obj in objects:
        # Name: full fallback chain so the map always shows something
        qid = obj.wikidata_qid or (obj.satcat.wikidata_qid if obj.celestrak_norad_cat_id is not None and obj.satcat else None)
        name = (
            (resolve_name(obj, lang, chunk_entities.get(qid)) if qid else None)
            or obj.name
            or obj.sbdb_mcp_designation
            or obj.provisional_designation
            or obj.horizons_naif_id
        )
        if not name:
            raise ValueError(f"No name found for object {obj} (id={obj.id})")
        flag = flags.get(obj.id, 0)
        lines.append(f"{flag}{_US}{name}")

    out_file.write_bytes(gzip.compress("\n".join(lines).encode()))
    named = sum(1 for line in lines if line.split(_US, 1)[1])
    logger.info("Wrote %d/%d labels to %s", named, len(lines), out_file)
