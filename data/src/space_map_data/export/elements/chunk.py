"""Write one (context, zoom, part) chunk: binary elements + labels + id list."""

from pathlib import Path

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.elements.labels import write_labels
from space_map_data.export.elements.writer import write_elements
from space_map_data.export.wikidata import WikidataEntity
from space_map_data.models.object import Object

CHUNK_SIZE = 50_000


def write_chunk(
    objects: list[Object],
    out_dir: Path,
    context_id: str,
    zoom: int,
    part: int,
    wikidata_entities: dict[str, WikidataEntity],
) -> int:
    """Write elements binary, label files, and id list for one chunk.

    Returns the size of the elements binary file in bytes.
    """
    elements_path = out_dir / "elements" / context_id / str(zoom) / f"{part}.bin"
    elements_path.parent.mkdir(parents=True, exist_ok=True)
    write_elements(objects, elements_path)
    elements_bytes = elements_path.stat().st_size

    for lang in LANGUAGES:
        labels_path = (
            out_dir / "element_labels" / lang / context_id / str(zoom) / f"{part}.txt"
        )
        labels_path.parent.mkdir(parents=True, exist_ok=True)
        write_labels(objects, labels_path, lang, wikidata_entities)

    ids_path = out_dir / "elements" / context_id / str(zoom) / f"{part}.txt"
    ids_path.write_text("\n".join(obj.id for obj in objects))

    return elements_bytes
