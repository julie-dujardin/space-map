"""The gates of the light grid. Each writes `gates/<name>.json` in the build directory.

Sky pixels are Nside 64 HEALPix, about 0.9 deg, in Galactic axes at the Sun. A pixel
holds four rays. Rays and true sums use the same exposure-free unit: flux of a star of
apparent magnitude 0 in a channel of 1.
"""

import functools
import json
from collections.abc import Callable
from pathlib import Path

import numpy as np

from space_map_data.dust import gates as dust_gates
from space_map_data.dust.parallel import forked_stream
from space_map_data.dust.resample import points_pixels
from space_map_data.export.extrasolar.build import served
from space_map_data.extrasolar.store import write_json
from space_map_data.glow import build, colour, deposit, form, light, march, sky_map
from space_map_data.glow.march import Textures, View
from space_map_data.utils.paths import EXTRASOLAR_DIR

BANDS = ((0, 2), (2, 5), (5, 10), (10, 20), (20, 40), (40, 60), (60, 90))
# (position in pc, limits). Limits span what the point budget allows there.
VIEWS = {
    "Sun": ((0.0, 0.0, 0.0), (7.5, 9.0)),
    "300 pc": ((-200.0, -200.0, 20.0), (9.0, 12.0)),
    "past Taurus": ((-1200.0, 126.0, -300.0), (10.0, 13.0)),
    "5 kpc to centre": ((5000.0, 500.0, 100.0), (11.0, 14.0)),
    "8 kpc above": ((0.0, 0.0, 8000.0), (14.0, 17.0)),
    "above centre": ((8000.0, 0.0, 8000.0), (14.0, 17.0)),
    "outside 30 kpc": ((-28000.0, 0.0, 6000.0), (16.0, 19.0)),
}
VIEW_DEPTH = 5


def _served[**P, R](gate: Callable[P, R]) -> Callable[P, R]:
    """Run a gate with the export held off, because it reads the served nest."""

    @functools.wraps(gate)
    def held(*args: P.args, **kwargs: P.kwargs) -> R:
        with served(EXTRASOLAR_DIR):
            return gate(*args, **kwargs)

    return held


def textures(build_dir: Path, tier: str) -> Textures:
    raw = build.read_encoding(build_dir)
    table = form.make_table(np.load(build_dir / build.CURVE))
    bits = np.load(build_dir / build.bits_name(tier))
    return Textures(build.GRIDS[tier], bits, raw["scale"], table)


def sky_flux(
    grid: Textures, nest: sky_map.Nest, view: View, depth: int, workers: int
) -> np.ndarray:
    """Flux per pixel of `depth` and channel, as the mean of four rays."""
    rays, _ = dust_gates.rays(depth + 1)
    seen = march.march_all(grid.read, nest, view, rays, workers)
    omega = 4 * np.pi / (12 * 4**depth)
    pixels = 12 * 4**depth
    of_pixel = np.arange(len(rays)) // 4
    mean = np.stack(
        [np.bincount(of_pixel, seen[:, c], pixels) / 4 for c in range(3)], axis=1
    )
    return mean * omega


def _write(build_dir: Path, name: str, result: dict) -> None:
    path = build_dir / "gates" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, result)


def weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    order = np.argsort(values)
    cumulative = np.cumsum(weights[order]) / weights.sum()
    return float(values[order][min(np.searchsorted(cumulative, q), len(values) - 1)])


def light_gate(build_dir: Path, _workers: int) -> None:
    """The grid's total against the stars, on the stored texels."""
    raw = build.read_encoding(build_dir)
    totals = json.loads((build_dir / build.TOTALS).read_text())
    stars = float(np.sum(totals["light"]))
    result: dict = {"stars": stars, "rows": totals["rows"]}
    for tier, grid in build.GRIDS.items():
        volumes = grid.volumes()
        values = np.load(build_dir / build.values_name(tier), mmap_mode="r")
        bits = np.load(build_dir / build.bits_name(tier), mmap_mode="r")
        stored = march.encode.bits_to_values(np.asarray(bits))
        used = volumes > 0
        sum_values = float(
            (np.asarray(values[..., 0], np.float64) * volumes)[used].sum()
        )
        sum_stored = float(
            (stored[..., 0].astype(np.float64) * volumes)[used].sum() / raw["scale"]
        )
        monotone = np.diff(stored[..., :-1], axis=-1).max()
        result[tier] = {
            "unrounded_over_stars": sum_values / stars,
            "stored_over_stars": sum_stored / stars,
            "nan": int(np.isnan(stored).sum()),
            "negative": int((stored < 0).sum()),
            "largest_rise_with_M": float(monotone),
            "top": float(stored[..., 0].max()),
        }
    _write(build_dir, "light", result)


@_served
def sun_gate(build_dir: Path, workers: int) -> None:
    """Grid and nest from the Sun against the observed flux of the same stars."""
    observed = np.load(build_dir / build.OBSERVED)
    nest = sky_map.load_nest()
    _, lat = dust_gates.rays(deposit.SKY_DEPTH)
    result: dict = {}
    summed = observed.sum(axis=1)
    for tier in build.GRIDS:
        grid = textures(build_dir, tier)
        seen = sky_flux(
            grid, nest, View(np.zeros(3), deposit.SUN_LIMIT), deposit.SKY_DEPTH, workers
        )
        atomic = build_dir / f"sun_sky.{tier}.npy"
        np.save(atomic, seen)
        ratio = seen.sum(axis=1) / np.maximum(summed, 1e-300)
        rows = []
        for low, high in BANDS:
            use = (np.abs(lat) >= low) & (np.abs(lat) < high) & (summed > 0)
            rows.append(
                {
                    "band": [low, high],
                    "pixels": int(use.sum()),
                    "median": float(np.median(ratio[use])),
                    "p10": float(np.percentile(ratio[use], 10)),
                    "p90": float(np.percentile(ratio[use], 90)),
                    "summed": float(seen[use].sum() / observed[use].sum()),
                    "blue_red_mag": float(
                        2.5
                        * np.log10(
                            (seen[use, 2].sum() / seen[use, 0].sum())
                            / (observed[use, 2].sum() / observed[use, 0].sum())
                        )
                    ),
                }
            )
        result[tier] = rows
    _write(build_dir, "sun", result)


# Forked workers read these.
_sample: np.ndarray | None = None
_origin: np.ndarray | None = None
_limit = 0.0
_sky: np.ndarray | None = None
SAMPLE_CHUNK = 2_000_000
SUMS = ("grid_rule", "shader_rule", "past_cap_grid", "past_cap_shader")


def _true_chunk(chunk: slice) -> np.ndarray:
    """The sums of one chunk, shape (4, pixels, 3), in the order of SUMS."""
    assert _sample is not None and _origin is not None and _sky is not None
    rows = np.asarray(_sample[chunk], np.float64)
    points, mag, bp_rp, column, weight = (
        rows[:, :3],
        rows[:, 3],
        rows[:, 4],
        rows[:, 5],
        rows[:, 6],
    )
    pixels = 12 * 4**VIEW_DEPTH
    offset = points - _origin
    s = np.maximum(np.linalg.norm(offset, axis=1), 1e-6)
    camera = sky_map.read_map(_sky, _origin, offset).astype(np.float64)
    bound = light.dust_bound(bp_rp, mag)
    taken = np.minimum(column, bound)
    m0 = light.dust_free_magnitude(mag, taken)
    modulus = 5 * np.log10(s / 10)
    tint = colour.star_colours(bp_rp) * weight[:, None]
    grid_side = m0 > _limit - modulus - light.K_G * camera
    flux = light.star_flux(mag, tint, taken)
    seen = flux * 10.0 ** (
        -0.4 * (light.K_RGB[None] * camera[:, None] + modulus[:, None])
    )
    # The shader's rule: the change of column, bound by the star's bound.
    dust = np.maximum(camera - column, -bound)
    shader_side = mag + modulus + light.K_G * dust > _limit
    own = tint * 10.0 ** (
        -0.4 * ((mag + modulus)[:, None] + light.K_RGB[None] * dust[:, None])
    )
    past_cap = column > taken
    pixel = points_pixels(offset, VIEW_DEPTH)

    def per_pixel(mask: np.ndarray, values: np.ndarray) -> np.ndarray:
        return np.stack(
            [np.bincount(pixel[mask], values[mask, c], pixels) for c in range(3)],
            axis=1,
        )

    return np.stack(
        (
            per_pixel(grid_side, seen),
            per_pixel(shader_side, own),
            per_pixel(grid_side & past_cap, seen),
            per_pixel(shader_side & past_cap, own),
        )
    )


def true_sums(
    sample: np.ndarray, origin: np.ndarray, limit: float, sky: np.ndarray, workers: int
) -> dict[str, np.ndarray]:
    """Per pixel of the view: the sum by the grid's rule, and by the shader's rule with
    the colour cap. The two differ only for stars past the cap."""
    global _sample, _origin, _limit, _sky
    chunks = [
        slice(at, at + SAMPLE_CHUNK) for at in range(0, len(sample), SAMPLE_CHUNK)
    ]
    total = np.zeros((len(SUMS), 12 * 4**VIEW_DEPTH, 3))
    _sample, _origin, _limit, _sky = sample, origin, limit, sky
    try:
        for part in forked_stream(_true_chunk, chunks, workers):
            total += part
    finally:
        _sample = _origin = _sky = None
        _limit = 0.0
    return dict(zip(SUMS, total, strict=True))


@_served
def cut_gate(build_dir: Path, workers: int) -> None:
    """The grid's fainter-than-cut sum against the true sum of a star sample."""
    sample = np.load(build_dir / build.SAMPLE, mmap_mode="r")
    nest = sky_map.load_nest()
    result: dict = {}
    tiers = {tier: textures(build_dir, tier) for tier in build.GRIDS}
    for name, (position, limits) in VIEWS.items():
        origin = np.array(position)
        sky = sky_map.build_map(nest, origin, workers)
        for limit in limits:
            sums = true_sums(sample, origin, limit, sky, workers)
            truth = sums["grid_rule"]
            summed = truth.sum(axis=1)
            row = {
                "shader_rule_over_grid_rule": float(
                    sums["shader_rule"].sum() / truth.sum()
                ),
                "past_cap_share_grid_rule": float(
                    sums["past_cap_grid"].sum() / truth.sum()
                ),
                "past_cap_share_shader_rule": float(
                    sums["past_cap_shader"].sum() / sums["shader_rule"].sum()
                ),
            }
            for tier, grid in tiers.items():
                seen = sky_flux(grid, nest, View(origin, limit), VIEW_DEPTH, workers)
                use = summed > 0
                error = np.abs(seen.sum(axis=1)[use] / summed[use] - 1)
                row[tier] = {
                    "total": float(seen.sum() / truth.sum()),
                    "median_error": weighted_quantile(error, summed[use], 0.5),
                    "p90_error": weighted_quantile(error, summed[use], 0.9),
                    "blue_red_mag": float(
                        2.5
                        * np.log10(
                            (seen[:, 2].sum() / seen[:, 0].sum())
                            / (truth[:, 2].sum() / truth[:, 0].sum())
                        )
                    ),
                }
            result[f"{name} U={limit:g}"] = row
    _write(build_dir, "cut", result)


@_served
def tier_gate(build_dir: Path, workers: int) -> None:
    """Light of `low` over `high`, per sky band, from three views."""
    nest = sky_map.load_nest()
    high = textures(build_dir, "high")
    low = textures(build_dir, "low")
    _, lat = dust_gates.rays(VIEW_DEPTH)
    result: dict = {}
    for name, origin, limit in (
        ("Sun", np.zeros(3), deposit.SUN_LIMIT),
        ("300 pc", np.array(VIEWS["300 pc"][0]), 12.0),
        ("8 kpc above", np.array(VIEWS["8 kpc above"][0]), 14.0),
    ):
        view = View(origin, limit)
        seen_high = sky_flux(high, nest, view, VIEW_DEPTH, workers).sum(axis=1)
        seen_low = sky_flux(low, nest, view, VIEW_DEPTH, workers).sum(axis=1)
        rows = []
        for lower, upper in BANDS:
            use = (np.abs(lat) >= lower) & (np.abs(lat) < upper)
            rows.append(
                {
                    "band": [lower, upper],
                    "summed": float(seen_low[use].sum() / seen_high[use].sum()),
                    "median_pixel": float(
                        np.median(seen_low[use] / np.maximum(seen_high[use], 1e-300))
                    ),
                }
            )
        result[name] = {
            "all_sky": float(seen_low.sum() / seen_high.sum()),
            "bands": rows,
        }
    _write(build_dir, "tiers", result)
