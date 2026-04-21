"""Aggregated credits file: `v1/credits.json`.

Feeds the `/credits` frontend page. Centralises everything that deserves a
public thank-you so the page can render without fanning out per-body requests.

Only texture credits are dynamic today — orbital ephemeris, rotation kernels,
and metadata providers are static knowledge baked into the frontend. When
asteroid textures or 3D mesh assets land later they should extend this file
(e.g. a `"models"` key) rather than spawning a parallel export.
"""

import logging
import orjson
from pathlib import Path

from sqlalchemy.orm import Session

from space_map_data.export.systems import texture_attribution
from space_map_data.models.object import Object, ObjectType

logger = logging.getLogger(__name__)

# Top-level NAIF hubs (SSB, Sun). Bodies parented here are standalone —
# asteroids and dwarf planets without a hosting planetary system.
_TOP_LEVEL_NAIF_IDS = {0, 10}


def _body_name(obj: Object) -> str:
    """Canonical English-ish display name for a textured body.

    Uses the DB's primary `name` column (clean canonical form for planets,
    moons, and named minor bodies) with MPC / provisional designations as
    fallbacks so asteroids without a name still render as something readable
    rather than the opaque object ID. Localised names will come later —
    tracked in context-manager.svelte.ts callers; for now the credits page
    ships English-only.
    """
    return obj.name or obj.mpc_designation or obj.provisional_designation or obj.id


def _load_system_lookup(
    session: Session,
) -> tuple[dict[int, str], dict[int, str], dict[str, str], dict[str, int]]:
    """Build the mappings needed to group a textured body under a system.

    Returns:
      * `bary_by_naif` — `{bary_naif_id: bary_obj_id}` (e.g. `3 → "naif-3"`).
      * `planet_to_bary` — `{child_naif_id: bary_obj_id}` for direct children
        of a barycenter, so a body parented on Earth (naif-399) routes to
        the Earth–Moon barycenter.
      * `system_name_by_id` — `{bary_obj_id: display_name}` using the primary
        planet's name (e.g. `"naif-3" → "Earth"`) rather than the cluttered
        `"Earth-Moon Barycenter"` DB label.
      * `system_order_by_id` — `{bary_obj_id: bary_naif_id}` so the output
        can render Mercury → Pluto by natural ordinal.
    """
    barycenters = (
        session.query(Object)
        .filter(
            Object.object_type == ObjectType.barycenter.value,
            Object.parent_naif_id.in_(list(_TOP_LEVEL_NAIF_IDS)),
            Object.naif_id.not_in(list(_TOP_LEVEL_NAIF_IDS)),
        )
        .all()
    )

    bary_by_naif: dict[int, str] = {}
    system_order_by_id: dict[str, int] = {}
    for b in barycenters:
        if b.naif_id is not None:
            bary_by_naif[b.naif_id] = b.id
            system_order_by_id[b.id] = b.naif_id

    planet_to_bary: dict[int, str] = {}
    for bary in barycenters:
        children = (
            session.query(Object).filter(Object.parent_naif_id == bary.naif_id).all()
        )
        for child in children:
            if child.naif_id is not None:
                planet_to_bary[child.naif_id] = bary.id

    # Prefer the primary planet's name as the system label (naif-X99 for
    # barycenter naif-X) — "Earth" reads better than "Earth-Moon Barycenter".
    system_name_by_id: dict[str, str] = {}
    primary_naif_ids = [
        (bary_naif or 0) * 100 + 99 for bary_naif in bary_by_naif.keys()
    ]
    primaries = session.query(Object).filter(Object.naif_id.in_(primary_naif_ids)).all()
    primary_by_naif = {p.naif_id: p for p in primaries}
    for bary_naif, bary_id in bary_by_naif.items():
        primary = primary_by_naif.get(bary_naif * 100 + 99)
        if primary and primary.name:
            system_name_by_id[bary_id] = primary.name
        else:
            # Fallback: strip the redundant "Barycenter" suffix.
            bary_obj = next((b for b in barycenters if b.id == bary_id), None)
            name = (bary_obj.name if bary_obj else None) or bary_id
            system_name_by_id[bary_id] = name.replace(" Barycenter", "").strip()

    return bary_by_naif, planet_to_bary, system_name_by_id, system_order_by_id


def _resolve_system_id(
    obj: Object,
    bary_by_naif: dict[int, str],
    planet_to_bary: dict[int, str],
) -> str | None:
    """Return the barycenter ID that textually owns *obj*, or None for standalones.

    Mirrors the containment rules used by `write_system_metadata`: a body
    parented directly on a barycenter, parented on one of its children (e.g.
    an Earth satellite routing up to Earth-Moon), or being a barycenter
    itself, all count as "inside" that system.
    """
    if obj.parent_naif_id in bary_by_naif:
        return bary_by_naif[obj.parent_naif_id]
    if obj.parent_naif_id in planet_to_bary:
        return planet_to_bary[obj.parent_naif_id]
    if obj.naif_id in bary_by_naif:
        return bary_by_naif[obj.naif_id]
    return None


def write_credits(
    session: Session, out_dir: Path, texture_metadata: dict[str, dict]
) -> None:
    """Emit `v1/credits.json` summarising every credit-worthy data source.

    Groups textured bodies by their host planetary system (Earth, Jupiter, …)
    so the frontend can render sections instead of a flat alphabetical list.
    A final null-id group collects standalones (sun-orbiting asteroids and
    dwarf planets like Bennu or Ceres) that don't belong to a system.
    """
    if not texture_metadata:
        logger.info("No texture metadata available; skipping credits.json")
        return

    body_ids = list(texture_metadata.keys())
    objects = session.query(Object).filter(Object.id.in_(body_ids)).all()
    by_id = {obj.id: obj for obj in objects}

    bary_by_naif, planet_to_bary, system_name_by_id, system_order_by_id = (
        _load_system_lookup(session)
    )

    grouped: dict[str | None, list[dict]] = {}
    for body_id, meta in texture_metadata.items():
        obj = by_id.get(body_id)
        if obj is None:
            # Orphan texture directory — its body was removed from the DB but
            # the .webp tree lingered. Skip rather than silently credit an
            # unknown target.
            logger.warning(
                "Texture metadata for %s has no matching Object row; skipping",
                body_id,
            )
            continue
        entry = {
            "body_id": body_id,
            "name": _body_name(obj),
            **texture_attribution(meta),
        }
        sys_id = _resolve_system_id(obj, bary_by_naif, planet_to_bary)
        grouped.setdefault(sys_id, []).append(entry)

    for entries in grouped.values():
        entries.sort(key=lambda e: e["name"].lower())

    # Systems first, in Mercury → Pluto order; standalones last.
    systems_out: list[dict] = []
    for sys_id in sorted(
        (s for s in grouped if s is not None),
        key=lambda s: system_order_by_id.get(s, 9999),
    ):
        systems_out.append(
            {
                "id": sys_id,
                "name": system_name_by_id.get(sys_id, sys_id),
                "textures": grouped[sys_id],
            }
        )
    if None in grouped:
        systems_out.append({"id": None, "name": None, "textures": grouped[None]})

    payload = {"systems": systems_out}
    (out_dir / "credits.json").write_bytes(
        orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    )
    total = sum(len(g["textures"]) for g in systems_out)
    logger.info(
        "Wrote credits.json (%d systems, %d textured bodies)",
        len(systems_out),
        total,
    )
