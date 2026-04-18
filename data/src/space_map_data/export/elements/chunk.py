"""Write one (zone, zoom, part) chunk: binary elements + labels + id list."""

import gzip
import logging
from pathlib import Path

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.elements.labels import write_labels
from space_map_data.export.elements.writer import (
    write_elements,
    write_parabolic_elements,
)
from space_map_data.export.objects.wikidata_claims import radius_km_from_claims
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.wikidata import WikidataEntity
from space_map_data.models.object import Object

logger = logging.getLogger(__name__)

CHUNK_SIZE = 10_000


def write_chunk(
    objects: list[Object],
    out_dir: Path,
    zone: str,
    zoom: int,
    part: int,
    chunk_entities: dict[str, WikidataEntity | None],
    object_flags: dict[str, dict[str, int]],
    units: UnitConverter,
) -> int:
    """Write elements binary, label files, and id list for one chunk.

    object_flags: {obj_id: {lang: 0|1|2}} as returned by write_objects().
    Returns the size of the elements binary file in bytes.
    """
    elements_path = out_dir / "elements" / zone / str(zoom) / f"{part}.bin.gz"
    elements_path.parent.mkdir(parents=True, exist_ok=True)
    radius_km_overrides: dict[str, float] = {}
    for obj in objects:
        qid = obj.wikidata_qid or (
            obj.satcat.wikidata_qid
            if obj.norad_cat_id is not None and obj.satcat
            else None
        )
        if qid and (wd := chunk_entities.get(qid)):
            try:
                r = radius_km_from_claims(wd["claims"], units, qid=qid)
            except Exception as exc:
                logger.error(
                    "Error extracting radius for %s (%s): %s",
                    obj.id,
                    qid,
                    exc,
                )
                r = None
            if r is not None:
                radius_km_overrides[obj.id] = r
    write_fn = write_parabolic_elements if zone == "PAR" else write_elements
    write_fn(objects, elements_path, radius_km_overrides or None)
    elements_bytes = elements_path.stat().st_size

    for lang in LANGUAGES:
        labels_path = out_dir / "elements" / zone / str(zoom) / f"{part}.loc.{lang}.gz"
        lang_flags = {
            obj.id: object_flags.get(obj.id, {}).get(lang, 0) for obj in objects
        }
        write_labels(objects, labels_path, lang, chunk_entities, lang_flags)

    ids_path = out_dir / "elements" / zone / str(zoom) / f"{part}.id.gz"
    ids_path.write_bytes(gzip.compress("\n".join(obj.id for obj in objects).encode()))

    return elements_bytes
