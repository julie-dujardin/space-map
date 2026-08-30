"""Which curated probe events fall on a date we can draw the spacecraft at.

`probe_gaps.py` asks whether the export has a hole; this asks the question
the timeline cares about — an event the map cannot place is a date with no
craft, however good the rest of the archive is. Two failure shapes:

  * a delayed start, where the archive begins after the mission did (Galileo
    launched in 1989 and the tour kernel starts in 1995)
  * an interior gap, where the archive stops and resumes (Pioneer Venus
    Orbiter is missing for five years mid-mission)

Coverage is the union of SPK windows across every kernel the exporter
furnishes, plus the landed phases `landing_events.py` synthesises for craft
with no kernel at all — the same two sources `write_probes` draws from.

Run from data/:
    uv run python scripts/probe_event_coverage.py
    uv run python scripts/probe_event_coverage.py --min-days 30
    uv run python scripts/probe_event_coverage.py --probe Galileo Cassini
    uv run python scripts/probe_event_coverage.py --format json > out.json
"""

import argparse
import datetime
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import spiceypy

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "data" / "src"))

from space_map_data.export.position.probes.kernels import (  # noqa: E402
    collect_generic_kernels,
    enumerate_probes,
)
from space_map_data.export.position.probes.time_grid import (  # noqa: E402
    PROBE_EXPORT_END_YEAR,
)
from space_map_data.probes.events import EventProbe, events_by_probe_id  # noqa: E402
from space_map_data.probes.landing_events import load_phases  # noqa: E402
from space_map_data.probes.probe_id import load_registry  # noqa: E402
from space_map_data.probes.trace import _merged_intervals  # noqa: E402
from space_map_data.utils.paths import SOURCES_POSITION_DIR  # noqa: E402
from space_map_data.utils.time import et_to_jd, jd_to_et, year_to_jd  # noqa: E402

logger = logging.getLogger(__name__)

# Event dates are day-precision at best, and coverage bounds land mid-day, so
# a same-day miss is not a miss.
_EDGE_TOLERANCE_DAYS = 0.5


@dataclass
class Row:
    probe_id: int
    name: str
    windows: list[tuple[float, float]]
    first_event_jd: float
    n_events: int
    delayed_days: float  # coverage start minus first event; <=0 when covered
    gaps: list[tuple[float, float]] = field(default_factory=list)
    before: list[str] = field(default_factory=list)  # "date type" per event
    inside_gap: list[str] = field(default_factory=list)
    after: list[str] = field(default_factory=list)

    @property
    def n_untracked(self) -> int:
        return len(self.before) + len(self.inside_gap) + len(self.after)


def _iso(jd: float) -> str:
    return datetime.date.fromordinal(int(jd - 1721424.5)).isoformat()


def _coverage_windows(
    probe: EventProbe,
    sources: dict[int, list[tuple[str, int]]],
    kernels_by_mission: dict[str, dict[int, list[str]]],
    phases_by_probe: dict[int, list[tuple[float, float]]],
) -> list[tuple[float, float]]:
    """Every JD span the exporter could read a position from, merged."""
    spans: list[tuple[float, float]] = list(phases_by_probe.get(probe.probe_id, []))
    for mission, naif in sources.get(probe.probe_id, []):
        paths = kernels_by_mission.get(mission, {}).get(naif)
        if not paths:
            continue
        for path in paths:
            spiceypy.furnsh(path)
        try:
            spans += [
                (et_to_jd(s), et_to_jd(e)) for s, e in _merged_intervals(naif, paths)
            ]
        finally:
            for path in paths:
                spiceypy.unload(path)
    merged: list[list[float]] = []
    for s, e in sorted(spans):
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def _classify(probe: EventProbe, windows: list[tuple[float, float]]) -> Row:
    events = probe.events
    first = min(e.jd for e in events)
    row = Row(
        probe_id=probe.probe_id,
        name=probe.name,
        windows=windows,
        first_event_jd=first,
        n_events=len(events),
        delayed_days=(windows[0][0] - first) if windows else float("inf"),
    )
    if not windows:
        row.before = [f"{e.date} {e.type}" for e in events]
        return row
    start, end = windows[0][0], windows[-1][1]
    row.gaps = [
        (windows[i][1], windows[i + 1][0])
        for i in range(len(windows) - 1)
        if windows[i + 1][0] - windows[i][1] > 1.0
    ]
    for event in events:
        label = f"{event.date} {event.type}"
        if event.jd < start - _EDGE_TOLERANCE_DAYS:
            row.before.append(label)
        elif event.jd > end + _EDGE_TOLERANCE_DAYS:
            row.after.append(label)
        elif any(
            gs + _EDGE_TOLERANCE_DAYS < event.jd < ge - _EDGE_TOLERANCE_DAYS
            for gs, ge in row.gaps
        ):
            row.inside_gap.append(label)
    return row


def collect_rows() -> list[Row]:
    """One row per probe that has curated events."""
    lsk_pck, _ = collect_generic_kernels(SOURCES_POSITION_DIR / "spice-kernels")
    for path in lsk_pck:
        spiceypy.furnsh(str(path))

    sources: dict[int, list[tuple[str, int]]] = {}
    for entry in load_registry():
        for src in entry.get("kernel_sources", []):
            sources.setdefault(int(entry["probe_id"]), []).append(
                (src["mission"], int(src["naif_id"]))
            )
    kernels_by_mission: dict[str, dict[int, list[str]]] = {}
    for mdir, kernels, naif in enumerate_probes():
        kernels_by_mission.setdefault(mdir.name, {})[naif] = [str(k) for k in kernels]

    phases_by_probe: dict[int, list[tuple[float, float]]] = {}
    for phase in load_phases(jd_to_et(year_to_jd(PROBE_EXPORT_END_YEAR))):
        phases_by_probe.setdefault(phase.probe_id, []).append(
            (et_to_jd(phase.start_et), et_to_jd(phase.end_et))
        )

    rows: list[Row] = []
    for probe in events_by_probe_id().values():
        if not probe.events:
            continue
        windows = _coverage_windows(probe, sources, kernels_by_mission, phases_by_probe)
        rows.append(_classify(probe, windows))
    return rows


def _print_table(rows: list[Row], min_days: float) -> None:
    total_events = sum(r.n_events for r in rows)
    untracked = sum(r.n_untracked for r in rows)
    print(
        f"\n{len(rows)} probes with events, {total_events} events, "
        f"{untracked} on a date with no trajectory "
        f"({100 * untracked / total_events:.0f}%)\n"
    )

    delayed = sorted(
        (r for r in rows if r.windows and r.delayed_days > min_days),
        key=lambda r: -r.delayed_days,
    )
    print(f"--- delayed starts (> {min_days:.0f} days) ---")
    for r in delayed:
        print(
            f"{r.delayed_days / 365.25:7.2f}y  {r.name[:30]:<30} "
            f"events from {_iso(r.first_event_jd)}, coverage from "
            f"{_iso(r.windows[0][0])}  ({len(r.before)} events before)"
        )

    print("\n--- interior gaps (holding an event) ---")
    for r in sorted(rows, key=lambda r: r.name):
        if not r.inside_gap:
            continue
        widest = max(ge - gs for gs, ge in r.gaps)
        print(f"{r.name[:30]:<30} {len(r.gaps)} gaps, widest {widest:.0f}d")
        for label in r.inside_gap:
            print(f"    {label}")

    dark = [r for r in rows if not r.windows]
    print(f"\n--- no coverage at all: {len(dark)} probes ---")
    for r in sorted(dark, key=lambda r: r.name):
        print(f"{r.name[:30]:<30} {r.n_events} events")


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--min-days", type=float, default=1.0)
    parser.add_argument("--probe", nargs="*", default=None)
    parser.add_argument("--format", choices=("table", "json"), default="table")
    args = parser.parse_args()

    try:
        rows = collect_rows()
    finally:
        spiceypy.kclear()
    if args.probe:
        wanted = tuple(p.lower() for p in args.probe)
        rows = [r for r in rows if r.name.lower().startswith(wanted)]
    if args.format == "json":
        print(json.dumps([asdict(r) for r in rows], indent=2))
    else:
        _print_table(rows, args.min_days)
    return 0


if __name__ == "__main__":
    sys.exit(main())
