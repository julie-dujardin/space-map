"""Measure two-body extrapolation drift against high-fidelity archive tails.

For each test probe: ablate the last ``ablation_yr`` of its SPK, propagate
from the cutoff state with SPK Type 5, sample position error vs the real
recon at offsets past the cutoff. Voyager 1/2 + New Horizons are the
canonical hyperbolic cases; Gaia / Ulysses cover bound heliocentric.

Run from data/:
    uv run python scripts/probe_propagation_validate.py
    uv run python scripts/probe_propagation_validate.py --ablation-yr 50
"""

import argparse
import logging
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import spiceypy

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "data" / "src"))

from space_map_data.download.providers.spice.probes.synthetic_index import (  # noqa: E402
    write_type5,
)
from space_map_data.export.position.probes.kernels import (  # noqa: E402
    enumerate_probes,
)
from space_map_data.probes.propagation import (  # noqa: E402
    AU_KM,
    classify_state,
    furnish_generic_kernels,
)
from space_map_data.probes.trace import _merged_intervals  # noqa: E402
from space_map_data.utils.paths import SOURCES_POSITION_DIR  # noqa: E402

logger = logging.getLogger(__name__)

S_PER_YEAR = 86400.0 * 365.25

# Short archives get filtered at runtime.
_TEST_CASES: tuple[tuple[str, int], ...] = (
    ("VOYAGER", -31),
    ("VOYAGER", -32),
    ("NEWHORIZONS", -98),
    ("HORIZONS-SYNTH", -226),  # Rosetta (heliocentric pre-impact extrap)
    ("HORIZONS-SYNTH", -227),  # Kepler
    ("GAIA", -123),
    ("LUCY", -49),
    ("PSYCHE", -255),
    ("ULYSSES", -55),
    ("SIRTF", -79),  # Spitzer
)


@dataclass
class DriftSample:
    label: str  # e.g. "+1yr"
    et_offset_yr: float
    error_km: float
    r_real_au: float


@dataclass
class CaseResult:
    mission: str
    naif: int
    regime: str
    archive_start_utc: str
    archive_end_utc: str
    cutoff_utc: str
    state_v_kms: float
    samples: list[DriftSample]


def _et_to_utc(et: float) -> str:
    return spiceypy.timout(et, "YYYY-MM-DD")


def _run_case(
    mission: str,
    naif: int,
    kpaths_full: list[str],
    ablation_yr: float,
    sample_offsets_yr: tuple[float, ...],
    tmpdir: Path,
) -> CaseResult | None:
    """Ablate this probe's tail, propagate from the cutoff, measure drift."""
    merged = _merged_intervals(naif, kpaths_full)
    if not merged:
        return None
    t_start = merged[0][0]
    t_end = merged[-1][1]
    coverage_yr = (t_end - t_start) / S_PER_YEAR
    if coverage_yr < ablation_yr + 1.0:
        logger.info(
            "skip %s/%d: archive %.1f yr < ablation %.1f yr",
            mission,
            naif,
            coverage_yr,
            ablation_yr,
        )
        return None
    cutoff_et = t_end - ablation_yr * S_PER_YEAR

    try:
        regime, state6, _, _, _, _ = classify_state(naif, cutoff_et, hill_mult=5.0)
    except spiceypy.exceptions.SpiceyError as exc:
        logger.warning(
            "skip %s/%d: classify_state at cutoff failed (%s)", mission, naif, exc
        )
        return None

    # Compare by furnishing/unloading the synth around each sample (cheaper
    # than maintaining two SPICE contexts).
    extrap_path = tmpdir / f"{mission}-{naif}-extrap.bsp"
    write_type5(
        extrap_path,
        naif,
        f"validate{naif}",
        [
            (
                tuple(float(v) for v in state6),
                cutoff_et,
                cutoff_et,
                t_end,
                f"VALIDATE {mission} {naif}",
            )
        ],
    )

    samples: list[DriftSample] = []
    for years in sample_offsets_yr:
        if years > ablation_yr:
            continue
        sample_et = cutoff_et + years * S_PER_YEAR
        try:
            real_pos, _ = spiceypy.spkpos(
                str(naif), sample_et, "ECLIPJ2000", "NONE", "10"
            )
        except spiceypy.exceptions.SpiceyError as exc:
            logger.warning(
                "skip %s/%d sample +%.1fyr: real spkpos failed (%s)",
                mission,
                naif,
                years,
                exc,
            )
            continue
        # Now furnish the extrap, look up the same ET, unload it again so
        # subsequent samples query the unaltered real-kernels pool.
        spiceypy.furnsh(str(extrap_path))
        try:
            synth_pos, _ = spiceypy.spkpos(
                str(naif), sample_et, "ECLIPJ2000", "NONE", "10"
            )
        finally:
            spiceypy.unload(str(extrap_path))
        err = float(np.linalg.norm(np.asarray(real_pos) - np.asarray(synth_pos)))
        r_au = float(np.linalg.norm(np.asarray(real_pos))) / AU_KM
        samples.append(
            DriftSample(
                label=f"+{years:.0f}yr" if years >= 1 else f"+{years:.2f}yr",
                et_offset_yr=years,
                error_km=err,
                r_real_au=r_au,
            )
        )

    return CaseResult(
        mission=mission,
        naif=naif,
        regime=regime,
        archive_start_utc=_et_to_utc(t_start),
        archive_end_utc=_et_to_utc(t_end),
        cutoff_utc=_et_to_utc(cutoff_et),
        state_v_kms=float(np.linalg.norm(state6[3:])),
        samples=samples,
    )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    p.add_argument(
        "--ablation-yr",
        type=float,
        default=20.0,
        help="years to ablate from the end of each archive (default: 20)",
    )
    p.add_argument(
        "--sample-offsets",
        type=float,
        nargs="+",
        default=[0.1, 1.0, 5.0, 10.0, 20.0, 50.0, 100.0],
        help="offsets (yr) past the cutoff to measure error at",
    )
    return p.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args()

    spice_root = SOURCES_POSITION_DIR / "spice-kernels"
    furnish_generic_kernels(spice_root)

    by_mission: dict[tuple[str, int], list[Path]] = {}
    for mdir, kernels, naif in enumerate_probes():
        by_mission[(mdir.name, naif)] = kernels

    results: list[CaseResult] = []
    try:
        with tempfile.TemporaryDirectory(prefix="probe_prop_val_") as tmp:
            tmpdir = Path(tmp)
            for mission, naif in _TEST_CASES:
                kernels = by_mission.get((mission, naif))
                if kernels is None:
                    logger.info("skip %s/%d: not in mission walker", mission, naif)
                    continue
                # Don't measure synth-vs-synth on a re-run after extrap landed.
                kpaths = [str(k) for k in kernels if not k.name.endswith("-extrap.bsp")]
                for k in kpaths:
                    spiceypy.furnsh(k)
                try:
                    r = _run_case(
                        mission,
                        naif,
                        kpaths,
                        ablation_yr=args.ablation_yr,
                        sample_offsets_yr=tuple(args.sample_offsets),
                        tmpdir=tmpdir,
                    )
                except spiceypy.exceptions.SpiceyError:
                    logger.exception("case %s/%d failed", mission, naif)
                    r = None
                finally:
                    for k in kpaths:
                        spiceypy.unload(k)
                if r is not None:
                    results.append(r)
    finally:
        spiceypy.kclear()

    if not results:
        print(
            "\nNo cases produced a result. Check the test set against on-disk archives."
        )
        return 1

    print(f"\n{len(results)} probes validated, ablation = {args.ablation_yr:.1f} yr.\n")
    print(
        f"| {'Mission':<14}| {'NAIF':>5} | {'Regime':<13}| "
        f"{'Archive end':<11}| {'Cutoff':<11}| {'v km/s':>6} | "
        + " | ".join(f"{f'+{y:g}yr':>10}" for y in args.sample_offsets)
        + " |"
    )
    print("|" + "-" * (87 + 13 * len(args.sample_offsets)) + "|")
    for r in results:
        cells: list[str] = []
        offsets = list(args.sample_offsets)
        for off in offsets:
            sample = next(
                (s for s in r.samples if abs(s.et_offset_yr - off) < 1e-6), None
            )
            if sample is None:
                cells.append(f"{'-':>10}")
            elif sample.error_km < 1.0:
                cells.append(f"{sample.error_km * 1000:>7.1f}m  ")
            elif sample.error_km < 1e6:
                cells.append(f"{sample.error_km:>8.1f}km")
            else:
                cells.append(f"{sample.error_km / AU_KM:>7.2f}AU")
        print(
            f"| {r.mission:<14}| {r.naif:>5d} | {r.regime:<13}| "
            f"{r.archive_end_utc:<11}| {r.cutoff_utc:<11}| {r.state_v_kms:>6.2f} | "
            + " | ".join(c.strip().ljust(10) for c in cells)
            + " |"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
