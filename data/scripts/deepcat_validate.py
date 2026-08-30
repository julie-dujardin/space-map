"""Score Deep Space Catalog arcs against archive trajectories.

Every probe that has both a GCAT solar phase and a real SPK is solved blind —
the archive is never an input — and the conic is then sampled against it across
the phase. The class medians in ``deepcat_arcs.CLASS_ACCURACY_AU`` come from
this script and should be refreshed from it whenever the solver changes.

A probe whose NAIF id is reused by an older mission is skipped: the kernel
walker keys by NAIF, so the "truth" for such an object is a blend of two
spacecraft and scores nothing meaningful.

    uv run python scripts/deepcat_validate.py [--json out.json]
"""

import argparse
import collections
import json
import logging

import numpy as np
import spiceypy

from space_map_data.download.providers.spice.probes.deepcat_synth import (
    MISSION_DIR_NAME,
)
from space_map_data.export.position.probes.kernels import enumerate_probes
from space_map_data.probes.deepcat import load_deepcat
from space_map_data.probes.deepcat_arcs import ArcClass, solve_object
from space_map_data.probes.propagation import AU_KM, GM_SUN, S_PER_YEAR
from space_map_data.probes.probe_id import load_registry
from space_map_data.probes.propagation import furnish_generic_kernels
from space_map_data.probes.trace import _merged_intervals
from space_map_data.utils.paths import SOURCES_POSITION_DIR

logger = logging.getLogger(__name__)

SAMPLES = 25
# An open arc is scored over two years, not over the whole archive. The claim
# being tested is the geometry of the conic, and decades of two-body drift on a
# phase that never ends would measure nothing else.
OPEN_ARC_SCORE_YEARS = 2.0


def _truth_kernels() -> dict[int, list[str]]:
    """NAIF to archive kernels, dropping ids that more than one mission claims.

    The catalogue's own synthesised kernels are excluded: they live in the same
    tree and the walker returns them like any other, which would score this
    solver against itself and report no error at all."""
    by_naif: dict[int, list[str]] = {}
    missions: dict[int, set[str]] = collections.defaultdict(set)
    for mission_dir, kernels, naif in enumerate_probes():
        if mission_dir.name == MISSION_DIR_NAME:
            continue
        by_naif.setdefault(naif, []).extend(str(k) for k in kernels)
        missions[naif].add(mission_dir.name)
    for naif, names in missions.items():
        if len(names) > 1:
            logger.info("skipping NAIF %d, claimed by %s", naif, sorted(names))
            by_naif.pop(naif, None)
    return by_naif


def _sample_error_au(
    naif: int, merged: list[tuple[float, float]], arc, end_et: float | None
) -> tuple[float, float, float] | None:
    """Median and worst position error over the arc, plus the days scored.

    The caller owns the kernel pool: the kernels depend on the probe, not the
    arc, and furnishing them per arc costs a second `spkcov` sweep over as many
    as 417 files."""
    if not merged:
        return None
    start = max(arc.start_et, merged[0][0])
    stop = end_et if end_et is not None else start + OPEN_ARC_SCORE_YEARS * S_PER_YEAR
    stop = min(stop, merged[-1][1])
    if stop <= start:
        return None
    seed = np.array(list(arc.solution.state_km_kms))
    errors = []
    for t in np.linspace(start, stop, SAMPLES):
        if not any(lo <= t <= hi for lo, hi in merged):
            continue
        try:
            state, _ = spiceypy.spkezr(str(naif), t, "ECLIPJ2000", "NONE", "10")
        except spiceypy.exceptions.SpiceyError:
            continue
        predicted = np.asarray(
            spiceypy.prop2b(GM_SUN, seed, t - arc.solution.epoch_et), dtype=float
        )
        errors.append(float(np.linalg.norm(predicted[:3] - np.asarray(state)[:3])))
    if not errors:
        return None
    return (
        float(np.median(errors)) / AU_KM,
        float(np.max(errors)) / AU_KM,
        (stop - start) / 86400.0,
    )


def _score_arcs(
    naif: int, merged: list[tuple[float, float]], arcs, name: str, deep_id: str
) -> list[dict]:
    """Score every arc of one probe against its archive coverage."""
    out: list[dict] = []
    for arc in arcs:
        measured = _sample_error_au(naif, merged, arc, arc.end_et)
        if measured is None:
            continue
        median_au, max_au, span_d = measured
        out.append(
            {
                "deep_id": deep_id,
                "name": name,
                "phase": arc.phase,
                "class": arc.arc_class.value,
                "anchor": arc.anchor_body,
                "arrival": arc.arrival_body,
                "vinf_kms": round(arc.solution.vinf_kms, 2),
                "miss_hill": round(arc.miss_hill, 2) if arc.miss_hill else None,
                "span_d": round(span_d, 1),
                "err_median_au": round(median_au, 4),
                "err_max_au": round(max_au, 4),
            }
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", help="write the per-arc scores here")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    objects, phases = load_deepcat()
    by_object: dict[str, list] = collections.defaultdict(list)
    for phase in phases:
        by_object[phase.deep_id].append(phase)

    registry = load_registry()
    by_norad = {
        int(e["norad_cat_id"]): e for e in registry if e.get("norad_cat_id") is not None
    }

    furnish_generic_kernels(SOURCES_POSITION_DIR / "spice-kernels")
    truth = _truth_kernels()

    scored: list[dict] = []
    rejected_counts: collections.Counter = collections.Counter()
    for deep_id, obj in sorted(objects.items()):
        arcs, rejected = solve_object(obj, by_object[deep_id])
        rejected_counts.update(r.reason for r in rejected)
        entry = by_norad.get(obj.norad_id) if obj.norad_id else None
        if entry is None:
            continue
        naif = entry.get("naif_id")
        if not isinstance(naif, int):
            continue
        kernels = truth.get(naif)
        if not kernels:
            continue
        for path in kernels:
            spiceypy.furnsh(path)
        try:
            merged = _merged_intervals(naif, kernels)
            scored.extend(_score_arcs(naif, merged, arcs, entry["name"], deep_id))
        finally:
            for path in kernels:
                spiceypy.unload(path)
    spiceypy.kclear()

    print(f"\nscored {len(scored)} arcs against archive trajectories\n")
    for arc_class in ArcClass:
        errs = [s["err_median_au"] for s in scored if s["class"] == arc_class.value]
        if not errs:
            continue
        print(
            f"  {arc_class.value:9s} n={len(errs):3d}  "
            f"median {np.median(errs):.4f} AU  "
            f"p75 {np.percentile(errs, 75):.4f}  "
            f"p90 {np.percentile(errs, 90):.4f}  "
            f"max {max(errs):.4f}"
        )
    print("\nphases declined:")
    for reason, count in rejected_counts.most_common():
        print(f"  {count:5d}  {reason}")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(scored, fh, indent=1)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
