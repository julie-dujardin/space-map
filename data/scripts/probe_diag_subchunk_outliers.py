"""Locate the worst sub-chunks per probe: when do the fits collapse?

For each (probe, zone), parse every chunk, evaluate every sub-chunk at 5
sample ETs, record (zone, probe_id, chunk_idx, subchunk_idx, t_start, max_err).
Top-30 worst sub-chunks across all probes get printed with date + method.

Run from data/:
    uv run python scripts/probe_diag_subchunk_outliers.py
    uv run python scripts/probe_diag_subchunk_outliers.py --probe-naif -123  # GAIA only
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "data" / "src"))
sys.path.insert(0, str(REPO_ROOT / "data"))

import numpy as np  # noqa: E402
import spiceypy  # noqa: E402

# Reuse the benchmark's parsing and evaluation helpers.
import scripts.probe_benchmark as pb  # noqa: E402
from space_map_data.constants.providers import PROVIDERS  # noqa: E402
from space_map_data.download.providers.spice.probes import MISSIONS_DIR  # noqa: E402
from space_map_data.export.position.probes.writer import (  # noqa: E402
    _STATIONARY_PATTERNS,
    _kernels_from_index,
)
from space_map_data.probes.probe_id import REGISTRY_PATH as PROBE_ID_CACHE  # noqa: E402


def _glob_kernels(mdir: Path) -> list[Path]:
    """Diagnostic-only: every .bsp under `mdir`, alphabetically sorted, with
    stationary patterns dropped. Matches the pre-fix `_mission_kernels` so
    we can A/B against the writer's filtered set.
    """
    return [
        k
        for k in (sorted(mdir.glob("*.bsp")) + sorted(mdir.glob("*.BSP")))
        if not any(p in k.name for p in _STATIONARY_PATTERNS)
    ]


from space_map_data.probes.zones import ZONES_BY_KEY  # noqa: E402
from space_map_data.utils.paths import DOWNLOAD_DIR, EXPORT_DIR  # noqa: E402


def _et_to_date(et):
    import datetime

    return (
        datetime.datetime(2000, 1, 1, 12, 0, 0) + datetime.timedelta(seconds=et)
    ).strftime("%Y-%m-%d")


_METHOD_NAME = {
    0: "uncov",
    1: "kpure",
    2: "kdrift",
    3: "cheb",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--probe-naif",
        type=int,
        default=None,
        help="restrict to one NAIF id (e.g. -123 for GAIA)",
    )
    ap.add_argument("--zone", default=None, help="restrict to one zone")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument(
        "--source",
        choices=["index", "glob"],
        default="index",
        help="kernel set: writer's _index.json (default) or benchmark's glob",
    )
    args = ap.parse_args()

    KR = DOWNLOAD_DIR / PROVIDERS.SPICE / "kernels"
    lsk_pck: list[Path] = []
    generic_spk: list[Path] = []
    for path in sorted(KR.rglob("*")):
        if not path.is_file():
            continue
        if any(p in {"missions", "probes"} for p in path.relative_to(KR).parts):
            continue
        suffix = path.suffix.lower()
        if suffix in (".tls", ".tpc"):
            lsk_pck.append(path)
        elif suffix == ".bsp":
            generic_spk.append(path)
    for p in lsk_pck:
        spiceypy.furnsh(str(p))

    # Build NAIF lookup.
    cache = json.loads(PROBE_ID_CACHE.read_text())
    naif_by_pid = {
        int(r["probe_id"]): (int(r["naif_id"]), r["mission"]) for r in cache.values()
    }

    # Mission kernels per probe via writer (`_kernels_from_index`) or
    # diagnostic glob.
    def mission_kernels_for(mission: str) -> list[Path]:
        mdir = MISSIONS_DIR / mission
        if args.source == "index":
            return _kernels_from_index(mdir)
        return _glob_kernels(mdir)

    # Scan probe zones.
    probes_root = EXPORT_DIR / "v1" / "position" / "probes"
    outliers: list[dict] = []
    zones = [args.zone] if args.zone else sorted(ZONES_BY_KEY)
    for zone_key in zones:
        if zone_key not in ZONES_BY_KEY:
            continue
        zone = ZONES_BY_KEY[zone_key]
        zone_dir = probes_root / zone_key
        if not zone_dir.exists():
            continue
        fit_center = zone.fit_center_naif_id
        try:
            mu = float(spiceypy.bodvrd(str(fit_center), "GM", 1)[1][0])
        except spiceypy.exceptions.SpiceyError:
            continue
        chunk_files = sorted(
            zone_dir.glob("*.bin.gz"), key=lambda p: int(p.stem.split(".")[0])
        )
        # Collect per-probe sub-chunks, wrapping each as a `_BenchSub` with
        # the resolved fit-center NAIF (a single probe can span chunks fit
        # against different centers).
        per_probe: dict[int, list[tuple[int, "pb._BenchSub"]]] = {}
        for cf in chunk_files:
            chunk_idx = int(cf.stem.split(".")[0])
            parsed = pb._parse_chunk(cf)
            for probe in parsed.probes:
                if args.probe_naif is not None:
                    naif_pair = naif_by_pid.get(probe.probe_id)
                    if not naif_pair or naif_pair[0] != args.probe_naif:
                        continue
                fit_center_naif = pb._resolve_fit_center_naif(
                    probe.fit_center_id_value,
                    probe.fit_center_id_type,
                    fit_center,
                )
                per_probe.setdefault(probe.probe_id, []).extend(
                    (
                        chunk_idx,
                        pb._BenchSub(
                            method=sub.method,
                            t_start_et=sub.t_start_et,
                            t_end_et=sub.t_end_et,
                            payload=sub.payload,
                            fit_center_naif=fit_center_naif,
                        ),
                    )
                    for sub in probe.sub_chunks
                )
        # Evaluate each sub-chunk. `mu` is resolved per sub-chunk's fit center
        # (cached) since a probe can change anchor mid-zone.
        for pid, subs in per_probe.items():
            naif_pair = naif_by_pid.get(pid)
            if not naif_pair:
                continue
            naif_id, mission = naif_pair
            mks = mission_kernels_for(mission)
            for k in mks:
                spiceypy.furnsh(str(k))
            for k in generic_spk:
                spiceypy.furnsh(str(k))
            mu_cache: dict[int, float] = {fit_center: mu}
            try:
                for chunk_idx, sub in subs:
                    if sub.fit_center_naif not in mu_cache:
                        try:
                            mu_cache[sub.fit_center_naif] = float(
                                spiceypy.bodvrd(str(sub.fit_center_naif), "GM", 1)[1][0]
                            )
                        except spiceypy.exceptions.SpiceyError:
                            continue
                    sub_mu = mu_cache[sub.fit_center_naif]
                    sample_ets = np.linspace(sub.t_start_et, sub.t_end_et, 5)
                    errs = pb._evaluate_subchunk(
                        sub,
                        naif_id,
                        sub_mu,
                        zone.float64_coeffs,
                        sample_ets,
                    )
                    if not errs:
                        continue
                    max_err = max(errs)
                    if max_err > 100.0:  # only track 100+ km outliers
                        outliers.append(
                            {
                                "zone": zone_key,
                                "probe_id": pid,
                                "naif": naif_id,
                                "mission": mission,
                                "chunk_idx": chunk_idx,
                                "method": _METHOD_NAME.get(sub.method, str(sub.method)),
                                "t_start": sub.t_start_et,
                                "max_err_km": max_err,
                            }
                        )
            finally:
                for k in reversed(generic_spk):
                    spiceypy.unload(str(k))
                for k in reversed(mks):
                    spiceypy.unload(str(k))
    outliers.sort(key=lambda r: -r["max_err_km"])
    print(
        f"\nTop {args.top} worst sub-chunks (max err > 100 km), source={args.source}:"
    )
    print(
        f"  {'zone':<14} {'naif':>5} {'mission':<14} {'chunk':>6} "
        f"{'method':<7} {'date':<12} {'max_err_km':>14}"
    )
    for r in outliers[: args.top]:
        print(
            f"  {r['zone']:<14} {r['naif']:>5} {r['mission']:<14} "
            f"{r['chunk_idx']:>6} {r['method']:<7} "
            f"{_et_to_date(r['t_start']):<12} {r['max_err_km']:>14.3e}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
