"""Benchmark exported Keplerian elements files against SPICE truth.

Propagates each body via the same formulation the frontend uses
(`orbitalElementsToPositionJD`) and compares against `spiceypy.spkezr`
truth. Catches what the chebyshev benchmark can't: static asteroid orbits
(SBDB Kepler) and time-chunked SPICE moons (Method C mean-element fit
with secular drift). Asteroid rows without SPICE coverage are skipped
silently — only the 373 bodies in `sb441-n373.bsp` plus anything covered
by mission kernels are scored.

Run from data/:
    uv run python scripts/elements_benchmark.py
    uv run python scripts/elements_benchmark.py --zones moons AMO
    uv run python scripts/elements_benchmark.py --samples-per-file 7
"""

import argparse
import gzip
import json
import logging
import math
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
    FORMAT_ELEMENTS,
    HEADER_SIZE,
    MAGIC,
    SOURCE_ORDINAL,
    SUBFORMAT_KEPLERIAN,
    VERSION,
    align8,
)
from space_map_data.utils.paths import DOWNLOAD_DIR, EXPORT_DIR  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

_S_PER_DAY = 86400.0
_J2000_JD = 2451545.0
_AU_KM = 149_597_870.7
_KERNELS_ROOT = DOWNLOAD_DIR / PROVIDERS.SPICE / "kernels"
_SOURCE_LABEL: dict[int, str] = {v: k.value for k, v in SOURCE_ORDINAL.items()}


def _position_root(export_root: Path) -> Path:
    return export_root / "v1" / "position"


def _manifest_path(export_root: Path) -> Path:
    return export_root / "v1" / "metadata.json"


# ── Binary parsing ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class BodyElements:
    """One row decoded from a Keplerian elements file."""

    id_value: int  # raw column-0 int (SPK-ID, NAIF, etc.)
    naif_id: int | None  # SPICE-addressable NAIF id, or None if unmappable
    parent_id: int  # column-2 int (always NAIF per writer.py)
    epoch_jd: float
    a_au: float
    e: float
    i_deg: float
    om_deg: float
    w_deg: float
    ma_deg: float
    n_deg_per_day: float
    om_dot: float  # deg/day, 0.0 when source didn't fit it
    w_dot: float  # deg/day, 0.0 when source didn't fit it


@dataclass(frozen=True)
class ParsedElementsFile:
    start_jd: float
    end_jd: float
    sub_format: int
    source_ordinal: int
    id_type_ordinal: int
    bodies: list[BodyElements]


def _id_to_naif(id_value: int, id_type_ordinal: int) -> int | None:
    """Return a SPICE-addressable NAIF id, or None when no mapping exists.

    ID_TYPE_ORDINAL: 0=NAIF, 1=SPKID, 2=NORAD_SATCAT, 4=PROBE (3 retired).
    Asteroids ship as SPK-IDs (20XXXXXX); SPICE addresses them as NAIF
    (2XXXXXX), so subtract the 18M offset. Comets use 1XXXXXX in both
    schemes (no offset). NORAD has no NAIF analogue here.
    """
    if id_type_ordinal == 0:  # NAIF
        return id_value
    if id_type_ordinal == 1:  # SPKID
        if id_value >= 20_000_000:
            return id_value - 18_000_000
        return id_value
    return None


def _read_col_int32(data: bytes, off: int, n: int) -> tuple[tuple[int, ...], int]:
    vals = struct.unpack(f"<{n}i", data[off : off + n * 4])
    return vals, off + align8(n * 4)


def _read_col_uint8(data: bytes, off: int, n: int) -> tuple[tuple[int, ...], int]:
    vals = struct.unpack(f"<{n}B", data[off : off + n])
    return vals, off + align8(n)


def _read_col_float32(data: bytes, off: int, n: int) -> tuple[tuple[float, ...], int]:
    vals = struct.unpack(f"<{n}f", data[off : off + n * 4])
    return vals, off + align8(n * 4)


def _read_col_float64(data: bytes, off: int, n: int) -> tuple[tuple[float, ...], int]:
    vals = struct.unpack(f"<{n}d", data[off : off + n * 8])
    return vals, off + n * 8


def _parse_elements_file(path: Path) -> ParsedElementsFile | None:
    """Decode a Keplerian elements file end-to-end.

    Returns None for files whose sub-format isn't Keplerian (parabolic
    comets and SGP4 satellites have different column layouts and don't
    line up with SPICE either way).
    """
    data = gzip.decompress(path.read_bytes())
    magic, ver, fmt, _, start_jd, end_jd = struct.unpack("<4sHBBdd", data[:24])
    assert magic == MAGIC and ver == VERSION, (
        f"{path}: bad header magic={magic!r} ver={ver}"
    )
    if fmt != FORMAT_ELEMENTS:
        return None
    sub_format, source, id_type, n = struct.unpack("<HBBI", data[24:HEADER_SIZE])
    if sub_format != SUBFORMAT_KEPLERIAN:
        return None

    off = HEADER_SIZE
    ids, off = _read_col_int32(data, off, n)
    _otypes, off = _read_col_uint8(data, off, n)
    parents, off = _read_col_int32(data, off, n)
    _scales, off = _read_col_uint8(data, off, n)
    epochs, off = _read_col_float64(data, off, n)
    cols: dict[str, tuple[float, ...]] = {}
    for attr in ("a", "e", "i", "om", "w", "ma", "n"):
        cols[attr], off = _read_col_float32(data, off, n)
    _radii, off = _read_col_float32(data, off, n)
    # om_dot/w_dot are present for source=spice (Method C drift). Other
    # sources may either omit them entirely (asteroid SBDB files) or write
    # zeros — we detect by remaining bytes.
    has_drift = (len(data) - off) >= align8(n * 4) * 2 + align8(n)
    if has_drift:
        om_dot, off = _read_col_float32(data, off, n)
        w_dot, off = _read_col_float32(data, off, n)
    else:
        om_dot = (0.0,) * n
        w_dot = (0.0,) * n

    bodies = [
        BodyElements(
            id_value=ids[k],
            naif_id=_id_to_naif(ids[k], id_type),
            parent_id=parents[k],
            epoch_jd=epochs[k],
            a_au=cols["a"][k],
            e=cols["e"][k],
            i_deg=cols["i"][k],
            om_deg=cols["om"][k],
            w_deg=cols["w"][k],
            ma_deg=cols["ma"][k],
            n_deg_per_day=cols["n"][k],
            om_dot=om_dot[k],
            w_dot=w_dot[k],
        )
        for k in range(n)
    ]
    return ParsedElementsFile(start_jd, end_jd, sub_format, source, id_type, bodies)


# ── Kepler propagation (mirrors the frontend) ─────────────────────────────

_DEG2RAD = math.pi / 180.0


def _solve_kepler(M: float, e: float) -> float:
    """Newton-Raphson for E - e·sin(E) = M (elliptic)."""
    E = M if e < 0.8 else math.pi
    for _ in range(40):
        f = E - e * math.sin(E) - M
        fp = 1.0 - e * math.cos(E)
        dE = f / fp
        E -= dE
        if abs(dE) < 1e-13:
            break
    return E


def _solve_kepler_hyperbolic(M: float, e: float) -> float:
    """Newton-Raphson for e·sinh(H) - H = M (hyperbolic)."""
    H = math.copysign(math.log(2.0 * abs(M) / e + 1.8), M) if abs(M) > 0 else 0.0
    for _ in range(80):
        f = e * math.sinh(H) - H - M
        fp = e * math.cosh(H) - 1.0
        dH = f / fp
        H -= dH
        if abs(dH) < 1e-13:
            break
    return H


def _propagate(el: BodyElements, jd: float) -> np.ndarray | None:
    """Return parent-relative ecliptic-J2000 position [x, y, z] in km."""
    a = el.a_au
    e = el.e
    if not (math.isfinite(a) and math.isfinite(e) and math.isfinite(el.ma_deg)):
        return None
    dt = jd - el.epoch_jd
    M = (el.ma_deg + el.n_deg_per_day * dt) * _DEG2RAD
    om = (el.om_deg + el.om_dot * dt) * _DEG2RAD
    w = (el.w_deg + el.w_dot * dt) * _DEG2RAD
    i = el.i_deg * _DEG2RAD

    if e < 1.0 or a > 0.0:
        ec = min(e, 1.0 - 1e-7)
        E = _solve_kepler(M, ec)
        denom = 1.0 - ec * math.cos(E)
        sin_nu = math.sqrt(1.0 - ec * ec) * math.sin(E) / denom
        cos_nu = (math.cos(E) - ec) / denom
        nu = math.atan2(sin_nu, cos_nu)
        r = a * (1.0 - ec * math.cos(E))
    else:
        H = _solve_kepler_hyperbolic(M, e)
        if not math.isfinite(H):
            return None
        denom = e * math.cosh(H) - 1.0
        if abs(denom) < 1e-15:
            return None
        sin_nu = math.sqrt(e * e - 1.0) * math.sinh(H) / denom
        cos_nu = (e - math.cosh(H)) / denom
        nu = math.atan2(sin_nu, cos_nu)
        r = a * (1.0 - e * math.cosh(H))

    x_orb = r * math.cos(nu)
    y_orb = r * math.sin(nu)
    cosW, sinW = math.cos(w), math.sin(w)
    cosI, sinI = math.cos(i), math.sin(i)
    cosOm, sinOm = math.cos(om), math.sin(om)
    x = (cosOm * cosW - sinOm * sinW * cosI) * x_orb + (
        -cosOm * sinW - sinOm * cosW * cosI
    ) * y_orb
    y = (sinOm * cosW + cosOm * sinW * cosI) * x_orb + (
        -sinOm * sinW + cosOm * cosW * cosI
    ) * y_orb
    z = sinW * sinI * x_orb + cosW * sinI * y_orb
    return np.array([x, y, z]) * _AU_KM


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


def _build_covered_naif_set() -> set[int]:
    """Enumerate every NAIF id that any loaded SPK kernel can position."""
    covered: set[int] = set()
    for path in _KERNELS_ROOT.rglob("*.bsp"):
        cell = spiceypy.support_types.SPICEINT_CELL(20000)
        try:
            spiceypy.spkobj(str(path), cell)
        except spiceypy.exceptions.SpiceyError:
            continue
        for nid in cell:
            covered.add(int(nid))
    return covered


def _sample_jds(
    file_start_jd: float,
    file_end_jd: float,
    epoch_jd: float,
    n: int,
    fallback_years: float,
) -> np.ndarray:
    """Pick `n` evenly-spaced JDs across the body's evaluation window.

    Uses the file's [start, end] when bounded; otherwise a fallback span
    centered on epoch_jd (asteroid SBDB files are unbounded — they're a
    pure mathematical solution, but error grows with |jd - epoch|, so we
    sample close to the epoch by default).
    """
    if math.isfinite(file_start_jd) and math.isfinite(file_end_jd):
        return np.linspace(file_start_jd, file_end_jd, n)
    half = fallback_years * 365.25 / 2.0
    return np.linspace(epoch_jd - half, epoch_jd + half, n)


def _evaluate_body(
    body: BodyElements,
    file_start_jd: float,
    file_end_jd: float,
    samples_per_file: int,
    fallback_years: float,
) -> list[float]:
    """Per-sample km errors for one body. Empty if no SPICE coverage hits."""
    if body.naif_id is None:
        return []
    errs: list[float] = []
    target = str(body.naif_id)
    center = str(body.parent_id)
    for jd in _sample_jds(
        file_start_jd, file_end_jd, body.epoch_jd, samples_per_file, fallback_years
    ):
        et = (float(jd) - _J2000_JD) * _S_PER_DAY
        try:
            truth, _ = spiceypy.spkezr(target, et, "ECLIPJ2000", "NONE", center)
        except spiceypy.exceptions.SpiceyError:
            continue
        fitted = _propagate(body, float(jd))
        if fitted is None:
            continue
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
        help="restrict to specific zones (default: every Keplerian-elements zone)",
    )
    p.add_argument(
        "--samples-per-file",
        type=int,
        default=5,
        help="evenly-spaced eval points per body per file (default: 5)",
    )
    p.add_argument(
        "--unbounded-window-years",
        type=float,
        default=2.0,
        help="for files with no validity bounds, span ±N/2 years around epoch (default: 2)",
    )
    p.add_argument(
        "--limit",
        type=int,
        help="cap on number of files processed per zone (default: no cap)",
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
        default=REPO_ROOT / "docs" / "elements-accuracy.md",
        help="write a markdown report to this path (default: docs/elements-accuracy.md)",
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


def _err_or_dash(samples: int, km: float) -> str:
    """Render a placeholder when there are no samples to compute an error from."""
    return _format_err(km) if samples else "—"


def _discover_elements_zone_files(
    manifest: dict, position_root: Path
) -> dict[str, list[Path]]:
    """Walk every (zone, zoom) in the manifest and collect *.bin.gz files.

    Walks all zooms because the `major` zone ships Chebyshev at zoom 0
    and Keplerian fallbacks at zooms 1/2 — the format byte at parse
    time discards anything that isn't Keplerian. Keys are `{zone}:z{N}`
    so the report can show zoom-1 vs zoom-2 rows separately. The
    underlying directory layout (parted / chunked / chunked-parted) is
    flattened by `rglob`.
    """
    out: dict[str, list[Path]] = {}
    for zone_key, entry in manifest.get("position", {}).get("zones", {}).items():
        zooms = entry.get("zooms")
        if not zooms:  # probes/* live at zone root, not under a zoom subdir
            continue
        for zoom_str in zooms:
            zone_dir = position_root / zone_key / zoom_str
            if not zone_dir.is_dir():
                continue
            files = sorted(zone_dir.rglob("*.bin.gz"))
            if files:
                out[f"{zone_key}:z{zoom_str}"] = files
    return out


def main() -> int:
    args = _parse_args()
    manifest_path = _manifest_path(args.export_dir)
    position_root = _position_root(args.export_dir)
    if not manifest_path.exists():
        logger.error("No manifest at %s — run `space-map-export` first", manifest_path)
        return 1
    manifest = json.loads(manifest_path.read_text())
    zone_files = _discover_elements_zone_files(manifest, position_root)
    if args.zones:
        # Accept both "moons" (any zoom) and "moons:z0" (exact key).
        wanted = set(args.zones)
        zone_files = {
            k: v
            for k, v in zone_files.items()
            if k in wanted or k.split(":", 1)[0] in wanted
        }
    if not zone_files:
        logger.error("No zone files matched (filter or empty export?)")
        return 1

    n_kernels = _furnish_all_kernels()
    covered = _build_covered_naif_set()
    logger.info(
        "Furnished %d kernels covering %d NAIF ids; scanning %d zones",
        n_kernels,
        len(covered),
        len(zone_files),
    )

    per_zone_errs: dict[str, list[float]] = defaultdict(list)
    per_zone_files: dict[str, list[int]] = defaultdict(list)
    per_zone_total_bodies: dict[str, set[int]] = defaultdict(set)
    per_zone_covered_bodies: dict[str, set[int]] = defaultdict(set)
    per_zone_source: dict[str, int] = {}
    per_body_errs: dict[tuple[str, int], list[float]] = defaultdict(list)
    per_body_parent: dict[tuple[str, int], int] = {}
    body_labels: dict[int, str] = {}

    try:
        for zone_key, files in sorted(zone_files.items()):
            if args.limit:
                files = files[: args.limit]
            kept = 0
            for cf in files:
                parsed = _parse_elements_file(cf)
                if parsed is None:
                    continue
                kept += 1
                per_zone_files[zone_key].append(cf.stat().st_size)
                per_zone_source.setdefault(zone_key, parsed.source_ordinal)
                for body in parsed.bodies:
                    per_zone_total_bodies[zone_key].add(body.id_value)
                    if body.naif_id is None or body.naif_id not in covered:
                        continue
                    per_zone_covered_bodies[zone_key].add(body.id_value)
                    key = (zone_key, body.naif_id)
                    per_body_parent.setdefault(key, body.parent_id)
                    if body.naif_id not in body_labels:
                        body_labels[body.naif_id] = _body_label(body.naif_id)
                    errs = _evaluate_body(
                        body,
                        parsed.start_jd,
                        parsed.end_jd,
                        args.samples_per_file,
                        args.unbounded_window_years,
                    )
                    per_zone_errs[zone_key].extend(errs)
                    per_body_errs[key].extend(errs)
            logger.info(
                "[%s] %d files (%d kept) — %d bodies, %d with SPICE coverage",
                zone_key,
                len(files),
                kept,
                len(per_zone_total_bodies[zone_key]),
                len(per_zone_covered_bodies[zone_key]),
            )
    finally:
        spiceypy.kclear()

    def pct(lst: list[int] | list[float], q: float) -> float:
        return lst[min(len(lst) - 1, int(q * len(lst)))] if lst else 0.0

    # ── Per-zone aggregates ──────────────────────────────────────────────
    zone_rows: list[dict] = []
    for zone_key in sorted(per_zone_files):
        errs = sorted(per_zone_errs[zone_key])
        sizes = sorted(per_zone_files[zone_key])
        zone_rows.append(
            {
                "zone": zone_key,
                "source": _SOURCE_LABEL.get(per_zone_source[zone_key], "?"),
                "files": len(sizes),
                "total_bodies": len(per_zone_total_bodies[zone_key]),
                "covered_bodies": len(per_zone_covered_bodies[zone_key]),
                "samples": len(errs),
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
    by_zone_bodies: dict[str, list[tuple[int, int, float, float, float, int]]] = (
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
            )
        )

    print()
    print(
        f"{'zone':<22} {'source':>8} {'files':>5} {'cov/total':>10} "
        f"{'samples':>7}  {'med_err':>9} {'p95_err':>9} {'max_err':>9}  "
        f"{'med_kb':>7} {'p95_kb':>7} {'max_kb':>7} {'sum_mb':>7}"
    )
    print("-" * 130)
    for r in zone_rows:
        cov = f"{r['covered_bodies']}/{r['total_bodies']}"
        s = r["samples"]
        print(
            f"{r['zone']:<22} {r['source']:>8} {r['files']:>5} {cov:>10} "
            f"{r['samples']:>7}  {_err_or_dash(s, r['med']):>9} "
            f"{_err_or_dash(s, r['p95']):>9} {_err_or_dash(s, r['max']):>9}  "
            f"{r['med_kb']:>6.1f}K {r['p95_kb']:>6.1f}K {r['max_kb']:>6.1f}K "
            f"{r['sum_mb']:>6.1f}M"
        )

    if args.output:
        _write_markdown(args.output, zone_rows, by_zone_bodies, body_labels)
        logger.info("Wrote %s", args.output)
    return 0


def _write_markdown(
    path: Path,
    zone_rows: list[dict],
    by_zone_bodies: dict[str, list[tuple[int, int, float, float, float, int]]],
    body_labels: dict[int, str],
) -> None:
    """Render the benchmark output as a markdown report.

    Two tables: per-zone aggregates (with SPICE coverage rate), then
    every body in every zone sorted by max sample error within each zone.
    """
    import datetime

    lines: list[str] = []
    lines.append("# Keplerian elements trajectory accuracy")
    lines.append("")
    lines.append(
        "> Auto-generated by `data/scripts/elements_benchmark.py`. Walks "
        "every Keplerian elements file under `position/{zone}/{zoom}/`, "
        "propagates each body via the same solver the frontend uses "
        "(`orbitalElementsToPositionJD` — mean-anomaly drift plus optional "
        "secular om/w drift), and compares against `spiceypy.spkezr` truth "
        "at 5 evenly-spaced sample points per file. Bodies without SPICE "
        "coverage are skipped silently; the SBDB asteroid zones almost "
        "all show 0/N coverage because every SPICE-tracked numbered "
        "asteroid (the 373 in `sb441-n373.bsp`) is shipped in the "
        "`major_asteroids` Chebyshev zone instead, not here. The signal "
        "lives in the time-chunked `moons:z0` Method C fits, the handful "
        "of comets and TNOs with mission-kernel coverage, and the active "
        "spacecraft. Regenerate after any change to the elements writer, "
        "the moon Kepler-fit pipeline, or the column layout."
    )
    lines.append("")
    lines.append(f"_Generated {datetime.date.today().isoformat()}._")
    lines.append("")

    lines.append("## Per-zone error & size aggregates")
    lines.append("")
    lines.append(
        "`cov/total` is the count of bodies the kernel pool can position "
        "vs the row count in the file. The `moons:z0` zone is fit *from* "
        "SPICE Method C and contains only non-whitelisted irregulars, so "
        "coverage is 100% and the residuals expose the cost of forcing a "
        "linear secular model onto chaotic outer-system orbits. Comet and "
        "spacecraft rows that match a mission kernel show two-body Kepler "
        "diverging from the real maneuvering trajectory — these errors "
        "are inherent to the elements representation, not the encoder."
    )
    lines.append("")
    lines.append(
        "| Zone | Source | Files | Cov / Total | Samples | "
        "Median err | p95 err | Max err | "
        "Median KiB | p95 KiB | Max KiB | Total MiB |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in zone_rows:
        s = r["samples"]
        lines.append(
            f"| `{r['zone']}` | {r['source']} | {r['files']} | "
            f"{r['covered_bodies']} / {r['total_bodies']} | {s} | "
            f"{_err_or_dash(s, r['med'])} | {_err_or_dash(s, r['p95'])} | "
            f"{_err_or_dash(s, r['max'])} | "
            f"{r['med_kb']:.1f} | {r['p95_kb']:.1f} | {r['max_kb']:.1f} | {r['sum_mb']:.1f} |"
        )
    lines.append("")

    lines.append("## Per-body error (worst-first within each zone)")
    lines.append("")
    lines.append(
        "Method C moons: secular drift on om/w is the only correction "
        "beyond mean-anomaly advance, so resonances, Kozai-Lidov cycles, "
        "and other short-period perturbations on the high-e/high-i outer "
        "irregulars set the error floor — the worst rows here are exactly "
        "the bodies that *would* benefit from being on the Chebyshev "
        "whitelist. Comets and spacecraft show two-body Kepler diverging "
        "from non-gravitational forces (outgassing) and propulsive "
        "maneuvers respectively."
    )
    lines.append("")
    lines.append(
        "| Zone | NAIF | Name | Parent | Samples | Median err | p95 err | Max err |"
    )
    lines.append("|---|---:|---|---:|---:|---:|---:|---:|")
    for zone_key in sorted(by_zone_bodies):
        for naif_id, parent_id, mx, p95, med, n in sorted(
            by_zone_bodies[zone_key], key=lambda r: -r[2]
        ):
            label = body_labels.get(naif_id, "") or ""
            lines.append(
                f"| `{zone_key}` | {naif_id} | {label} | {parent_id} | {n} | "
                f"{_format_err(med)} | {_format_err(p95)} | {_format_err(mx)} |"
            )
    lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
