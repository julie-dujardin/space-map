"""`v1/about-data.json` for the `/about/data` page.

One row for each map of each world: how fine it is on the ground, and how many
files and bytes it takes. A patch of a tile pyramid is a row of its own. Each
figure comes from the metadata that ingest writes for a bundle and for a tile
pyramid, so the file needs no pass over the tiles.
"""

import logging
import math
import time
from datetime import UTC, datetime
from pathlib import Path

import orjson
from PIL import Image
from sqlalchemy.orm import Session

from space_map_data.export.system_groups import (
    body_name,
    load_system_lookup,
    resolve_system_id,
)
from space_map_data.export.systems import (
    load_alternate_metadata,
    load_clouds_metadata,
    load_displacement_metadata,
    load_night_metadata,
    load_radii,
    load_specular_metadata,
    load_texture_metadata,
)
from space_map_data.ingest.providers.textures.tiles import HEIGHT_LEVELS
from space_map_data.models.object import Object
from space_map_data.utils.paths import DOWNLOAD_DIR, EXPORT_DIR

logger = logging.getLogger(__name__)

# Values a whole-globe height image can hold: it has 8 bits.
_TIER_HEIGHT_LEVELS = 255


def _figures(value: float, digits: int = 4) -> float:
    """``value`` to ``digits`` significant figures."""
    return float(f"{value:.{digits}g}")


def equator_radius_km(radii: dict) -> float:
    """Mean radius of the equator of a body, from its three semi-axes."""
    return (radii["a"] + radii["b"]) / 2


def ground_scale(width: int, radius_km: float | None) -> dict:
    """``m_per_px`` of a map that is ``width`` pixels around the equator.
    Empty for a body of unknown size."""
    if radius_km is None:
        return {}
    return {"m_per_px": _figures(2 * math.pi * radius_km * 1000 / width)}


def tier_rows(meta: dict) -> list[dict]:
    """The whole-globe images of a bundle, coarsest first. A monthly map has
    one image for each frame, and their sizes add up."""
    exports = meta.get("exports") or {}
    frames = (
        list(exports.values()) if meta["type"] == "cylindrical_monthly" else [exports]
    )
    rows = [
        {
            "name": name,
            "width": image["width"],
            "height": image["height"],
            "size_bytes": sum(frame[name]["size_bytes"] for frame in frames),
        }
        for name, image in frames[0].items()
    ]
    return sorted(rows, key=lambda row: row["width"])


def cloud_tier_rows(bundle_dir: Path, meta: dict) -> list[dict]:
    """The images of a cloud overlay, coarsest first. Its metadata does not
    state their size, so the files tell it."""
    rows = []
    for name in meta["tiers"]:
        files = sorted(bundle_dir.glob(f"{name}_*.webp"))
        if not files:
            continue
        with Image.open(files[0]) as image:
            width, height = image.size
        rows.append(
            {
                "name": name,
                "width": width,
                "height": height,
                "size_bytes": sum(file.stat().st_size for file in files),
            }
        )
    return sorted(rows, key=lambda row: row["width"])


def _source_row(index: int, layer: dict, radius_km: float | None) -> dict:
    """One source of a pyramid. ``base`` covers the whole body, an ``inset``
    replaces it over a band, and ``detail`` gives a colour map its fine
    detail."""
    role = "detail" if layer.get("role") == "brightness" else "inset"
    row: dict = {
        "role": "base" if index == 0 else role,
        "width": layer["full_width"],
        **ground_scale(layer["full_width"], radius_km),
    }
    if layer.get("lat_range") is not None:
        row["lat_range"] = layer["lat_range"]
    return row


def patch_row(patch: dict, tile_size: int, radius_km: float | None) -> dict:
    """One patch: its sharpness, the ground it covers, its tiles."""
    grid_width = 2 * tile_size << patch["max_level"]
    bounds = patch["bounds"]
    row: dict = {
        "id": patch["id"],
        "name": patch["name"],
        "max_level": patch["max_level"],
        # The grid of a level can be finer than the mosaic.
        **ground_scale(min(grid_width, patch["full_width"]), radius_km),
        "lat": round((bounds["north"] + bounds["south"]) / 2, 4),
        "lon": round((bounds["east"] + bounds["west"]) / 2, 4),
        "tiles": sum(level["tiles"] for level in patch["levels"]),
        "size_bytes": sum(level["size_bytes"] for level in patch["levels"]),
    }
    if radius_km is not None:
        per_degree = math.radians(radius_km)
        row["width_km"] = _figures(
            (bounds["east"] - bounds["west"])
            * per_degree
            * math.cos(math.radians(row["lat"]))
        )
        row["height_km"] = _figures((bounds["north"] - bounds["south"]) * per_degree)
    return row


def pyramid_block(tiles: dict, radius_km: float | None) -> dict:
    """The tile pyramid of a map, from its descriptor."""
    width = 2 * tiles["tile_size"] << tiles["max_level"]
    levels = [*tiles["levels"], *tiles["cap_levels"]]
    finest = max(layer["full_width"] for layer in tiles["layers"])
    block: dict = {
        "max_level": tiles["max_level"],
        "width": width,
        "height": width // 2,
        # A level can be wider than the finest source, which then sets the scale.
        **ground_scale(min(width, finest), radius_km),
        "tiles": sum(level["tiles"] for level in levels),
        "size_bytes": sum(level["size_bytes"] for level in levels),
        "sources": [
            _source_row(index, layer, radius_km)
            for index, layer in enumerate(tiles["layers"])
        ],
    }
    if "displacement_scale_km" in tiles:
        block["height_step_m"] = _figures(
            tiles["displacement_scale_km"] * 1000 / HEIGHT_LEVELS
        )
    if tiles.get("patches"):
        block["patches"] = [
            patch_row(patch, tiles["tile_size"], radius_km)
            for patch in tiles["patches"]
        ]
    return block


def map_row(
    layer: str,
    meta: dict,
    tiers: list[dict],
    radius_km: float | None,
    *,
    alternate: bool = False,
) -> dict:
    """One map of a world: its whole-globe images, and its pyramid if it has
    one."""
    row: dict = {"id": meta["id"], "layer": layer}
    if alternate:
        row["alternate"] = True
    frames = meta.get("frames")
    count = len(frames) if isinstance(frames, list) else frames
    if count and count > 1:
        row["frames"] = count
    row["tiers"] = [
        {**tier, **ground_scale(tier["width"], radius_km)} for tier in tiers
    ]
    if "displacement_scale_km" in meta:
        row["height_step_m"] = _figures(
            meta["displacement_scale_km"] * 1000 / _TIER_HEIGHT_LEVELS
        )
    if meta.get("tiles") is not None:
        row["tiles"] = pyramid_block(meta["tiles"], radius_km)
    return row


def world_maps(
    body_id: str,
    radius_km: float | None,
    out_dir: Path,
    textures: dict[str, dict],
    alternates: dict[str, list[dict]],
    clouds: dict[str, dict],
    night: dict[str, dict],
    specular: dict[str, dict],
    displacement: dict[str, dict],
) -> list[dict]:
    """The maps of one world, in the layer order of the credits page."""
    rows = []
    if body_id in textures:
        meta = textures[body_id]
        rows.append(map_row("surface", meta, tier_rows(meta), radius_km))
    for meta in alternates.get(body_id, []):
        rows.append(
            map_row("surface", meta, tier_rows(meta), radius_km, alternate=True)
        )
    if body_id in clouds:
        meta = clouds[body_id]
        tiers = cloud_tier_rows(out_dir / "textures" / meta["id"], meta)
        rows.append(map_row("clouds", meta, tiers, radius_km))
    for layer, metas in (
        ("night", night),
        ("specular", specular),
        ("topography", displacement),
    ):
        if body_id in metas:
            meta = metas[body_id]
            rows.append(map_row(layer, meta, tier_rows(meta), radius_km))
    return rows


def _world_order(obj: Object) -> tuple:
    """The primary of a system first, then its moons in the order of their
    numbers. Bodies with no number go by name."""
    naif = obj.naif_id
    primary = naif is not None and naif % 100 == 99 and naif < 1000
    return (not primary, naif is None, naif or 0, body_name(obj).lower())


def build_about_data(
    session: Session,
    out_dir: Path,
    radii: dict[int, dict],
    textures: dict[str, dict],
    alternates: dict[str, list[dict]],
    clouds: dict[str, dict],
    night: dict[str, dict],
    specular: dict[str, dict],
    displacement: dict[str, dict],
) -> dict:
    """The payload: worlds grouped by planetary system, Mercury to Pluto, then
    the bodies that belong to none."""
    layers = (textures, alternates, clouds, night, specular, displacement)
    body_ids = set().union(*layers)
    objects = session.query(Object).filter(Object.id.in_(body_ids)).all()
    bary_by_id, child_to_bary, system_names, system_order = load_system_lookup(session)
    for body_id in sorted(body_ids - {obj.id for obj in objects}):
        logger.warning("Map metadata for %s has no matching Object row", body_id)

    grouped: dict[str | None, list[dict]] = {}
    for obj in sorted(objects, key=_world_order):
        triaxial = radii.get(obj.naif_id) if obj.naif_id is not None else None
        radius_km = equator_radius_km(triaxial) if triaxial else None
        if radius_km is None:
            logger.warning("No radius for %s: its maps get no ground scale", obj.id)
        world: dict = {"id": obj.id, "name": body_name(obj)}
        if radius_km is not None:
            world["radius_km"] = _figures(radius_km, 6)
        world["maps"] = world_maps(obj.id, radius_km, out_dir, *layers)
        system_id = resolve_system_id(obj, bary_by_id, child_to_bary)
        grouped.setdefault(system_id, []).append(world)

    systems = [
        {
            "id": sys_id,
            "name": system_names[sys_id],
            # The planet the system takes its name from: naif-X99 for naif-X.
            "primary_id": f"naif-{system_order[sys_id] * 100 + 99}",
            "worlds": worlds,
        }
        for sys_id, worlds in sorted(
            ((s, w) for s, w in grouped.items() if s is not None),
            key=lambda item: system_order[item[0]],
        )
    ]
    if None in grouped:
        systems.append({"id": None, "name": None, "worlds": grouped[None]})
    return {"generated_at": datetime.now(UTC).isoformat(), "systems": systems}


def write_about_data(
    session: Session,
    out_dir: Path,
    radii: dict[int, dict],
    textures: dict[str, dict],
    alternates: dict[str, list[dict]],
    clouds: dict[str, dict],
    night: dict[str, dict],
    specular: dict[str, dict],
    displacement: dict[str, dict],
) -> None:
    """Emit `v1/about-data.json`."""
    t0 = time.monotonic()
    payload = build_about_data(
        session,
        out_dir,
        radii,
        textures,
        alternates,
        clouds,
        night,
        specular,
        displacement,
    )
    (out_dir / "about-data.json").write_bytes(
        orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    )
    worlds = [world for system in payload["systems"] for world in system["worlds"]]
    maps = [row for world in worlds for row in world["maps"]]
    logger.info(
        "Wrote about-data.json (%d worlds, %d maps, %d with tiles, %d patches) in %.1fs",
        len(worlds),
        len(maps),
        sum(1 for row in maps if "tiles" in row),
        sum(len(row["tiles"].get("patches", [])) for row in maps if "tiles" in row),
        time.monotonic() - t0,
    )


def export_about_data_only(engine) -> None:
    """`space-map-export --only about-data`. It writes that one file."""
    out_dir = EXPORT_DIR / "v1"
    with Session(engine) as session:
        write_about_data(
            session,
            out_dir,
            load_radii(DOWNLOAD_DIR),
            load_texture_metadata(out_dir),
            load_alternate_metadata(out_dir),
            load_clouds_metadata(out_dir),
            load_night_metadata(out_dir),
            load_specular_metadata(out_dir),
            load_displacement_metadata(out_dir),
        )
