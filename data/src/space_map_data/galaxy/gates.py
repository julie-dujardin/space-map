"""The gates of the model light. Each writes its numbers to `<build>/gates/`."""

import gzip
import itertools
import json
import logging
from pathlib import Path

import numpy as np

from space_map_data.extrasolar.store import write_json
from space_map_data.galaxy import build, calibrate, model, photometry, residual, sources
from space_map_data.galaxy.geometry import R0
from space_map_data.galaxy.model import Model
from space_map_data.galaxy.volumes import TIERS, Box

logger = logging.getLogger(__name__)

# Lian et al. 2024, and the targets the report sets beside it.
LIAN_HALF_LIGHT_PC = (5750.0, 380.0)
FLYNN_SIGMA_V = 24.4
TARGET_M_V = -21.4
TARGET_G_R = (0.68, 0.72)
TARGET_B_V = 0.73
# Lian's profile ends at 17 kpc (their R0 = 8.2 kpc).
LIAN_REACH_PC = 17_000.0 * R0 / sources.LIAN_R0
RING_STEP_PC = 50.0
RING_REACH_PC = 30_000.0
AZIMUTHS = 96
EXCESS_SHARE = 0.5


def _heights() -> np.ndarray:
    """Heights for an integral through the disc, dense at the plane."""
    half = 2.0 * np.sinh(np.linspace(0.0, np.arcsinh(15_000.0 / 2.0), 400))
    return np.concatenate((-half[:0:-1], half))


def face_on_rings(m: Model, names) -> dict[str, dict[str, np.ndarray]]:
    """Per component, the light in each ring about the centre, in G and V flux."""
    edges = np.arange(0.0, RING_REACH_PC + RING_STEP_PC, RING_STEP_PC)
    middle = 0.5 * (edges[1:] + edges[:-1])
    angle = (np.arange(AZIMUTHS) + 0.5) / AZIMUTHS * 2 * np.pi
    R, A = np.meshgrid(middle, angle, indexing="ij")
    x, y = R0 + R.ravel() * np.cos(A.ravel()), R.ravel() * np.sin(A.ravel())
    heights = _heights()
    dz = np.gradient(heights)
    area = np.pi * np.diff(edges**2)
    out = {
        name: {"G": np.zeros(len(middle)), "V": np.zeros(len(middle))} for name in names
    }
    for h, step in zip(heights, dz, strict=True):
        z = np.full(len(x), h - 21.0)
        for name, density in m.densities(x, y, z, names).items():
            column = density.reshape(len(middle), AZIMUTHS).mean(axis=1) * step
            bp = (
                np.interp(middle, m.radius, m.thin_bp_rp)
                if name == "thin"
                else m.bp_rp[name]
            )
            out[name]["G"] += column * area
            out[name]["V"] += (
                column * area * 10.0 ** (0.4 * photometry.gaia_minus_v(bp))
            )
    out["_edges"] = {"G": edges, "V": edges}
    return out


def half_light(rings: dict, names, band: str, reach: float) -> float:
    edges = rings["_edges"][band]
    total = sum(rings[name][band] for name in names)
    keep = edges[1:] <= reach
    cumulative = np.cumsum(total[keep])
    return float(np.interp(0.5 * cumulative[-1], cumulative, edges[1:][keep]))


def lian_half_light(values: np.ndarray) -> float:
    """The half-light radius of a Lian profile as their method takes it: linear
    between ring centres on 10 pc steps."""
    lian = sources.lian_profiles()
    fine = np.arange(0.0, lian.edges[-1], 10.0)
    sigma = np.interp(fine, lian.radius, values)
    light = np.cumsum(2 * np.pi * fine * sigma * 10.0)
    return float(np.interp(0.5 * light[-1], light, fine))


def band_totals(m: Model, rings: dict, names) -> dict:
    """Absolute magnitudes and colours of the summed light of `names`."""
    flux = {band: 0.0 for band in ("G", "V", "B", "g", "r")}
    for name in names:
        if name in rings:
            g_flux = rings[name]["G"]
            bp = (
                np.interp(
                    0.5 * (rings["_edges"]["G"][1:] + rings["_edges"]["G"][:-1]),
                    m.radius,
                    m.thin_bp_rp,
                )
                if name == "thin"
                else np.full(len(g_flux), m.bp_rp[name])
            )
        else:
            g_flux, bp = np.array([m.flux[name]]), np.array([m.bp_rp[name]])
        offsets = photometry.band_magnitudes(np.zeros(len(bp)), bp)
        for band in flux:
            flux[band] += float((g_flux * 10.0 ** (-0.4 * offsets[band])).sum())
    mags = {band: -2.5 * np.log10(value) for band, value in flux.items()}
    return {
        "M_G": mags["G"],
        "M_V": mags["V"],
        "L_V_sun": 10.0 ** (-0.4 * (mags["V"] - photometry.SUN_V)),
        "g_r": mags["g"] - mags["r"],
        "B_V": mags["B"] - mags["V"],
    }


def galaxy_gate(out: Path, glow_dir: Path, far_side: float) -> None:
    """Gates 1 to 3: half-light radius, the column at the Sun, the whole Galaxy."""
    m = Model.load(out / calibrate.CALIBRATION, far_side)
    disc_names = (*model.DISC, *model.CENTRE, "halo")
    rings = face_on_rings(m, disc_names)
    lian_like = (*model.DISC, "bulge", "bar", "superthin")
    lian = sources.lian_profiles()
    half = {
        band: {
            "as_lian_to_17_kpc": half_light(rings, lian_like, band, LIAN_REACH_PC),
            "with_nuclear_disc": half_light(
                rings, (*lian_like, "nsd", "nsc"), band, LIAN_REACH_PC
            ),
            "all_to_30_kpc": half_light(rings, disc_names, band, RING_REACH_PC),
        }
        for band in ("G", "V")
    }
    half["lian_files"] = {
        "bolometric": lian_half_light(lian.bolometric),
        "r": lian_half_light(lian.r),
        "H": lian_half_light(lian.h),
    }
    column = json.loads((out / calibrate.COLUMN).read_text())
    parts = calibrate.model_column(m, (*model.DISC, *model.CENTRE, "halo"))
    model_g = sum(part["g"] for part in parts.values())
    model_rgb = sum(part["rgb"] for part in parts.values())
    bp_model = float(photometry.bp_rp_of_display(model_rgb))
    bp_cat = column["column_bp_rp"]

    def to_v(flux_g: float, bp: float) -> float:
        flux_v = flux_g * 10.0 ** (0.4 * photometry.gaia_minus_v(bp))
        return float(flux_v / 10.0 ** (-0.4 * photometry.SUN_V))

    lian_r_sun = float(np.interp(R0, lian.radius, lian.r))
    local = {
        "catalogue_g_per_pc2": column["column_g_per_pc2"],
        "model_g_per_pc2": model_g,
        "catalogue_l_v_per_pc2": to_v(column["column_g_per_pc2"], bp_cat),
        "model_l_v_per_pc2": to_v(model_g, bp_model),
        "flynn_l_v_per_pc2": FLYNN_SIGMA_V,
        "lian_r_at_sun_l_r_per_pc2": lian_r_sun,
        "column_height_pc": calibrate.COLUMN_HEIGHT_PC,
        "model_bp_rp": bp_model,
        "catalogue_bp_rp": bp_cat,
        "share_by_component": {k: v["g"] / model_g for k, v in parts.items()},
    }
    everything = band_totals(m, rings, disc_names)
    by_component = {name: band_totals(m, rings, (name,)) for name in disc_names}
    clouds = {name: band_totals(m, rings, (name,)) for name in ("lmc", "smc")}
    result = {
        "half_light_pc": half,
        "half_light_target_pc": LIAN_HALF_LIGHT_PC,
        "local": local,
        "galaxy": everything,
        "galaxy_targets": {"M_V": TARGET_M_V, "g_r": TARGET_G_R, "B_V": TARGET_B_V},
        "components": by_component,
        "clouds": clouds,
        "far_side": far_side,
    }
    write_json(out / "gates" / "galaxy.json", result)
    logger.info("galaxy: R_half %s, M_V %.2f", half["G"], everything["M_V"])


def _tint_bp(rgb: np.ndarray) -> np.ndarray:
    return photometry.bp_rp_of_display(np.maximum(rgb, 1e-30))


def form_gate(out: Path, glow_dir: Path, far_side: float, workers: int = 8) -> None:
    """The stored form: one channel with colour from the table, against RGBA16F at
    the same bytes. Errors against the residual of each voxel at full resolution."""
    table = np.array(json.loads((out / build.TABLE_FILE).read_text())["rgb"])
    box = TIERS["high"]["inner"]
    baked = np.load(out / build.bake_name("inner"))
    model_rgb, cat_rgb = baked[..., :3], baked[..., 3:6]
    sigma = build.COMPARE_SIGMA["inner"]
    light = build.residual_light(model_rgb, cat_rgb, box, sigma)
    weight = light.reshape(-1)
    centres = residual.voxel_centres(box)
    truth_bp = _tint_bp(model_rgb.reshape(-1, 3))
    single_bp = _tint_bp(residual.table_colour(table, centres))
    used = weight > 0
    w = weight[used] / weight[used].sum()
    single_error = np.abs(single_bp - truth_bp)[used]
    # RGBA16F at the same bytes: half the texels in x and y, each channel clamped.
    half_xy = (
        model_rgb.reshape(256, 2, 256, 2, 32, 3).mean(axis=(1, 3)),
        cat_rgb.reshape(256, 2, 256, 2, 32, 3).mean(axis=(1, 3)),
    )
    half_box = Box(box.half, (256, 256, box.size[2]), box.z_scale)
    rgba = np.stack(
        [
            half_xy[0][..., c]
            * np.maximum(
                1.0
                - build.catalogue_ratio(
                    half_xy[0][..., c], half_xy[1][..., c], half_box, (1.0, 1.0, sigma)
                ),
                0.0,
            )
            for c in range(3)
        ],
        axis=-1,
    )
    rgba_light = rgba.sum(-1)
    up = np.repeat(np.repeat(rgba, 2, axis=0), 2, axis=1).reshape(-1, 3)
    rgba_bp = _tint_bp(up)
    clamped = (half_xy[0] < half_xy[1]).sum(-1)
    partial = (clamped > 0) & (clamped < 3)
    light_up = np.repeat(np.repeat(rgba_light, 2, axis=0), 2, axis=1).reshape(-1)
    rgba_error = np.abs(rgba_bp - truth_bp)[used]
    single_bits = np.load(out / build.bits_name("inner", "high"))
    sizes = {
        "single_r16f_mib": single_bits.nbytes / 2**20,
        "single_r16f_gzip_mb": len(gzip.compress(single_bits.tobytes(), 6)) / 1e6,
        "rgba16f_mib": rgba.size * 2 / 2**20 * 4 / 3,
        "rgba16f_gzip_mb": len(
            gzip.compress(
                np.concatenate((rgba, rgba_light[..., None]), -1)
                .astype(np.float16)
                .tobytes(),
                6,
            )
        )
        / 1e6,
    }
    result = {
        "single": {
            "bp_rp_error_light_weighted_mean": float((w * single_error).sum()),
            "bp_rp_error_p90": float(_weighted_quantile(single_error, w, 0.9)),
            "light": 1.0,
        },
        "rgba_half_xy": {
            "bp_rp_error_light_weighted_mean": float((w * rgba_error).sum()),
            "bp_rp_error_p90": float(_weighted_quantile(rgba_error, w, 0.9)),
            "light_over_single": float(rgba_light.sum() * 4 / weight.sum()),
            "light_share_with_one_or_two_channels_clamped": float(
                (rgba_light[partial].sum()) / max(rgba_light.sum(), 1e-30)
            ),
            "light_error_per_voxel_light_weighted": float(
                (w * np.abs(light_up[used] - weight[used]) / weight[used]).sum()
            ),
        },
        "sizes": sizes,
    }
    write_json(out / "gates" / "forms.json", result)
    logger.info("forms: %s", result)


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    order = np.argsort(values)
    cumulative = np.cumsum(weights[order])
    return float(np.interp(q * cumulative[-1], cumulative, values[order]))


def excess_gate(out: Path, glow_dir: Path, far_side: float) -> None:
    """Gate 4: where the catalogue holds more light than the model by more than
    `EXCESS_SHARE`, by direction and distance from the Sun."""
    box = TIERS["high"]["inner"]
    baked = np.load(out / build.bake_name("inner"))
    # On the compare scale of the residual, so a voxel's few bright stars do not
    # count as a region.
    model_l = baked[..., :3].sum(-1)
    ratio = build.catalogue_ratio(
        model_l, baked[..., 3:6].sum(-1), box, build.COMPARE_SIGMA["inner"]
    ).reshape(-1)
    model_l = model_l.reshape(-1)
    cat_l = model_l * ratio
    volume = build.voxel_volumes(box).reshape(-1)
    centres = residual.voxel_centres(box)
    over = cat_l > (1 + EXCESS_SHARE) * model_l
    excess = np.where(over, cat_l - model_l, 0.0) * volume
    d = np.linalg.norm(centres, axis=1)
    lon = np.degrees(np.arctan2(centres[:, 1], centres[:, 0])) % 360
    lat = np.degrees(np.arcsin(np.clip(centres[:, 2] / np.maximum(d, 1e-9), -1, 1)))
    cat_total = float((cat_l * volume).sum())
    rows = []
    shells = (0.0, 500.0, 1000.0, 2000.0, 3000.0, 5000.0, 8000.0, 12000.0, 40000.0)
    for low, high in itertools.pairwise(shells):
        sel = (d >= low) & (d < high)
        rows.append(
            {
                "shell_pc": (low, high),
                "excess_light": float(excess[sel].sum()),
                "excess_share_of_catalogue": float(excess[sel].sum() / cat_total),
                "catalogue_light": float((cat_l * volume)[sel].sum()),
                "model_light": float((model_l * volume)[sel].sum()),
                "voxels_over": int((over & sel).sum()),
            }
        )
    # The strongest patches: 10 deg in l, 5 in b, by shell.
    key = (
        (lon // 10).astype(int) * 100 + ((lat + 90) // 5).astype(int)
    ) * 100 + np.searchsorted(shells, d, side="right")
    unique, inverse = np.unique(key, return_inverse=True)
    sums = np.bincount(inverse, excess)
    cat_in = np.bincount(inverse, cat_l * volume)
    model_in = np.bincount(inverse, model_l * volume)
    top = np.argsort(sums)[::-1][:25]
    patches = []
    for k in top:
        if sums[k] <= 0:
            break
        code = int(unique[k])
        shell = code % 100
        lat_bin = (code // 100) % 100
        lon_bin = code // 10000
        patches.append(
            {
                "l_deg": (lon_bin * 10, lon_bin * 10 + 10),
                "b_deg": (lat_bin * 5 - 90, lat_bin * 5 - 85),
                "shell_pc": (shells[shell - 1], shells[min(shell, len(shells) - 1)]),
                "excess_share_of_catalogue": float(sums[k] / cat_total),
                "catalogue_over_model": float(cat_in[k] / max(model_in[k], 1e-30)),
            }
        )
    result = {
        "share": EXCESS_SHARE,
        "excess_share_of_catalogue": float(excess.sum() / cat_total),
        "catalogue_light_in_box": cat_total,
        "model_light_in_box": float((model_l * volume).sum()),
        "shells": rows,
        "patches": patches,
    }
    write_json(out / "gates" / "excess.json", result)
    np.save(
        out / "gates" / "excess.inner.npy", excess.reshape(box.size).astype(np.float32)
    )
    logger.info(
        "excess: %.3f of the catalogue's light", result["excess_share_of_catalogue"]
    )
