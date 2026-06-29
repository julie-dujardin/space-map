"""Write per-system metadata: systems/{barycenter_id}.json.

Each file contains texture tier info and orientation data for bodies in that
planetary system.
"""

import csv
import logging
import orjson
from pathlib import Path

from sqlalchemy.orm import Session

from space_map_data.export.sidecar_io import mirror_path
from space_map_data.models.object import Object, ObjectType

logger = logging.getLogger(__name__)

_TOP_LEVEL_NAIF_IDS = {0, 10}  # SSB and Sun

# Bodies whose texture directory name ends with this carry a cloud-overlay
# bundle rather than a regular surface texture. The host body id is the
# directory name minus this suffix.
_CLOUDS_SUFFIX = "_clouds"
# Sibling bundle holding a specular/roughness map for the host body
# (e.g. naif-399_specular carries Earth's ocean mask).
_SPECULAR_SUFFIX = "_specular"
# Sibling bundle holding an emissive night-lights map for the host body
# (e.g. naif-399_night carries NASA Black Marble for Earth).
_NIGHT_SUFFIX = "_night"
# Sibling bundle holding a displacement/height map for the host body
# (e.g. naif-301_displacement carries the Moon's LRO LOLA topography).
_DISPLACEMENT_SUFFIX = "_displacement"
# Top-level celestial-sphere texture directory — `textures/stars/`. Holds the
# cubemap-skybox bundle the renderer drops behind the whole scene as
# `scene.background`. Not tied to any NAIF body.
_SKYBOX_DIR = "stars"

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
    """Load orientation polynomial coefficients from SPICE orientation.csv.

    Returns {naif_id: {pole_ra_0, pole_ra_1, pole_dec_0, pole_dec_1, w0, w1, w2}}.
    """
    csv_path = download_dir / "derived" / "position" / "tables" / "orientation.csv"
    if not csv_path.exists():
        logger.warning("No orientation CSV at %s", csv_path)
        return {}
    result: dict[int, dict] = {}
    with csv_path.open(newline="") as f:
        for row in csv.DictReader(f):
            naif_id = int(row["naif_id"])
            result[naif_id] = {
                "pole_ra_0": float(row["pole_ra_0"]),
                "pole_ra_1": float(row["pole_ra_1"]),
                "pole_dec_0": float(row["pole_dec_0"]),
                "pole_dec_1": float(row["pole_dec_1"]),
                "w0": float(row["w0"]),
                "w1": float(row["w1"]),
                "w2": float(row["w2"]),
            }
    logger.info("Loaded %d orientation records", len(result))
    return result


def load_nut_prec(download_dir: Path) -> dict[int, dict[str, list[float]]]:
    """Load NUT_PREC coefficient arrays per body.

    Returns {naif_id: {"ra": [...], "dec": [...], "pm": [...]}}.
    """
    json_path = download_dir / "derived" / "position" / "tables" / "nut_prec.json"
    if not json_path.exists():
        logger.warning("No nut_prec JSON at %s", json_path)
        return {}
    raw = orjson.loads(json_path.read_bytes())
    result = {int(naif_id): coeffs for naif_id, coeffs in raw.items()}
    logger.info("Loaded NUT_PREC coefficients for %d bodies", len(result))
    return result


def load_nut_prec_angles(download_dir: Path) -> dict[int, list[float]]:
    """Load NUT_PREC_ANGLES per owner (planetary system barycenter).

    Returns {owner_naif_id: [θ₀_1, θ₁_1, θ₀_2, θ₁_2, ...]} (deg, deg/century).
    """
    json_path = (
        download_dir / "derived" / "position" / "tables" / "nut_prec_angles.json"
    )
    if not json_path.exists():
        logger.warning("No nut_prec_angles JSON at %s", json_path)
        return {}
    raw = orjson.loads(json_path.read_bytes())
    result = {int(owner): vals for owner, vals in raw.items()}
    logger.info("Loaded NUT_PREC_ANGLES for %d owners", len(result))
    return result


def texture_attribution(meta: dict) -> dict:
    """Extract the user-facing attribution subset from a texture metadata dict."""
    result = {
        "source": meta["source"],
        "organisation": meta["organisation"],
        "type": meta["type"],
    }
    if meta.get("attribution") is not None:
        result["attribution"] = meta["attribution"]
    if meta.get("description") is not None:
        result["description"] = meta["description"]
    if meta.get("frames") is not None:
        result["frames"] = meta["frames"]
    return result


def _tiers_from_meta(meta: dict) -> list[str]:
    """Return the sorted tier names available for a textured body.

    Single-frame metadata stores ``exports = {tier: rec}``; monthly metadata
    stores ``exports = {frame: {tier: rec}}``; cloud-overlay metadata skips
    per-frame export records entirely and lists tiers explicitly. We expose
    the per-tier enumeration in any case so the frontend's URL builder
    doesn't have to care about the layout.
    """
    if meta.get("type") == "clouds_overlay":
        return sorted(meta.get("tiers") or [])
    exports = meta.get("exports") or {}
    if meta.get("type") == "cylindrical_monthly":
        first_frame = next(iter(exports.values()), {})
        return sorted(first_frame.keys())
    return sorted(exports.keys())


def load_texture_metadata(out_dir: Path) -> dict[str, dict]:
    """Load all per-body surface texture metadata.json files from the export tree.

    Returns {object_id: metadata_dict}. Sibling bundles whose directory ends
    in ``_clouds``, ``_specular`` or ``_night`` are filtered out; use the
    dedicated loaders for those.

    Body ids come from the data dir (``out_dir/textures``) but metadata.json
    is read from the mirror dir; ingest writes the texture's webp variants
    and its metadata.json to those two paths separately.
    """
    textures_dir = out_dir / "textures"
    result: dict[str, dict] = {}
    if not textures_dir.exists():
        return result
    for body_dir in textures_dir.iterdir():
        if not body_dir.is_dir() or body_dir.name.endswith(
            (_CLOUDS_SUFFIX, _SPECULAR_SUFFIX, _NIGHT_SUFFIX, _DISPLACEMENT_SUFFIX)
        ):
            continue
        meta_file = mirror_path(body_dir / "metadata.json")
        if meta_file.exists():
            result[body_dir.name] = orjson.loads(meta_file.read_bytes())
    logger.info("Loaded texture metadata for %d bodies", len(result))
    return result


def load_clouds_metadata(out_dir: Path) -> dict[str, dict]:
    """Load per-body cloud-overlay metadata.json files from the export tree.

    Returns {host_object_id: metadata_dict} — the directory's ``_clouds``
    suffix is stripped so callers can look up by the surface body's id
    (e.g. ``naif-399`` for Earth's clouds at ``textures/naif-399_clouds/``).
    The full export id (``naif-399_clouds``) is preserved in the metadata's
    own ``id`` field for URL composition.
    """
    textures_dir = out_dir / "textures"
    result: dict[str, dict] = {}
    if not textures_dir.exists():
        return result
    for body_dir in textures_dir.iterdir():
        if not body_dir.is_dir() or not body_dir.name.endswith(_CLOUDS_SUFFIX):
            continue
        meta_file = mirror_path(body_dir / "metadata.json")
        if meta_file.exists():
            host_id = body_dir.name.removesuffix(_CLOUDS_SUFFIX)
            result[host_id] = orjson.loads(meta_file.read_bytes())
    logger.info("Loaded cloud-overlay metadata for %d bodies", len(result))
    return result


def clouds_block(meta: dict) -> dict:
    """Build the per-body ``clouds`` block emitted into systems/{bary}.json
    and the global object detail file.

    Carries everything the renderer needs to fetch and credit a cloud
    overlay: the export's own id (its directory, parallel to the surface
    texture), the tier list, the available snapshot frame ids, and
    attribution fields. The frontend composes URLs as
    ``/v1/textures/{clouds.id}/{tier}_{frame}.webp``.
    """
    block: dict = {
        "id": meta["id"],
        "tiers": _tiers_from_meta(meta),
        "frames": list(meta.get("frames") or []),
        "source": meta["source"],
        "organisation": meta["organisation"],
        "type": meta["type"],
    }
    if meta.get("attribution") is not None:
        block["attribution"] = meta["attribution"]
    if meta.get("description") is not None:
        block["description"] = meta["description"]
    return block


def load_specular_metadata(out_dir: Path) -> dict[str, dict]:
    """Load per-body specular-map metadata.json files from the export tree.

    Returns {host_object_id: metadata_dict} keyed by the surface body's id
    (e.g. ``naif-399`` for ``textures/naif-399_specular/``). The full export
    id is preserved in the metadata's own ``id`` field for URL composition.
    """
    textures_dir = out_dir / "textures"
    result: dict[str, dict] = {}
    if not textures_dir.exists():
        return result
    for body_dir in textures_dir.iterdir():
        if not body_dir.is_dir() or not body_dir.name.endswith(_SPECULAR_SUFFIX):
            continue
        meta_file = mirror_path(body_dir / "metadata.json")
        if meta_file.exists():
            host_id = body_dir.name.removesuffix(_SPECULAR_SUFFIX)
            result[host_id] = orjson.loads(meta_file.read_bytes())
    logger.info("Loaded specular metadata for %d bodies", len(result))
    return result


def specular_block(meta: dict) -> dict:
    """Build the per-body ``specular`` block emitted into systems/{bary}.json.

    Carries the export's own id (sibling directory of the surface texture),
    the available tier list, and attribution. The frontend composes URLs as
    ``/v1/textures/{specular.id}/{tier}.webp`` — single-frame, no per-frame
    suffix.
    """
    block: dict = {
        "id": meta["id"],
        "tiers": _tiers_from_meta(meta),
        "source": meta["source"],
        "organisation": meta["organisation"],
        "type": meta["type"],
    }
    if meta.get("attribution") is not None:
        block["attribution"] = meta["attribution"]
    if meta.get("description") is not None:
        block["description"] = meta["description"]
    return block


def load_night_metadata(out_dir: Path) -> dict[str, dict]:
    """Load per-body night-lights metadata.json files from the export tree.

    Returns {host_object_id: metadata_dict} keyed by the surface body's id
    (e.g. ``naif-399`` for ``textures/naif-399_night/``). The full export
    id is preserved in the metadata's own ``id`` field for URL composition.
    """
    textures_dir = out_dir / "textures"
    result: dict[str, dict] = {}
    if not textures_dir.exists():
        return result
    for body_dir in textures_dir.iterdir():
        if not body_dir.is_dir() or not body_dir.name.endswith(_NIGHT_SUFFIX):
            continue
        meta_file = mirror_path(body_dir / "metadata.json")
        if meta_file.exists():
            host_id = body_dir.name.removesuffix(_NIGHT_SUFFIX)
            result[host_id] = orjson.loads(meta_file.read_bytes())
    logger.info("Loaded night-lights metadata for %d bodies", len(result))
    return result


def night_block(meta: dict) -> dict:
    """Build the per-body ``night`` block emitted into systems/{bary}.json.

    Carries the export's own id (sibling directory of the surface texture),
    the available tier list, and attribution. The frontend composes URLs as
    ``/v1/textures/{night.id}/{tier}.webp`` — single-frame, no per-frame
    suffix.
    """
    block: dict = {
        "id": meta["id"],
        "tiers": _tiers_from_meta(meta),
        "source": meta["source"],
        "organisation": meta["organisation"],
        "type": meta["type"],
    }
    if meta.get("attribution") is not None:
        block["attribution"] = meta["attribution"]
    if meta.get("description") is not None:
        block["description"] = meta["description"]
    return block


def load_displacement_metadata(out_dir: Path) -> dict[str, dict]:
    """Load per-body displacement-map metadata.json files from the export tree.

    Returns {host_object_id: metadata_dict} keyed by the surface body's id
    (e.g. ``naif-301`` for ``textures/naif-301_displacement/``). The full
    export id is preserved in the metadata's own ``id`` field for URL composition.
    """
    textures_dir = out_dir / "textures"
    result: dict[str, dict] = {}
    if not textures_dir.exists():
        return result
    for body_dir in textures_dir.iterdir():
        if not body_dir.is_dir() or not body_dir.name.endswith(_DISPLACEMENT_SUFFIX):
            continue
        meta_file = mirror_path(body_dir / "metadata.json")
        if meta_file.exists():
            host_id = body_dir.name.removesuffix(_DISPLACEMENT_SUFFIX)
            result[host_id] = orjson.loads(meta_file.read_bytes())
    logger.info("Loaded displacement metadata for %d bodies", len(result))
    return result


def displacement_block(meta: dict) -> dict:
    """Build the per-body ``displacement`` block emitted into systems/{bary}.json.

    Carries the export's own id (sibling directory of the surface texture),
    the tier list, and the physical km mapping the renderer needs to scale
    `material.displacementMap`: radial offset km = bias + scale * texel. The
    frontend composes URLs as ``/v1/textures/{displacement.id}/{tier}.webp``.
    """
    block: dict = {
        "id": meta["id"],
        "tiers": _tiers_from_meta(meta),
        "scale_km": meta["displacement_scale_km"],
        "bias_km": meta["displacement_bias_km"],
        "source": meta["source"],
        "organisation": meta["organisation"],
        "type": meta["type"],
    }
    if meta.get("attribution") is not None:
        block["attribution"] = meta["attribution"]
    if meta.get("description") is not None:
        block["description"] = meta["description"]
    return block


def load_skybox_metadata(out_dir: Path) -> dict | None:
    """Load the cubemap-skybox bundle metadata.json from the export tree.

    Returns the parsed metadata dict, or None when no skybox bundle has been
    ingested. The renderer drops a single skybox behind the whole scene; if
    multiple skyboxes ever ship, this returns the one at ``textures/stars/``.
    """
    meta_file = mirror_path(out_dir / "textures" / _SKYBOX_DIR / "metadata.json")
    if not meta_file.exists():
        return None
    return orjson.loads(meta_file.read_bytes())


def skybox_block(meta: dict) -> dict:
    """Build the top-level ``skybox`` block embedded in v1/metadata.json.

    Carries only what the frontend needs to fetch faces and credit the
    bundle: id, face/tier shape, encoding, sky frame, and attribution.
    The renderer composes URLs as ``/v1/textures/{skybox.id}/{tier}_{face}.webp``
    where face ∈ ``faces`` and tier ∈ ``tiers``.
    """
    block: dict = {
        "id": meta["id"],
        "type": meta["type"],
        "encoding": meta["encoding"],
        "frame": meta["frame"],
        "faces": list(meta["faces"]),
        "tiers": list(meta["tiers"]),
        "tier_face_size": dict(meta["tier_face_size"]),
        "source": meta["source"],
        "organisation": meta["organisation"],
    }
    if meta.get("attribution") is not None:
        block["attribution"] = meta["attribution"]
    if meta.get("description") is not None:
        block["description"] = meta["description"]
    return block


def load_ring_metadata(out_dir: Path) -> dict[str, dict]:
    """Load all per-body ring metadata.json files from the export tree.

    Returns {object_id: metadata_dict}. Only bodies whose ring bundle was
    successfully ingested are included.
    """
    rings_dir = out_dir / "rings"
    result: dict[str, dict] = {}
    if not rings_dir.exists():
        return result
    for body_dir in rings_dir.iterdir():
        if not body_dir.is_dir():
            continue
        meta_file = mirror_path(body_dir / "metadata.json")
        if meta_file.exists():
            result[body_dir.name] = orjson.loads(meta_file.read_bytes())
    logger.info("Loaded ring metadata for %d bodies", len(result))
    return result


def load_model_metadata(out_dir: Path) -> dict[str, dict]:
    """Load all per-slug 3D-model metadata.json files from the export tree.

    Returns ``{slug: metadata_dict}``. Unlike the texture/ring/clouds
    loaders, the model metadata.json lives in ``EXPORT_DIR`` itself
    (publicly served — clients fetch it to get the source catalog, tier
    stats, and mission list); no mirror_path indirection.
    """
    models_dir = out_dir / "models"
    result: dict[str, dict] = {}
    if not models_dir.exists():
        return result
    for slug_dir in models_dir.iterdir():
        if not slug_dir.is_dir():
            continue
        meta_file = slug_dir / "metadata.json"
        if meta_file.exists():
            result[slug_dir.name] = orjson.loads(meta_file.read_bytes())
    logger.info("Loaded model metadata for %d slugs", len(result))
    return result


def ring_block(meta: dict) -> dict:
    """Build the per-body `rings` block emitted into systems/{bary}.json and
    the global object detail.

    Carries the geometry constants the renderer needs (inner/outer radius,
    sample count, color space) plus credit fields and a flat channel→file
    map; the frontend composes URLs as
    ``/v1/rings/{body_id}/{channels[name]}``.
    """
    block = {
        "source": meta["source"],
        "organisation": meta["organisation"],
        "inner_radius_km": float(meta["inner_radius_km"]),
        "outer_radius_km": float(meta["outer_radius_km"]),
        "sample_count": int(meta["sample_count"]),
        "color_space": meta.get("color_space", "srgb"),
        "channels": {name: rec["file"] for name, rec in meta["channels"].items()},
    }
    if meta.get("attribution") is not None:
        block["attribution"] = meta["attribution"]
    if meta.get("description") is not None:
        block["description"] = meta["description"]
    return block


def load_radii(download_dir: Path) -> dict[int, dict]:
    """Load triaxial radii from SPICE radii.csv.

    Returns {naif_id: {a, b, c}} in km along body-fixed X, Y, Z.
    """
    csv_path = download_dir / "derived" / "position" / "tables" / "radii.csv"
    if not csv_path.exists():
        logger.warning("No radii CSV at %s", csv_path)
        return {}
    result: dict[int, dict] = {}
    with csv_path.open(newline="") as f:
        for row in csv.DictReader(f):
            naif_id = int(row["naif_id"])
            result[naif_id] = {
                "a": float(row["radius_a_km"]),
                "b": float(row["radius_b_km"]),
                "c": float(row["radius_c_km"]),
            }
    logger.info("Loaded %d radii records", len(result))
    return result


def load_gms(download_dir: Path) -> dict[int, float]:
    """Load gravitational parameters (km^3/s^2) from SPICE gm.csv.

    Returns {naif_id: gm_km3_s2}. The CSV includes a synthesized SSB row
    (naif_id 0) reusing the Sun's GM — see `_extract_gms` in the SPICE
    download module.
    """
    csv_path = download_dir / "derived" / "position" / "tables" / "gm.csv"
    if not csv_path.exists():
        logger.warning("No GM CSV at %s", csv_path)
        return {}
    result: dict[int, float] = {}
    with csv_path.open(newline="") as f:
        for row in csv.DictReader(f):
            result[int(row["naif_id"])] = float(row["gm_km3_s2"])
    logger.info("Loaded %d GM records", len(result))
    return result


def load_planet_elements(download_dir: Path) -> dict[int, dict]:
    """Mean planet elements (Horizons) → {naif_id: {"a": AU, "i": deg}}.

    Baked at download time by `fetch_planet_elements`; the major planets carry no
    SBDB row, so this is the minimap's source for their distance + inclination.
    """
    path = download_dir / "derived" / "position" / "tables" / "planet_elements.json"
    if not path.exists():
        logger.warning("No planet elements JSON at %s", path)
        return {}
    data = orjson.loads(path.read_bytes())
    result = {int(k): {"a": v["a"], "i": v["i"]} for k, v in data.items()}
    logger.info("Loaded %d planet element records", len(result))
    return result


def write_systems_global(
    out_dir: Path,
    gms: dict[int, float],
    nut_prec_angles: dict[int, list[float]],
) -> None:
    """Write the always-loaded `systems/global.json` lookup file.

    Holds context-independent data the frontend needs upfront regardless of
    which planetary system the user is viewing:

    - `gm`: full per-body GM table (km^3/s^2). Used by chebyshev trail-buffer
      sizing to estimate orbital periods via Kepler's third law for any
      parent NAIF id encountered.
    - `nut_prec_angles`: NUT_PREC_ANGLES coefficients per planetary-system
      owner. Paired with per-body `nut_prec` arrays in the per-system files.
    """
    if not gms and not nut_prec_angles:
        return
    systems_dir = out_dir / "systems"
    systems_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, dict] = {}
    if gms:
        payload["gm"] = {str(naif_id): gm for naif_id, gm in sorted(gms.items())}
    if nut_prec_angles:
        payload["nut_prec_angles"] = {
            str(owner): vals for owner, vals in sorted(nut_prec_angles.items())
        }
    (systems_dir / "global.json").write_bytes(orjson.dumps(payload))
    logger.info(
        "Wrote systems/global.json (%d GMs, %d nut_prec_angles owners)",
        len(gms),
        len(nut_prec_angles),
    )


def write_system_metadata(
    session: Session,
    out_dir: Path,
    orientation: dict[int, dict],
    radii: dict[int, dict],
    nut_prec: dict[int, dict[str, list[float]]],
    texture_metadata: dict[str, dict],
    ring_metadata: dict[str, dict],
    clouds_metadata: dict[str, dict],
    specular_metadata: dict[str, dict],
    night_metadata: dict[str, dict],
    displacement_metadata: dict[str, dict],
) -> None:
    """Generate one metadata file per planetary system.

    Each file is keyed by body ID and contains texture tiers (if available)
    and orientation data (if available from SPICE PCK).
    """
    # Build barycenter Object.id set (planetary system barycenters parented
    # directly on SSB / Sun).
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
    bary_ids: set[str] = {b.id for b in barycenters}

    # Map child Object.id -> barycenter Object.id (one level down — e.g.
    # naif-399 (Earth) → naif-3 (EMB)).
    child_to_bary: dict[str, str] = {}
    for bary in barycenters:
        children = session.query(Object).filter(Object.parent_id == bary.id).all()
        for child in children:
            child_to_bary[child.id] = bary.id

    # Query all bodies that belong to planetary systems (not just textured ones)
    system_bodies = (
        session.query(Object)
        .filter(Object.object_type.in_([t.value for t in _SYSTEM_TYPES]))
        .all()
    )

    # Group by system barycenter
    systems: dict[str, list[Object]] = {}
    for obj in system_bodies:
        if obj.parent_id in bary_ids:
            sys_id = obj.parent_id
        elif obj.parent_id in child_to_bary:
            sys_id = child_to_bary[obj.parent_id]
        elif obj.id in bary_ids:
            # The barycenter itself
            sys_id = obj.id
        else:
            continue  # top-level or not in a system
        assert sys_id is not None
        systems.setdefault(sys_id, []).append(obj)

    # Write one JSON file per system
    systems_dir = out_dir / "systems"
    systems_dir.mkdir(parents=True, exist_ok=True)
    for sys_id, objs in systems.items():
        bodies: dict[str, dict] = {}
        for obj in objs:
            entry: dict = {}

            # Texture tiers + attribution
            if obj.map_texture_available:
                meta = texture_metadata.get(obj.id)
                if meta is not None:
                    entry["tiers"] = _tiers_from_meta(meta)
                    entry["texture"] = texture_attribution(meta)
                else:
                    logger.warning(
                        "Texture metadata missing for %s (system %s), skipping tiers",
                        obj.id,
                        sys_id,
                    )

            # Orientation data
            if obj.naif_id is not None and obj.naif_id in orientation:
                entry["orientation"] = orientation[obj.naif_id]

            # Nutation/precession coefficients (paired with global nut_prec_angles.json)
            if obj.naif_id is not None and obj.naif_id in nut_prec:
                entry["nut_prec"] = nut_prec[obj.naif_id]

            # Triaxial radii (km, along body-fixed X, Y, Z)
            if obj.naif_id is not None and obj.naif_id in radii:
                entry["radii"] = radii[obj.naif_id]

            # Ring profile bundle (only on bodies whose ingest produced one).
            if obj.has_rings:
                meta = ring_metadata.get(obj.id)
                if meta is not None:
                    entry["rings"] = ring_block(meta)
                else:
                    logger.warning(
                        "Ring metadata missing for %s (system %s), skipping",
                        obj.id,
                        sys_id,
                    )

            # Cloud overlay (separate texture bundle parallel to the surface).
            clouds_meta = clouds_metadata.get(obj.id)
            if clouds_meta is not None:
                entry["clouds"] = clouds_block(clouds_meta)

            # Specular/roughness map (separate single-frame bundle parallel
            # to the surface; e.g. naif-399 → Earth's ocean mask).
            spec_meta = specular_metadata.get(obj.id)
            if spec_meta is not None:
                entry["specular"] = specular_block(spec_meta)

            # Night-lights emissive map (separate single-frame bundle
            # parallel to the surface; e.g. naif-399 → NASA Black Marble).
            night_meta = night_metadata.get(obj.id)
            if night_meta is not None:
                entry["night"] = night_block(night_meta)

            # Displacement/height map (separate single-frame bundle parallel
            # to the surface; e.g. naif-301 → the Moon's LRO LOLA topography).
            disp_meta = displacement_metadata.get(obj.id)
            if disp_meta is not None:
                entry["displacement"] = displacement_block(disp_meta)

            if entry:
                bodies[obj.id] = entry

        if bodies:
            (systems_dir / f"{sys_id}.json").write_bytes(orjson.dumps(bodies))
            logger.info("System metadata %s: %d bodies", sys_id, len(bodies))
