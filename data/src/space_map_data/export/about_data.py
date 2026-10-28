"""`v1/about-data.json` for the `/about/data` page.

One row for each kind of object, each map, each ring bundle and each 3D model:
how fine it is, and how many files and bytes it takes. A patch of a tile
pyramid is a row of its own. The shapes that come from light curves are one
row together. The figures of a map, a ring or a model come from the metadata
that ingest writes for its bundle, so there is no pass over the tiles or the
meshes. The objects are measured from their files, see `about_objects`.
"""

import logging
import math
import time
from datetime import UTC, datetime
from pathlib import Path

import orjson
from PIL import Image
from sqlalchemy.orm import Session

from space_map_data.constants.atmosphere.facts import ATMOSPHERE_FACTS
from space_map_data.export.about_objects import object_rows
from space_map_data.export.system_groups import (
    body_name,
    load_system_lookup,
    resolve_system_id,
)
from space_map_data.export.systems import (
    load_alternate_metadata,
    load_clouds_metadata,
    load_displacement_metadata,
    load_model_metadata,
    load_night_metadata,
    load_radii,
    load_ring_metadata,
    load_specular_metadata,
    load_texture_metadata,
    ring_block,
)
from space_map_data.ingest.providers.models.config import MODEL_CATALOGS
from space_map_data.ingest.providers.textures.tiles import HEIGHT_LEVELS
from space_map_data.models.object import Object
from space_map_data.utils.paths import DOWNLOAD_DIR, EXPORT_DIR, EXTRASOLAR_DIR

logger = logging.getLogger(__name__)

# Values a whole-globe height image can hold: it has 8 bits.
_TIER_HEIGHT_LEVELS = 255

# The files of a model, low before high.
_MODEL_TIERS = ("low", "high")

# Kinds of craft model in the order of the page. Other kinds follow by name.
_CRAFT_KINDS = (
    "probe",
    "earth_sat",
    "station",
    "lander",
    "robot",
    "rocket",
    "generic_sat",
    "comparable",
)


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


def credit(meta: dict) -> dict:
    """Where a map or a patch comes from: the page of its source, who gives
    it, and the credit line."""
    fields = {"source": meta["source"], "organisation": meta["organisation"]}
    if meta.get("attribution") is not None:
        fields["attribution"] = meta["attribution"]
    return fields


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
        **credit(patch),
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
    one. The credit is that of the pyramid, which can have another source
    than the images."""
    row: dict = {
        "id": meta["id"],
        "layer": layer,
        **credit(meta.get("tiles") or meta),
    }
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


def has_no_surface(body_id: str) -> bool:
    """True for a giant planet: its surface map shows its cloud top."""
    facts = ATMOSPHERE_FACTS.get(body_id)
    return facts is not None and facts.note == "no_surface"


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


def ring_row(meta: dict) -> dict:
    """One ring bundle: its radial range, its samples and its strip. The
    figures are those of the system files."""
    block = ring_block(meta)
    inner = block["inner_radius_km"]
    outer = block["outer_radius_km"]
    samples = block["sample_count"]
    return {
        "id": block["bundle"],
        "inner_radius_km": inner,
        "outer_radius_km": outer,
        "samples": samples,
        # The first and the last sample are on the two edges.
        "km_per_sample": _figures((outer - inner) / (samples - 1)),
        "size_bytes": meta["strip"]["size_bytes"],
        "sources": [
            {
                "source": source["source"],
                "organisation": source["organisation"],
                "attribution": source["work"],
            }
            for source in meta["sources"]
        ],
    }


def model_tiers(meta: dict) -> list[dict]:
    """The files of a model, low before high."""
    exports = meta["exports"]
    return [
        {
            "name": name,
            "triangles": exports[name]["stats"]["triangles"],
            "size_bytes": exports[name]["size_bytes"],
        }
        for name in _MODEL_TIERS
        if name in exports
    ]


def _model_credit(credit: dict, attribution: str | None = None) -> dict:
    """The credit of a model in the fields of a map credit. A model can have
    no source page."""
    fields = {"organisation": credit["name"]}
    if credit.get("url") is not None:
        fields["source"] = credit["url"]
    if attribution is not None:
        fields["attribution"] = attribution
    return fields


def craft_sources(meta: dict) -> list[dict]:
    """Who made the files of a model, the high file first. One author has one
    entry, with the page of the highest file."""
    sources: dict[str, dict] = {}
    for name in reversed(_MODEL_TIERS):
        tier = meta["exports"].get(name)
        if tier is not None:
            sources.setdefault(tier["credit"]["name"], _model_credit(tier["credit"]))
    return list(sources.values())


def shape_row(meta: dict) -> dict:
    """The shape model of a world. Its credit line is the citation of the
    data set."""
    return {
        "slug": meta["slug"],
        "provenance": meta["provenance"],
        "tiers": model_tiers(meta),
        "extent_m": _figures(meta["true_scale"]["max_extent_km"] * 1000),
        "sources": [_model_credit(meta["credit"], meta.get("citation"))],
    }


def craft_row(meta: dict, objects: list[tuple[str, str]]) -> dict:
    """One model of a craft or of another object. ``objects`` are the ids and
    names of the objects that the map draws with it."""
    row: dict = {"slug": meta["slug"], "tiers": model_tiers(meta)}
    if (extent := meta["exports"]["high"].get("scale_meters")) is not None:
        row["extent_m"] = extent
    row["sources"] = craft_sources(meta)
    row["objects"] = len(objects)
    if len(objects) == 1:
        row["object"] = {"id": objects[0][0], "name": objects[0][1]}
    return row


def lightcurve_block(metas: list[dict]) -> dict:
    """The shapes from light curves, as one row. Their credit is that of their
    catalogues."""
    tiers = [tier for meta in metas for tier in meta["exports"].values()]
    catalogs = dict.fromkeys(tier["catalog"] for tier in tiers)
    return {
        "models": len(metas),
        "worlds": len({meta["object_id"] for meta in metas}),
        "triangles": sum(model_tiers(meta)[-1]["triangles"] for meta in metas),
        "size_bytes": sum(tier["size_bytes"] for tier in tiers),
        "sources": [
            {
                "source": MODEL_CATALOGS[name]["url"],
                "organisation": MODEL_CATALOGS[name]["default_attribution"],
            }
            for name in catalogs
        ],
    }


def craft_groups(session: Session, metas: list[dict]) -> list[dict]:
    """The models that are not shapes of worlds, by kind. A model lists the
    objects whose ``model_name`` is its slug."""
    slugs = [meta["slug"] for meta in metas]
    drawn: dict[str, list[tuple[str, str]]] = {}
    rows = session.query(Object.id, Object.name, Object.model_name).filter(
        Object.model_name.in_(slugs)
    )
    for object_id, name, slug in rows:
        drawn.setdefault(slug, []).append((object_id, name or object_id))

    by_kind: dict[str, list[dict]] = {}
    for meta in sorted(metas, key=lambda meta: meta["slug"]):
        by_kind.setdefault(meta["kind"], []).append(
            craft_row(meta, sorted(drawn.get(meta["slug"], [])))
        )
    kinds = sorted(
        by_kind,
        key=lambda kind: (
            _CRAFT_KINDS.index(kind) if kind in _CRAFT_KINDS else len(_CRAFT_KINDS),
            kind,
        ),
    )
    return [{"kind": kind, "models": by_kind[kind]} for kind in kinds]


def _world_order(obj: Object) -> tuple:
    """The primary of a system first, then its moons in the order of their
    numbers. Bodies with no number go by name."""
    naif = obj.naif_id
    primary = naif is not None and naif % 100 == 99 and naif < 1000
    return (not primary, naif is None, naif or 0, body_name(obj).lower())


def _placed(
    session: Session, body_ids: set[str], lookup: tuple
) -> list[tuple[Object, str | None]]:
    """The objects of ``body_ids`` in the order of the page, each with the id
    of its system: Mercury to Pluto, then the bodies that belong to none."""
    bary_by_id, child_to_bary, _, system_order = lookup
    objects = session.query(Object).filter(Object.id.in_(body_ids)).all()
    for body_id in sorted(body_ids - {obj.id for obj in objects}):
        logger.warning("Metadata for %s has no matching Object row", body_id)
    placed = [
        (obj, resolve_system_id(obj, bary_by_id, child_to_bary)) for obj in objects
    ]
    return sorted(
        placed,
        key=lambda item: (
            item[1] is None,
            system_order.get(item[1], 0),
            _world_order(item[0]),
        ),
    )


def _world_rows(
    placed: list[tuple[Object, str | None]], field: str, rows: dict[str, list[dict]]
) -> list[dict]:
    """The worlds that have ``rows``, in the order of the page."""
    return [
        {"id": obj.id, "name": body_name(obj), field: rows[obj.id]}
        for obj, _ in placed
        if obj.id in rows
    ]


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
    rings: dict[str, list[dict]],
    models: dict[str, dict],
    extrasolar_dir: Path,
) -> dict:
    """The payload. The objects are one row for each kind, with the
    extrasolar export below `extrasolar_dir`.
    The maps are grouped by planetary system. The rings and the shape models
    are lists of worlds in the same order."""
    layers = (textures, alternates, clouds, night, specular, displacement)
    mapped = set().union(*layers)
    lightcurve = []
    craft = []
    shapes: dict[str, list[dict]] = {}
    for _, meta in sorted(models.items()):
        if meta["kind"] != "shape_model":
            craft.append(meta)
        elif meta["provenance"] == "lightcurve":
            lightcurve.append(meta)
        else:
            shapes.setdefault(meta["object_id"], []).append(shape_row(meta))

    lookup = load_system_lookup(session)
    _, _, system_names, system_order = lookup
    placed = _placed(session, mapped | set(rings) | set(shapes), lookup)

    grouped: dict[str | None, list[dict]] = {}
    for obj, system_id in placed:
        if obj.id not in mapped:
            continue
        triaxial = radii.get(obj.naif_id) if obj.naif_id is not None else None
        radius_km = equator_radius_km(triaxial) if triaxial else None
        if radius_km is None:
            logger.warning("No radius for %s: its maps get no ground scale", obj.id)
        world: dict = {"id": obj.id, "name": body_name(obj)}
        if radius_km is not None:
            world["radius_km"] = _figures(radius_km, 6)
        if has_no_surface(obj.id):
            world["no_surface"] = True
        world["maps"] = world_maps(obj.id, radius_km, out_dir, *layers)
        grouped.setdefault(system_id, []).append(world)

    systems: list[dict] = [
        {
            "id": sys_id,
            "name": system_names[sys_id],
            # The planet the system takes its name from: naif-X99 for naif-X.
            "primary_id": f"naif-{system_order[sys_id] * 100 + 99}",
            "worlds": worlds,
        }
        for sys_id, worlds in grouped.items()
        if sys_id is not None
    ]
    if None in grouped:
        systems.append({"id": None, "name": None, "worlds": grouped[None]})

    model_block: dict = {
        "worlds": _world_rows(placed, "models", shapes),
        "craft": craft_groups(session, craft),
    }
    if lightcurve:
        model_block["lightcurve"] = lightcurve_block(lightcurve)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        # The bodies with a map, a ring or a shape model. Shapes from light
        # curves do not count: the models figure already holds them.
        "worlds": len(placed),
        "objects": object_rows(out_dir, extrasolar_dir),
        "systems": systems,
        "rings": _world_rows(
            placed,
            "rings",
            {
                body_id: [ring_row(meta) for meta in metas]
                for body_id, metas in rings.items()
            },
        ),
        "models": model_block,
    }


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
    rings: dict[str, list[dict]],
    models: dict[str, dict],
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
        rings,
        models,
        EXTRASOLAR_DIR,
    )
    (out_dir / "about-data.json").write_bytes(
        orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    )
    worlds = [world for system in payload["systems"] for world in system["worlds"]]
    maps = [row for world in worlds for row in world["maps"]]
    model_block = payload["models"]
    logger.info(
        "Wrote about-data.json (%d objects in %d kinds, %d worlds, %d maps, "
        "%d with tiles, %d patches, %d ring bundles, %d shape models, "
        "%d from light curves, %d other models) in %.1fs",
        sum(row["count"] for row in payload["objects"]),
        len(payload["objects"]),
        payload["worlds"],
        len(maps),
        sum(1 for row in maps if "tiles" in row),
        sum(len(row["tiles"].get("patches", [])) for row in maps if "tiles" in row),
        sum(len(world["rings"]) for world in payload["rings"]),
        sum(len(world["models"]) for world in model_block["worlds"]),
        model_block.get("lightcurve", {}).get("models", 0),
        sum(len(group["models"]) for group in model_block["craft"]),
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
            load_ring_metadata(out_dir),
            load_model_metadata(out_dir),
        )
