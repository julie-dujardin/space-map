"""Benchmark exported Chebyshev chunks against SPICE truth.

Reads `EXPORT_DIR/v1/position/{zone}/0/{chunk}.bin.gz` (zone ∈ {major,
major_asteroids, moons/<parent>}), parses every body's segments via the
same decode logic the frontend will use, and compares positions against
`spiceypy.spkezr` truth. Reports per-zone and per-body aggregates
(median / p95 / max error, file sizes, segment counts).

Validates the *shipped* binary end-to-end — catches packing bugs, float32
coefficient quantization, and frontend-mirror drift. Don't trust the
fit-time err report from the extractor alone; this is the real number.

Run from data/:
    uv run python scripts/chebyshev_benchmark.py
    uv run python scripts/chebyshev_benchmark.py --zones major
    uv run python scripts/chebyshev_benchmark.py --samples-per-segment 11
"""

import argparse
import gzip
import json
import logging
import struct
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import spiceypy

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "data" / "src"))

from space_map_data.constants.providers import PROVIDERS  # noqa: E402
from space_map_data.export.position.format import (  # noqa: E402
    BODY_HEADER_SIZE,
    CHEBYSHEV_FLAG_FLOAT64_COEFFS,
    FORMAT_CHEBYSHEV,
    HEADER_SIZE,
    MAGIC,
    VERSION,
)
from space_map_data.utils.paths import DOWNLOAD_DIR, EXPORT_DIR  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

_S_PER_DAY = 86400.0
_J2000_JD = 2451545.0
_KERNELS_ROOT = DOWNLOAD_DIR / PROVIDERS.SPICE / "kernels"


def _position_root(export_root: Path) -> Path:
    return export_root / "v1" / "position"


def _manifest_path(export_root: Path) -> Path:
    return export_root / "v1" / "metadata.json"


# ── Binary parsing ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class Segment:
    start_jd: float
    end_jd: float
    coeffs: np.ndarray  # (3, coeffs_per_axis) float64


@dataclass(frozen=True)
class BodyRecord:
    naif_id: int
    parent_id: int
    segments: list[Segment]


@dataclass
class ParsedChunk:
    start_jd: float
    end_jd: float
    bodies: list[BodyRecord]


def _parse_chunk(path: Path) -> ParsedChunk:
    """Decode a chebyshev chunk file end-to-end. Mirrors `pack_*_header`."""
    data = gzip.decompress(path.read_bytes())
    magic, ver, fmt, _, start_jd, end_jd = struct.unpack("<4sHBBdd", data[:24])
    assert magic == MAGIC and ver == VERSION and fmt == FORMAT_CHEBYSHEV, (
        f"{path}: bad header magic={magic!r} ver={ver} fmt={fmt}"
    )
    body_count, flags, _r1, _r2 = struct.unpack("<IBBH", data[24:HEADER_SIZE])
    float64_coeffs = bool(flags & CHEBYSHEV_FLAG_FLOAT64_COEFFS)
    coeff_dtype = np.float64 if float64_coeffs else np.float32
    coeff_bytes = 8 if float64_coeffs else 4

    off = HEADER_SIZE
    bodies: list[BodyRecord] = []
    for _ in range(body_count):
        (
            naif_id,
            parent_id,
            _obj_id_value,
            _radius_km,
            coeffs_per_axis,
            _id_type,
            _has_loc,
            _obj_type,
            _reserved,
            segment_count,
        ) = struct.unpack("<iiifHBBBBH", data[off : off + BODY_HEADER_SIZE])
        off += BODY_HEADER_SIZE
        segments: list[Segment] = []
        seg_coeffs_bytes = coeffs_per_axis * 3 * coeff_bytes
        for _ in range(segment_count):
            seg_start, seg_end = struct.unpack("<dd", data[off : off + 16])
            off += 16
            coeffs = (
                np.frombuffer(
                    data, dtype=coeff_dtype, count=3 * coeffs_per_axis, offset=off
                )
                .reshape(3, coeffs_per_axis)
                .astype(np.float64)
            )
            off += seg_coeffs_bytes
            segments.append(Segment(seg_start, seg_end, coeffs))
        bodies.append(BodyRecord(naif_id, parent_id, segments))
    assert off == len(data), f"{path}: trailing data ({off} vs {len(data)})"
    return ParsedChunk(start_jd, end_jd, bodies)


# ── Decoders (mirror the frontend) ───────────────────────────────────────


def _eval_segment(seg: Segment, et: float) -> np.ndarray:
    """Evaluate Chebyshev position at `et` (mirrors `chebval` over τ ∈ [-1, 1])."""
    seg_start_et = (seg.start_jd - _J2000_JD) * _S_PER_DAY
    seg_end_et = (seg.end_jd - _J2000_JD) * _S_PER_DAY
    tau = 2 * (et - seg_start_et) / (seg_end_et - seg_start_et) - 1
    return np.array(
        [np.polynomial.chebyshev.chebval(tau, seg.coeffs[axis]) for axis in range(3)]
    )


# ── Benchmark ────────────────────────────────────────────────────────────


def _furnish_all_kernels() -> int:
    n = 0
    for path in sorted(_KERNELS_ROOT.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in (".bsp", ".tls", ".tpc"):
            spiceypy.furnsh(str(path))
            n += 1
    return n


def _sample_ets(seg: Segment, n: int) -> np.ndarray:
    seg_start_et = (seg.start_jd - _J2000_JD) * _S_PER_DAY
    seg_end_et = (seg.end_jd - _J2000_JD) * _S_PER_DAY
    return np.linspace(seg_start_et, seg_end_et, n)


def _evaluate_body(body: BodyRecord, sample_per_seg: int) -> list[float]:
    """Return per-sample km errors aggregated across every segment."""
    errs: list[float] = []
    target = str(body.naif_id)
    center = str(body.parent_id)
    for seg in body.segments:
        for et in _sample_ets(seg, sample_per_seg):
            try:
                truth, _ = spiceypy.spkezr(
                    target, float(et), "ECLIPJ2000", "NONE", center
                )
            except spiceypy.exceptions.SpiceyError:
                continue
            fitted = _eval_segment(seg, float(et))
            errs.append(float(np.linalg.norm(fitted - np.asarray(truth[:3]))))
    return errs


def _body_label(naif_id: int) -> str:
    try:
        return spiceypy.bodc2n(naif_id)
    except spiceypy.exceptions.SpiceyError:
        return ""


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--zones",
        nargs="+",
        help="restrict to specific zones (default: every chunked Chebyshev zone)",
    )
    p.add_argument(
        "--samples-per-segment",
        type=int,
        default=5,
        help="how many evenly-spaced eval points per segment (default: 5)",
    )
    p.add_argument(
        "--limit",
        type=int,
        help="cap on number of chunk files processed per zone (default: no cap)",
    )
    p.add_argument(
        "--export-dir",
        type=Path,
        default=EXPORT_DIR,
        help=f"override export root (default: {EXPORT_DIR})",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "docs" / "chebyshev-accuracy.md",
        help="write a markdown report to this path (default: docs/chebyshev-accuracy.md)",
    )
    return p.parse_args()


def _format_err(km: float) -> str:
    if km < 1e-3:
        return f"{km * 1e6:.0f}mm"
    if km < 1:
        return f"{km * 1000:.0f}m"
    if km < 1e6:
        return f"{km:.1f}km"
    return f"{km:.1e}km"


def _format_chunk_span(years: float) -> str:
    if years < 1:
        return f"{years * 12:.0f}mo"
    return f"{years:.0f}y"


def _discover_chebyshev_zones(manifest: dict) -> dict[str, dict]:
    """Pull every position zone whose zoom-0 is chunked (Chebyshev)."""
    out: dict[str, dict] = {}
    for zone_key, entry in manifest.get("position", {}).get("zones", {}).items():
        zoom0 = entry.get("zooms", {}).get("0")
        if zoom0 and zoom0.get("shape") == "chunked":
            out[zone_key] = zoom0
    return out


def main() -> int:
    args = _parse_args()
    manifest_path = _manifest_path(args.export_dir)
    position_root = _position_root(args.export_dir)
    if not manifest_path.exists():
        logger.error("No manifest at %s — run `space-map-export` first", manifest_path)
        return 1
    manifest = json.loads(manifest_path.read_text())
    cheb_zones = _discover_chebyshev_zones(manifest)
    if args.zones:
        cheb_zones = {k: v for k, v in cheb_zones.items() if k in args.zones}
    if not cheb_zones:
        logger.error("No Chebyshev zones in manifest (filter or empty export?)")
        return 1

    n = _furnish_all_kernels()
    logger.info("Furnished %d kernels; benchmarking %d zones", n, len(cheb_zones))

    per_zone_errs: dict[str, list[float]] = defaultdict(list)
    per_zone_files: dict[str, list[int]] = defaultdict(list)
    per_zone_segments: dict[str, int] = defaultdict(int)
    per_zone_chunk_years: dict[str, float] = {}
    # (zone, naif_id) → errs, plus parent_id snapshot for labeling.
    per_body_errs: dict[tuple[str, int], list[float]] = defaultdict(list)
    per_body_parent: dict[tuple[str, int], int] = {}
    per_body_segments: dict[tuple[str, int], int] = defaultdict(int)
    body_labels: dict[int, str] = {}

    try:
        for zone_key, zone_entry in sorted(cheb_zones.items()):
            per_zone_chunk_years[zone_key] = float(zone_entry.get("chunk_years", 0.0))
            zone_dir = position_root / zone_key / "0"
            if not zone_dir.is_dir():
                logger.warning(
                    "zone %s has no zoom-0 directory at %s", zone_key, zone_dir
                )
                continue
            chunk_files = sorted(
                zone_dir.glob("*.bin.gz"), key=lambda p: int(p.stem.split(".")[0])
            )
            if args.limit:
                chunk_files = chunk_files[: args.limit]
            logger.info("[%s] %d chunk files", zone_key, len(chunk_files))

            for cf in chunk_files:
                per_zone_files[zone_key].append(cf.stat().st_size)
                parsed = _parse_chunk(cf)
                for body in parsed.bodies:
                    key = (zone_key, body.naif_id)
                    per_body_parent.setdefault(key, body.parent_id)
                    per_zone_segments[zone_key] += len(body.segments)
                    per_body_segments[key] += len(body.segments)
                    if body.naif_id not in body_labels:
                        body_labels[body.naif_id] = _body_label(body.naif_id)
                    errs = _evaluate_body(body, args.samples_per_segment)
                    per_zone_errs[zone_key].extend(errs)
                    per_body_errs[key].extend(errs)
    finally:
        spiceypy.kclear()

    def pct(lst: list[int] | list[float], q: float) -> float:
        return lst[min(len(lst) - 1, int(q * len(lst)))] if lst else 0.0

    # ── Per-zone aggregates ──────────────────────────────────────────────
    zone_rows: list[dict] = []
    for zone_key in sorted(per_zone_errs):
        errs = sorted(per_zone_errs[zone_key])
        sizes = sorted(per_zone_files[zone_key])
        bodies_in_zone = [k for k in per_body_errs if k[0] == zone_key]
        zone_rows.append(
            {
                "zone": zone_key,
                "chunk_years": per_zone_chunk_years.get(zone_key, 0.0),
                "files": len(sizes),
                "bodies": len(bodies_in_zone),
                "segments": per_zone_segments[zone_key],
                "med": pct(errs, 0.5),
                "p95": pct(errs, 0.95),
                "max": errs[-1] if errs else 0.0,
                "med_kb": pct(sizes, 0.5) / 1024 if sizes else 0,
                "p95_kb": pct(sizes, 0.95) / 1024 if sizes else 0,
                "max_kb": sizes[-1] / 1024 if sizes else 0,
                "sum_mb": sum(sizes) / 1024 / 1024,
            }
        )

    # ── Per-body aggregates ──────────────────────────────────────────────
    # Layout: (naif_id, parent_id, max_err, p95_err, median_err, n_samples, n_segments).
    by_zone_bodies: dict[str, list[tuple[int, int, float, float, float, int, int]]] = (
        defaultdict(list)
    )
    for (zone_key, naif_id), errs in per_body_errs.items():
        if not errs:
            continue
        sorted_e = sorted(errs)
        by_zone_bodies[zone_key].append(
            (
                naif_id,
                per_body_parent[(zone_key, naif_id)],
                sorted_e[-1],
                pct(sorted_e, 0.95),
                pct(sorted_e, 0.5),
                len(sorted_e),
                per_body_segments[(zone_key, naif_id)],
            )
        )

    # Brief stdout summary (per-zone). Per-body table lives in the markdown.
    print()
    print(
        f"{'zone':<22} {'chunk':>5} {'files':>5} {'bodies':>6} {'segments':>8}  "
        f"{'med_err':>9} {'p95_err':>9} {'max_err':>9}  "
        f"{'med_kb':>7} {'p95_kb':>7} {'max_kb':>7} {'sum_mb':>7}"
    )
    print("-" * 125)
    for r in zone_rows:
        print(
            f"{r['zone']:<22} {_format_chunk_span(r['chunk_years']):>5} "
            f"{r['files']:>5} {r['bodies']:>6} {r['segments']:>8}  "
            f"{_format_err(r['med']):>9} {_format_err(r['p95']):>9} {_format_err(r['max']):>9}  "
            f"{r['med_kb']:>6.1f}K {r['p95_kb']:>6.1f}K {r['max_kb']:>6.1f}K {r['sum_mb']:>6.1f}M"
        )

    if args.output:
        _write_markdown(args.output, zone_rows, by_zone_bodies, body_labels)
        logger.info("Wrote %s", args.output)
    return 0


def _write_markdown(
    path: Path,
    zone_rows: list[dict],
    by_zone_bodies: dict[str, list[tuple[int, int, float, float, float, int, int]]],
    body_labels: dict[int, str],
) -> None:
    """Render the benchmark output as a markdown report.

    Two tables: per-zone aggregates, then every body in every zone sorted
    by max sample error (worst-first within each zone).
    """
    import datetime

    lines: list[str] = []
    lines.append("# Chebyshev trajectory accuracy")
    lines.append("")
    lines.append(
        "> Auto-generated by `data/scripts/chebyshev_benchmark.py`. Reads "
        "the exported `position/{zone}/0/` binaries, decodes every segment "
        "via the same logic the frontend will use, and compares against "
        "`spiceypy.spkezr` truth at 5 evenly-spaced sample points per "
        "segment. Regenerate after any change to the Chebyshev format, "
        "fitter, or sub-interval policy."
    )
    lines.append("")
    lines.append(f"_Generated {datetime.date.today().isoformat()}._")
    lines.append("")

    lines.append("## Per-zone error & size aggregates")
    lines.append("")
    lines.append(
        "Chunk span is the on-disk streaming-chunk duration (the unit the "
        "frontend swaps in). Errors come from comparing the decoded "
        "Chebyshev polynomial against parent-relative ECLIPJ2000 positions "
        "from `spkezr`."
    )
    lines.append("")
    lines.append(
        "| Zone | Chunk span | Files | Bodies | Segments | Median err | p95 err | Max err | "
        "Median KiB | p95 KiB | Max KiB | Total MiB |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in zone_rows:
        lines.append(
            f"| `{r['zone']}` | {_format_chunk_span(r['chunk_years'])} | "
            f"{r['files']} | {r['bodies']} | {r['segments']} | "
            f"{_format_err(r['med'])} | {_format_err(r['p95'])} | {_format_err(r['max'])} | "
            f"{r['med_kb']:.1f} | {r['p95_kb']:.1f} | {r['max_kb']:.1f} | {r['sum_mb']:.1f} |"
        )
    lines.append("")

    lines.append("## Per-body error (worst-first within each zone)")
    lines.append("")
    lines.append(
        "Fit residual is small by construction (Chebyshev–Lobatto "
        "interpolation at degree+1 nodes is exact through the sample "
        "points), so the dominant error source is float32 coefficient "
        "quantization. That makes the per-body max scale with the body's "
        "absolute distance from its parent — outer-planet barycenters "
        "relative to the SSB hit hundreds of km, while close-in moons stay "
        "in the meter range."
    )
    lines.append("")
    lines.append(
        "| Zone | NAIF | Name | Parent | Segments | Samples | "
        "Median err | p95 err | Max err |"
    )
    lines.append("|---|---:|---|---:|---:|---:|---:|---:|---:|")
    for zone_key in sorted(by_zone_bodies):
        for naif_id, parent_id, mx, p95, med, n, n_seg in sorted(
            by_zone_bodies[zone_key], key=lambda r: -r[2]
        ):
            label = body_labels.get(naif_id, "") or ""
            lines.append(
                f"| `{zone_key}` | {naif_id} | {label} | {parent_id} | "
                f"{n_seg} | {n} | "
                f"{_format_err(med)} | {_format_err(p95)} | {_format_err(mx)} |"
            )
    lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
