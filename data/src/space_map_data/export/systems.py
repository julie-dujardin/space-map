"""Write per-system metadata: systems/{barycenter_id}.json.

Each file contains texture tier info and orientation data for bodies in that
planetary system.
"""

import csv
import logging
from collections import Counter
import orjson
from pathlib import Path

from sqlalchemy.orm import Session

from space_map_data.constants.occultation_shapes import (
    occultation_orientations,
    occultation_radii,
)
from space_map_data.constants.orientation import (
    ORIENTATION_SOURCE_LIGHTCURVE,
    ORIENTATION_SOURCE_PCK,
)
from space_map_data.export.sidecar_io import mirror_path
from space_map_data.models.object import Object, ObjectType

logger = logging.getLogger(__name__)

_TOP_LEVEL_NAIF_IDS = {0, 10}  # SSB and Sun

# Sibling texture-bundle dirs, named `<host id><suffix>`, holding overlays for
# the host body rather than its own surface texture.
_CLOUDS_SUFFIX = "_clouds"
_SPECULAR_SUFFIX = "_specular"  # e.g. Earth's ocean mask
_NIGHT_SUFFIX = "_night"  # e.g. NASA Black Marble
_DISPLACEMENT_SUFFIX = "_displacement"  # e.g. the Moon's LRO LOLA topography
# `textures/stars/`: the cubemap skybox bundle behind the whole scene, not tied
# to any NAIF body.
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


def _read_orientation_csv(csv_path: Path, source: str) -> dict[int, dict]:
    result: dict[int, dict] = {}
    with csv_path.open(newline="") as f:
        for row in csv.DictReader(f):
            result[int(row["naif_id"])] = {
                "pole_ra_0": float(row["pole_ra_0"]),
                "pole_ra_1": float(row["pole_ra_1"]),
                "pole_dec_0": float(row["pole_dec_0"]),
                "pole_dec_1": float(row["pole_dec_1"]),
                "w0": float(row["w0"]),
                "w1": float(row["w1"]),
                "w2": float(row["w2"]),
                "source": source,
            }
    return result


def load_orientation(download_dir: Path) -> dict[int, dict]:
    """Orientation polynomials: SPICE PCK merged with DAMIT lightcurve spin and
    occultation-derived poles of the ringed small bodies. PCK wins where both
    exist; each record names its own ``source`` so the frontend credits it right.
    """
    tables = download_dir / "derived" / "position" / "tables"
    csv_path = tables / "orientation.csv"
    if not csv_path.exists():
        logger.warning("No orientation CSV at %s", csv_path)
        result: dict[int, dict] = {}
    else:
        result = _read_orientation_csv(csv_path, ORIENTATION_SOURCE_PCK)

    damit_path = download_dir / "derived" / "models" / "damit_orientation.csv"
    if damit_path.exists():
        damit = _read_orientation_csv(damit_path, ORIENTATION_SOURCE_LIGHTCURVE)
        added = sum(1 for naif in damit if naif not in result)
        result = {**damit, **result}  # PCK entries override DAMIT
        logger.info("Merged %d DAMIT spin-orientation records", added)

    occultation = occultation_orientations()
    added = sum(1 for naif in occultation if naif not in result)
    result = {**occultation, **result}
    logger.info("Merged %d occultation spin-orientation records", added)

    by_source = Counter(record["source"] for record in result.values())
    logger.info("Loaded %d orientation records %s", len(result), dict(by_source))
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
    if meta.get("license") is not None:
        result["license"] = meta["license"]
    if meta.get("attribution") is not None:
        result["attribution"] = meta["attribution"]
    if meta.get("description") is not None:
        result["description"] = meta["description"]
    if meta.get("frames") is not None:
        result["frames"] = meta["frames"]
    return result


def _tiers_from_meta(meta: dict) -> list[str]:
    """Sorted tier names for a textured body, normalized across the three
    metadata layouts (single-frame, monthly, cloud-overlay) so the frontend's
    URL builder doesn't have to care which one it's reading.
    """
    if meta.get("type") == "clouds_overlay":
        return sorted(meta.get("tiers") or [])
    exports = meta.get("exports") or {}
    if meta.get("type") == "cylindrical_monthly":
        first_frame = next(iter(exports.values()), {})
        return sorted(first_frame.keys())
    return sorted(exports.keys())


def load_texture_metadata(out_dir: Path) -> dict[str, dict]:
    """{object_id: metadata_dict} for surface textures; sibling overlay bundles
    are filtered out (use the dedicated loaders for those).

    Body ids come from ``out_dir/textures``, but metadata.json is read from
    the mirror dir — ingest writes those two paths separately.
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
    """{host_object_id: metadata_dict} for cloud overlays, keyed by the surface
    body's id (``_clouds`` suffix stripped). The full export id stays in the
    metadata's own ``id`` field for URL composition.
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
    """Per-body ``clouds`` block for systems/{bary}.json and object detail.

    URLs: ``/v1/textures/{clouds.id}/{tier}_{frame}.webp``.
    """
    block: dict = {
        "id": meta["id"],
        "tiers": _tiers_from_meta(meta),
        "frames": list(meta.get("frames") or []),
        "source": meta["source"],
        "organisation": meta["organisation"],
        "type": meta["type"],
    }
    if meta.get("license") is not None:
        block["license"] = meta["license"]
    if meta.get("attribution") is not None:
        block["attribution"] = meta["attribution"]
    if meta.get("description") is not None:
        block["description"] = meta["description"]
    return block


def load_specular_metadata(out_dir: Path) -> dict[str, dict]:
    """{host_object_id: metadata_dict} for specular maps, keyed by the surface
    body's id (``_specular`` suffix stripped)."""
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
    """Per-body ``specular`` block for systems/{bary}.json.

    URLs: ``/v1/textures/{specular.id}/{tier}.webp`` (single-frame).
    """
    block: dict = {
        "id": meta["id"],
        "tiers": _tiers_from_meta(meta),
        "source": meta["source"],
        "organisation": meta["organisation"],
        "type": meta["type"],
    }
    if meta.get("license") is not None:
        block["license"] = meta["license"]
    if meta.get("attribution") is not None:
        block["attribution"] = meta["attribution"]
    if meta.get("description") is not None:
        block["description"] = meta["description"]
    return block


def load_night_metadata(out_dir: Path) -> dict[str, dict]:
    """{host_object_id: metadata_dict} for night-lights maps, keyed by the
    surface body's id (``_night`` suffix stripped)."""
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
    """Per-body ``night`` block for systems/{bary}.json.

    URLs: ``/v1/textures/{night.id}/{tier}.webp`` (single-frame).
    """
    block: dict = {
        "id": meta["id"],
        "tiers": _tiers_from_meta(meta),
        "source": meta["source"],
        "organisation": meta["organisation"],
        "type": meta["type"],
    }
    if meta.get("license") is not None:
        block["license"] = meta["license"]
    if meta.get("attribution") is not None:
        block["attribution"] = meta["attribution"]
    if meta.get("description") is not None:
        block["description"] = meta["description"]
    return block


def load_displacement_metadata(out_dir: Path) -> dict[str, dict]:
    """{host_object_id: metadata_dict} for displacement maps, keyed by the
    surface body's id (``_displacement`` suffix stripped)."""
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
    """Per-body ``displacement`` block for systems/{bary}.json.

    Carries id, tiers, and the km mapping (offset km = bias + scale·texel) the
    renderer needs to scale `displacementMap`. URLs: ``{displacement.id}/{tier}.webp``.
    """
    block: dict = {
        "id": meta["id"],
        "tiers": _tiers_from_meta(meta),
        "scale_km": meta["displacement_scale_km"],
        "bias_km": meta["displacement_bias_km"],
        "absolute_radius": meta.get("absolute_radius", False),
        "source": meta["source"],
        "organisation": meta["organisation"],
        "type": meta["type"],
    }
    if meta.get("license") is not None:
        block["license"] = meta["license"]
    if meta.get("attribution") is not None:
        block["attribution"] = meta["attribution"]
    if meta.get("description") is not None:
        block["description"] = meta["description"]
    return block


def load_skybox_metadata(out_dir: Path) -> dict | None:
    """The cubemap-skybox metadata dict, or None if no bundle is ingested."""
    meta_file = mirror_path(out_dir / "textures" / _SKYBOX_DIR / "metadata.json")
    if not meta_file.exists():
        return None
    return orjson.loads(meta_file.read_bytes())


def skybox_block(meta: dict) -> dict:
    """Top-level ``skybox`` block for v1/metadata.json.

    URLs: ``/v1/textures/{skybox.id}/{tier}_{face}.webp``.
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
    if meta.get("license") is not None:
        block["license"] = meta["license"]
    if meta.get("attribution") is not None:
        block["attribution"] = meta["attribution"]
    if meta.get("description") is not None:
        block["description"] = meta["description"]
    return block


def load_ring_metadata(out_dir: Path) -> dict[str, list[dict]]:
    """Load all per-bundle ring metadata.json files from the export tree.

    Returns {object_id: [metadata_dict, ...]} ordered inner → outer. Only
    bodies with at least one successfully ingested bundle are included; a
    body may own several radially disjoint ones (Saturn).
    """
    rings_dir = out_dir / "rings"
    result: dict[str, list[dict]] = {}
    if not rings_dir.exists():
        return result
    for body_dir in rings_dir.iterdir():
        if not body_dir.is_dir():
            continue
        for bundle_dir in sorted(p for p in body_dir.iterdir() if p.is_dir()):
            meta_file = mirror_path(bundle_dir / "metadata.json")
            if meta_file.exists():
                result.setdefault(body_dir.name, []).append(
                    orjson.loads(meta_file.read_bytes())
                )
    for metas in result.values():
        metas.sort(key=lambda m: float(m["inner_radius_km"]))
    logger.info(
        "Loaded ring metadata for %d bodies (%d bundles)",
        len(result),
        sum(len(m) for m in result.values()),
    )
    return result


def load_model_metadata(out_dir: Path) -> dict[str, dict]:
    """{slug: metadata_dict} for 3D models. Unlike texture/ring/clouds metadata,
    this lives in ``EXPORT_DIR`` itself (publicly served), not behind
    ``mirror_path``.
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
    """One entry of the per-body `rings` array for systems/{bary}.json and object
    detail. Fetched as ``/v1/rings/{body_id}/{strip}``.
    """
    bundle = meta.get("bundle", "primary")
    block = {
        "bundle": bundle,
        # Every work behind the bundle, each with its own contribution note.
        "sources": meta["sources"],
        "inner_radius_km": float(meta["inner_radius_km"]),
        "outer_radius_km": float(meta["outer_radius_km"]),
        "sample_count": int(meta["sample_count"]),
        # Stored channel value × intensity_scale = physical value; synthetic
        # tenuous systems are normalised so 8-bit survives τ ~1e-6.
        "intensity_scale": float(meta.get("intensity_scale", 1.0)),
        # 0 = flat rings (no thickness row); else km per unit of that row.
        "thickness_scale_km": float(meta.get("thickness_scale_km", 0.0)),
        "color_space": meta.get("color_space", "srgb"),
        "strip": f"{bundle}/{meta['strip']['file']}",
        "strip_height": int(meta["strip"]["height"]),
        "strip_rows": meta["strip"]["rows"],
    }
    if meta.get("description") is not None:
        block["description"] = meta["description"]
    return block


def load_radii(download_dir: Path) -> dict[int, dict]:
    """Load triaxial radii, SPICE radii.csv merged with the occultation-fitted
    ellipsoids of the ringed small bodies.

    Returns {naif_id: {a, b, c}} in km along body-fixed X, Y, Z. PCK radii win
    where both exist.
    """
    csv_path = download_dir / "derived" / "position" / "tables" / "radii.csv"
    if not csv_path.exists():
        logger.warning("No radii CSV at %s", csv_path)
        return dict(occultation_radii())
    result: dict[int, dict] = dict(occultation_radii())
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

    Holds data the frontend needs regardless of which system it's viewing:
    `gm` (full GM table, for chebyshev trail-buffer period estimates) and
    `nut_prec_angles` (paired with per-body `nut_prec` in the per-system files).
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
    ring_metadata: dict[str, list[dict]],
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

    # Not just textured bodies — anything that belongs in a planetary system.
    system_bodies = (
        session.query(Object)
        .filter(Object.object_type.in_([t.value for t in _SYSTEM_TYPES]))
        .all()
    )

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

    systems_dir = out_dir / "systems"
    systems_dir.mkdir(parents=True, exist_ok=True)
    for sys_id, objs in systems.items():
        bodies: dict[str, dict] = {}
        for obj in objs:
            entry: dict = {}

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

            if obj.naif_id is not None and obj.naif_id in orientation:
                entry["orientation"] = orientation[obj.naif_id]

            # Paired with the global nut_prec_angles.json.
            if obj.naif_id is not None and obj.naif_id in nut_prec:
                entry["nut_prec"] = nut_prec[obj.naif_id]

            # km, along body-fixed X, Y, Z.
            if obj.naif_id is not None and obj.naif_id in radii:
                entry["radii"] = radii[obj.naif_id]

            # Ring profile bundles, inner → outer.
            if obj.has_rings:
                metas = ring_metadata.get(obj.id)
                if metas:
                    entry["rings"] = [ring_block(m) for m in metas]
                else:
                    logger.warning(
                        "Ring metadata missing for %s (system %s), skipping",
                        obj.id,
                        sys_id,
                    )

            clouds_meta = clouds_metadata.get(obj.id)
            if clouds_meta is not None:
                entry["clouds"] = clouds_block(clouds_meta)

            spec_meta = specular_metadata.get(obj.id)
            if spec_meta is not None:
                entry["specular"] = specular_block(spec_meta)

            night_meta = night_metadata.get(obj.id)
            if night_meta is not None:
                entry["night"] = night_block(night_meta)

            disp_meta = displacement_metadata.get(obj.id)
            if disp_meta is not None:
                entry["displacement"] = displacement_block(disp_meta)

            if entry:
                bodies[obj.id] = entry

        if bodies:
            (systems_dir / f"{sys_id}.json").write_bytes(orjson.dumps(bodies))
            logger.info("System metadata %s: %d bodies", sys_id, len(bodies))
