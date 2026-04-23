"""Write one (zone, zoom, part) chunk: binary elements + labels + id list."""

import gzip
import logging
from pathlib import Path

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.elements.format import (
    UNBOUNDED_END_JD,
    UNBOUNDED_START_JD,
)
from space_map_data.export.elements.labels import write_labels
from space_map_data.export.elements.writer import (
    write_elements,
    write_parabolic_elements,
    write_sgp4_elements,
)
from space_map_data.export.objects.wikidata_claims import radius_km_from_claims
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.wikidata import WikidataEntity
from space_map_data.models.object import Object, OrbitalSource

logger = logging.getLogger(__name__)

CHUNK_SIZE = 10_000

# Days of slack to add around the spread of TLE epochs when bounding an SGP4
# chunk's validity window. TLE accuracy degrades quickly and the SGP4
# propagator itself errors out a year or two past epoch — ±14d is the
# conventional "still reasonably accurate" window for LEO.
SGP4_VALIDITY_SLACK_DAYS = 14.0


def _sgp4_validity_window(objects: list[Object]) -> tuple[float, float]:
    """Derive [start_jd, end_jd] for an SGP4 chunk from the epoch spread.

    Falls back to unbounded when no object carries an epoch (shouldn't happen
    for valid TLEs but keeps behaviour defined).
    """
    epochs = [o.epoch_jd for o in objects if o.epoch_jd is not None]
    if not epochs:
        return UNBOUNDED_START_JD, UNBOUNDED_END_JD
    return min(epochs) - SGP4_VALIDITY_SLACK_DAYS, max(
        epochs
    ) + SGP4_VALIDITY_SLACK_DAYS


def write_chunk(
    objects: list[Object],
    out_dir: Path,
    zone: str,
    zoom: int,
    part: int,
    chunk_entities: dict[str, WikidataEntity | None],
    object_flags: dict[str, dict[str, int]],
    units: UnitConverter,
    orbital_source: OrbitalSource,
) -> int:
    """Write elements binary, label files, and id list for one chunk.

    object_flags: {obj_id: {lang: 0|1|2}} as returned by build_chunk_object_data.
    `orbital_source` is stamped in the file header; writer raises if any row
    disagrees.
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
    # SGP4 (Earth satellites) needs a tight validity window — the propagator
    # blows up past ~a year from epoch and spammy warnings are not useful.
    # Kepler/parabolic orbits are mathematical solutions with no hard cutoff,
    # so leave them unbounded.
    start_jd: float = UNBOUNDED_START_JD
    end_jd: float = UNBOUNDED_END_JD
    if zone == "PAR":
        write_fn = write_parabolic_elements
    elif zone == "earth":
        write_fn = write_sgp4_elements
        start_jd, end_jd = _sgp4_validity_window(objects)
    else:
        write_fn = write_elements
    write_fn(
        objects,
        elements_path,
        orbital_source,
        radius_km_overrides or None,
        start_jd=start_jd,
        end_jd=end_jd,
    )
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
