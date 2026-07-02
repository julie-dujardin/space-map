"""Minimal indexed-GLB writer for DAMIT convex models.

The convex lightcurve models are tiny (~1-2k facets), so launching Blender or a
gltf-transform subprocess per model would dominate wall-time across the ~16k
set. We emit a self-contained glTF 2 binary directly: positions (km) + smoothed
vertex normals + a triangle index buffer. No Meshopt — uncompressed convex
meshes are already small, and skipping it keeps the full pass subprocess-free.
"""

import json
import struct
from pathlib import Path

import numpy as np


def write_glb(vertices: np.ndarray, faces: np.ndarray, dst: Path) -> None:
    """Write an indexed triangle mesh to ``dst`` as a .glb.

    ``vertices``: (N, 3) float km. ``faces``: (M, 3) int, 0-based.
    """
    vertices = np.ascontiguousarray(vertices, dtype=np.float32)
    faces = np.ascontiguousarray(faces, dtype=np.uint32)
    normals = _smooth_normals(vertices, faces)

    idx_bytes = faces.tobytes()
    pos_bytes = vertices.tobytes()
    nrm_bytes = normals.tobytes()

    # bufferViews are 4-byte aligned; float/uint data already is.
    idx_off = 0
    pos_off = idx_off + _pad4(len(idx_bytes))
    nrm_off = pos_off + _pad4(len(pos_bytes))
    total = nrm_off + _pad4(len(nrm_bytes))

    buf = bytearray(total)
    buf[idx_off : idx_off + len(idx_bytes)] = idx_bytes
    buf[pos_off : pos_off + len(pos_bytes)] = pos_bytes
    buf[nrm_off : nrm_off + len(nrm_bytes)] = nrm_bytes

    pos_min = vertices.min(axis=0).tolist()
    pos_max = vertices.max(axis=0).tolist()

    gltf = {
        "asset": {"version": "2.0", "generator": "space-map damit glb_writer"},
        "scenes": [{"nodes": [0]}],
        "scene": 0,
        "nodes": [{"mesh": 0}],
        "meshes": [
            {"primitives": [{"attributes": {"POSITION": 1, "NORMAL": 2}, "indices": 0}]}
        ],
        "buffers": [{"byteLength": total}],
        "bufferViews": [
            {
                "buffer": 0,
                "byteOffset": idx_off,
                "byteLength": len(idx_bytes),
                "target": 34963,
            },
            {
                "buffer": 0,
                "byteOffset": pos_off,
                "byteLength": len(pos_bytes),
                "target": 34962,
            },
            {
                "buffer": 0,
                "byteOffset": nrm_off,
                "byteLength": len(nrm_bytes),
                "target": 34962,
            },
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5125,
                "count": faces.size,
                "type": "SCALAR",
            },
            {
                "bufferView": 1,
                "componentType": 5126,
                "count": len(vertices),
                "type": "VEC3",
                "min": pos_min,
                "max": pos_max,
            },
            {
                "bufferView": 2,
                "componentType": 5126,
                "count": len(normals),
                "type": "VEC3",
            },
        ],
    }

    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * (_pad4(len(json_bytes)) - len(json_bytes))
    bin_bytes = bytes(buf) + b"\x00" * (_pad4(len(buf)) - len(buf))

    total_len = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, total_len))
        f.write(struct.pack("<II", len(json_bytes), 0x4E4F534A))  # JSON
        f.write(json_bytes)
        f.write(struct.pack("<II", len(bin_bytes), 0x004E4942))  # BIN
        f.write(bin_bytes)


def _smooth_normals(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Area-weighted per-vertex normals (convex → outward-consistent winding)."""
    normals = np.zeros_like(vertices)
    v0 = vertices[faces[:, 0]]
    v1 = vertices[faces[:, 1]]
    v2 = vertices[faces[:, 2]]
    face_n = np.cross(v1 - v0, v2 - v0)  # magnitude ∝ 2·area
    for i in range(3):
        np.add.at(normals, faces[:, i], face_n)
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    lengths[lengths == 0] = 1.0
    return (normals / lengths).astype(np.float32)


def _pad4(n: int) -> int:
    return (n + 3) & ~3
