"""Export orchestrator: query DB, write chunked output files."""

import orjson
import logging
import math
import shutil
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import case
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, joinedload

from space_map_data.export.elements import CHUNK_SIZE, write_chunk
from space_map_data.export.elements.format import VERSION
from space_map_data.export.objects import write_objects
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.units import write_unit_labels
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.models.object import Object, ObjectType, SBDB
from space_map_data.utils.paths import EXPORT_DIR

logger = logging.getLogger(__name__)

_EARTH_NAIF_ID = 399

_EARTH_CONTEXT_TYPES = {ObjectType.spacecraft, ObjectType.debris}
_EARTH_TYPE_VALUES = [t.value for t in _EARTH_CONTEXT_TYPES]

_SUN_MAJOR_TYPES = {
    ObjectType.star,
    ObjectType.barycenter,
    ObjectType.lagrange_point,
    ObjectType.planet,
    ObjectType.dwarf_planet,
}
_SUN_MAJOR_TYPE_VALUES = [t.value for t in _SUN_MAJOR_TYPES]

_DEFAULT_ZONE_LIMIT = 10_000


def _build_metadata(
    zone_structure: dict[str, dict[int, int]],
    object_counts: dict[tuple[str, int], int],
    total_bytes: dict[tuple[str, int], int],
) -> dict:
    zones = {}
    for zone, zoom_parts in sorted(zone_structure.items()):
        zooms = {}
        for zoom, part_count in sorted(zoom_parts.items()):
            count = object_counts.get((zone, zoom), 0)
            nbytes = total_bytes.get((zone, zoom), 0)
            zooms[str(zoom)] = {
                "parts": part_count,
                "object_count": count,
                "avg_part_bytes": nbytes // part_count if part_count else 0,
            }
        zones[zone] = {"zooms": zooms}
    return {
        "version": VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "zones": zones,
    }


def _remove_old_outputs(out_dir: Path) -> None:
    """Remove all chunk output directories before a fresh export."""
    for d in ("elements", "element_labels", "objects"):
        p = out_dir / d
        if p.exists():
            shutil.rmtree(p)


def _write_parts(
    objects: list[Object],
    out_dir: Path,
    zone: str,
    zoom: int,
    wikidata_entities: WikidataEntityCache,
    units: UnitConverter,
) -> tuple[int, int]:
    """Split objects into CHUNK_SIZE parts and write. Returns (num_parts, total_bytes)."""
    num_parts = max(1, math.ceil(len(objects) / CHUNK_SIZE))
    total_bytes = 0
    for part_idx in range(num_parts):
        chunk = objects[part_idx * CHUNK_SIZE : (part_idx + 1) * CHUNK_SIZE]
        chunk_entities = {
            qid: wikidata_entities.get_entity(qid)
            for obj in chunk
            if (qid := obj.wikidata_qid)
        }
        # write_objects must come first — its return value feeds write_chunk
        object_flags = write_objects(
            chunk,
            out_dir,
            wikidata_entities,
            chunk_entities,
            units,
        )
        total_bytes += write_chunk(
            chunk,
            out_dir,
            zone,
            zoom,
            part_idx,
            chunk_entities,
            object_flags,
            units,
        )
    return num_parts, total_bytes


def export(engine: Engine, limit_per_zone: int = _DEFAULT_ZONE_LIMIT) -> None:
    """Run the full export pipeline."""
    t0 = time.monotonic()
    out_dir = EXPORT_DIR / "v1"
    out_dir.mkdir(parents=True, exist_ok=True)
    _remove_old_outputs(out_dir)

    wikidata_entities = WikidataEntityCache()
    units = UnitConverter(wikidata_entities)

    zone_structure: defaultdict[str, dict[int, int]] = defaultdict(dict)
    object_counts: defaultdict[tuple[str, int], int] = defaultdict(int)
    total_bytes_map: defaultdict[tuple[str, int], int] = defaultdict(int)

    futures: dict = {}

    with Session(engine) as session:
        with ThreadPoolExecutor() as executor:
            # Non-SBDB zones
            non_sbdb = [
                (
                    "major",
                    session.query(Object)
                    .options(joinedload(Object.sbdb))
                    .filter(Object.object_type.in_(_SUN_MAJOR_TYPE_VALUES)),
                ),
                (
                    "moons",
                    session.query(Object).filter(
                        Object.sbdb_spkid.is_(None),
                        Object.object_type == ObjectType.moon.value,
                    ),
                ),
                (
                    "earth",
                    session.query(Object).filter(
                        Object.sbdb_spkid.is_(None),
                        Object.object_type.in_(_EARTH_TYPE_VALUES),
                        Object.parent_naif_id == _EARTH_NAIF_ID,
                    ),
                ),
                (
                    "spacecraft",
                    session.query(Object).filter(
                        Object.sbdb_spkid.is_(None),
                        Object.object_type.in_(_EARTH_TYPE_VALUES),
                        Object.parent_naif_id != _EARTH_NAIF_ID,
                    ),
                ),
            ]
            for zone, q in non_sbdb:
                objects = q.order_by(Object.random_int).limit(limit_per_zone).all()
                if not objects:
                    logger.info("  %s: empty, skipping", zone)
                    continue
                if zone == "major":
                    # Barycenters must come first so parents resolve before children.
                    objects.sort(key=lambda o: o.object_type != ObjectType.barycenter)
                f = executor.submit(
                    _write_parts,
                    objects,
                    out_dir,
                    zone,
                    0,
                    wikidata_entities,
                    units,
                )
                futures[f] = (zone, 0, len(objects))

            # SBDB: one query per (class, zoom)
            named_col = case((SBDB.name.is_not(None), 1), else_=0).label("named")
            sbdb_combos = (
                session.query(SBDB.class_, named_col)
                .group_by(SBDB.class_, named_col)
                .all()
            )
            for cls, named in sbdb_combos:
                zoom = 0 if named else 1
                name_filter = SBDB.name.is_not(None) if named else SBDB.name.is_(None)
                objects = (
                    session.query(Object)
                    .options(joinedload(Object.sbdb))
                    .join(Object.sbdb)
                    .filter(
                        SBDB.class_ == cls,
                        name_filter,
                        Object.object_type.not_in(_SUN_MAJOR_TYPE_VALUES),
                    )
                    .order_by(Object.random_int)
                    .limit(limit_per_zone)
                    .all()
                )
                if not objects:
                    continue
                zone = cls.value if hasattr(cls, "value") else cls
                f = executor.submit(
                    _write_parts,
                    objects,
                    out_dir,
                    zone,
                    zoom,
                    wikidata_entities,
                    units,
                )
                futures[f] = (zone, zoom, len(objects))
            # executor joins here — session still open so ORM objects remain valid

    for f in as_completed(futures):
        zone, zoom, count = futures[f]
        num_parts, nbytes = f.result()
        object_counts[(zone, zoom)] += count
        total_bytes_map[(zone, zoom)] += nbytes
        zone_structure[zone][zoom] = num_parts
        logger.info("  %s zoom=%d: %d objects, %d parts", zone, zoom, count, num_parts)

    # --- Other outputs ---
    write_unit_labels(out_dir, wikidata_entities)

    metadata = _build_metadata(zone_structure, object_counts, total_bytes_map)
    (out_dir / "metadata.json").write_bytes(
        orjson.dumps(metadata, option=orjson.OPT_INDENT_2)
    )

    total = sum(object_counts.values())
    elapsed = time.monotonic() - t0
    logger.info("Export complete: %d objects to %s in %.1fs", total, out_dir, elapsed)
