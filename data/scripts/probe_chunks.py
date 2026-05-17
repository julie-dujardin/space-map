"""List which probes are present in which (zone, chunk) of the export.

Walks `EXPORT_DIR/v1/position/probes/{zone}/*.meta.json`, reads the probe-id
list out of each sidecar, and prints a table grouped by zone → probe → run
of consecutive chunk indices. Date columns are derived from each zone's
`start_jd` + `chunk_years * 365.25` in the manifest.

Run from data/:
    uv run python scripts/probe_chunks.py
    uv run python scripts/probe_chunks.py --probe NEWHORIZONS
    uv run python scripts/probe_chunks.py --zone interplanetary jupiter
"""

import argparse
import datetime
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "data" / "src"))

from space_map_data.probes.probe_id import CACHE_PATH as PROBE_ID_CACHE  # noqa: E402
from space_map_data.utils.paths import EXPORT_DIR  # noqa: E402

_JD_UNIX_EPOCH = 2440587.5  # JD of 1970-01-01 00:00 UTC


def _jd_to_date(jd: float) -> str:
    dt = datetime.datetime(1970, 1, 1) + datetime.timedelta(days=jd - _JD_UNIX_EPOCH)
    return dt.strftime("%Y-%m-%d")


def _load_probe_names() -> dict[int, str]:
    """`probe_id → "MISSION/naif"` from the on-disk probe_id cache."""
    cache = json.loads(PROBE_ID_CACHE.read_text())
    return {int(r["probe_id"]): key for key, r in cache.items()}


def _collapse_runs(idxs: list[int]) -> list[tuple[int, int]]:
    """Collapse a list of ints into contiguous `(start, end_inclusive)` runs."""
    if not idxs:
        return []
    idxs = sorted(idxs)
    runs: list[list[int]] = [[idxs[0], idxs[0]]]
    for x in idxs[1:]:
        if x == runs[-1][1] + 1:
            runs[-1][1] = x
        else:
            runs.append([x, x])
    return [(a, b) for a, b in runs]


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
        "--zone",
        nargs="+",
        help="filter to specific zones (e.g. interplanetary jupiter)",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    export_v1 = args.export_dir / "v1"
    metadata_path = export_v1 / "metadata.json"
    if not metadata_path.exists():
        print(f"No manifest at {metadata_path} — run space-map-export first")
        return 1

    manifest = json.loads(metadata_path.read_text())
    zones_meta = {
        k.removeprefix("probes/"): v
        for k, v in manifest["position"]["zones"].items()
        if k.startswith("probes/")
    }
    if args.zone:
        zones_meta = {k: v for k, v in zones_meta.items() if k in args.zone}
    if not zones_meta:
        print("No probe zones in manifest (filter or empty export?)")
        return 1

    probe_name = _load_probe_names()
    name_filters = [s.lower() for s in args.probe] if args.probe else None

    # probe_id → zone → sorted list of chunk indices
    coverage: dict[int, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for zone_key in zones_meta:
        zone_dir = export_v1 / "position" / "probes" / zone_key
        if not zone_dir.exists():
            continue
        for meta_path in zone_dir.glob("*.meta.json"):
            chunk_idx = int(meta_path.stem.split(".")[0])
            try:
                data = json.loads(meta_path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            for pid_str in data.get("probes", {}):
                coverage[int(pid_str)][zone_key].append(chunk_idx)

    rows: list[tuple[str, str, int, int, int, str, str]] = []
    for pid, by_zone in coverage.items():
        name = probe_name.get(pid, f"<unknown probe_id={pid}>")
        if name_filters and not any(f in name.lower() for f in name_filters):
            continue
        for zone_key, idxs in by_zone.items():
            info = zones_meta[zone_key]
            start_jd = info["start_jd"]
            chunk_days = info["chunk_years"] * 365.25
            for a, b in _collapse_runs(idxs):
                t0 = start_jd + a * chunk_days
                t1 = start_jd + (b + 1) * chunk_days
                rows.append(
                    (name, zone_key, a, b, b - a + 1, _jd_to_date(t0), _jd_to_date(t1))
                )

    rows.sort(key=lambda r: (r[1], r[0], r[2]))
    print("| Probe (mission/naif) | Zone | Chunks | N | Start | End |")
    print("|---|---|---|---|---|---|")
    for name, zone_key, a, b, n, t0, t1 in rows:
        chunks = f"{a}" if a == b else f"{a}..{b}"
        print(f"| {name} | {zone_key} | {chunks} | {n} | {t0} | {t1} |")
    print()
    print(f"Total runs: {len(rows)}, probes shown: {len({r[0] for r in rows})}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
