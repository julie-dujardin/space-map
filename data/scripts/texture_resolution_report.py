"""Report spatial resolution of every exported texture bundle.

For each bundle (surface / clouds / night / specular / displacement) prints
px per degree of longitude and km per pixel at the equator — best-case for
an equirect map; it improves toward the poles — for the source image and
each export tier. Radii come from the exported object bundles, falling back
to SBDB diameter for bodies without PCK radii.

Run from data/:
    uv run python scripts/texture_resolution_report.py
"""

import gzip
import hashlib
import json
import math
import sqlite3

from PIL import Image

from space_map_data.utils.paths import DB_FILE, EXPORT_DIR, EXPORT_METADATA_DIR

TEXTURES_META = EXPORT_METADATA_DIR / "v1" / "textures"

SUFFIXES = ["_displacement", "_specular", "_night", "_clouds"]
TIERS = ["low", "medium", "high"]

_bundle_count = json.loads((EXPORT_DIR / "v1" / "metadata.json").read_text())[
    "object_bundles"
]["global"]
_bucket_cache: dict[int, dict] = {}
_db = sqlite3.connect(DB_FILE)


def load_object(oid: str) -> dict:
    bucket = (
        int.from_bytes(hashlib.sha256(oid.encode()).digest()[:4], "big") % _bundle_count
    )
    if bucket not in _bucket_cache:
        raw = (
            EXPORT_DIR / "v1" / "objects" / "__global__" / f"{bucket}.json.gz"
        ).read_bytes()
        _bucket_cache[bucket] = json.loads(gzip.decompress(raw))
    return _bucket_cache[bucket].get(oid, {})


def equatorial_circumference_km(oid: str, obj: dict) -> float | None:
    radii = obj.get("radii")
    if radii:
        return 2 * math.pi * (radii["a"] + radii["b"]) / 2
    row = _db.execute(
        "select s.diameter from objects o join sbdb s on s.object_id = o.id where o.id = ?",
        (oid,),
    ).fetchone()
    if row and row[0]:
        return math.pi * row[0]
    return None


def split_id(bundle_id: str) -> tuple[str, str]:
    for suf in SUFFIXES:
        if bundle_id.endswith(suf):
            return bundle_id[: -len(suf)], suf[1:]
    return bundle_id, "surface"


def tier_widths(meta: dict) -> dict[str, tuple[int, int]]:
    """Normalize the per-type export shapes to {tier: (w, h)}."""
    exports = meta.get("exports") or {}
    ttype = meta.get("type")
    if ttype == "cylindrical_monthly":
        first = exports[sorted(exports)[0]]
        return {t: (e["width"], e["height"]) for t, e in first.items()}
    if ttype == "clouds_overlay":
        # No dims in metadata; read one frame per tier from disk.
        out = {}
        bundle_dir = EXPORT_DIR / "v1" / "textures" / meta["id"]
        for tier in meta.get("tiers", []):
            files = sorted(bundle_dir.glob(f"{tier}_*.webp"))
            if files:
                with Image.open(files[0]) as im:
                    out[tier] = im.size
        return out
    return {t: (e["width"], e["height"]) for t, e in exports.items()}


def fmt_km(km: float | None) -> str:
    if km is None:
        return "-"
    if km >= 100:
        return f"{km:.0f}"
    if km >= 1:
        return f"{km:.1f}"
    m = km * 1000
    if m >= 10:
        return f"{m:.0f} m"
    if m >= 1:
        return f"{m:.1f} m"
    return f"{m * 100:.0f} cm"


def main() -> None:
    rows = []
    skybox_rows = []
    for meta_path in sorted(TEXTURES_META.glob("*/metadata.json")):
        if meta_path.parent.name.startswith("_"):
            continue  # archived/inactive bundles
        meta = json.loads(meta_path.read_text())
        bundle_id = meta["id"]

        if meta.get("type") == "cubemap_skybox":
            skybox_rows.append(meta)
            continue

        base_id, kind = split_id(bundle_id)
        obj = load_object(base_id)
        name = obj.get("name", base_id)
        circ = equatorial_circumference_km(base_id, obj)

        def res(width: int | None, circ: float | None = circ) -> tuple[str, str]:
            if not width:
                return "-", "-"
            return f"{width / 360:.1f}", fmt_km(circ / width if circ else None)

        src_w = (meta.get("source_dimensions") or [None])[0]
        widths = tier_widths(meta)
        row = {
            "name": name,
            "kind": kind,
            "src_file": meta.get("source_file") or "-",
            "src_dim": "x".join(map(str, meta["source_dimensions"]))
            if meta.get("source_dimensions")
            else "-",
            "src": res(src_w),
        }
        for tier in TIERS:
            wh = widths.get(tier)
            row[tier] = res(wh[0]) if wh else ("-", "-")
            row[f"{tier}_dim"] = f"{wh[0]}x{wh[1]}" if wh else "-"
        row["_sort"] = (
            0 if base_id.startswith("naif") else 1,
            int("".join(c for c in base_id.split("-")[1] if c.isdigit())),
            kind,
        )
        rows.append(row)

    rows.sort(key=lambda r: r["_sort"])

    hdr = (
        f"{'Body':<14} {'Layer':<12} {'Source file':<52} {'Source px':<12} "
        f"{'src px/°':>8} {'src km/px':>9} | "
        f"{'low km/px':>9} {'med km/px':>9} {'high km/px':>10} | {'high px':<11} {'hi px/°':>7}"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(
            f"{r['name']:<14.14} {r['kind']:<12} {r['src_file']:<52.52} {r['src_dim']:<12} "
            f"{r['src'][0]:>8} {r['src'][1]:>9} | "
            f"{r['low'][1]:>9} {r['medium'][1]:>9} {r['high'][1]:>10} | {r['high_dim']:<11} {r['high'][0]:>7}"
        )

    for meta in skybox_rows:
        print()
        faces = {
            t: next(iter(fs.values()))["width"]
            for t, fs in (meta.get("exports") or {}).items()
        }
        tiers = ", ".join(
            f"{t}: {w}px/face ({w / 90:.1f} px/°)" for t, w in faces.items()
        )
        src = meta.get("source_dimensions")
        src_txt = f"{src[0]}x{src[1]} ({src[0] / 360:.1f} px/°)" if src else "-"
        print(f"Skybox ({meta['id']}): source {src_txt}; {tiers}")


if __name__ == "__main__":
    main()
