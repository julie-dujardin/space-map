"""Benchmark exported probe chunks against SPICE truth.

Reads `EXPORT_DIR/v1/position/probes/{zone}/{chunk}.bin.gz`, parses every
sub-chunk via the same decode logic the frontend will use, and compares
positions against `spiceypy.spkezr` truth. Reports per-probe and per-zone
aggregates (median / p95 / max error, file sizes, sample counts).

Validates the *shipped* binary end-to-end — catches packing bugs, float32
quantization, and frontend-mirror drift. Don't trust the fit-time err
report from sizing.py alone; this is the real number.

Run from data/:
    uv run python scripts/probe_benchmark.py
    uv run python scripts/probe_benchmark.py --zones interplanetary mars
    uv run python scripts/probe_benchmark.py --samples-per-subchunk 11
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
from space_map_data.download.providers.objects.probes import MISSIONS_DIR  # noqa: E402
from space_map_data.export.position.format import (  # noqa: E402
    FORMAT_PROBES,
    HEADER_SIZE,
    MAGIC,
    METHOD_CHEBYSHEV,
    METHOD_KEPLER_DRIFT,
    METHOD_KEPLER_PURE,
    METHOD_UNCOVERABLE,
    SUBCHUNK_HEADER_SIZE,
    VERSION,
)
from space_map_data.export.position.probes.sizing import CHEBYSHEV_DEGREE  # noqa: E402
from space_map_data.export.position.probes.writer import (  # noqa: E402
    _mission_kernels,
)
from space_map_data.probes.probe_id import (  # noqa: E402
    CACHE_PATH as PROBE_ID_CACHE,
    load_probe_labels,
)
from space_map_data.probes.zones import ZONES_BY_KEY  # noqa: E402
from space_map_data.utils.paths import DOWNLOAD_DIR, EXPORT_DIR  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

_S_PER_DAY = 86400.0
_J2000_JD = 2451545.0
_KERNELS_ROOT = DOWNLOAD_DIR / PROVIDERS.SPICE / "kernels"


def _probes_root(export_root: Path) -> Path:
    return export_root / "v1" / "position" / "probes"


def _manifest_path(export_root: Path) -> Path:
    return export_root / "v1" / "metadata.json"


_METHOD_NAME = {
    METHOD_UNCOVERABLE: "uncov",
    METHOD_KEPLER_PURE: "kpure",
    METHOD_KEPLER_DRIFT: "kdrift",
    METHOD_CHEBYSHEV: "cheb",
}


# ── Binary parsing ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class SubChunkRecord:
    method: int
    t_start_et: float
    t_end_et: float
    payload: bytes  # method-specific


@dataclass(frozen=True)
class ProbeChunkRecord:
    probe_id: int
    sub_chunks: list[SubChunkRecord]


@dataclass
class ParsedChunk:
    start_jd: float
    end_jd: float
    subchunk_days: float
    probes: list[ProbeChunkRecord]


def _parse_chunk(path: Path) -> ParsedChunk:
    data = gzip.decompress(path.read_bytes())
    magic, ver, fmt, _, start_jd, end_jd = struct.unpack("<4sHBBdd", data[:24])
    assert magic == MAGIC and ver == VERSION and fmt == FORMAT_PROBES, (
        f"{path}: bad header magic={magic} ver={ver} fmt={fmt}"
    )
    probe_count, subchunk_days = struct.unpack("<If", data[24:HEADER_SIZE])
    chunk_start_et = (start_jd - _J2000_JD) * _S_PER_DAY
    sub_s = subchunk_days * _S_PER_DAY

    off = HEADER_SIZE
    probes: list[ProbeChunkRecord] = []
    for _ in range(probe_count):
        obj_id_value, _id_type, _obj_type, _has_loc, _, n_sub, first_off = (
            struct.unpack("<iBBBBHH", data[off : off + 12])
        )
        off += 12
        sub_chunks: list[SubChunkRecord] = []
        for i in range(n_sub):
            method, _, _, payload_len = struct.unpack(
                "<BBHI", data[off : off + SUBCHUNK_HEADER_SIZE]
            )
            off += SUBCHUNK_HEADER_SIZE
            payload = data[off : off + payload_len]
            off += payload_len
            sub_start_et = chunk_start_et + (first_off + i) * sub_s
            sub_chunks.append(
                SubChunkRecord(method, sub_start_et, sub_start_et + sub_s, payload)
            )
        probes.append(ProbeChunkRecord(obj_id_value, sub_chunks))
    assert off == len(data), f"{path}: trailing data ({off} vs {len(data)})"
    return ParsedChunk(start_jd, end_jd, subchunk_days, probes)


# ── Decoders (mirror the frontend) ───────────────────────────────────────


def _decode_kepler(payload: bytes, drift: bool, float64: bool) -> dict:
    """Unpack a kepler_pure (7) or kepler_drift (10) element record.

    Trailing float is `t_anchor_offset_s = t_snap_et - sub_t_start_et`,
    needed to reconstruct the snapshot epoch the fit was anchored at.
    """
    dtype = np.float64 if float64 else np.float32
    n = 10 if drift else 7
    arr = np.frombuffer(payload, dtype=dtype, count=n).astype(np.float64)
    return {
        "a_km": float(arr[0]),
        "e": float(arr[1]),
        "i": float(arr[2]),
        "om0": float(arr[3]),
        "w0": float(arr[4]),
        "m0": float(arr[5]),
        "om_dot": float(arr[6]) if drift else 0.0,
        "w_dot": float(arr[7]) if drift else 0.0,
        "n_mean_rad_s": float(arr[8]) if drift else 0.0,
        "t_anchor_offset_s": float(arr[-1]),
        "drift": drift,
    }


def _eval_kepler(elts: dict, mu: float, sub_t_start_et: float, et: float) -> np.ndarray:
    """Evaluate Kepler position at `et`. Anchor epoch reconstructed from the
    sub-chunk start + the payload's stored offset.

    Pure: `conics` propagates M via mu from `t_anchor`.
    Drift: we manually advance om/w/M, then pass t0=et so conics doesn't re-propagate.
    """
    t_anchor = sub_t_start_et + elts["t_anchor_offset_s"]
    dt = et - t_anchor
    om_t = elts["om0"] + elts["om_dot"] * dt
    w_t = elts["w0"] + elts["w_dot"] * dt
    rp = elts["a_km"] * (1 - elts["e"])
    if elts["drift"]:
        m_t = elts["m0"] + elts["n_mean_rad_s"] * dt
        t0 = et
    else:
        m_t = elts["m0"]
        t0 = t_anchor
    elts_arr = np.array(
        [rp, elts["e"], elts["i"], om_t, w_t, m_t, t0, mu], dtype=np.float64
    )
    state = spiceypy.conics(elts_arr, et)
    return state[:3]


def _eval_chebyshev(
    payload: bytes, sub_start_et: float, sub_end_et: float, float64: bool, et: float
) -> np.ndarray:
    """Evaluate a Chebyshev sub-chunk at `et` (mirrors `chebval` over τ ∈ [-1, 1])."""
    dtype = np.float64 if float64 else np.float32
    n_per_seg = 3 * (CHEBYSHEV_DEGREE + 1)
    n_seg = len(payload) // (n_per_seg * (8 if float64 else 4))
    arr = (
        np.frombuffer(payload, dtype=dtype, count=n_seg * n_per_seg)
        .reshape(n_seg, 3, CHEBYSHEV_DEGREE + 1)
        .astype(np.float64)
    )
    seg_dt = (sub_end_et - sub_start_et) / n_seg
    seg_idx = min(int((et - sub_start_et) / seg_dt), n_seg - 1)
    seg_start = sub_start_et + seg_idx * seg_dt
    seg_end = seg_start + seg_dt
    tau = 2 * (et - seg_start) / (seg_end - seg_start) - 1
    return np.array(
        [np.polynomial.chebyshev.chebval(tau, arr[seg_idx, axis]) for axis in range(3)]
    )


# ── Benchmark ────────────────────────────────────────────────────────────


@dataclass
class SampleResult:
    zone: str
    probe_id: int
    method: int
    err_km: float


def _invert_probe_id_cache() -> dict[int, tuple[str, int]]:
    """`probe_id → (label, naif_id)` with HORIZONS-SYNTH names resolved
    per-spacecraft via `load_probe_labels`."""
    cache = json.loads(PROBE_ID_CACHE.read_text())
    naif_by_pid: dict[int, int] = {
        int(r["probe_id"]): int(r["naif_id"]) for r in cache.values()
    }
    labels = load_probe_labels()
    out: dict[int, tuple[str, int]] = {}
    for pid, naif in naif_by_pid.items():
        label = labels.get(pid, f"?/{naif}")
        # labels are "Name/naif"; split off the naif suffix the benchmark
        # builds its own table column for.
        name = label.rsplit("/", 1)[0] if "/" in label else label
        out[pid] = (name, naif)
    return out


def _build_probe_kernels() -> dict[int, list[Path]]:
    """`probe_id → [mission kernel paths]` mirroring the writer's per-probe
    furnsh set. Required because some NAIF codes are shared across mission
    directories (CASSINI/HUYGENS both target -82, with the HUYGENS dir
    carrying a predicted Cassini OPK to chain Huygens' coast kernel against
    Cassini's position before separation). Furnishing every mission kernel
    at once would let SPICE's last-furnshed-wins return the wrong probe's
    truth at evaluation time — Cassini's reconstructed SCPSE fits get
    benchmarked against the Huygens dir's predicted OPK, inflating the
    reported error by 4 orders of magnitude. This mapping lets the
    benchmark furnsh exactly the kernels the writer saw when it fit each
    probe.
    """
    cache = json.loads(PROBE_ID_CACHE.read_text())
    mission_kernels: dict[str, list[Path]] = {}
    out: dict[int, list[Path]] = {}
    for rec in cache.values():
        mission = rec["mission"]
        if mission not in mission_kernels:
            mdir = MISSIONS_DIR / mission
            mission_kernels[mission] = _mission_kernels(mdir) if mdir.exists() else []
        out[int(rec["probe_id"])] = mission_kernels[mission]
    return out


def _mu_for_center(naif_id: int) -> float:
    return float(spiceypy.bodvrd(str(naif_id), "GM", 1)[1][0])


def _collect_kernels() -> tuple[list[Path], list[Path]]:
    """Return `(lsk_pck_paths, generic_spk_paths)` — same split as the writer.

    LSK/PCK are leapseconds + physical constants, no SPK precedence
    implications. Generic SPKs are planetary DEs and satellite ephemerides
    (de440, sat441, …). The writer furnshes generic SPKs AFTER mission
    kernels so they win for shared targets like Saturn (699), since pre-
    de440-era mission kernels (p11-a.bsp, vg2_sat.bsp, …) carry their own
    1970s-vintage planetary data which would otherwise contaminate the fit.
    The benchmark mirrors that ordering per probe.
    """
    skip_dirs = {"missions", "probes"}
    lsk_pck: list[Path] = []
    generic_spk: list[Path] = []
    for path in sorted(_KERNELS_ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(_KERNELS_ROOT).parts
        suffix = path.suffix.lower()
        if suffix in (".tls", ".tpc"):
            lsk_pck.append(path)
        elif suffix == ".bsp" and not any(p in skip_dirs for p in rel_parts):
            generic_spk.append(path)
    return lsk_pck, generic_spk


def _sample_ets(sub: SubChunkRecord, n: int) -> np.ndarray:
    return np.linspace(sub.t_start_et, sub.t_end_et, n)


def _evaluate_subchunk(
    sub: SubChunkRecord,
    naif_id: int,
    mu: float,
    fit_center: int,
    float64: bool,
    sample_ets: np.ndarray,
) -> list[float]:
    """Return per-sample km errors for one sub-chunk."""
    errs: list[float] = []
    if sub.method == METHOD_UNCOVERABLE:
        return errs
    elts: dict | None = None
    if sub.method in (METHOD_KEPLER_PURE, METHOD_KEPLER_DRIFT):
        elts = _decode_kepler(sub.payload, sub.method == METHOD_KEPLER_DRIFT, float64)
    for et in sample_ets:
        try:
            truth, _ = spiceypy.spkezr(
                str(naif_id), float(et), "ECLIPJ2000", "NONE", str(fit_center)
            )
        except spiceypy.exceptions.SpiceyError:
            continue
        truth = np.asarray(truth[:3])
        if sub.method == METHOD_CHEBYSHEV:
            try:
                fitted = _eval_chebyshev(
                    sub.payload, sub.t_start_et, sub.t_end_et, float64, float(et)
                )
            except Exception:  # noqa: BLE001
                continue
        else:
            assert elts is not None
            try:
                fitted = _eval_kepler(elts, mu, sub.t_start_et, float(et))
            except spiceypy.exceptions.SpiceyError:
                continue
        errs.append(float(np.linalg.norm(fitted - truth)))
    return errs


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--zones",
        nargs="+",
        choices=[z.key for z in ZONES_BY_KEY.values()],
        help="restrict to specific zones (default: all)",
    )
    p.add_argument(
        "--samples-per-subchunk",
        type=int,
        default=5,
        help="how many evenly-spaced eval points per sub-chunk (default: 5)",
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
        default=REPO_ROOT / "docs" / "probe-accuracy.md",
        help="write a markdown report to this path (default: docs/probe-accuracy.md)",
    )
    return p.parse_args()


def _format_err(km: float) -> str:
    if km < 1:
        return f"{km * 1000:.0f}m"
    if km < 1e6:
        return f"{km:.1f}km"
    return f"{km:.1e}km"


def _format_chunk_span(years: float) -> str:
    """Human-friendly streaming-chunk duration: months under 1 y, else years."""
    if years < 1:
        return f"{years * 12:.0f}mo"
    return f"{years:.0f}y"


def main() -> int:
    args = _parse_args()
    manifest_path = _manifest_path(args.export_dir)
    probes_root = _probes_root(args.export_dir)
    if not manifest_path.exists():
        logger.error("No manifest at %s — run `space-map-export` first", manifest_path)
        return 1
    manifest = json.loads(manifest_path.read_text())
    probe_zones = {
        k.removeprefix("probes/"): v
        for k, v in manifest["position"]["zones"].items()
        if k.startswith("probes/")
    }
    if args.zones:
        probe_zones = {k: v for k, v in probe_zones.items() if k in args.zones}
    if not probe_zones:
        logger.error("No probe zones in manifest (filter or empty export?)")
        return 1

    probe_id_to_naif = _invert_probe_id_cache()
    probe_kernels = _build_probe_kernels()
    lsk_pck_paths, generic_spk_paths = _collect_kernels()
    for p in lsk_pck_paths:
        spiceypy.furnsh(str(p))
    logger.info(
        "Furnished %d LSK/PCK kernels at outer scope; per probe, %d generic "
        "SPKs furnshed AFTER the mission kernels (matching writer order, so "
        "modern planetary DEs win over 1970s-era embedded ephemerides); "
        "benchmarking %d zones",
        len(lsk_pck_paths),
        len(generic_spk_paths),
        len(probe_zones),
    )

    # zone → list[SampleResult]; per-probe accumulator inside
    per_zone_errs: dict[str, list[float]] = defaultdict(list)
    per_zone_files: dict[str, list[int]] = defaultdict(list)
    per_zone_method_counts: dict[str, dict[int, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    per_probe_errs: dict[tuple[str, int], list[float]] = defaultdict(list)

    try:
        for zone_key, manifest_entry in sorted(probe_zones.items()):
            if zone_key not in ZONES_BY_KEY:
                logger.warning("unknown zone %s in manifest, skipping", zone_key)
                continue
            zone = ZONES_BY_KEY[zone_key]
            fit_center = zone.fit_center_naif_id
            mu = _mu_for_center(fit_center)
            float64 = manifest_entry.get("float64_coeffs", zone.float64_coeffs)

            zone_dir = probes_root / zone_key
            chunk_files = sorted(
                zone_dir.glob("*.bin.gz"), key=lambda p: int(p.stem.split(".")[0])
            )
            if args.limit:
                chunk_files = chunk_files[: args.limit]
            logger.info(
                "[%s] %d chunk files, mu=%.3e km³/s²", zone_key, len(chunk_files), mu
            )

            # Pass 1: parse every chunk once, collect sub-chunks grouped by
            # probe_id so the SPICE-truth comparison can run probe-major (one
            # furnsh/unload pair per probe, not per chunk).
            per_probe_subs: dict[int, list[SubChunkRecord]] = defaultdict(list)
            for cf in chunk_files:
                per_zone_files[zone_key].append(cf.stat().st_size)
                parsed = _parse_chunk(cf)
                for probe in parsed.probes:
                    per_probe_subs[probe.probe_id].extend(probe.sub_chunks)
                    for sub in probe.sub_chunks:
                        per_zone_method_counts[zone_key][sub.method] += 1

            # Pass 2: per-probe — furnsh only that probe's mission kernels
            # (mirrors `writer._fit_pass`), evaluate every sub-chunk against
            # SPICE truth, unload. Critical when NAIF codes are shared across
            # mission dirs (CASSINI/HUYGENS both target -82): the writer fit
            # against the high-fidelity CASSINI kernels alone, so the
            # benchmark must do the same or it compares against a different
            # probe's predicted truth.
            for probe_id in sorted(per_probe_subs):
                mission_naif = probe_id_to_naif.get(probe_id)
                if mission_naif is None:
                    logger.warning(
                        "probe_id=%d in zone %s not in cache", probe_id, zone_key
                    )
                    continue
                _, naif_id = mission_naif
                kernels = probe_kernels.get(probe_id, [])
                for k in kernels:
                    spiceypy.furnsh(str(k))
                for p in generic_spk_paths:
                    spiceypy.furnsh(str(p))
                try:
                    for sub in per_probe_subs[probe_id]:
                        sample_ets = _sample_ets(sub, args.samples_per_subchunk)
                        errs = _evaluate_subchunk(
                            sub, naif_id, mu, fit_center, float64, sample_ets
                        )
                        per_zone_errs[zone_key].extend(errs)
                        per_probe_errs[(zone_key, probe_id)].extend(errs)
                finally:
                    for p in generic_spk_paths:
                        spiceypy.unload(str(p))
                    for k in kernels:
                        spiceypy.unload(str(k))
    finally:
        spiceypy.kclear()

    def pct(lst: list[int] | list[float], q: float) -> float:
        return lst[min(len(lst) - 1, int(q * len(lst)))] if lst else 0.0

    # ── Per-zone aggregates ──────────────────────────────────────────────
    zone_rows: list[dict] = []
    for zone_key in sorted(per_zone_errs):
        errs = sorted(per_zone_errs[zone_key])
        sizes = sorted(per_zone_files[zone_key])
        counts = per_zone_method_counts[zone_key]
        zone_rows.append(
            {
                "zone": zone_key,
                "chunk_years": ZONES_BY_KEY[zone_key].chunk_years,
                "coeff_dtype": "f64"
                if ZONES_BY_KEY[zone_key].float64_coeffs
                else "f32",
                "files": len(sizes),
                "n_sub": sum(counts.values()),
                "med": pct(errs, 0.5),
                "p95": pct(errs, 0.95),
                "max": errs[-1] if errs else 0.0,
                "med_kb": pct(sizes, 0.5) / 1024 if sizes else 0,
                "p95_kb": pct(sizes, 0.95) / 1024 if sizes else 0,
                "max_kb": sizes[-1] / 1024 if sizes else 0,
                "sum_mb": sum(sizes) / 1024 / 1024,
                "kpure": counts.get(METHOD_KEPLER_PURE, 0),
                "kdrift": counts.get(METHOD_KEPLER_DRIFT, 0),
                "cheb": counts.get(METHOD_CHEBYSHEV, 0),
                "uncov": counts.get(METHOD_UNCOVERABLE, 0),
            }
        )

    # ── Per-probe-per-zone aggregates ────────────────────────────────────
    # Tuple layout: (probe_id, max_err, p95_err, median_err, sample_count).
    by_zone_probes: dict[str, list[tuple[int, float, float, float, int]]] = defaultdict(
        list
    )
    for (zone_key, pid), errs in per_probe_errs.items():
        if not errs:
            continue
        sorted_e = sorted(errs)
        by_zone_probes[zone_key].append(
            (pid, sorted_e[-1], pct(sorted_e, 0.95), pct(sorted_e, 0.5), len(sorted_e))
        )

    # Brief stdout summary (per-zone). The full per-probe table lives in the
    # markdown file.
    print()
    print(
        f"{'zone':<14} {'chunk':>5} {'coef':>4} {'files':>5} {'subchunks':>10}  "
        f"{'med_err':>9} {'p95_err':>9} {'max_err':>9}  "
        f"{'med_kb':>7} {'p95_kb':>7} {'max_kb':>7} {'sum_mb':>7}  method mix (k_pure / k_drift / cheb / uncov)"
    )
    print("-" * 150)
    for r in zone_rows:
        mix = f"{r['kpure']:>5} / {r['kdrift']:>5} / {r['cheb']:>5} / {r['uncov']:>3}"
        print(
            f"{r['zone']:<14} {_format_chunk_span(r['chunk_years']):>5} "
            f"{r['coeff_dtype']:>4} {r['files']:>5} {r['n_sub']:>10}  "
            f"{_format_err(r['med']):>9} {_format_err(r['p95']):>9} {_format_err(r['max']):>9}  "
            f"{r['med_kb']:>6.1f}K {r['p95_kb']:>6.1f}K {r['max_kb']:>6.1f}K {r['sum_mb']:>6.1f}M  {mix}"
        )

    if args.output:
        _write_markdown(args.output, zone_rows, by_zone_probes, probe_id_to_naif)
        logger.info("Wrote %s", args.output)
    return 0


def _write_markdown(
    path: Path,
    zone_rows: list[dict],
    by_zone_probes: dict[str, list[tuple[int, float, float, float, int]]],
    probe_id_to_naif: dict[int, tuple[str, int]],
) -> None:
    """Render the benchmark output as a markdown report.

    Two tables: per-zone aggregates, then every probe in every zone
    sorted by max sample error (worst-first within each zone).
    """
    import datetime

    lines: list[str] = []
    lines.append("# Probe trajectory accuracy")
    lines.append("")
    lines.append(
        "> Auto-generated by `data/scripts/probe_benchmark.py`. Reads the "
        "exported `position/probes/` binaries, decodes every sub-chunk via "
        "the same logic the frontend will use, and compares against "
        "`spiceypy.spkezr` truth at 5 evenly-spaced sample points per "
        "sub-chunk. Regenerate after any change to the probe format or "
        "fitter."
    )
    lines.append("")
    lines.append(f"_Generated {datetime.date.today().isoformat()}._")
    lines.append("")

    lines.append("## Per-zone error & size aggregates")
    lines.append("")
    lines.append(
        "Chunk span is the on-disk streaming-chunk duration (the unit the "
        "frontend swaps in). Coeff dtype is float32 (`f32`) for planet-"
        "centric zones and float64 (`f64`) only where position magnitudes "
        "exceed the float32 ~600 km quantization floor (interplanetary, "
        "with Voyagers/Pioneers at 100+ AU)."
    )
    lines.append("")
    lines.append(
        "| Zone | Chunk span | Coeff dtype | Files | Sub-chunks | Median err | p95 err | Max err | "
        "Median KiB | p95 KiB | Max KiB | Total MiB | k_pure | k_drift | cheb | uncov |"
    )
    lines.append(
        "|---|---:|:--:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    )
    for r in zone_rows:
        lines.append(
            f"| `{r['zone']}` | {_format_chunk_span(r['chunk_years'])} | "
            f"`{r['coeff_dtype']}` | "
            f"{r['files']} | {r['n_sub']} | "
            f"{_format_err(r['med'])} | {_format_err(r['p95'])} | {_format_err(r['max'])} | "
            f"{r['med_kb']:.1f} | {r['p95_kb']:.1f} | {r['max_kb']:.1f} | {r['sum_mb']:.1f} | "
            f"{r['kpure']} | {r['kdrift']} | {r['cheb']} | {r['uncov']} |"
        )
    lines.append("")

    lines.append("## Per-probe error (worst-first within each zone)")
    lines.append("")
    lines.append(
        "Outliers are typically physically motivated — single-pass planetary "
        "flybys (Voyager, Pioneer), EDLs (Phoenix, MSL), or maneuver-heavy "
        "windows where the finest-intlen Chebyshev fit still exceeds the "
        "zone threshold."
    )
    lines.append("")
    lines.append(
        "| Zone | probe_id | Mission | NAIF | Samples | Median err | p95 err | Max err |"
    )
    lines.append("|---|---:|---|---:|---:|---:|---:|---:|")
    for zone_key in sorted(by_zone_probes):
        for pid, mx, p95, med, n in sorted(
            by_zone_probes[zone_key], key=lambda r: -r[1]
        ):
            mission, naif_id = probe_id_to_naif.get(pid, ("?", 0))
            lines.append(
                f"| `{zone_key}` | `{pid}` | {mission} | {naif_id} | "
                f"{n} | {_format_err(med)} | {_format_err(p95)} | {_format_err(mx)} |"
            )
    lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
