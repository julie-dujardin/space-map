"""The gates of the nest. Each writes its numbers to `nest-build/gates/`."""

import json
import logging

import numpy as np
from astropy import units as u
from cdshealpix import nested
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks, peak_widths

from space_map_data.dust import nest
from space_map_data.dust.disc import ratio_stats
from space_map_data.dust.encode import block_mean, encoded_dir, read_encodings
from space_map_data.dust.layers import DEPTH_EDENHOFER, Spherical
from space_map_data.dust.march import (
    CodeStack,
    LinearStack,
    Stack,
    finest_level,
    integrate,
    march,
)
from space_map_data.dust.merge import merged_dir
from space_map_data.dust.nest import LEVELS
from space_map_data.dust.parallel import forked_map
from space_map_data.dust.resample import pixels
from space_map_data.dust.sky import SKY_DIR
from space_map_data.dust.sources import BUILD_DIR, K550, atomic_npy

logger = logging.getLogger(__name__)

GATE_DIR = BUILD_DIR / "gates"
LATITUDE_BANDS = (
    (80, 90),
    (60, 80),
    (40, 60),
    (20, 40),
    (10, 20),
    (5, 10),
    (2, 5),
    (0, 2),
)
# Viewpoints in pc: the Sun, then points in level 3, level 2, level 1 and above the disc.
VIEWPOINTS = {
    "sun": (0.0, 0.0, 0.0),
    "near": (120.0, -90.0, 30.0),
    "regional": (700.0, 500.0, 100.0),
    "far": (-2000.0, 1200.0, -150.0),
    "above": (0.0, 0.0, 1500.0),
}
# O'Neill et al. 2024, section 2.2, with Pmin in mag/pc.
BUBBLE_MIN_PC = 69.0
BUBBLE_MAX_PC = 650.0
BUBBLE_SIGMA_PC = 7.0
BUBBLE_PROMINENCE = 2.04e-6 * K550
BUBBLE_THICKNESS_PC = 3.0
RAY_CHUNK = 4096
_shared = None
# Step growth per step, from 10 pc to the edge of the nest.
STEP_LAWS = ((0.18, "48 steps"), (0.1, "84 steps"), (0.03, "250 steps"))
JITTER_FRAMES = 8
FACE_POINTS = 2_000_000


def rays(depth: int) -> tuple[np.ndarray, np.ndarray]:
    """Unit vectors and latitudes in degrees of nested pixel centres."""
    lon, lat = nested.healpix_to_lonlat(
        np.arange(12 * 4**depth, dtype=np.uint64), depth
    )
    return (
        nest.directions(lon.to_value(u.rad), lat.to_value(u.rad)),
        lat.to_value(u.deg),
    )


def _decoded(variant: str, tier: str) -> dict[int, np.ndarray]:
    encodings = read_encodings(variant)
    return {
        level.index: encodings[level.index].decode(
            np.load(encoded_dir(variant) / f"l{level.index}.{tier}.npy")
        )
        for level in LEVELS
    }


def _codes(variant: str, tier: str) -> dict[int, np.ndarray]:
    return {
        level.index: np.load(encoded_dir(variant) / f"l{level.index}.{tier}.npy")
        for level in LEVELS
    }


def _over_chunks(work, shared, directions: np.ndarray, workers: int) -> list:
    """Run `work(shared, chunk, start)` over chunks of rays.

    Forked workers inherit `shared`. `start` is the index of the first ray.
    """
    global _shared
    _shared = (work, shared, directions)
    try:
        return forked_map(_chunk, range(0, len(directions), RAY_CHUNK), workers)
    finally:
        _shared = None


def _chunk(start: int):
    assert _shared is not None
    work, shared, directions = _shared
    return work(shared, directions[start : start + RAY_CHUNK], start)


def _integrated(shared, directions: np.ndarray, _start: int) -> np.ndarray:
    stacks, origin, per_voxel = shared
    return integrate(stacks, origin, directions, per_voxel)


def columns(stacks, origin, directions, workers: int, per_voxel=2.0) -> np.ndarray:
    parts = _over_chunks(_integrated, (stacks, origin, per_voxel), directions, workers)
    return np.concatenate(parts, axis=1)


def sky_gate(variant: str, workers: int) -> dict:
    """The Sun-view column against Planck and against Gaia TGE, on Nside 128."""
    depth = 7
    directions, latitude = rays(depth)
    directory = merged_dir(variant)
    observed = Stack(
        {
            level.index: np.load(
                directory / f"l{level.index}.observed.npy", mmap_mode="r"
            )
            for level in LEVELS
        }
    )
    total = CodeStack(_codes(variant, "high"), read_encodings(variant))
    nest_column, observed_column = columns(
        (total, observed), np.zeros(3), directions, workers
    )
    per_pixel = 4 ** (8 - depth)
    planck = np.load(SKY_DIR / "planck.total.npy").reshape(-1, per_pixel).mean(axis=1)
    tge = np.load(SKY_DIR / "tge.a0_550.npy")
    out = GATE_DIR / variant
    atomic_npy(out / "sky.nest.npy", nest_column.astype("f4"))
    atomic_npy(out / "sky.observed.npy", observed_column.astype("f4"))
    report = {}
    b = np.abs(latitude)
    for low, high in LATITUDE_BANDS:
        band = (b >= low) & (b < high)
        report[f"{low}-{high}"] = {
            "nest_median": round(float(np.median(nest_column[band])), 3),
            "planck_median": round(float(np.median(planck[band])), 3),
            "tge_median": round(float(np.nanmedian(tge[band])), 3),
            "tge_coverage": round(float(np.isfinite(tge[band]).mean()), 3),
            "nest_over_planck": ratio_stats(nest_column[band] / planck[band]),
            "observed_over_planck": ratio_stats(observed_column[band] / planck[band]),
            "nest_over_tge": ratio_stats(nest_column[band] / tge[band]),
            "observed_over_tge": ratio_stats(observed_column[band] / tge[band]),
        }
    return report


def _quantiles(value: np.ndarray, reference: np.ndarray) -> dict:
    """How `value` departs from `reference`. `sum_bias` weights rays by their column."""
    ratio = value / reference
    off = np.abs(ratio - 1.0)
    return {
        "bias": round(float(np.median(ratio) - 1.0), 5),
        "sum_bias": round(float(value.sum() / reference.sum() - 1.0), 5),
        "median_abs": round(float(np.median(off)), 5),
        "p95_abs": round(float(np.percentile(off, 95)), 5),
        "p99_abs": round(float(np.percentile(off, 99)), 5),
        "within_1pct": round(float((off <= 0.01).mean()), 4),
    }


def _marched(shared, directions: np.ndarray, start: int) -> np.ndarray:
    stack, origin, growth, first, per_step, seed = shared
    jitter = None
    if seed is not None:
        # A ray keeps its jitter in both tiers, and no two chunks repeat one.
        jitter = np.random.default_rng((seed, start)).random(len(directions))
    return march(stack, origin, directions, growth, first, per_step, jitter)


def marched(stack, origin, directions, workers, growth, first, per_step, seed=None):
    shared = (stack, origin, growth, first, per_step, seed)
    return np.concatenate(_over_chunks(_marched, shared, directions, workers))


def _patches(values: np.ndarray, depth_from: int, depth_to: int) -> np.ndarray:
    return values.reshape(-1, 4 ** (depth_from - depth_to)).mean(axis=1)


def _patch_gate(stacks, origin: np.ndarray, workers: int) -> dict:
    """`low` over `high` for sky patches, so both see one beam."""
    depth = 7
    directions, _ = rays(depth)
    high, low, filtered_high, filtered_low = columns(
        stacks, origin, directions, workers
    )
    report = {}
    for patch in (5, 4, 3):
        a, b = _patches(high, depth, patch), _patches(low, depth, patch)
        c, d = (
            _patches(filtered_high, depth, patch),
            _patches(filtered_low, depth, patch),
        )
        used = a > 1e-3
        report[f"nside {2**patch}"] = {
            "decoded": _quantiles(b[used], a[used]),
            "filtered": _quantiles(d[used], c[used]),
        }
    return report


def tier_gate(variant: str, workers: int) -> dict:
    """`high` against `low` on decoded R8 data, exact and as a marcher steps."""
    directions, _ = rays(5)
    encodings = read_encodings(variant)
    decoded = {tier: Stack(_decoded(variant, tier)) for tier in ("high", "low")}
    codes = {
        tier: CodeStack(_codes(variant, tier), encodings) for tier in ("high", "low")
    }
    density = {
        level.index: np.load(merged_dir(variant) / f"l{level.index}.density.npy")
        for level in LEVELS
    }
    truth = Stack(density)
    linear = LinearStack(density)
    rounded = {
        tier: Stack(
            {
                level.index: encodings[level.index].decode(
                    encodings[level.index].encode(
                        density[level.index]
                        if tier == "high"
                        else block_mean(density[level.index])
                    )
                )
                for level in LEVELS
            }
        )
        for tier in ("high", "low")
    }
    report: dict = {}
    for name, origin in VIEWPOINTS.items():
        origin = np.array(origin)
        exact, high, low, filtered_high, filtered_low, smooth, round_high, round_low = (
            columns(
                (
                    truth,
                    decoded["high"],
                    decoded["low"],
                    codes["high"],
                    codes["low"],
                    linear,
                    rounded["high"],
                    rounded["low"],
                ),
                origin,
                directions,
                workers,
            )
        )
        used = exact > 1e-3
        entry: dict = {
            "rays": int(used.sum()),
            "column_median": round(float(np.median(exact[used])), 4),
            "rounding_high": _quantiles(round_high[used], exact[used]),
            "rounding_low_over_high": _quantiles(round_low[used], round_high[used]),
            "nearest_high_over_exact": _quantiles(high[used], exact[used]),
            "nearest_low_over_high": _quantiles(low[used], high[used]),
            "filtered_high_over_exact": _quantiles(filtered_high[used], exact[used]),
            "filtered_high_over_linear": _quantiles(filtered_high[used], smooth[used]),
            "filtered_low_over_exact": _quantiles(filtered_low[used], exact[used]),
            "filtered_low_over_high": _quantiles(
                filtered_low[used], filtered_high[used]
            ),
            "linear_filter_over_exact": _quantiles(smooth[used], exact[used]),
            "sky_patches": _patch_gate(
                (decoded["high"], decoded["low"], codes["high"], codes["low"]),
                origin,
                workers,
            ),
        }
        steps = {}
        for growth, label in STEP_LAWS:
            for per_step, lod in ((None, "finest"), (1.0, "matched")):
                high_tau = marched(
                    codes["high"], origin, directions, workers, growth, 10.0, per_step
                )
                low_tau = marched(
                    codes["low"], origin, directions, workers, growth, 10.0, per_step
                )
                steps[f"{label} {lod}"] = {
                    "low_over_high": _quantiles(low_tau[used], high_tau[used]),
                    "high_over_exact": _quantiles(high_tau[used], exact[used]),
                }
        frames = {}
        for tier in ("high", "low"):
            frames[tier] = np.mean(
                [
                    marched(
                        codes[tier], origin, directions, workers, 0.18, 10.0, None, seed
                    )
                    for seed in range(JITTER_FRAMES)
                ],
                axis=0,
            )
        steps[f"48 steps jittered, {JITTER_FRAMES} frames"] = {
            "low_over_high": _quantiles(frames["low"][used], frames["high"][used]),
            "high_over_exact": _quantiles(frames["high"][used], exact[used]),
        }
        entry["marcher"] = steps
        report[name] = entry
        logger.info("tiers %s %s: %s", variant, name, entry["filtered_low_over_high"])
    return report


def _first_peak(profile: np.ndarray) -> float:
    """The distance of the first peak that O'Neill's rule accepts, or NaN."""
    peaks, props = find_peaks(profile, prominence=BUBBLE_PROMINENCE)
    if not len(peaks):
        return np.nan
    widths = peak_widths(
        profile,
        peaks,
        rel_height=0.5,
        prominence_data=(
            props["prominences"],
            props["left_bases"],
            props["right_bases"],
        ),
    )[0]
    wide = peaks[widths >= BUBBLE_THICKNESS_PC]
    return float(BUBBLE_MIN_PC + wide[0]) if len(wide) else np.nan


def _bubble_chunk(reader, directions: np.ndarray, _start: int) -> np.ndarray:
    r = np.arange(BUBBLE_MIN_PC, BUBBLE_MAX_PC, 1.0)
    profile = reader(directions, r)
    smooth = gaussian_filter1d(profile, BUBBLE_SIGMA_PC, axis=1, mode="nearest")
    return np.array([_first_peak(row) for row in smooth])


class NestProfile:
    """Density at distances along rays from the Sun, read from the nest."""

    def __init__(self, stack: Stack):
        self.stack = stack

    def __call__(self, directions: np.ndarray, r: np.ndarray) -> np.ndarray:
        points = (directions[:, None, :] * r[None, :, None]).reshape(-1, 3)
        found = finest_level(points)
        out = np.zeros(len(points), np.float32)
        for index in np.unique(found):
            chosen = found == index
            out[chosen] = self.stack.read(int(index), points[chosen])
        return out.reshape(len(directions), len(r))


class SourceProfile:
    """The same profile read from Edenhofer 2024, the control of the method."""

    def __init__(self):
        self.map = Spherical("e24")

    def __call__(self, directions: np.ndarray, r: np.ndarray) -> np.ndarray:
        lon, lat, _ = nest.lonlat(*directions.T)
        pixel = np.repeat(pixels(lon, lat, DEPTH_EDENHOFER), len(r))
        distances = np.tile(r, len(directions))
        density = self.map.density(pixel, distances)
        return density.reshape(len(directions), len(r))


def bubble_distances(reader, depth: int, workers: int) -> np.ndarray:
    directions, _ = rays(depth)
    return np.concatenate(_over_chunks(_bubble_chunk, reader, directions, workers))


def _bubble_stats(distances: np.ndarray) -> dict:
    found = distances[np.isfinite(distances)]
    return {
        "rays": len(distances),
        "with_peak": round(float(len(found) / len(distances)), 4),
        "mean": round(float(found.mean()), 1),
        "median": round(float(np.median(found)), 1),
        "p2": round(float(np.percentile(found, 2.28)), 1),
        "p98": round(float(np.percentile(found, 97.72)), 1),
    }


def bubble_gate(variant: str, workers: int, depth: int = 8) -> dict:
    """The Local Bubble shell by O'Neill's method, on decoded data and on the source."""
    stack = CodeStack(_codes(variant, "high"), read_encodings(variant))
    built = bubble_distances(NestProfile(stack), depth, workers)
    source = bubble_distances(SourceProfile(), depth, workers)
    out = GATE_DIR / variant
    atomic_npy(out / "bubble.nest.npy", built.astype("f4"))
    atomic_npy(out / "bubble.source.npy", source.astype("f4"))
    both = np.isfinite(built) & np.isfinite(source)
    return {
        "nest": _bubble_stats(built),
        "source": _bubble_stats(source),
        "median_abs_difference_pc": round(
            float(np.median(np.abs(built[both] - source[both]))), 1
        ),
    }


def _band_change(table: np.ndarray, r: np.ndarray, latitude: np.ndarray) -> dict:
    """The change of density across a window of 200 pc, centred at each distance.

    A step at a seam shows as a peak in this curve, against the rest of the curve.
    """
    width = 20
    logs = np.log10(np.maximum(table, 1e-7))
    change = np.abs(logs[:, width:] - logs[:, :-width])
    near_plane = np.abs(latitude) < 10.0
    centres = r[:-width] + 100.0
    curves = {
        "all_sky": np.median(change, axis=0),
        "under_10_deg": np.median(change[near_plane], axis=0),
    }
    out = {}
    for name, curve in curves.items():
        out[name] = {
            "median": round(float(np.median(curve)), 3),
            "max": round(float(curve.max()), 3),
            "max_at_pc": float(centres[int(curve.argmax())]),
            "at_local_band": round(
                float(curve[np.abs(centres - sum(nest.LOCAL_FADE) / 2).argmin()]), 3
            ),
            "at_regional_band": round(
                float(curve[np.abs(centres - sum(nest.REGIONAL_FADE) / 2).argmin()]), 3
            ),
        }
    return out


def seam_gate(variant: str, workers: int) -> dict:
    """Numbers at the hand-overs and at the level faces."""
    directions, latitude = rays(6)
    density = {
        level.index: np.load(merged_dir(variant) / f"l{level.index}.density.npy")
        for level in LEVELS
    }
    stack = CodeStack(_codes(variant, "high"), read_encodings(variant))
    r = np.arange(600.0, 2800.0, 10.0)
    profile = NestProfile(stack)
    table = np.concatenate(
        [
            profile(directions[start : start + RAY_CHUNK], r)
            for start in range(0, len(directions), RAY_CHUNK)
        ]
    )
    report: dict = {"density_change_across_200_pc": _band_change(table, r, latitude)}
    rng = np.random.default_rng(0)
    plain = Stack(density)
    faces = {}
    for fine, coarse in zip(LEVELS[1:], LEVELS[:-1]):
        half = np.array(fine.half)
        inside = rng.uniform(-half, half, (FACE_POINTS, 3))
        inside[:, 2] = np.clip(inside[:, 2], -coarse.half[2], coarse.half[2])
        means = [
            float(read.read(fine.index, inside).mean(dtype="f8"))
            / float(read.read(coarse.index, inside).mean(dtype="f8"))
            for read in (plain, stack)
        ]
        # Points on the faces of the fine box, where a ray changes level.
        face = rng.uniform(-half, half, (FACE_POINTS, 3))
        side = rng.integers(0, 3, FACE_POINTS)
        at = np.arange(FACE_POINTS)
        face[at, side] = np.sign(face[at, side]) * half[side] * 0.999
        face[:, 2] = np.clip(face[:, 2], -coarse.half[2], coarse.half[2])
        a, b = stack.read(fine.index, face), stack.read(coarse.index, face)
        used = (a > 1e-5) | (b > 1e-5)
        faces[f"{fine.index} in {coarse.index}"] = {
            "mean_ratio_density": round(means[0], 4),
            "mean_ratio_filtered": round(means[1], 4),
            "face_mean_ratio": round(float(a[used].mean() / b[used].mean()), 4),
            "face_median_abs_dex": round(
                float(
                    np.median(
                        np.abs(
                            np.log10(
                                np.maximum(a[used], 1e-7) / np.maximum(b[used], 1e-7)
                            )
                        )
                    )
                ),
                3,
            ),
        }
    report["level_faces"] = faces
    return report


def write_gate(variant: str, name: str, report: dict) -> None:
    path = GATE_DIR / variant / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=1))
