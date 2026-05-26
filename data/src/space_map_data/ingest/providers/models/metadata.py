"""Helpers: object_id resolution + tier-source selection + source hashing + glTF stats."""

import hashlib
import json
import logging
import struct
from pathlib import Path

from space_map_data.constants.providers import ID_TYPES, make_object_id
from space_map_data.ingest.providers.models import config

log = logging.getLogger(__name__)


def resolve_mission_object_id(
    mission: dict, satcat_norad_to_object_id: dict[int, str] | None = None
) -> str | None:
    """Map one mission descriptor to its canonical object_id.

    Priority: ``probe_id`` > ``naif_id`` > ``norad_cat_id`` > ``spkid``.
    Returns None when nothing resolves, so the caller can skip that mission.

    When ``satcat_norad_to_object_id`` is provided, a NORAD lookup follows
    the reverse of ``Object.satcat_norad_cat_id`` — which may have been
    consolidated onto a probe Object (e.g. NORAD 25008 → ``probe-88592384``
    for Cassini) rather than minted as a standalone ``norad_satcat-N`` stub.
    """
    probe_id = mission.get("probe_id")
    if probe_id is not None:
        return make_object_id(ID_TYPES.PROBE, probe_id)
    naif = mission.get("naif_id")
    if naif is not None:
        return make_object_id(ID_TYPES.NAIF, naif)
    norad = mission.get("norad_cat_id")
    if norad is not None:
        if satcat_norad_to_object_id is not None:
            resolved = satcat_norad_to_object_id.get(norad)
            if resolved is not None:
                return resolved
        return make_object_id(ID_TYPES.NORAD_SATCAT, norad)
    spkid = mission.get("spkid")
    if spkid is not None:
        return make_object_id(ID_TYPES.SPKID, spkid)
    return None


def convertible_files(files: list[dict]) -> list[dict]:
    """Return entry files whose ``type`` is in ``CONVERTIBLE_FORMATS``.

    Replaces the old format-priority picker — actual tier picking now
    happens post-compression, after every candidate has been cached. See
    ``processor._pick_tiers_from_cached``.
    """
    return [m for m in files if m.get("type") in config.CONVERTIBLE_FORMATS]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def gltf_stats(glb_path: Path) -> dict[str, int]:
    """Parse a .glb's JSON chunk and return content stats.

    Stats are cheap to extract because every glTF accessor's element count
    is stored in the JSON header — no buffer decode needed. Returns an
    empty dict if the file isn't a glTF 2 binary or the JSON chunk fails
    to parse.

    ``triangles`` counts only primitives with ``mode == 4`` (TRIANGLES);
    other topologies (lines, points, strips) are excluded — they wouldn't
    be triangle-rendered anyway.
    """
    try:
        with glb_path.open("rb") as f:
            header = f.read(12)
            if len(header) < 12:
                return {}
            magic, version, _length = struct.unpack("<4sII", header)
            if magic != b"glTF" or version != 2:
                return {}
            chunk_header = f.read(8)
            if len(chunk_header) < 8:
                return {}
            chunk_len, chunk_type = struct.unpack("<II", chunk_header)
            if chunk_type != 0x4E4F534A:  # "JSON" little-endian
                return {}
            json_bytes = f.read(chunk_len)
        gltf = json.loads(json_bytes)
    except (OSError, struct.error, json.JSONDecodeError) as exc:
        log.warning("failed to parse glTF stats for %s: %s", glb_path, exc)
        return {}

    accessors = gltf.get("accessors") or []
    triangles = 0
    for mesh in gltf.get("meshes") or []:
        for prim in mesh.get("primitives") or []:
            if prim.get("mode", 4) != 4:
                continue
            if "indices" in prim:
                acc_idx = prim["indices"]
            else:
                acc_idx = (prim.get("attributes") or {}).get("POSITION")
            if acc_idx is None or acc_idx >= len(accessors):
                continue
            triangles += accessors[acc_idx].get("count", 0) // 3

    return {
        "triangles": triangles,
        "meshes": len(gltf.get("meshes") or []),
        "nodes": len(gltf.get("nodes") or []),
        "textures": len(gltf.get("textures") or []),
        "animations": len(gltf.get("animations") or []),
    }
