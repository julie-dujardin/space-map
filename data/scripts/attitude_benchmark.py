"""Benchmark exported probe-attitude chunks against SPICE truth.

For every mission with an `_attitude_index.json`, furnishes its kernels,
runs the real `extract_attitude`, then decodes the shipped `.bin.gz` chunks
with the same logic the frontend uses and compares the reconstructed
orientation against `pxform("J2000", frame)` truth.

Reports per-probe coverage, chunk count + sizes (the max chunk is what the
frontend loads per focus, since chunks fetch on demand), keyframe count,
baseline kind, and angular error (median / p95 / max), mirroring
`probe_benchmark.py` for positions.

Run from data/:
    uv run python scripts/attitude_benchmark.py
    uv run python scripts/attitude_benchmark.py --missions GAIA MRO
    uv run python scripts/attitude_benchmark.py --samples 4000 --json out.json
"""

import argparse
import datetime
import gzip
import json
import logging
import struct
import sys
import time
from pathlib import Path

import numpy as np
import spiceypy

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "data" / "src"))

from space_map_data.export.position.probes.attitude.extractor import (  # noqa: E402
    extract_attitude,
    manifest_entry,
)
from space_map_data.export.position.probes.attitude.quaternion import (  # noqa: E402
    angle_between,
    slerp,
)
from space_map_data.probes.probe_id import load_registry  # noqa: E402
from space_map_data.utils.paths import SOURCES_POSITION_DIR  # noqa: E402

KERNELS = SOURCES_POSITION_DIR / "spice-kernels"
MISSIONS = KERNELS / "missions"
LSK = KERNELS / "lsk" / "naif0012.tls"
PCK = KERNELS / "pck" / "pck00011.tpc"
J2000_JD = 2451545.0
S_PER_DAY = 86400.0
COMPONENT_SCALE = 32767.0
HEADER_SIZE = 16
KEYFRAME_SIZE = 11
RAD2DEG = 180.0 / np.pi


def iso(jd: float) -> str:
    return (
        datetime.datetime(2000, 1, 1, 12) + datetime.timedelta(days=jd - J2000_JD)
    ).strftime("%Y-%m-%d")


def furnish(mission_dir: Path, index: dict) -> None:
    spiceypy.kclear()
    spiceypy.furnsh(str(LSK))
    spiceypy.furnsh(str(PCK))
    spiceypy.furnsh(str(mission_dir / index["fk"]))
    spiceypy.furnsh(str(mission_dir / index["sclk"]))
    for name in index["ck_files"]:
        spiceypy.furnsh(str(mission_dir / name))


def decode_chunk(path: str) -> tuple[np.ndarray, np.ndarray]:
    """Decode one chunk → (jd[], residual_quat[w,x,y,z][]), mirroring the
    frontend `parseAttitudeChunk`. Quats are residuals when a baseline was fit."""
    buf = gzip.open(path, "rb").read()
    start_jd = struct.unpack_from("<d", buf, 8)[0]
    n = (len(buf) - HEADER_SIZE) // KEYFRAME_SIZE
    times: list[float] = []
    quats: list[list[float]] = []
    cursor = 0.0
    for i in range(n):
        off = HEADER_SIZE + i * KEYFRAME_SIZE
        if i > 0:
            cursor += struct.unpack_from("<f", buf, off)[0]
        times.append(start_jd + cursor / S_PER_DAY)
        idx = buf[off + 4]
        a, b, c = struct.unpack_from("<hhh", buf, off + 5)
        comps = [a / COMPONENT_SCALE, b / COMPONENT_SCALE, c / COMPONENT_SCALE]
        dropped = max(0.0, 1.0 - sum(v * v for v in comps)) ** 0.5
        q, k = [], 0
        for slot in range(4):
            if slot == idx:
                q.append(dropped)
            else:
                q.append(comps[k])
                k += 1
        quats.append(q)
    return np.array(times), np.array(quats)


def decode_chunks(out_dir: Path, files: list[dict]) -> list[dict]:
    """Decode each manifest file in order → per-chunk dict mirroring how the
    frontend holds resident chunks, tagged with its `baseline_index`."""
    chunks = []
    for f in files:
        times, quats = decode_chunk(str(out_dir / f["name"]))
        chunks.append(
            {"times": times, "quats": quats, "bi": f.get("baseline_index", 0)}
        )
    return chunks


def baseline_quat(axis: np.ndarray, rate: float, t_seconds: float) -> np.ndarray:
    half = rate * t_seconds / 2.0
    return np.array([np.cos(half), *(np.sin(half) * axis)])


def q_mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return np.array(
        [
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        ]
    )


def _file_index_for(files: list[dict], jd: float) -> int:
    """Last file whose window starts at or before `jd` (clamped) — mirrors
    `AttitudeTrack.fileIndexFor`."""
    if jd <= files[0]["start_jd"]:
        return 0
    lo, hi = 0, len(files) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if files[mid]["start_jd"] <= jd:
            lo = mid
        else:
            hi = mid
    return hi if files[hi]["start_jd"] <= jd else lo


def _sample_residual(jd: float, ci: int, chunks: list[dict]) -> np.ndarray:
    """SLERP the residual at `jd` within chunk `ci`, bridging to the next chunk
    only when it shares this chunk's baseline — mirrors `sampleChunk`."""
    chunk = chunks[ci]
    times, quats = chunk["times"], chunk["quats"]
    if jd <= times[0]:
        return quats[0]
    if jd >= times[-1]:
        nxt = chunks[ci + 1] if ci + 1 < len(chunks) else None
        if (
            nxt is not None
            and nxt["bi"] == chunk["bi"]
            and len(nxt["times"]) > 0
            and nxt["times"][0] > times[-1]
        ):
            span = nxt["times"][0] - times[-1]
            t = min(1.0, (jd - times[-1]) / span)
            return slerp(quats[-1], nxt["quats"][0], t)
        return quats[-1]
    hi = int(np.searchsorted(times, jd))
    lo = hi - 1
    span = times[hi] - times[lo]
    t = (jd - times[lo]) / span if span > 0 else 0.0
    return slerp(quats[lo], quats[hi], t)


def reconstruct(jd: float, manifest: dict, chunks: list[dict]) -> np.ndarray:
    """Full J2000→body quaternion at `jd` — pick the active chunk, SLERP its
    residual, recompose its span's baseline, exactly as `orientationAt` does."""
    ci = _file_index_for(manifest["files"], jd)
    resid = _sample_residual(jd, ci, chunks)
    baselines = manifest["baselines"]
    if baselines is None:
        return resid
    b = baselines[chunks[ci]["bi"]]
    axis = np.array(b["axis"])
    t_s = (jd - b["anchor_jd"]) * S_PER_DAY
    base = q_mul(baseline_quat(axis, b["rate_rad_s"], t_s), np.array(b["anchor"]))
    return q_mul(base, resid)


def accuracy(
    frame: str, manifest: dict, chunks: list[dict], n_samples: int
) -> tuple[float, float, float]:
    """median / p95 / max angular error (deg) of the shipped reconstruction vs
    `pxform` truth, over `n_samples` points spread across coverage."""
    test_jds = np.linspace(manifest["start_jd"], manifest["end_jd"], n_samples)
    errs = []
    for jd in test_jds:
        et = (jd - J2000_JD) * S_PER_DAY
        try:
            truth = spiceypy.m2q(spiceypy.pxform("J2000", frame, et))
        except spiceypy.exceptions.SpiceyError:
            continue
        recon = reconstruct(jd, manifest, chunks)
        errs.append(angle_between(recon, truth) * RAD2DEG)
    if not errs:
        return float("nan"), float("nan"), float("nan")  # no truth in window
    a = np.array(errs)
    return float(np.median(a)), float(np.percentile(a, 95)), float(a.max())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--missions", nargs="*", help="subset of mission dir names")
    ap.add_argument("--samples", type=int, default=3000, help="accuracy test points")
    ap.add_argument("--json", type=Path, help="also write rows as JSON here")
    args = ap.parse_args()
    logging.disable(logging.WARNING)  # silence per-file pxform-gap warnings

    registry = load_registry()
    naif_by_mission: dict[str, int] = {}
    name_by_mission: dict[str, str] = {}
    for entry in registry:
        for src in entry["kernel_sources"]:
            naif_by_mission.setdefault(src["mission"], src["naif_id"])
            name_by_mission.setdefault(src["mission"], entry["name"])

    print(
        f"{'probe':<20} {'mission':<14} {'coverage':<24} {'days':>6} {'base':>4} "
        f"{'keyframes':>9} {'chk':>3} {'total_kb':>8} {'maxchk_kb':>9} "
        f"{'med°':>6} {'p95°':>6} {'max°':>6} {'sec':>4}",
        flush=True,
    )
    print("-" * 140, flush=True)

    out_rows = []
    for index_path in sorted(MISSIONS.glob("*/_attitude_index.json")):
        mission_dir = index_path.parent
        mission = mission_dir.name
        if args.missions and mission not in args.missions:
            continue
        naif = naif_by_mission.get(mission)
        if naif is None:
            continue
        index = json.loads(index_path.read_text())
        ck_paths = [str(mission_dir / n) for n in index["ck_files"]]
        out_dir = Path(REPO_ROOT) / "data" / ".attitude_bench" / mission
        out_dir.mkdir(parents=True, exist_ok=True)
        for stale in out_dir.glob("*.bin.gz"):
            stale.unlink()

        furnish(mission_dir, index)
        t0 = time.time()
        try:
            res = extract_attitude(out_dir, ck_paths, naif * 1000, index["frame_name"])
        except Exception as exc:  # noqa: BLE001
            print(f"{mission}: extraction failed: {exc}", file=sys.stderr, flush=True)
            continue
        extract_s = time.time() - t0

        sizes = [Path(out_dir / f.name).stat().st_size for f in res.files]
        total_kb = sum(sizes) / 1024
        max_kb = (max(sizes) / 1024) if sizes else 0.0
        manifest = manifest_entry(res, frame_name=index["frame_name"])
        n_base = len(manifest["baselines"]) if manifest["baselines"] else 0
        chunks = decode_chunks(out_dir, manifest["files"])
        med, p95, mx = accuracy(index["frame_name"], manifest, chunks, args.samples)

        name = name_by_mission.get(mission, "?")[:20]
        days = res.coverage_end_jd - res.coverage_start_jd
        cov = f"{iso(res.coverage_start_jd)}..{iso(res.coverage_end_jd)}"
        base_col = str(n_base) if n_base else "—"
        print(
            f"{name:<20} {mission:<14} {cov:<24} {days:>6.0f} "
            f"{base_col:>4} {res.n_keyframes:>9} {len(res.files):>3} "
            f"{total_kb:>8.0f} {max_kb:>9.1f} {med:>6.3f} {p95:>6.3f} {mx:>6.3f} {extract_s:>4.0f}",
            flush=True,
        )
        out_rows.append(
            {
                "probe": name,
                "mission": mission,
                "start_jd": res.coverage_start_jd,
                "end_jd": res.coverage_end_jd,
                "days": days,
                "n_baselines": n_base,
                "n_keyframes": res.n_keyframes,
                "n_chunks": len(res.files),
                "total_kb": total_kb,
                "max_chunk_kb": max_kb,
                "err_med_deg": med,
                "err_p95_deg": p95,
                "err_max_deg": mx,
                "extract_s": extract_s,
            }
        )

    if args.json:
        args.json.write_text(json.dumps(out_rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
