"""Survey SPK segment types across mission kernels.

For each .bsp in missions/, list per-segment (target, type, start, end).
Type 10 (SGP4/SDP4) is what the user wants to pass through as-is.
Other notable types: 1 (modified-difference arrays, old), 2/3 (Chebyshev
position/state), 9 (Lagrange unequal-spaced), 13 (Hermite).
"""

import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "data" / "src"))

import spiceypy  # noqa: E402

from space_map_data.download.providers.objects.probes import MISSIONS_DIR  # noqa: E402


def _segments(kernel: Path) -> list[tuple[int, int, float, float]]:
    """Return per-segment (target, type, start_et, end_et) tuples."""
    out: list[tuple[int, int, float, float]] = []
    try:
        handle = spiceypy.dafopr(str(kernel))
    except spiceypy.exceptions.SpiceyError:
        return out
    try:
        spiceypy.dafbfs(handle)
        while spiceypy.daffna():
            summ = spiceypy.dafgs(n=8)  # 2 doubles + 6 ints, all packed
            dc, ic = spiceypy.dafus(summ, 2, 6)
            target = int(ic[0])
            seg_type = int(ic[3])
            out.append((target, seg_type, float(dc[0]), float(dc[1])))
    finally:
        spiceypy.dafcls(handle)
    return out


def _et_to_date(et: float) -> str:
    import datetime

    return (
        datetime.datetime(2000, 1, 1, 12, 0, 0) + datetime.timedelta(seconds=et)
    ).strftime("%Y-%m-%d")


def main() -> int:
    counter: Counter[int] = Counter()
    by_type: defaultdict[int, list[tuple[str, str, int, float]]] = defaultdict(list)

    for mdir in sorted(MISSIONS_DIR.iterdir()):
        if not mdir.is_dir():
            continue
        for kernel in sorted(list(mdir.glob("*.bsp")) + list(mdir.glob("*.BSP"))):
            for target, seg_type, s, e in _segments(kernel):
                counter[seg_type] += 1
                if -999 <= target <= -1:
                    span_d = (e - s) / 86400.0
                    by_type[seg_type].append((mdir.name, kernel.name, target, span_d))

    print("=== Segment type histogram (all targets) ===")
    for t, c in sorted(counter.items()):
        print(f"  type {t:>2}: {c:>6} segments")
    print()

    for t in sorted(by_type):
        rows = by_type[t]
        print(f"=== Type {t}: {len(rows)} segments covering spacecraft ===")
        # Aggregate per (mission, kernel)
        agg: defaultdict[tuple[str, str, int], list[float]] = defaultdict(list)
        for mission, kname, naif, span_d in rows:
            agg[(mission, kname, naif)].append(span_d)
        for (mission, kname, naif), spans in sorted(agg.items())[:30]:
            total = sum(spans)
            print(
                f"  {mission:<16} {kname:<48} NAIF={naif:>5}  "
                f"{len(spans)} segments, {total:.0f} d total"
            )
        if len(agg) > 30:
            print(f"  ... +{len(agg) - 30} more")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
