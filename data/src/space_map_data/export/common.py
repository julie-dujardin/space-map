"""Export orchestrator: query DB, write chunked output files."""

import json
import logging
import shutil
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload
from tqdm import tqdm

from space_map_data.export.elements import CHUNK_SIZE, write_chunk
from space_map_data.export.elements.format import VERSION
from space_map_data.export.objects import write_objects
from space_map_data.export.objects.wikipedia import load_wikipedia_summaries
from space_map_data.export.units import write_unit_labels
from space_map_data.export.wikidata import load_wikidata_entities
from space_map_data.models.object import Object, ObjectType
from space_map_data.utils.paths import EXPORT_DIR

logger = logging.getLogger(__name__)

_EARTH_NAIF_ID = 399

_EARTH_CONTEXT_TYPES = {ObjectType.spacecraft, ObjectType.debris}

_SUN_ZOOM0_TYPES = {
    ObjectType.star,
    ObjectType.barycenter,
    ObjectType.lagrange_point,
    ObjectType.planet,
    ObjectType.dwarf_planet,
}

_ASTEROID_TYPES = {
    ObjectType.asteroid,
    ObjectType.asteroid_inner,
    ObjectType.asteroid_main_belt,
    ObjectType.asteroid_trojan,
    ObjectType.asteroid_centaur,
    ObjectType.asteroid_tno,
}


def _assign_chunk(obj: Object) -> tuple[str, int]:
    """Return (context_id, zoom) for an object."""
    t = obj.object_type

    if t in _EARTH_CONTEXT_TYPES and obj.parent_naif_id == _EARTH_NAIF_ID:
        return ("earth", 0)

    if t in _SUN_ZOOM0_TYPES:
        return ("sun", 0)

    if t == ObjectType.moon:
        return ("sun", 1)

    if t == ObjectType.comet or obj.name is not None:
        return ("sun", 2)

    return ("sun", 3)


def _iter_zoom3_batches(session: Session, limit: int | None) -> Iterator[list[Object]]:
    """Yield CHUNK_SIZE-object batches for zoom 3 in random order, streamed from DB."""
    asteroid_type_values = [t.value for t in _ASTEROID_TYPES]
    q = (
        session.query(Object)
        .options(joinedload(Object.sbdb))
        .filter(
            Object.object_type.in_(asteroid_type_values),
            Object.name.is_(None),
        )
        .order_by(func.random())
    )
    if limit is not None:
        q = q.limit(limit)
    batch: list[Object] = []
    for obj in q.yield_per(CHUNK_SIZE):
        batch.append(obj)
        if len(batch) == CHUNK_SIZE:
            yield batch
            batch = []
    if batch:
        yield batch


def _build_metadata(
    chunk_structure: dict[str, dict[int, int]],
    object_counts: dict[tuple[str, int], int],
    total_bytes: dict[tuple[str, int], int],
    limit_asteroids: int | None,
) -> dict:
    contexts = {}
    for context_id, zoom_parts in sorted(chunk_structure.items()):
        zooms = {}
        for zoom, part_count in sorted(zoom_parts.items()):
            count = object_counts.get((context_id, zoom), 0)
            nbytes = total_bytes.get((context_id, zoom), 0)
            zooms[str(zoom)] = {
                "parts": part_count,
                "object_count": count,
                "avg_part_size": count // part_count if part_count else 0,
                "avg_part_bytes": nbytes // part_count if part_count else 0,
            }
        contexts[context_id] = {"zooms": zooms}
    return {
        "version": VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "contexts": contexts,
        "asteroid_limit": limit_asteroids,
    }


def _remove_old_outputs(out_dir: Path) -> None:
    """Remove all chunk output directories and legacy files before a fresh export."""
    for d in ("elements", "element_labels"):
        p = out_dir / d
        if p.exists():
            shutil.rmtree(p)


def export(session: Session, *, limit_asteroids: int | None = 10_000) -> None:
    """Run the full export pipeline."""
    out_dir = EXPORT_DIR / "v1"
    out_dir.mkdir(parents=True, exist_ok=True)
    _remove_old_outputs(out_dir)

    wikidata_entities = load_wikidata_entities()
    wiki_summaries = load_wikipedia_summaries()

    asteroid_type_values = [t.value for t in _ASTEROID_TYPES]

    # --- Non-zoom-3: everything except unnamed asteroids ---
    non_zoom3 = (
        session.query(Object)
        .options(joinedload(Object.sbdb))
        .filter(~(Object.object_type.in_(asteroid_type_values) & Object.name.is_(None)))
        .all()
    )
    logger.info("Loaded %d non-zoom-3 objects", len(non_zoom3))

    # Classify into (context_id, zoom) buckets
    buckets: dict[tuple[str, int], list[Object]] = {}
    for obj in non_zoom3:
        key = _assign_chunk(obj)
        buckets.setdefault(key, []).append(obj)

    # Write non-zoom-3 chunks
    chunk_structure: dict[str, dict[int, int]] = {}
    object_counts: dict[tuple[str, int], int] = {}
    total_bytes: dict[tuple[str, int], int] = {}

    with tqdm(total=len(non_zoom3), unit="obj", desc="non-zoom-3") as progress:
        for (context_id, zoom), objs in sorted(buckets.items()):
            parts = [objs[i : i + CHUNK_SIZE] for i in range(0, len(objs), CHUNK_SIZE)]
            for part_idx, part_objs in enumerate(parts):
                nbytes = write_chunk(
                    part_objs, out_dir, context_id, zoom, part_idx, wikidata_entities
                )
                total_bytes[(context_id, zoom)] = (
                    total_bytes.get((context_id, zoom), 0) + nbytes
                )
                progress.update(len(part_objs))
            chunk_structure.setdefault(context_id, {})[zoom] = len(parts)
            object_counts[(context_id, zoom)] = len(objs)

    write_objects(non_zoom3, out_dir, wikidata_entities, wiki_summaries)

    # --- Zoom 3: unnamed asteroids, streamed from DB in random order ---
    zoom3_part_count = 0
    zoom3_total = 0
    zoom3_bytes = 0
    with tqdm(total=limit_asteroids, unit="obj", desc="zoom3") as progress:
        for part_idx, batch in enumerate(_iter_zoom3_batches(session, limit_asteroids)):
            nbytes = write_chunk(batch, out_dir, "sun", 3, part_idx, wikidata_entities)
            write_objects(batch, out_dir, wikidata_entities, wiki_summaries)
            zoom3_part_count += 1
            zoom3_total += len(batch)
            zoom3_bytes += nbytes
            progress.update(len(batch))

    if zoom3_part_count:
        chunk_structure.setdefault("sun", {})[3] = zoom3_part_count
        object_counts[("sun", 3)] = zoom3_total
        total_bytes[("sun", 3)] = zoom3_bytes

    # --- Other outputs ---
    write_unit_labels(out_dir, wikidata_entities)

    metadata = _build_metadata(
        chunk_structure, object_counts, total_bytes, limit_asteroids
    )
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

    total = sum(object_counts.values())
    logger.info("Export complete: %d objects to %s", total, out_dir)
