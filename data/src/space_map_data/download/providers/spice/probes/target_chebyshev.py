"""Chebyshev ephemeris for the probe-visited small bodies.

The bodies in `probes.small_bodies` anchor a probe's metre-accurate
`small-bodies` fits, but their own positions ship as SBDB Keplerian elements
— hundreds of km out, which the probe inherits. This fits SPICE positions for
them into their own `.npz` pool, exported as an *overlay* zone: the body keeps
its element row (and with it its point-cloud dot, class membership, and
promotion state), and the segments only override where it sits.

The pool is deliberately separate from `derived/position/chebyshev`:
`probes.fit_centers.load_candidates` walks that directory, so a body landing
in it joins the interplanetary fit-center candidate set and invalidates every
cached interplanetary fit.

Segment bounds are adaptive rather than a uniform grid. Mission kernels are
Type 1/21, which carry no sub-interval length to copy, and a uniform grid fine
enough for Apophis' 2029 Earth flyby would be wasted on the other 99 years.
"""

import hashlib
import logging
from pathlib import Path

import httpx
import numpy as np
import spiceypy
from tqdm import tqdm

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader
from space_map_data.download.providers.spice.bodies.elements import (
    load_chebyshev_config,
)
from space_map_data.probes.small_bodies import SMALL_BODY_TARGET_NAIF_IDS
from space_map_data.utils.paths import DERIVED_POSITION_DIR
from space_map_data.utils.time import S_PER_DAY, et_to_jd, jd_to_et, year_to_jd

from ..naif_http import merge_intervals, spk_targets
from .layout import MISSIONS_DIR, collect_generic_kernels

logger = logging.getLogger(__name__)

TARGET_CHEBYSHEV_DIR = DERIVED_POSITION_DIR / "chebyshev-small-bodies"
# The major-body pool, whose fits win where the two overlap.
PERTURBER_CHEBYSHEV_DIR = DERIVED_POSITION_DIR / "chebyshev"

_KERNELS_ROOT = MISSIONS_DIR.parent

# SSB-relative, like every other chebyshev zone. `resolvePrimaryOverride`
# subtracts a probe's stamped fit center from its zone center and refuses the
# pair unless both sit in the same chebyshev frame — the Sun's is the SSB.
FIT_PARENT_NAIF_ID = 0

# Degree and starting interval mirror the sb441 asteroid fits, so a body whose
# source is sb441 re-interpolates its own polynomial and never subdivides.
_DEGREE = 7
_BASE_INTERVAL_S = 32 * S_PER_DAY
# Floor on subdivision. Bounds the recursion around a close approach, where no
# polynomial of this degree converges.
_MIN_INTERVAL_S = 3600.0
# Well under a pixel at any range these bodies are seen from, and small enough
# that the probe fits anchored to them keep their own accuracy.
_TOLERANCE_KM = 0.05

# SPICE cells are ~8 MB each and only reclaimed lazily, so they are allocated
# once and reset per use.
_CELL_SIZE = 10_000

# Chebyshev-Lobatto extrema on [-1, 1] and the mid-node taus the fit is scored
# at — the fit is exact at the nodes, so error has to be read between them.
_NODES_TAU = np.cos(np.pi * np.arange(_DEGREE + 1) / _DEGREE)
_TEST_TAU = 0.5 * (_NODES_TAU[:-1] + _NODES_TAU[1:])


def _coverage_windows(
    paths: list[Path], naif_id: int, cell
) -> list[tuple[float, float]]:
    """Merged `(start_et, end_et)` intervals covering `naif_id` across `paths`.

    Takes a caller-owned cell rather than calling `naif_http.spk_coverage`,
    which allocates a 200k-double cell per call — Bennu alone matches 335
    OSIRIS-REx kernels, and SPICE cells are only reclaimed lazily.
    """
    raw: list[tuple[float, float]] = []
    for path in paths:
        spiceypy.scard(0, cell)
        try:
            spiceypy.spkcov(str(path), naif_id, cell)
        except spiceypy.exceptions.SpiceyError:
            continue
        for i in range(spiceypy.wncard(cell)):
            lo, hi = spiceypy.wnfetd(cell, i)
            if hi > lo:
                raw.append((lo, hi))
    return merge_intervals(raw)


def _positions_at(naif_id: int, ets: np.ndarray) -> np.ndarray:
    """`(n, 3)` ECLIPJ2000 positions of `naif_id` relative to the fit parent."""
    target = str(naif_id)
    parent = str(FIT_PARENT_NAIF_ID)
    out = np.empty((ets.size, 3), dtype=np.float64)
    for i, et in enumerate(ets):
        position, _ = spiceypy.spkpos(target, float(et), "ECLIPJ2000", "NONE", parent)
        out[i] = position
    return out


def _fit_interval(naif_id: int, lo: float, hi: float) -> tuple[np.ndarray, float]:
    """Fit one interval and score it. Returns `(coeffs, max_error_km)`."""
    mid = 0.5 * (lo + hi)
    half = 0.5 * (hi - lo)
    nodes = _positions_at(naif_id, mid + half * _NODES_TAU)
    coeffs = np.empty((3, _DEGREE + 1), dtype=np.float64)
    for axis in range(3):
        coeffs[axis] = np.polynomial.chebyshev.chebfit(
            _NODES_TAU, nodes[:, axis], _DEGREE
        )
    truth = _positions_at(naif_id, mid + half * _TEST_TAU)
    approx = np.stack(
        [np.polynomial.chebyshev.chebval(_TEST_TAU, coeffs[axis]) for axis in range(3)],
        axis=1,
    )
    return coeffs, float(np.max(np.linalg.norm(approx - truth, axis=1)))


def _fit_recursive(
    naif_id: int,
    lo: float,
    hi: float,
    out: list[tuple[float, float, np.ndarray]],
) -> None:
    """Fit `[lo, hi)`, halving until the mid-node error clears the tolerance or
    the interval hits the floor."""
    coeffs, err = _fit_interval(naif_id, lo, hi)
    if err <= _TOLERANCE_KM or (hi - lo) <= 2 * _MIN_INTERVAL_S:
        out.append((lo, hi, coeffs))
        return
    mid = 0.5 * (lo + hi)
    _fit_recursive(naif_id, lo, mid, out)
    _fit_recursive(naif_id, mid, hi, out)


def _fit_windows(
    naif_id: int, windows: list[tuple[float, float]]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fit each coverage window on its own grid and concatenate, ascending —
    windows are sorted and the recursion emits each half in order. Fitting per
    window rather than across the whole span leaves a kernel's gaps (Itokawa
    stops in 2010) as gaps."""
    segments: list[tuple[float, float, np.ndarray]] = []
    for w_lo, w_hi in windows:
        n = max(1, int(np.ceil((w_hi - w_lo) / _BASE_INTERVAL_S)))
        edges = np.linspace(w_lo, w_hi, n + 1)
        for i in range(n):
            try:
                _fit_recursive(naif_id, float(edges[i]), float(edges[i + 1]), segments)
            except spiceypy.exceptions.SpiceyError as exc:
                logger.warning(
                    "small-body chebyshev: %d interval %.1f..%.1f failed: %s",
                    naif_id,
                    et_to_jd(edges[i]),
                    et_to_jd(edges[i + 1]),
                    exc,
                )
    if not segments:
        empty = np.empty(0, dtype=np.float64)
        return empty, empty, np.empty((0, 3, _DEGREE + 1), dtype=np.float64)
    return (
        np.array([et_to_jd(s) for s, _, _ in segments], dtype=np.float64),
        np.array([et_to_jd(e) for _, e, _ in segments], dtype=np.float64),
        np.stack([c for _, _, c in segments]),
    )


def _source_digest(paths: list[Path]) -> str:
    """Fingerprint of the kernels a body is fit from.

    The kernels shape the fit more than any knob does — a new mission SPK
    extends a target's coverage without moving the requested year range — so
    they belong in the cache key alongside the fit parameters.
    """
    parts = sorted(f"{p.name}:{p.stat().st_size}:{p.stat().st_mtime_ns}" for p in paths)
    return hashlib.sha1("\n".join(parts).encode()).hexdigest()


def _cached(
    path: Path, naif_id: int, start_et: float, end_et: float, digest: str
) -> bool:
    """Whether the on-disk npz was fit under the parameters in force now.

    Every knob that shapes the fit is compared, so tightening the tolerance,
    widening the year range or landing a new kernel refits instead of silently
    shipping the old coefficients.
    """
    if not path.exists():
        return False
    try:
        with np.load(path) as data:
            meta, params = data["meta"], data["params"]
            if data["coeffs"].dtype != np.float64:
                return False
            if str(data["sources"][0]) != digest:
                return False
    except OSError, KeyError, ValueError, IndexError:
        return False
    if meta.shape != (3,) or params.shape != (4,):
        return False
    return (
        int(meta[0]) == naif_id
        and int(meta[1]) == FIT_PARENT_NAIF_ID
        and int(meta[2]) == _DEGREE
        and abs(float(params[0]) - et_to_jd(start_et)) < 1e-6
        and abs(float(params[1]) - et_to_jd(end_et)) < 1e-6
        and float(params[2]) == _BASE_INTERVAL_S
        and float(params[3]) == _TOLERANCE_KM
    )


def extract_target_chebyshev(out_dir: Path = TARGET_CHEBYSHEV_DIR) -> int:
    """Fit and cache Chebyshev segments for every probe-visited small body.

    Writes `{out_dir}/{naif_id}.npz` in the same schema as the major-body pool.
    Returns the number of bodies with a file on disk afterwards; stale files are
    removed so the directory always reflects the current target list.
    """
    cfg = load_chebyshev_config()
    start_year, end_year = int(cfg["start_year"]), int(cfg["end_year"])
    out_dir.mkdir(parents=True, exist_ok=True)

    lsk_pck, generic_spk = collect_generic_kernels(_KERNELS_ROOT)
    if not lsk_pck:
        logger.warning("small-body chebyshev: no LSK/PCK under %s", _KERNELS_ROOT)
        return 0
    mission_spk = sorted(MISSIONS_DIR.rglob("*.bsp")) if MISSIONS_DIR.exists() else []

    kept: set[Path] = set()
    extracted = 0
    cached = 0
    uncovered: list[int] = []
    try:
        for path in lsk_pck:
            spiceypy.furnsh(str(path))
        id_cell = spiceypy.support_types.SPICEINT_CELL(_CELL_SIZE)
        win_cell = spiceypy.support_types.SPICEDOUBLE_CELL(_CELL_SIZE)

        # Ceres, Vesta and Psyche are probe targets *and* perturbers. The
        # perturber pool fits them across the whole export range, and the
        # export prefers that file, so a mission-limited refit here is work
        # thrown away.
        already_fit = {p.stem for p in PERTURBER_CHEBYSHEV_DIR.glob("*.npz")}
        targets = {n for n in SMALL_BODY_TARGET_NAIF_IDS if str(n) not in already_fit}
        sources: dict[int, list[Path]] = {n: [] for n in targets}
        for path in [*generic_spk, *mission_spk]:
            for naif_id in spk_targets(path, id_cell) & targets:
                sources[naif_id].append(path)

        # Mission kernels furnish first so the generics loaded after win any
        # target they share — the same precedence the probes exporter uses.
        generic_set = set(generic_spk)
        mission_needed = {
            p for paths in sources.values() for p in paths if p not in generic_set
        }
        for path in sorted(mission_needed):
            spiceypy.furnsh(str(path))
        for path in generic_spk:
            spiceypy.furnsh(str(path))
        logger.info(
            "small-body chebyshev: %d generic + %d mission SPKs furnished for "
            "%d targets",
            len(generic_spk),
            len(mission_needed),
            len(targets),
        )

        start_et = jd_to_et(year_to_jd(start_year))
        end_et = jd_to_et(year_to_jd(end_year))
        for naif_id in tqdm(sorted(targets), desc="Small-body Chebyshev", unit="body"):
            windows = [
                (max(lo, start_et), min(hi, end_et))
                for lo, hi in _coverage_windows(sources[naif_id], naif_id, win_cell)
                if hi > start_et and lo < end_et
            ]
            if not windows:
                uncovered.append(naif_id)
                continue

            out_path = out_dir / f"{naif_id}.npz"
            digest = _source_digest(sources[naif_id])
            if _cached(out_path, naif_id, start_et, end_et, digest):
                kept.add(out_path)
                cached += 1
                continue

            starts, ends, coeffs = _fit_windows(naif_id, windows)
            if starts.size == 0:
                logger.warning(
                    "small-body chebyshev: %d has coverage but no sampleable "
                    "interval; skipped",
                    naif_id,
                )
                continue
            np.savez(
                out_path,
                start_jds=starts,
                end_jds=ends,
                coeffs=coeffs,
                meta=np.array([naif_id, FIT_PARENT_NAIF_ID, _DEGREE], dtype=np.int64),
                # The requested range and the fit knobs, not the covered range
                # — this is what `_cached` compares against. The major-body pool
                # keeps the same first three slots.
                params=np.array(
                    [
                        et_to_jd(start_et),
                        et_to_jd(end_et),
                        _BASE_INTERVAL_S,
                        _TOLERANCE_KM,
                    ],
                    dtype=np.float64,
                ),
                sources=np.array([digest]),
            )
            logger.info(
                "small-body chebyshev: %d -> %d segments over %.1f..%.1f, "
                "shortest %.3f d",
                naif_id,
                starts.size,
                starts[0],
                ends[-1],
                float((ends - starts).min()),
            )
            kept.add(out_path)
            extracted += 1
    finally:
        spiceypy.kclear()

    removed = 0
    for existing in out_dir.glob("*.npz"):
        if existing not in kept:
            existing.unlink()
            removed += 1
    if uncovered:
        logger.warning(
            "small-body chebyshev: no SPK coverage for %s — these keep their "
            "SBDB elements",
            ", ".join(str(n) for n in uncovered),
        )
    logger.info(
        "small-body chebyshev: %d fit, %d cached, %d uncovered, %d stale removed -> %s",
        extracted,
        cached,
        len(uncovered),
        removed,
        out_dir,
    )
    return extracted + cached


class SmallBodyChebyshevDownloader(Downloader):
    """Fits Chebyshev segments for the probe-visited small bodies from kernels
    already on disk. No HTTP — it slots into the download phase so it runs
    after ProbesDownloader has fetched the target ephemerides."""

    name = PROVIDERS.SPICE_SMALL_BODY_CHEBYSHEV

    def __init__(self, client: httpx.Client) -> None:
        self.client = client  # base-class contract; unused (no HTTP)
        self.out_dir = TARGET_CHEBYSHEV_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def is_complete(self, limit: int | None) -> bool:
        # Per-body npz caching already short-circuits the expensive part.
        return False

    def download(self, limit: int | None = None, **_: object) -> None:
        count = extract_target_chebyshev()
        self._save_metadata(url="local-fit", record_count=count, complete=True)
