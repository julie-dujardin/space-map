"""Measure what a spacecraft mesh actually draws: full span, body, and centre.

A model normally draws the craft fully deployed, so its bounding box is set by
whatever reaches furthest — a magnetometer boom, a wire dipole, a deployed mast.
That span is the right scale for the *mesh* (it is what the mesh is), but the
wrong size for the halo, the label, and the craft's slot in a lineup, and its
centre is not where the craft is. Ulysses draws a 63 m dipole around a 3 m bus.

The body is separated from what it deploys by cross-sectional perimeter: surface
area per unit length along an axis. A boom or wire measures centimetres across,
a solar wing or a bus metres, whatever units the model is authored in.
"""

import json
import logging
import struct
import subprocess
import tempfile
from pathlib import Path

from space_map_data.ingest.providers.models import conversion

log = logging.getLogger(__name__)

#: Slices per axis. Fine enough to cut a boom off a bus, coarse enough that a
#: panel gap doesn't read as empty space.
BINS = 64
#: A slice whose perimeter falls below this fraction of the thickest slice's is
#: something the craft deploys, not the craft. Booms and wire antennas land
#: below 0.03; solar wings, dishes and radiators sit above 0.1.
APPENDAGE_PERIMETER = 0.08

#: glTF componentType → (struct code, byte width, normalisation divisor).
_COMPONENT = {
    5120: ("b", 1, 127),
    5121: ("B", 1, 255),
    5122: ("h", 2, 32767),
    5123: ("H", 2, 65535),
    5125: ("I", 4, None),
    5126: ("f", 4, None),
}
_IDENTITY = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)


def measure_bundle(glb_path: Path) -> dict | None:
    """Body-vs-deployed geometry of an exported .glb, in normalised units.

    Returns ``{body_span_ratio, model_anchor}``: the body's longest dimension as
    a fraction of the mesh's, and the body centre's offset from the bounding-box
    centre in the frontend's post-fit units (the mesh spans 2 of them). None when
    the file can't be read or holds no triangles.
    """
    tris = _triangles(glb_path)
    if not tris:
        return None
    lo = [min(c[k] for c, _a in tris) for k in range(3)]
    hi = [max(c[k] for c, _a in tris) for k in range(3)]
    outer = [hi[k] - lo[k] for k in range(3)]
    longest = max(outer)
    if longest <= 0:
        return None
    body = [_body_range(tris, lo, hi, k) for k in range(3)]
    unit = longest / 2
    return {
        "body_span_ratio": round(max(b - a for a, b in body) / longest, 4),
        "model_anchor": [
            round(((b + a) / 2 - (hi[k] + lo[k]) / 2) / unit, 4)
            for k, (a, b) in enumerate(body)
        ],
    }


def _body_range(tris, lo, hi, axis: int) -> tuple[float, float]:
    """Extent on ``axis`` of the slices thick enough to be craft, not appendage.

    Outermost qualifying slice on each side, not a run outward from the peak: a
    solar wing is panels with gaps between them, and a run would stop at the
    first gap.
    """
    length = hi[axis] - lo[axis]
    if length <= 0:
        return lo[axis], hi[axis]
    perimeter = [0.0] * BINS
    for centroid, area in tris:
        b = min(int((centroid[axis] - lo[axis]) / length * BINS), BINS - 1)
        perimeter[b] += area
    cut = max(perimeter) * APPENDAGE_PERIMETER
    kept = [i for i, p in enumerate(perimeter) if p >= cut]
    return (
        lo[axis] + kept[0] / BINS * length,
        lo[axis] + (kept[-1] + 1) / BINS * length,
    )


def _triangles(glb_path: Path) -> list[tuple[tuple[float, float, float], float]]:
    """(centroid, area) per triangle in scene space.

    Exported bundles are Meshopt-compressed, which no stdlib can decode, so the
    file is round-tripped through gltf-transform first — it decompresses on read
    and writes plain buffers.
    """
    with tempfile.TemporaryDirectory(prefix="smd-measure-") as tmp:
        plain = Path(tmp) / "plain.glb"
        try:
            conversion.gltf_transform_copy(glb_path, plain)
        except (subprocess.CalledProcessError, RuntimeError) as exc:
            log.info("cannot decompress %s for measurement: %s", glb_path.name, exc)
            return []
        return _triangles_plain(plain)


def _triangles_plain(path: Path):
    gltf, blob = _read_glb(path)
    if gltf is None:
        return []
    nodes = gltf.get("nodes") or []
    scene = gltf.get("scenes", [{}])[gltf.get("scene", 0)]
    roots = scene.get("nodes", range(len(nodes)))
    out: list[tuple[tuple[float, float, float], float]] = []

    def walk(index: int, parent: tuple) -> None:
        node = nodes[index]
        world = _mat_mul(parent, _node_matrix(node))
        if "mesh" in node:
            for prim in gltf["meshes"][node["mesh"]].get("primitives") or []:
                if prim.get("mode", 4) != 4:  # triangles only
                    continue
                pos = (prim.get("attributes") or {}).get("POSITION")
                if pos is None:
                    continue
                verts = [_apply(world, v) for v in _read_vec3(gltf, blob, pos)]
                if "indices" in prim:
                    idx = _read_scalars(gltf, blob, prim["indices"])
                else:
                    idx = range(len(verts))
                _accumulate(out, verts, idx)
        for child in node.get("children") or []:
            walk(child, world)

    for i in roots:
        walk(i, _IDENTITY)
    return out


def _accumulate(out: list, verts: list, idx) -> None:
    idx = list(idx)
    for t in range(0, len(idx) - 2, 3):
        a, b, c = verts[idx[t]], verts[idx[t + 1]], verts[idx[t + 2]]
        u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
        cross = (
            u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0],
        )
        area = 0.5 * (cross[0] ** 2 + cross[1] ** 2 + cross[2] ** 2) ** 0.5
        if area <= 0:
            continue
        out.append(
            (
                (
                    (a[0] + b[0] + c[0]) / 3,
                    (a[1] + b[1] + c[1]) / 3,
                    (a[2] + b[2] + c[2]) / 3,
                ),
                area,
            )
        )


def _read_glb(path: Path) -> tuple[dict | None, bytes]:
    """Parse a .glb's JSON and BIN chunks."""
    try:
        with path.open("rb") as f:
            magic, version, _length = struct.unpack("<4sII", f.read(12))
            if magic != b"glTF" or version != 2:
                return None, b""
            length, kind = struct.unpack("<II", f.read(8))
            if kind != 0x4E4F534A:  # "JSON"
                return None, b""
            gltf = json.loads(f.read(length))
            head = f.read(8)
            if len(head) < 8:
                return gltf, b""
            length, kind = struct.unpack("<II", head)
            return gltf, (f.read(length) if kind == 0x004E4942 else b"")  # "BIN"
    except (OSError, ValueError, struct.error) as exc:
        log.info("unreadable glb %s: %s", path.name, exc)
        return None, b""


def _accessor_view(gltf: dict, accessor: dict) -> tuple[int, int, tuple]:
    fmt, size, norm = _COMPONENT[accessor["componentType"]]
    view = gltf["bufferViews"][accessor["bufferView"]]
    offset = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    return offset, view.get("byteStride", 0), (fmt, size, norm)


def _read_vec3(gltf: dict, blob: bytes, index: int):
    accessor = gltf["accessors"][index]
    offset, stride, (fmt, size, norm) = _accessor_view(gltf, accessor)
    stride = stride or size * 3
    divisor = norm if accessor.get("normalized") else None
    for i in range(accessor["count"]):
        v = struct.unpack_from("<" + fmt * 3, blob, offset + i * stride)
        # Normalised ints map to [-1, 1]; the spec clamps the extra negative step.
        yield tuple(max(c / divisor, -1.0) for c in v) if divisor else v


def _read_scalars(gltf: dict, blob: bytes, index: int):
    accessor = gltf["accessors"][index]
    offset, stride, (fmt, size, _norm) = _accessor_view(gltf, accessor)
    if stride and stride != size:
        return [
            struct.unpack_from("<" + fmt, blob, offset + i * stride)[0]
            for i in range(accessor["count"])
        ]
    return struct.unpack_from("<" + fmt * accessor["count"], blob, offset)


def _mat_mul(a: tuple, b: tuple) -> tuple:
    """Column-major 4x4 product."""
    return tuple(
        sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4))
        for c in range(4)
        for r in range(4)
    )


def _node_matrix(node: dict) -> tuple:
    if "matrix" in node:
        return tuple(float(v) for v in node["matrix"])
    tx, ty, tz = node.get("translation", (0, 0, 0))
    x, y, z, w = node.get("rotation", (0, 0, 0, 1))
    sx, sy, sz = node.get("scale", (1, 1, 1))
    return (
        (1 - 2 * (y * y + z * z)) * sx,
        (2 * (x * y + z * w)) * sx,
        (2 * (x * z - y * w)) * sx,
        0,
        (2 * (x * y - z * w)) * sy,
        (1 - 2 * (x * x + z * z)) * sy,
        (2 * (y * z + x * w)) * sy,
        0,
        (2 * (x * z + y * w)) * sz,
        (2 * (y * z - x * w)) * sz,
        (1 - 2 * (x * x + y * y)) * sz,
        0,
        tx,
        ty,
        tz,
        1,
    )


def _apply(m: tuple, p: tuple) -> tuple:
    x, y, z = p
    return (
        m[0] * x + m[4] * y + m[8] * z + m[12],
        m[1] * x + m[5] * y + m[9] * z + m[13],
        m[2] * x + m[6] * y + m[10] * z + m[14],
    )
