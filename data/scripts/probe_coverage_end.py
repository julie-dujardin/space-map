"""For every spacecraft on disk, report when its SPK coverage ends.

Walks `missions/*/_index.json`, calls `spkcov` per `(naif_id, kernel)` to
get the latest covered ET, converts to a UTC date, and prints rows sorted
by recency. The intent is to surface missions whose archive ends well
before today so we can decide between:

  * re-pulling agency SPKs (active operational missions)
  * augmenting with HORIZONS-SYNTH (where Horizons has fresher state)
  * propagating from the last good vector (escape trajectories where the
    spacecraft is no longer being tracked but the dynamics are simple)

Run from data/:
    uv run python scripts/probe_coverage_end.py
    uv run python scripts/probe_coverage_end.py --max-gap-days 30
    uv run python scripts/probe_coverage_end.py --no-synth
"""

import argparse
import datetime
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "data" / "src"))

from space_map_data.probes.trace import _merged_intervals  # noqa: E402
from space_map_data.utils.paths import DOWNLOAD_DIR  # noqa: E402

_S_PER_DAY = 86400.0
_J2000_UNIX = 946727935.816  # 2000-01-01 12:00:00 TDB in unix seconds (approx)


def _et_to_date(et: float) -> str:
    # ET → UTC date, good to ~1 minute (TDB-UTC drift is ~70s in 2026).
    dt = datetime.datetime(2000, 1, 1, 12, 0, 0) + datetime.timedelta(seconds=et)
    return dt.strftime("%Y-%m-%d")


def _scan_mission(mdir: Path, skip_synth: bool) -> list[dict]:
    idx_path = mdir / "_index.json"
    if not idx_path.exists():
        return []
    if skip_synth and mdir.name == "HORIZONS-SYNTH":
        return []
    try:
        idx = json.loads(idx_path.read_text())
    except (OSError, json.JSONDecodeError):
        return []

    # Per-naif name hints from the synth downloader; agency dirs fall back
    # to the mission folder name.
    name_hint: dict[int, str] = {}
    for f in idx.get("files", []):
        hint = f.get("name_horizons")
        if not hint:
            continue
        for t in f.get("targets", []):
            try:
                name_hint[int(t)] = hint
            except (TypeError, ValueError):
                pass

    targets = idx.get("targets", {})
    spacecraft = sorted(t for t in (int(s) for s in targets) if t < 0)
    if not spacecraft:
        return []

    all_kpaths = [
        str(k) for k in sorted(mdir.glob("*.bsp")) + sorted(mdir.glob("*.BSP"))
    ]
    rows: list[dict] = []
    for naif in spacecraft:
        files = targets.get(str(naif), [])
        kpaths = (
            [str(mdir / fn) for fn in files if (mdir / fn).exists()]
            if files
            else all_kpaths
        )
        if not kpaths:
            continue
        intervals = _merged_intervals(naif, kpaths)
        if not intervals:
            continue
        end_et = max(iv[1] for iv in intervals)
        start_et = min(iv[0] for iv in intervals)
        rows.append(
            {
                "mission": mdir.name,
                "naif": naif,
                "name": name_hint.get(naif) or mdir.name,
                "start_et": start_et,
                "end_et": end_et,
            }
        )
    return rows


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    p.add_argument(
        "--missions-dir",
        type=Path,
        default=DOWNLOAD_DIR / "spice" / "kernels" / "missions",
        help="override missions dir",
    )
    p.add_argument(
        "--max-gap-days",
        type=float,
        default=None,
        help="only print spacecraft whose coverage ends MORE than N days ago "
        "(i.e. potential gaps)",
    )
    p.add_argument(
        "--no-synth",
        action="store_true",
        help="exclude HORIZONS-SYNTH (so we see the agency-only state)",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    today = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    today_date = today.strftime("%Y-%m-%d")

    rows: list[dict] = []
    for mdir in sorted(args.missions_dir.iterdir()):
        if not mdir.is_dir():
            continue
        rows.extend(_scan_mission(mdir, args.no_synth))

    # Compute gap to today and sort by it descending (oldest end first).
    today_et = (today - datetime.datetime(2000, 1, 1, 12, 0, 0)).total_seconds()
    for r in rows:
        r["end_date"] = _et_to_date(r["end_et"])
        r["start_date"] = _et_to_date(r["start_et"])
        r["gap_days"] = (today_et - r["end_et"]) / _S_PER_DAY

    if args.max_gap_days is not None:
        rows = [r for r in rows if r["gap_days"] > args.max_gap_days]

    rows.sort(key=lambda r: -r["gap_days"])

    print(f"\n{len(rows)} spacecraft. Today = {today_date}.\n")
    print(
        f"| {'Mission':<18} | {'NAIF':>8} | {'Name':<38} | {'Start':<10} | {'End':<10} | {'Gap (d)':>8} |"
    )
    print(f"|{'-' * 20}|{'-' * 10}|{'-' * 40}|{'-' * 12}|{'-' * 12}|{'-' * 10}|")
    for r in rows:
        print(
            f"| {r['mission']:<18} | {r['naif']:>8} | {r['name'][:38]:<38} "
            f"| {r['start_date']:<10} | {r['end_date']:<10} | {r['gap_days']:>8.0f} |"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
