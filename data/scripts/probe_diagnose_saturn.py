"""Find which Pioneer 11 Saturn sub-chunk has the worst error and decode it.

The fit-truth disagreement under different furnish orders is only 1-2 km,
so SPK precedence isn't the 1271 km residual. Drill into the actual
exported binary: locate the worst sub-chunk for Pioneer 11 in Saturn,
decode it, evaluate at sample points, and compare to SPICE truth using
the same kernel set the writer would have used.

Run from data/:
    uv run python scripts/probe_diagnose_saturn.py
"""

import gzip
import struct
import sys
from pathlib import Path

import numpy as np
import spiceypy

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "data" / "src"))

from space_map_data.export.position.format import (  # noqa: E402
    FORMAT_PROBES,
    HEADER_SIZE,
    MAGIC,
    METHOD_CHEBYSHEV,
    SUBCHUNK_HEADER_SIZE,
    VERSION,
)
from space_map_data.export.position.probes.sizing import CHEBYSHEV_DEGREE  # noqa: E402
from space_map_data.utils.paths import DOWNLOAD_DIR, EXPORT_DIR  # noqa: E402

_KERNELS = DOWNLOAD_DIR / "spice" / "kernels"
_PROBES_ROOT = EXPORT_DIR / "v1" / "position" / "probes"
_J2000_JD = 2451545.0
_S_PER_DAY = 86400.0

_NAIF_PROBE = -24
_NAIF_SATURN = 699
_PROBE_ID_PIONEER11 = 42479616


def _furnish_writer_order() -> None:
    """Same order the writer uses: generics first, then mission kernels."""
    spiceypy.kclear()
    skip = {"missions", "probes"}
    for p in sorted(_KERNELS.rglob("*")):
        if not p.is_file():
            continue
        if any(part in skip for part in p.relative_to(_KERNELS).parts):
            continue
        if p.suffix.lower() in (".bsp", ".tls", ".tpc"):
            spiceypy.furnsh(str(p))
    for p in sorted((_KERNELS / "missions" / "PIONEER11").glob("*.bsp")):
        spiceypy.furnsh(str(p))


def _furnish_benchmark_order() -> None:
    """Same order the benchmark uses: every kernel via rglob path-sorted.
    missions/ < spk/ alphabetically, so generic SPKs are last → win for
    shared targets like Saturn 699."""
    spiceypy.kclear()
    for path in sorted(_KERNELS.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in (".bsp", ".tls", ".tpc"):
            spiceypy.furnsh(str(path))


def _parse_saturn_pioneer_chunks() -> list[dict]:
    """Return [{chunk_idx, sub_start_et, sub_end_et, n_seg, coeffs}] for
    every Pioneer 11 Chebyshev sub-chunk in Saturn zone."""
    saturn_dir = _PROBES_ROOT / "saturn"
    out: list[dict] = []
    for cf in sorted(saturn_dir.glob("*.bin.gz"), key=lambda p: int(p.stem.split(".")[0])):
        chunk_idx = int(cf.stem.split(".")[0])
        data = gzip.decompress(cf.read_bytes())
        magic, ver, fmt, _, start_jd, end_jd = struct.unpack("<4sHBBdd", data[:24])
        assert magic == MAGIC and ver == VERSION and fmt == FORMAT_PROBES
        probe_count, subchunk_days = struct.unpack("<If", data[24:HEADER_SIZE])
        chunk_start_et = (start_jd - _J2000_JD) * _S_PER_DAY
        sub_s = subchunk_days * _S_PER_DAY

        off = HEADER_SIZE
        for _ in range(probe_count):
            (obj_id, _idt, _ot, _hl, _, n_sub, first_off) = struct.unpack(
                "<iBBBBHH", data[off : off + 12]
            )
            off += 12
            for i in range(n_sub):
                method, _, _, payload_len = struct.unpack(
                    "<BBHI", data[off : off + SUBCHUNK_HEADER_SIZE]
                )
                off += SUBCHUNK_HEADER_SIZE
                payload = data[off : off + payload_len]
                off += payload_len
                if obj_id != _PROBE_ID_PIONEER11 or method != METHOD_CHEBYSHEV:
                    continue
                sub_start_et = chunk_start_et + (first_off + i) * sub_s
                sub_end_et = sub_start_et + sub_s
                # All Saturn coeffs are float32 (zone.float64_coeffs = False).
                n_per_seg = 3 * (CHEBYSHEV_DEGREE + 1)
                n_seg = payload_len // (n_per_seg * 4)
                coeffs = (
                    np.frombuffer(payload, dtype=np.float32, count=n_seg * n_per_seg)
                    .reshape(n_seg, 3, CHEBYSHEV_DEGREE + 1)
                    .astype(np.float64)
                )
                out.append(
                    {
                        "chunk_idx": chunk_idx,
                        "sub_start_et": sub_start_et,
                        "sub_end_et": sub_end_et,
                        "n_seg": n_seg,
                        "coeffs": coeffs,
                    }
                )
        assert off == len(data)
    return out


def _eval_cheb(sub: dict, et: float) -> np.ndarray:
    n_seg = sub["n_seg"]
    seg_dt = (sub["sub_end_et"] - sub["sub_start_et"]) / n_seg
    seg_idx = min(int((et - sub["sub_start_et"]) / seg_dt), n_seg - 1)
    seg_start = sub["sub_start_et"] + seg_idx * seg_dt
    seg_end = seg_start + seg_dt
    tau = 2 * (et - seg_start) / (seg_end - seg_start) - 1
    return np.array(
        [
            np.polynomial.chebyshev.chebval(tau, sub["coeffs"][seg_idx, axis])
            for axis in range(3)
        ]
    )


def _scan(label: str, subs: list[dict], n_samp: int = 11) -> tuple[float, int]:
    """Sample each sub-chunk, return (max_err, worst_idx)."""
    max_err = 0.0
    worst_idx = -1
    for idx, sub in enumerate(subs):
        ets = np.linspace(sub["sub_start_et"], sub["sub_end_et"], n_samp)
        for et in ets:
            truth, _ = spiceypy.spkezr(
                str(_NAIF_PROBE), float(et), "ECLIPJ2000", "NONE", str(_NAIF_SATURN)
            )
            fitted = _eval_cheb(sub, float(et))
            e = float(np.linalg.norm(fitted - np.asarray(truth[:3])))
            if e > max_err:
                max_err = e
                worst_idx = idx
    print(f"  [{label}] max_err = {max_err:.2f} km  (sub_chunk idx={worst_idx})")
    return max_err, worst_idx


def main() -> int:
    # Parse once (file structure doesn't depend on furnish order)
    _furnish_writer_order()
    subs = _parse_saturn_pioneer_chunks()
    print(f"Pioneer 11 Saturn Chebyshev sub-chunks: {len(subs)}")

    # Compare error under both furnish orders
    print("\n=== Worst-error sweep under each furnish order ===")
    _furnish_writer_order()
    me_w, idx_w = _scan("writer order (generics→mission)", subs)
    _furnish_benchmark_order()
    me_b, idx_b = _scan("benchmark order (rglob: mission→generics)", subs)

    # Continue under benchmark order so the rest of the diagnostic uses
    # the same truth the benchmark would have seen.
    _furnish_benchmark_order()

    # For each sub-chunk, sample 11 points, compute max error against SPICE.
    n_samp = 11
    by_err: list[tuple[float, int, dict, list[tuple[float, np.ndarray, np.ndarray]]]] = []
    for sub in subs:
        ets = np.linspace(sub["sub_start_et"], sub["sub_end_et"], n_samp)
        samples = []
        max_err = 0.0
        for et in ets:
            truth, _ = spiceypy.spkezr(
                str(_NAIF_PROBE), float(et), "ECLIPJ2000", "NONE", str(_NAIF_SATURN)
            )
            truth = np.asarray(truth[:3])
            fitted = _eval_cheb(sub, float(et))
            err = float(np.linalg.norm(fitted - truth))
            samples.append((float(et), truth, fitted))
            if err > max_err:
                max_err = err
        by_err.append((max_err, sub["n_seg"], sub, samples))

    by_err.sort(reverse=True, key=lambda r: r[0])
    print(f"\nTop 5 worst sub-chunks (out of {len(by_err)}):")
    print(f"{'max_err_km':>12} {'n_seg':>6}  jd_range  (chunk_idx)")
    for max_err, n_seg, sub, _ in by_err[:5]:
        jd0 = _J2000_JD + sub["sub_start_et"] / _S_PER_DAY
        jd1 = _J2000_JD + sub["sub_end_et"] / _S_PER_DAY
        print(
            f"{max_err:>12.2f} {n_seg:>6}  jd=[{jd0:.2f}, {jd1:.2f}]  "
            f"(chunk {sub['chunk_idx']})"
        )

    print("\nDecode + truth comparison of the WORST sub-chunk:")
    max_err, n_seg, sub, samples = by_err[0]
    print(f"  sub_start_et = {sub['sub_start_et']:.1f}")
    print(f"  sub_end_et   = {sub['sub_end_et']:.1f}")
    print(f"  n_seg = {n_seg}, seg_dt = {(sub['sub_end_et']-sub['sub_start_et'])/n_seg:.1f} s")
    for et, truth, fitted in samples[::2]:
        jd = _J2000_JD + et / _S_PER_DAY
        d = fitted - truth
        print(
            f"  jd={jd:.4f}  |truth|={np.linalg.norm(truth):.1f}  "
            f"|fitted|={np.linalg.norm(fitted):.1f}  "
            f"err={np.linalg.norm(d):.2f} km  Δ={d}"
        )

    # Re-fit the same sub-chunk in isolation under the writer's kernels.
    # If our exported binary doesn't match what a fresh fit would produce
    # right now, the writer was given different inputs OR the encode/decode
    # roundtrip lost data.
    print("\nFresh fit of the same sub-chunk (isolated):")
    n_nodes = CHEBYSHEV_DEGREE + 1
    k = np.arange(n_nodes)
    nodes_tau = np.cos(np.pi * k / CHEBYSHEV_DEGREE)
    seg_dt = (sub["sub_end_et"] - sub["sub_start_et"]) / n_seg
    fresh_coeffs = np.zeros((n_seg, 3, n_nodes), dtype=np.float64)
    for s_idx in range(n_seg):
        seg_start = sub["sub_start_et"] + s_idx * seg_dt
        seg_end = seg_start + seg_dt
        mid = 0.5 * (seg_start + seg_end)
        half = 0.5 * (seg_end - seg_start)
        for ii, samp in enumerate(mid + half * nodes_tau):
            state, _ = spiceypy.spkezr(
                str(_NAIF_PROBE), float(samp), "ECLIPJ2000", "NONE", str(_NAIF_SATURN)
            )
            pos = np.asarray(state[:3])
            if ii == 0:
                positions = np.empty((n_nodes, 3))
            positions[ii] = pos
        for axis in range(3):
            fresh_coeffs[s_idx, axis] = np.polynomial.chebyshev.chebfit(
                nodes_tau, positions[:, axis], CHEBYSHEV_DEGREE
            )

    print("  Δ between exported coeffs and fresh-fit coeffs (per segment):")
    max_coeff_diff = 0.0
    for s_idx in range(n_seg):
        d = np.abs(sub["coeffs"][s_idx] - fresh_coeffs[s_idx]).max()
        if d > max_coeff_diff:
            max_coeff_diff = d
    print(f"  max |Δcoeff| across all segments = {max_coeff_diff:.6e} km")

    # Eval with fresh coeffs at the same sample points.
    print("\n  fresh-fit residual against SPICE truth:")
    for et, truth, _ in samples[::2]:
        # eval with fresh_coeffs
        seg_idx = min(int((et - sub["sub_start_et"]) / seg_dt), n_seg - 1)
        seg_start = sub["sub_start_et"] + seg_idx * seg_dt
        seg_end = seg_start + seg_dt
        tau = 2 * (et - seg_start) / (seg_end - seg_start) - 1
        fitted = np.array(
            [
                np.polynomial.chebyshev.chebval(tau, fresh_coeffs[seg_idx, axis])
                for axis in range(3)
            ]
        )
        err = np.linalg.norm(fitted - truth)
        jd = _J2000_JD + et / _S_PER_DAY
        print(f"    jd={jd:.4f}  err={err:.6f} km")

    spiceypy.kclear()
    return 0


if __name__ == "__main__":
    sys.exit(main())
