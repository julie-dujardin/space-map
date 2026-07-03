"""Normalize natural-body shape-model source files to Wavefront OBJ.

Covers every encoding the bodies manifests list: passthrough meshes Blender
reads directly (obj/ply/stl), gzip wrappers, Gaskell ICQ cube grids, the three
PDS plate-table dialects, lat/lon/radius grids (either column order), and
VRML2 IndexedFaceSet.
Battle-tested on the real archive files.
"""

import gzip
import logging
import math
import re
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

# Formats Blender imports as-is; the rest need normalising to OBJ first.
_BLENDER_NATIVE = frozenset({"obj", "ply", "stl"})


def normalize_to_mesh(
    src: Path, fmt: str, work_dir: Path, *, lon_first: bool = False
) -> Path:
    """Return a Blender-importable mesh path for ``src`` (format ``fmt``).

    Passthrough formats return ``src`` unchanged; gzip wrappers are inflated;
    table/grid/VRML/ICQ dialects are converted to OBJ under ``work_dir``.
    ``lon_first`` flips a lat/lon grid's column order (see ``_parse_grid``).
    """
    if fmt in _BLENDER_NATIVE:
        return src
    if fmt.endswith(".gz") or src.suffix == ".gz":
        inflated = work_dir / src.name.removesuffix(".gz")
        with gzip.open(src, "rb") as fh, inflated.open("wb") as out:
            shutil.copyfileobj(fh, out)
        return inflated
    out = work_dir / (src.stem + ".obj")
    if fmt == "icq":
        icq_to_obj(src, out)
    elif fmt in ("pds-vertab", "wrl"):
        table_to_obj(src, out, lon_first=lon_first)
    else:
        raise ValueError(f"unknown mesh format {fmt!r} for {src.name}")
    return out


def icq_to_obj(src: Path, dst: Path) -> None:
    """Gaskell ICQ (Implicitly Connected Quadrilateral) → OBJ.

    Six q×q quad-grid cube faces; connectivity is implicit. Seam vertices are
    duplicated across faces — harmless, Blender's weld pass merges them.
    """
    tokens = src.read_text().split()
    q = int(tokens[0])
    per_face = (q + 1) * (q + 1)
    want = 1 + 6 * per_face * 3
    if len(tokens) < want:
        raise ValueError(f"{src}: expected {want} tokens for q={q}, got {len(tokens)}")
    with dst.open("w") as out:
        it = iter(tokens[1:want])
        for x, y, z in zip(it, it, it):
            out.write(f"v {x} {y} {z}\n")
        for face in range(6):
            base = 1 + face * per_face
            for i in range(q):
                for j in range(q):
                    a = base + i * (q + 1) + j
                    b = a + 1
                    c = a + (q + 1)
                    d = c + 1
                    out.write(f"f {a} {b} {d}\nf {a} {d} {c}\n")


def table_to_obj(src: Path, dst: Path, *, lon_first: bool = False) -> tuple[int, int]:
    """PDS plate table (.tab) or VRML2 IndexedFaceSet (.wrl) → OBJ."""
    is_wrl = src.suffix.lower() == ".wrl"
    verts, faces = _parse_wrl(src) if is_wrl else _parse_tab(src, lon_first=lon_first)
    nv = len(verts)
    for f in faces:
        if any(i < 1 or i > nv for i in f):
            raise ValueError(f"{src}: face index out of range: {f}")
    with dst.open("w") as out:
        for v in verts:
            out.write(f"v {v[0]} {v[1]} {v[2]}\n")
        for f in faces:
            out.write(f"f {f[0]} {f[1]} {f[2]}\n")
    return nv, len(faces)


def _parse_vf(lines: list[list[str]]) -> tuple[list, list]:
    """Hudson/Thomas plate table: ``v x y z`` rows then ``f i j k`` rows."""
    verts, faces = [], []
    for parts in lines:
        if parts[0].lower() == "v":
            verts.append(tuple(float(x) for x in parts[1:4]))
        elif parts[0].lower() == "f":
            faces.append(tuple(int(float(x)) for x in parts[1:4]))
    return verts, faces


def _parse_counts(lines: list[list[str]]) -> tuple[list, list]:
    """Numeric plate table: header counts, then indexed vertex + plate rows."""
    header = [int(float(x)) for x in lines[0]]
    nv = header[0]
    row = 1
    verts = []
    for parts in lines[row : row + nv]:
        vals = [float(x) for x in parts]
        verts.append(tuple(vals[-3:]))  # drop leading index column if present
    row += nv
    if len(header) > 1:
        np_ = header[1]
    else:
        np_ = int(float(lines[row][0]))
        row += 1
    faces = []
    for parts in lines[row : row + np_]:
        vals = [int(float(x)) for x in parts]
        faces.append(tuple(vals[-3:]))
    return verts, faces


def _parse_grid(
    lines: list[list[str]], *, lon_first: bool = False
) -> tuple[list, list]:
    """Digital shape model: lat/lon/radius_km rows on a lat/lon grid.

    Column order varies by archive (Thomas: lat,lon,r; Stooke: lon,lat,r); the
    manifest's ``grid_order`` field declares which via ``lon_first``. Normalise
    to (lat, lon, radius).
    """
    raw = [(float(a), float(b), float(c)) for a, b, c in lines]
    rows = [(lat, lon, r) for lon, lat, r in raw] if lon_first else raw
    lats = sorted({r[0] for r in rows})
    lons = sorted({r[1] for r in rows})
    by_key = {(lat, lon): r for lat, lon, r in rows}
    verts, index = [], {}
    for lat in lats:
        for lon in lons:
            r = by_key.get((lat, lon))
            if r is None:
                continue
            la, lo = math.radians(lat), math.radians(lon)
            index[(lat, lon)] = len(verts) + 1
            verts.append(
                (
                    r * math.cos(la) * math.cos(lo),
                    r * math.cos(la) * math.sin(lo),
                    r * math.sin(la),
                )
            )
    faces = []
    wraps = math.isclose(lons[0] % 360.0, lons[-1] % 360.0)
    ncols = len(lons) - 1 if wraps else len(lons)
    for i in range(len(lats) - 1):
        for j in range(ncols):
            j2 = (j + 1) % len(lons)
            quad = [
                index.get((lats[i], lons[j])),
                index.get((lats[i], lons[j2])),
                index.get((lats[i + 1], lons[j2])),
                index.get((lats[i + 1], lons[j])),
            ]
            if None in quad:
                continue
            a, b, c, d = quad
            faces.append((a, b, c))
            faces.append((a, c, d))
    return verts, faces


def _parse_tab(src: Path, *, lon_first: bool = False) -> tuple[list, list]:
    lines = [ln.split() for ln in src.read_text().splitlines() if ln.strip()]
    if any(parts[0].lower() in ("v", "f") for parts in lines[:5]):
        verts, faces = _parse_vf(lines)
    elif len(lines[0]) == 3 and all(len(p) == 3 for p in lines[:50]):
        verts, faces = _parse_grid(lines, lon_first=lon_first)
    else:
        verts, faces = _parse_counts(lines)
    if not verts or not faces:
        raise ValueError(f"{src}: parsed {len(verts)} verts / {len(faces)} faces")
    # 0-based indices exist in the wild; normalize to OBJ's 1-based.
    lo = min(min(f) for f in faces)
    if lo == 0:
        faces = [(a + 1, b + 1, c + 1) for a, b, c in faces]
    elif lo != 1:
        raise ValueError(f"{src}: face indices start at {lo}")
    return verts, faces


def _parse_wrl(src: Path) -> tuple[list, list]:
    text = re.sub(r"#[^\n]*", "", src.read_text())
    pm = re.search(r"point\s*\[(.*?)\]", text, re.DOTALL)
    im = re.search(r"coordIndex\s*\[(.*?)\]", text, re.DOTALL)
    if not pm or not im:
        raise ValueError(f"{src}: no IndexedFaceSet point/coordIndex arrays found")
    coords = [float(x) for x in re.split(r"[,\s]+", pm.group(1).strip()) if x]
    verts = [tuple(coords[i : i + 3]) for i in range(0, len(coords), 3)]
    idx = [int(x) for x in re.split(r"[,\s]+", im.group(1).strip()) if x]
    faces, poly = [], []
    for i in idx:
        if i == -1:
            if len(poly) != 3:
                raise ValueError(f"{src}: non-triangle face with {len(poly)} verts")
            faces.append((poly[0] + 1, poly[1] + 1, poly[2] + 1))
            poly = []
        else:
            poly.append(i)
    if not verts or not faces:
        raise ValueError(f"{src}: parsed {len(verts)} verts / {len(faces)} faces")
    return verts, faces
