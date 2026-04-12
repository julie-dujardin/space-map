"""Write per-system metadata: systems/{barycenter_id}.json.

Each file contains texture tier info and orientation data for bodies in that
planetary system.
"""

import csv
import logging
import orjson
from pathlib import Path

from sqlalchemy.orm import Session

from space_map_data.constants.providers import PROVIDERS
from space_map_data.models.object import Object, ObjectType

logger = logging.getLogger(__name__)

_TOP_LEVEL_NAIF_IDS = {0, 10}  # SSB and Sun

# Object types that belong in planetary systems
_SYSTEM_TYPES = frozenset(
    {
        ObjectType.star,
        ObjectType.planet,
        ObjectType.dwarf_planet,
        ObjectType.moon,
        ObjectType.barycenter,
    }
)


def load_orientation(download_dir: Path) -> dict[int, dict]:
    """Load orientation data from SPICE orientation.csv.

    Returns {naif_id: {pole_ra, pole_dec, w0, w_rate}}.
    """
    csv_path = download_dir / PROVIDERS.SPICE / "orientation.csv"
    if not csv_path.exists():
        logger.warning("No orientation CSV at %s", csv_path)
        return {}
    result: dict[int, dict] = {}
    with csv_path.open(newline="") as f:
        for row in csv.DictReader(f):
            naif_id = int(row["naif_id"])
            result[naif_id] = {
                "pole_ra": float(row["pole_ra"]),
                "pole_dec": float(row["pole_dec"]),
                "w0": float(row["w0"]),
                "w_rate": float(row["w_rate"]),
            }
    logger.info("Loaded %d orientation records", len(result))
    return result


def write_system_metadata(
    session: Session, out_dir: Path, orientation: dict[int, dict]
) -> dict[int, dict]:
    """Generate one metadata file per planetary system.

    Each file is keyed by body ID and contains texture tiers (if available)
    and orientation data (if available from SPICE PCK).

    Returns the orientation lookup for use by object detail export.
    """
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

    # Map planet/body NAIF number -> barycenter object ID (one level down)
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

    # Query all bodies that belong to planetary systems (not just textured ones)
    system_bodies = (
        session.query(Object)
        .filter(Object.object_type.in_([t.value for t in _SYSTEM_TYPES]))
        .all()
    )

    # Group by system barycenter
    systems: dict[str, list[Object]] = {}
    for obj in system_bodies:
        if obj.parent_naif_id in bary_by_naif:
            sys_id = bary_by_naif[obj.parent_naif_id]
        elif obj.parent_naif_id in planet_to_bary:
            sys_id = planet_to_bary[obj.parent_naif_id]
        elif obj.horizons_naif_id in bary_by_naif:
            # The barycenter itself
            sys_id = bary_by_naif[obj.horizons_naif_id]
        else:
            continue  # top-level or not in a system
        systems.setdefault(sys_id, []).append(obj)

    # Write one JSON file per system
    systems_dir = out_dir / "systems"
    systems_dir.mkdir(parents=True, exist_ok=True)
    for sys_id, objs in systems.items():
        bodies: dict[str, dict] = {}
        for obj in objs:
            entry: dict = {}

            # Texture tiers
            if obj.map_texture_available:
                meta_file = out_dir / "textures" / obj.id / "metadata.json"
                if meta_file.exists():
                    meta = orjson.loads(meta_file.read_bytes())
                    entry["tiers"] = sorted(meta.get("exports", {}).keys())
                else:
                    logger.warning(
                        "Texture metadata missing for %s (system %s), skipping tiers",
                        obj.id,
                        sys_id,
                    )

            # Orientation data
            if obj.horizons_naif_id is not None and obj.horizons_naif_id in orientation:
                entry["orientation"] = orientation[obj.horizons_naif_id]

            if entry:
                bodies[obj.id] = entry

        if bodies:
            (systems_dir / f"{sys_id}.json").write_bytes(orjson.dumps(bodies))
            logger.info("System metadata %s: %d bodies", sys_id, len(bodies))

    return orientation
