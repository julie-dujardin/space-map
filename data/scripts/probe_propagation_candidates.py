"""Verdict table/JSON for the propagation detector — read-only.

Run from data/:
    uv run python scripts/probe_propagation_candidates.py
    uv run python scripts/probe_propagation_candidates.py --stale-yr 0.5 --hill-mult 5
    uv run python scripts/probe_propagation_candidates.py --candidates-only
    uv run python scripts/probe_propagation_candidates.py --format json > out.json
"""

import argparse
import datetime
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

import spiceypy

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "data" / "src"))

from space_map_data.probes.propagation import (  # noqa: E402
    Candidate,
    PropagationConfig,
    detect_all,
)


def _et_to_utc(et: float) -> str:
    return (
        datetime.datetime(2000, 1, 1, 12, 0, 0) + datetime.timedelta(seconds=et)
    ).strftime("%Y-%m-%d")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    p.add_argument("--stale-yr", type=float, default=0.5)
    p.add_argument("--hill-mult", type=float, default=5.0)
    p.add_argument("--candidates-only", action="store_true")
    p.add_argument("--format", choices=("table", "json"), default="table")
    return p.parse_args()


def _print_table(cands: list[Candidate]) -> None:
    rows = sorted(cands, key=lambda c: (c.verdict, -c.stale_yr))
    counts = {
        v: sum(1 for c in rows if c.verdict == v)
        for v in {
            "PROPAGATE_HYP",
            "PROPAGATE_HELIO",
            "PROPAGATE_FORCED_ON",
            "SKIP_FRESH",
            "SKIP_IN_SOI",
            "SKIP_VETOED",
            "SKIP_FORCED_OFF",
        }
    }
    print(
        f"\n{len(rows)} spacecraft scanned. "
        + " ".join(f"{k}={v}" for k, v in counts.items() if v)
        + "\n"
    )
    hdr = (
        f"| {'Verdict':<20}| {'Mission':<14}| {'NAIF':>5} | {'Name':<26}| "
        f"{'COSPAR':<10}| {'End UTC':<10}| {'Stale yr':>8} | "
        f"{'r_AU':>6} | {'v km/s':>6} | {'Regime':<13}| "
        f"{'Nearest planet':<16}| {'Events status':<15}|"
    )
    print(hdr)
    print("|" + "-" * (len(hdr) - 2) + "|")
    for c in rows:
        d_hill = c.nearest_dist_km / c.nearest_hill_km if c.nearest_hill_km else 0
        near = f"{c.nearest_planet} ({d_hill:.1f}rH)"
        print(
            f"| {c.verdict:<20}| {c.mission:<14}| {c.naif:>5d} | "
            f"{c.name[:26]:<26}| {(c.cospar or '-'):<10}| {_et_to_utc(c.end_et):<10}| "
            f"{c.stale_yr:>8.1f} | {c.r_sun_au:>6.2f} | {c.v_kms:>6.2f} | "
            f"{c.regime:<13}| {near:<16}| {(c.events_status.where if c.events_status else '-'):<15}|"
        )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args()
    cfg = PropagationConfig(stale_yr=args.stale_yr, hill_mult=args.hill_mult)
    try:
        cands = detect_all(cfg)
    finally:
        spiceypy.kclear()
    if args.candidates_only:
        cands = [c for c in cands if c.is_propagate]
    if args.format == "json":
        print(json.dumps([asdict(c) for c in cands], indent=2, default=str))
    else:
        _print_table(cands)
    return 0


if __name__ == "__main__":
    sys.exit(main())
