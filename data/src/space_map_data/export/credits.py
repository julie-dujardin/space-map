"""Aggregated `v1/credits.json` for the `/credits` frontend page.

Per-body credits (textures, rings, clouds, skybox) plus the static
ephemeris-archive catalog. Each body's archive id lives in its global JSON
under `ephemeris_source`.
"""

import logging
import orjson
from pathlib import Path

from sqlalchemy.orm import Session

from space_map_data.export.ephemeris import EPHEMERIS_ARCHIVES
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
) -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, int]]:
    """Build the mappings needed to group a textured body under a system.

    Returns:
      * `bary_by_id` — `{bary_obj_id: bary_obj_id}` (e.g. `"naif-3" → "naif-3"`).
        Identity map; lookups use `obj.parent_id in bary_by_id`.
      * `child_to_bary` — `{child_obj_id: bary_obj_id}` for direct children
        of a barycenter, so a body parented on Earth (`naif-399`) routes to
        the Earth–Moon barycenter (`naif-3`).
      * `system_name_by_id` — `{bary_obj_id: display_name}` using the primary
        planet's name (e.g. `"naif-3" → "Earth"`) rather than the cluttered
        `"Earth-Moon Barycenter"` DB label.
      * `system_order_by_id` — `{bary_obj_id: bary_naif_id}` so the output
        can render Mercury → Pluto by natural ordinal.
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

    # Prefer the primary planet's name as the system label (naif-X99 for
    # barycenter naif-X) — "Earth" reads better than "Earth-Moon Barycenter".
    system_name_by_id: dict[str, str] = {}
    primary_naif_ids = [
        (b.naif_id or 0) * 100 + 99 for b in barycenters if b.naif_id is not None
    ]
    primaries = session.query(Object).filter(Object.naif_id.in_(primary_naif_ids)).all()
    primary_by_naif = {p.naif_id: p for p in primaries}
    for bary in barycenters:
        if bary.naif_id is None:
            continue
        primary = primary_by_naif.get(bary.naif_id * 100 + 99)
        if primary and primary.name:
            system_name_by_id[bary.id] = primary.name
        else:
            # Fallback: strip the redundant "Barycenter" suffix.
            name = bary.name or bary.id
            system_name_by_id[bary.id] = name.replace(" Barycenter", "").strip()

    return bary_by_id, child_to_bary, system_name_by_id, system_order_by_id


def _resolve_system_id(
    obj: Object,
    bary_by_id: dict[str, str],
    child_to_bary: dict[str, str],
) -> str | None:
    """Return the barycenter ID that textually owns *obj*, or None for standalones.

    Mirrors the containment rules used by `write_system_metadata`: a body
    parented directly on a barycenter, parented on one of its children (e.g.
    an Earth satellite routing up to Earth-Moon), or being a barycenter
    itself, all count as "inside" that system.
    """
    if obj.parent_id in bary_by_id:
        return bary_by_id[obj.parent_id]
    if obj.parent_id in child_to_bary:
        return child_to_bary[obj.parent_id]
    if obj.id in bary_by_id:
        return bary_by_id[obj.id]
    return None


def _sibling_credit_entry(body_id: str, name: str, meta: dict) -> dict:
    """Shape a non-texture credit entry (rings, clouds, …).

    Mirrors a texture entry minus the ``type`` field; the array name does the
    disambiguation, so no synthetic body id like ``naif-699-rings`` is needed.
    """
    entry: dict = {
        "body_id": body_id,
        "name": name,
        "source": meta["source"],
        "organisation": meta["organisation"],
    }
    if meta.get("attribution") is not None:
        entry["attribution"] = meta["attribution"]
    if meta.get("description") is not None:
        entry["description"] = meta["description"]
    return entry


def _skybox_credit_entry(meta: dict) -> dict:
    """Shape the top-level skybox credit entry from the bundle metadata."""
    entry: dict = {
        "source": meta["source"],
        "organisation": meta["organisation"],
    }
    if meta.get("attribution") is not None:
        entry["attribution"] = meta["attribution"]
    if meta.get("description") is not None:
        entry["description"] = meta["description"]
    return entry


def write_credits(
    session: Session,
    out_dir: Path,
    texture_metadata: dict[str, dict],
    ring_metadata: dict[str, dict],
    clouds_metadata: dict[str, dict],
    skybox_metadata: dict | None,
) -> None:
    """Emit `v1/credits.json` summarising every credit-worthy data source.

    Groups credit-worthy bodies by their host planetary system (Earth,
    Jupiter, …) so the frontend can render sections instead of a flat
    alphabetical list. A final null-id group collects standalones (sun-
    orbiting asteroids and dwarf planets like Bennu or Ceres) that don't
    belong to a system. Each system bucket carries sibling `textures`,
    `rings`, and `clouds` arrays — all optional; only populated arrays are
    emitted. The whole-sky cubemap skybox is a one-off backdrop with no host
    body, so it rides at the top level alongside `systems`.
    """
    body_ids = set(texture_metadata) | set(ring_metadata) | set(clouds_metadata)
    objects = session.query(Object).filter(Object.id.in_(body_ids)).all()
    by_id = {obj.id: obj for obj in objects}

    bary_by_id, child_to_bary, system_name_by_id, system_order_by_id = (
        _load_system_lookup(session)
    )

    textures_grouped: dict[str | None, list[dict]] = {}
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
        sys_id = _resolve_system_id(obj, bary_by_id, child_to_bary)
        textures_grouped.setdefault(sys_id, []).append(entry)

    rings_grouped: dict[str | None, list[dict]] = {}
    for body_id, meta in ring_metadata.items():
        obj = by_id.get(body_id)
        if obj is None:
            logger.warning(
                "Ring metadata for %s has no matching Object row; skipping",
                body_id,
            )
            continue
        sys_id = _resolve_system_id(obj, bary_by_id, child_to_bary)
        rings_grouped.setdefault(sys_id, []).append(
            _sibling_credit_entry(body_id, _body_name(obj), meta)
        )

    clouds_grouped: dict[str | None, list[dict]] = {}
    for body_id, meta in clouds_metadata.items():
        obj = by_id.get(body_id)
        if obj is None:
            logger.warning(
                "Cloud metadata for %s has no matching Object row; skipping",
                body_id,
            )
            continue
        sys_id = _resolve_system_id(obj, bary_by_id, child_to_bary)
        clouds_grouped.setdefault(sys_id, []).append(
            _sibling_credit_entry(body_id, _body_name(obj), meta)
        )

    for entries in textures_grouped.values():
        entries.sort(key=lambda e: e["name"].lower())
    for entries in rings_grouped.values():
        entries.sort(key=lambda e: e["name"].lower())
    for entries in clouds_grouped.values():
        entries.sort(key=lambda e: e["name"].lower())

    # Systems first, in Mercury → Pluto order; standalones last.
    sys_ids: set[str | None] = (
        set(textures_grouped) | set(rings_grouped) | set(clouds_grouped)
    )
    systems_out: list[dict] = []
    for sys_id in sorted(
        (s for s in sys_ids if s is not None),
        key=lambda s: system_order_by_id.get(s, 9999),
    ):
        bucket: dict = {
            "id": sys_id,
            "name": system_name_by_id.get(sys_id, sys_id),
        }
        if sys_id in textures_grouped:
            bucket["textures"] = textures_grouped[sys_id]
        if sys_id in rings_grouped:
            bucket["rings"] = rings_grouped[sys_id]
        if sys_id in clouds_grouped:
            bucket["clouds"] = clouds_grouped[sys_id]
        systems_out.append(bucket)
    if None in sys_ids:
        bucket = {"id": None, "name": None}
        if None in textures_grouped:
            bucket["textures"] = textures_grouped[None]
        if None in rings_grouped:
            bucket["rings"] = rings_grouped[None]
        if None in clouds_grouped:
            bucket["clouds"] = clouds_grouped[None]
        systems_out.append(bucket)

    payload: dict = {
        "systems": systems_out,
        "ephemeris_archives": EPHEMERIS_ARCHIVES,
    }
    if skybox_metadata is not None:
        payload["skybox"] = _skybox_credit_entry(skybox_metadata)
    (out_dir / "credits.json").write_bytes(
        orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    )
    n_textures = sum(len(g) for g in textures_grouped.values())
    n_rings = sum(len(g) for g in rings_grouped.values())
    n_clouds = sum(len(g) for g in clouds_grouped.values())
    logger.info(
        "Wrote credits.json (%d systems, %d textured / %d ringed / %d clouded bodies%s)",
        len(systems_out),
        n_textures,
        n_rings,
        n_clouds,
        ", + skybox" if skybox_metadata is not None else "",
    )
