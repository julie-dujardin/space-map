"""Export orchestrator: query DB, write all output files."""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload
from tqdm import tqdm

from space_map_data.export.elements import write_elements
from space_map_data.export.format import VERSION
from space_map_data.export.labels import load_wikidata_entities, write_labels
from space_map_data.export.objects import write_objects
from space_map_data.models.object import Object, ObjectType
from space_map_data.utils.paths import EXPORT_DIR

logger = logging.getLogger(__name__)

# Sort priority: lower = earlier id
_TYPE_PRIORITY: dict[ObjectType, int] = {
    ObjectType.star: 0,
    ObjectType.barycenter: 1,
    ObjectType.lagrange_point: 2,
    ObjectType.planet: 3,
    ObjectType.dwarf_planet: 4,
    ObjectType.moon: 5,
    ObjectType.asteroid: 10,
    ObjectType.asteroid_inner: 11,
    ObjectType.asteroid_main_belt: 12,
    ObjectType.asteroid_trojan: 13,
    ObjectType.asteroid_centaur: 14,
    ObjectType.asteroid_tno: 15,
    ObjectType.comet: 20,
    ObjectType.spacecraft: 30,
    ObjectType.debris: 40,
    ObjectType.undocumented: 50,
}

_ASTEROID_TYPES = {
    ObjectType.asteroid,
    ObjectType.asteroid_inner,
    ObjectType.asteroid_main_belt,
    ObjectType.asteroid_trojan,
    ObjectType.asteroid_centaur,
    ObjectType.asteroid_tno,
}


def export(session: Session, *, limit_asteroids: int = 10_000) -> None:
    """Run the full export pipeline."""
    out_dir = EXPORT_DIR / "v1"
    out_dir.mkdir(parents=True, exist_ok=True)

    asteroid_type_values = [t.value for t in _ASTEROID_TYPES]

    others = (
        session.query(Object)
        .options(joinedload(Object.sbdb))
        .filter(Object.object_type.notin_(asteroid_type_values))
        .all()
    )

    asteroids = (
        session.query(Object)
        .options(joinedload(Object.sbdb))
        .filter(Object.object_type.in_(asteroid_type_values))
        .order_by(func.random())
        .limit(limit_asteroids)
        .all()
    )

    logger.info(
        "Loaded %d non-asteroids + %d asteroids (limit %d)",
        len(others),
        len(asteroids),
        limit_asteroids,
    )

    # Combine and sort by type priority, then semi-major axis
    selected = others + asteroids
    selected.sort(
        key=lambda o: (
            _TYPE_PRIORITY.get(o.object_type, 99),
            o.a if o.a is not None else float("inf"),
        )
    )

    logger.info("Exporting %d objects", len(selected))

    wikidata_entities = load_wikidata_entities()

    steps = tqdm(total=5, desc="Exporting", unit="step")

    write_elements(selected, out_dir)
    steps.set_postfix_str("elements.bin")
    steps.update()

    write_labels(selected, out_dir, wikidata_entities)
    steps.set_postfix_str("labels")
    steps.update()

    write_objects(selected, out_dir, wikidata_entities)
    steps.set_postfix_str("objects")
    steps.update()

    # Write id_map.json (id → object.id for debugging)
    id_map = {str(i): obj.id for i, obj in enumerate(selected)}
    (out_dir / "id_map.json").write_text(json.dumps(id_map, indent=2))
    steps.set_postfix_str("id_map.json")
    steps.update()

    # Write metadata.json
    metadata = {
        "version": VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "object_count": len(selected),
        "asteroid_limit": limit_asteroids,
    }
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
    steps.set_postfix_str("metadata.json")
    steps.update()
    steps.close()

    logger.info("Export complete: %d objects to %s", len(selected), out_dir)
