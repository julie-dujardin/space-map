"""Bodies grouped by planetary system, for the pages that list one row for
each body."""

from sqlalchemy.orm import Session

from space_map_data.export.names import SYSTEM_PRIMARIES, Names, ObjectNames
from space_map_data.models.object import Object, ObjectType

# The Solar System barycentre and the Sun. A body with one of them as parent
# belongs to no planetary system.
_TOP_LEVEL_NAIF_IDS = {0, 10}


def load_system_lookup(
    session: Session, names: ObjectNames
) -> tuple[dict[str, str], dict[str, str], dict[str, Names], dict[str, int]]:
    """The maps that put a body in its system.

    Returns ``(bary_by_id, child_to_bary, system_name_by_id, system_order_by_id)``:
    the ids of the system barycentres, the barycentre of each of their
    children, the names of the planet of each system and its place from
    Mercury to Pluto. A system with no planet row, or a barycentre that is no
    planet's, takes the barycentre's own names.
    """
    top_level_ids = [f"naif-{n}" for n in _TOP_LEVEL_NAIF_IDS]
    barycenters = (
        session.query(Object)
        .filter(
            Object.object_type == ObjectType.barycenter.value,
            Object.parent_id.in_(top_level_ids),
            Object.naif_id.not_in(list(_TOP_LEVEL_NAIF_IDS)),
        )
        .all()
    )

    bary_by_id: dict[str, str] = {}
    system_order_by_id: dict[str, int] = {}
    for b in barycenters:
        if b.naif_id is not None:
            bary_by_id[b.id] = b.id
            system_order_by_id[b.id] = b.naif_id

    child_to_bary: dict[str, str] = {}
    for bary in barycenters:
        children = session.query(Object).filter(Object.parent_id == bary.id).all()
        for child in children:
            child_to_bary[child.id] = bary.id

    system_name_by_id: dict[str, Names] = {}
    for bary_id in bary_by_id:
        primary = SYSTEM_PRIMARIES.get(bary_id)
        found = names.find(primary) if primary is not None else None
        system_name_by_id[bary_id] = found or names.object(bary_id)

    return bary_by_id, child_to_bary, system_name_by_id, system_order_by_id


def resolve_system_id(
    obj: Object,
    bary_by_id: dict[str, str],
    child_to_bary: dict[str, str],
) -> str | None:
    """Id of the system barycentre that holds ``obj``, or None for a body in
    no system. The rules are those of ``write_system_metadata``."""
    if obj.parent_id in bary_by_id:
        return bary_by_id[obj.parent_id]
    if obj.parent_id in child_to_bary:
        return child_to_bary[obj.parent_id]
    if obj.id in bary_by_id:
        return bary_by_id[obj.id]
    return None
