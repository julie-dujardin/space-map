"""Find time windows with no export data for a probe between its overall
start and end — holes the user would notice as the probe vanishing
mid-mission. A gap spans no chunk in the union of all zones, excludes
pre-launch/post-mission, and exceeds `--min-gap-days`.

Interplanetary alone now covers most timelines (post-FIT_VERSION 5, it
spans the full contiguous SPK interval), but the cross-zone union still
catches missions with only planet-zone cruise coverage (e.g. Juno) and
masks regressions where interplanetary loses a flyby/capture span. The
classic catch: NH's 2007-2014 hole between the Jupiter-flyby and
Pluto-approach kernels.

Run from data/:
    uv run python scripts/probe_gaps.py
    uv run python scripts/probe_gaps.py --min-gap-days 30
    uv run python scripts/probe_gaps.py --probe NEWHORIZONS VOYAGER
"""

import argparse
import datetime
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "data" / "src"))

from space_map_data.probes.probe_id import load_probe_labels  # noqa: E402
from space_map_data.utils.paths import EXPORT_DIR  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

_S_PER_DAY = 86400.0
_J2000_JD = 2451545.0
_JD_UNIX_EPOCH = 2440587.5


def _jd_to_date(jd: float) -> str:
    dt = datetime.datetime(1970, 1, 1) + datetime.timedelta(days=jd - _JD_UNIX_EPOCH)
    return dt.strftime("%Y-%m-%d")


def _load_probe_names() -> dict[int, str]:
    return load_probe_labels()


def _collect_intervals(
    export_v1: Path, zones_meta: dict[str, dict]
) -> dict[int, list[tuple[float, float, str]]]:
    """For every probe, list `(start_jd, end_jd, zone)` for every chunk it
    contributes to. Sub-chunk granularity isn't recorded in the meta sidecar
    (just probe presence per chunk), so this is per-chunk — which is the
    same granularity gaps would actually show up at since `_chunk_aligned_range`
    snaps to sub-chunk boundaries anyway."""
    out: dict[int, list[tuple[float, float, str]]] = defaultdict(list)
    for zone_key, info in zones_meta.items():
        zone_dir = export_v1 / "position" / "probes" / zone_key
        if not zone_dir.exists():
            continue
        start_jd = info["start_jd"]
        chunk_days = info["chunk_days"]
        for meta_path in zone_dir.glob("*.meta.json"):
            chunk_idx = int(meta_path.stem.split(".")[0])
            try:
                data = json.loads(meta_path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            t0 = start_jd + chunk_idx * chunk_days
            t1 = t0 + chunk_days
            for pid_str in data.get("probes", {}):
                out[int(pid_str)].append((t0, t1, zone_key))
    return out


def _merge_overlaps(
    intervals: list[tuple[float, float, str]],
) -> list[tuple[float, float, set[str]]]:
    """Merge overlapping intervals (irrespective of zone), tracking which
    zones contributed to each merged run."""
    if not intervals:
        return []
    sorted_ivs = sorted(intervals, key=lambda x: x[0])
    merged: list[tuple[float, float, set[str]]] = [
        (sorted_ivs[0][0], sorted_ivs[0][1], {sorted_ivs[0][2]})
    ]
    for s, e, z in sorted_ivs[1:]:
        last_s, last_e, last_zs = merged[-1]
        if s <= last_e:
            merged[-1] = (last_s, max(last_e, e), last_zs | {z})
        else:
            merged.append((s, e, {z}))
    return merged


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    p.add_argument(
        "--export-dir",
        type=Path,
        default=EXPORT_DIR,
        help=f"override export root (default: {EXPORT_DIR})",
    )
    p.add_argument(
        "--probe",
        nargs="+",
        help="filter to probes whose `MISSION/naif` name contains any of these "
        "substrings (case-insensitive)",
    )
    p.add_argument(
        "--min-gap-days",
        type=float,
        default=1.0,
        help="ignore gaps shorter than this many days (default: 1)",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    export_v1 = args.export_dir / "v1"
    manifest_path = export_v1 / "metadata.json"
    if not manifest_path.exists():
        logger.error("No manifest at %s — run space-map-export first", manifest_path)
        return 1

    manifest = json.loads(manifest_path.read_text())
    zones_meta = {
        k.removeprefix("probes/"): v
        for k, v in manifest["position"]["zones"].items()
        if k.startswith("probes/")
    }
    if not zones_meta:
        logger.error("No probe zones in manifest")
        return 1

    probe_name = _load_probe_names()
    name_filters = [s.lower() for s in args.probe] if args.probe else None
    per_probe = _collect_intervals(export_v1, zones_meta)

    rows: list[tuple[str, str, str, float, str]] = []
    for pid, intervals in per_probe.items():
        name = probe_name.get(pid, f"probe_id={pid}")
        if name_filters and not any(f in name.lower() for f in name_filters):
            continue
        merged = _merge_overlaps(intervals)
        if len(merged) < 2:
            continue  # zero or one merged run = no internal gaps
        for (a_start, a_end, a_zones), (b_start, b_end, b_zones) in zip(
            merged, merged[1:], strict=False
        ):
            gap_days = b_start - a_end
            if gap_days < args.min_gap_days:
                continue
            zones_label = ",".join(sorted(a_zones | b_zones))
            rows.append(
                (
                    name,
                    _jd_to_date(a_end),
                    _jd_to_date(b_start),
                    gap_days,
                    zones_label,
                )
            )

    rows.sort(key=lambda r: -r[3])
    print(f"\nFound {len(rows)} internal gap(s) ≥ {args.min_gap_days} day(s).\n")
    if not rows:
        return 0
    print("| Probe | Gap start | Gap end | Days | Zones (around gap) |")
    print("|---|---|---|---|---|")
    for name, t0, t1, days, zones in rows:
        print(f"| {name} | {t0} | {t1} | {days:.0f} | {zones} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
