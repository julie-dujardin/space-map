"""Write per-system texture metadata: textures/systems/{barycenter_id}.json."""

import logging
import orjson
from pathlib import Path

from sqlalchemy.orm import Session

from space_map_data.models.object import Object, ObjectType

logger = logging.getLogger(__name__)

_TOP_LEVEL_NAIF_IDS = {0, 10}  # SSB and Sun


def write_system_textures(session: Session, out_dir: Path) -> None:
    """Generate one metadata file per planetary system listing its textured bodies.

    Each file is keyed by the system barycenter ID (e.g. naif-3 for Earth-Moon)
    and lists body IDs that have textures, along with available tiers read from
    the per-object texture metadata already on disk.
    """
    textured = (
        session.query(Object).filter(Object.map_texture_available.is_(True)).all()
    )
    if not textured:
        return

    # Build barycenter NAIF number -> barycenter object ID mapping
    barycenters = (
        session.query(Object)
        .filter(
            Object.object_type == ObjectType.barycenter.value,
            Object.parent_naif_id.in_(list(_TOP_LEVEL_NAIF_IDS)),
            Object.horizons_naif_id.not_in(list(_TOP_LEVEL_NAIF_IDS)),
        )
        .all()
    )
    bary_by_naif: dict[int, str] = {}
    for b in barycenters:
        if b.horizons_naif_id is not None:
            bary_by_naif[b.horizons_naif_id] = b.id

    # Map planet NAIF number -> barycenter object ID (one level down)
    planet_to_bary: dict[int, str] = {}
    for bary in barycenters:
        children = (
            session.query(Object)
            .filter(Object.parent_naif_id == bary.horizons_naif_id)
            .all()
        )
        for child in children:
            if child.horizons_naif_id is not None:
                planet_to_bary[child.horizons_naif_id] = bary.id

    # Group textured objects by their system barycenter
    systems: dict[str, list[str]] = {}
    for obj in textured:
        if obj.parent_naif_id in bary_by_naif:
            sys_id = bary_by_naif[obj.parent_naif_id]
        elif obj.parent_naif_id in planet_to_bary:
            sys_id = planet_to_bary[obj.parent_naif_id]
        else:
            continue  # top-level or not in a system (e.g. asteroid)
        systems.setdefault(sys_id, []).append(obj.id)

    # Write one JSON file per system
    systems_dir = out_dir / "textures" / "systems"
    systems_dir.mkdir(parents=True, exist_ok=True)
    for sys_id, body_ids in systems.items():
        bodies: dict[str, dict] = {}
        for body_id in body_ids:
            meta_file = out_dir / "textures" / body_id / "metadata.json"
            if not meta_file.exists():
                logger.warning(
                    "Texture metadata missing for %s (system %s), skipping",
                    body_id,
                    sys_id,
                )
                continue
            meta = orjson.loads(meta_file.read_bytes())
            bodies[body_id] = {"tiers": sorted(meta.get("exports", {}).keys())}
        if bodies:
            (systems_dir / f"{sys_id}.json").write_bytes(orjson.dumps(bodies))
            logger.info("System texture metadata %s: %d bodies", sys_id, len(bodies))
