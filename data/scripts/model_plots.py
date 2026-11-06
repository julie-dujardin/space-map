"""Gates and images of the model light.

    uv run --with matplotlib --with py360convert python scripts/model_plots.py join looks excess lanes maps

`join` adds the stored residual to the band gate of the light grid (`glow_plots.py
band` first) and compares with the sky cube at the Sun. `looks` renders the model and
the render's light through the nest from 30 kpc, face-on and edge-on, beside NGC 6744
and NGC 891 at their physical scale. `excess` maps where the catalogue holds more
than the model. `lanes` puts the dust's rest layer on the young arms and compares the
far-side column with the nest before. `maps` draws the residual and the colour table.
"""

import json
import sys
from pathlib import Path

import cdshealpix
import numpy as np
from astropy import units as u

from space_map_data.dust import gates as dust_gates
from space_map_data.dust.parallel import forked_stream
from space_map_data.galaxy import build as model_build
from space_map_data.galaxy import calibrate, geometry, residual, volumes
from space_map_data.galaxy.geometry import R0, Z0
from space_map_data.galaxy.model import Model
from space_map_data.glow import build, gates, light, march, sky_map
from space_map_data.glow.march import View
from space_map_data.utils.paths import CACHE_DIR, EXTRASOLAR_DIR

MODEL = model_build.BUILD_DIR
GLOW = build.BUILD_DIR
OUT = CACHE_DIR / "milky-way-3d"
DEPTH = 6
PIXELS = 12 * 4**DEPTH
LUMA = np.array((0.2126, 0.7152, 0.0722))
# glow_plots.py: the screen value of flux per sr at the Sun, 60 deg over 900 CSS px.
LINEAR_GAIN = None
# LVG (Karachentsev et al. 2013) TRGB distance moduli.
NGC6744_MPC = 10 ** (29.89 / 5 + 1) / 1e6
NGC891_MPC = 10 ** (29.99 / 5 + 1) / 1e6
NGC6744_FOV_ARCMIN = (21.07, 17.74)
NGC891_FOV_ARCMIN = (18.23, 14.38)
REFERENCES = OUT / "references"


def _use_fade(model_dir: Path) -> None:
    """The catalogue fade the model build was made with."""
    raw = json.loads((model_dir / model_build.ENCODING_FILE).read_text())
    fade = raw.get("catalogue_fade_pc")
    residual.CATALOGUE_FADE_PC = tuple(fade) if fade else None


def _kpc(arcmin: float, mpc: float) -> float:
    return mpc * 1000.0 * np.radians(arcmin / 60.0)


def join(
    workers: int = 8, model_dir: Path = MODEL, tag: str = "", tier: str = "high"
) -> None:
    """Gate 6: drawn stars, catalogue glow and the residual against the cube."""
    sys.path.insert(0, str(Path(__file__).parent))
    import glow_plots

    band = np.load(GLOW / "band.npz")
    nest = sky_map.load_nest()
    stored = residual.StoredResidual.load(model_dir, tier)
    _use_fade(model_dir)
    tex = gates.textures(GLOW, "high")
    from space_map_data.glow import form

    def read(points: np.ndarray, cut: np.ndarray) -> np.ndarray:
        out = stored.read(points)
        if residual.CATALOGUE_FADE_PC is not None:
            # The grid's glow, faded, in place of the band's unfaded glow.
            weight = residual.catalogue_weight(np.linalg.norm(points, axis=1))
            soft = form.read_values(tex.filtered(points), cut, tex.table, True)
            out = out + soft * (weight - 1.0)[:, None]
        return out

    rays, _ = dust_gates.rays(DEPTH + 1)
    seen = march.march_all(
        read, nest, View(np.zeros(3), glow_plots.LIMIT), rays, workers
    )
    of_pixel = np.arange(len(rays)) // 4
    sky = np.stack(
        [np.bincount(of_pixel, seen[:, c], PIXELS) / 4 for c in range(3)], axis=1
    )
    np.save(model_dir / f"sun_sky_residual{tag}.{tier}.npy", sky)
    model_light = sky @ LUMA * glow_plots.LINEAR_GAIN
    cube, drawn, glow_soft = band["cube"], band["drawn"], band["glow_soft"]
    lon, lat = cdshealpix.healpix_to_lonlat(np.arange(PIXELS, dtype=np.uint64), DEPTH)
    lon, lat = lon.to_value(u.deg), lat.to_value(u.deg)
    alat = np.abs(lat)
    before = drawn + glow_soft
    after = before + model_light

    def row(name: str, mask: np.ndarray) -> dict:
        return {
            "name": name,
            "pixels": int(mask.sum()),
            "cube_median": float(np.median(cube[mask])),
            "before_over_cube": float(np.median(before[mask]) / np.median(cube[mask])),
            "after_over_cube": float(np.median(after[mask]) / np.median(cube[mask])),
            "means_after_over_cube": float(after[mask].mean() / cube[mask].mean()),
            "residual_share_of_after": float(
                model_light[mask].mean() / after[mask].mean()
            ),
        }

    def around(l0: float, b0: float, radius: float) -> np.ndarray:
        c = np.cos(np.radians(lat)) * np.cos(np.radians(lon - l0))
        cos_d = (
            np.sin(np.radians(lat)) * np.sin(np.radians(b0))
            + np.cos(np.radians(b0)) * c
        )
        return cos_d > np.cos(np.radians(radius))

    def band_l(low: float, high: float, b_max: float) -> np.ndarray:
        sel = (
            ((lon >= low) | (lon < high))
            if low > high
            else ((lon >= low) & (lon < high))
        )
        return sel & (alat < b_max)

    rows = [row("whole sky", alat <= 90)]
    for low, high in gates.BANDS:
        rows.append(row(f"|b| {low}-{high}", (alat >= low) & (alat < high)))
    rows.append(row("|b| < 5", alat < 5))
    rows.append(row("centre |b| < 5, l +-15", band_l(345, 15, 5)))
    rows.append(row("anticentre |b| < 5, l 165-195", band_l(165, 195, 5)))
    rows.append(row("Carina |b| < 5, l 280-295", band_l(280, 295, 5)))
    rows.append(row("north pole b > 60", lat > 60))
    rows.append(row("south pole b < -60", lat < -60))
    for b_low, b_high in ((0, 5), (5, 10), (10, 20), (20, 40)):
        for name, l_low, l_high in (("centre", 345, 15), ("anticentre", 165, 195)):
            sel = band_l(l_low, l_high, 90) & (alat >= b_low) & (alat < b_high)
            rows.append(row(f"{name} |b| {b_low}-{b_high}", sel))
    rows.append(row("LMC within 4 deg", around(280.47, -32.89, 4.0)))
    rows.append(row("SMC within 2 deg", around(302.80, -44.30, 2.0)))
    result = {"rows": rows, "model_build": str(model_dir)}
    (model_dir / "gates" / f"join{tag}.json").write_text(json.dumps(result, indent=1))
    for r in rows:
        print(
            f"{r['name']:34s} before {r['before_over_cube']:.2f} after {r['after_over_cube']:.2f}"
            f" (means {r['means_after_over_cube']:.2f}) residual {r['residual_share_of_after']:.2f}"
        )


def tiers(model_dir: Path = MODEL, tag: str = "") -> None:
    """Gate 9: the residual's sky from the Sun on `low` over `high`, by band."""
    high = np.load(model_dir / f"sun_sky_residual{tag}.high.npy") @ LUMA
    low = np.load(model_dir / f"sun_sky_residual{tag}.low.npy") @ LUMA
    _, lat = cdshealpix.healpix_to_lonlat(np.arange(PIXELS, dtype=np.uint64), DEPTH)
    alat = np.abs(lat.to_value(u.deg))
    rows = {"whole sky": float(low.sum() / high.sum())}
    for lo, hi in gates.BANDS:
        sel = (alat >= lo) & (alat < hi)
        rows[f"|b| {lo}-{hi}"] = float(low[sel].sum() / high[sel].sum())
    (model_dir / "gates" / f"tiers{tag}.json").write_text(json.dumps(rows, indent=1))
    print(json.dumps(rows, indent=1))


# ---------------------------------------------------------------------- looks

_render = None


def _render_rows(job: tuple[int, int]) -> np.ndarray:
    assert _render is not None
    start, stop = job
    return _render(start, stop)


def render(
    width_pc: float,
    height_pc: float,
    pixel_pc: float,
    face_on: bool,
    sources_of_light,
    nest,
    workers: int,
) -> np.ndarray:
    """An orthographic image through the nest, (rows, columns, 3) in flux per sr.

    Face-on looks down from +z at the Galactic centre; edge-on looks from +y toward
    -y. `sources_of_light(points) -> (n, 3)` gives flux per pc^3 and channel."""
    global _render
    columns = round(width_pc / pixel_pc)
    rows = round(height_pc / pixel_pc)
    across = (np.arange(columns) + 0.5) * pixel_pc - width_pc / 2
    up = height_pc / 2 - (np.arange(rows) + 0.5) * pixel_pc
    if face_on:
        depth = 2.0 * np.sinh(
            np.linspace(np.arcsinh(15000 / 2.0), -np.arcsinh(15000 / 2.0), 361)
        )
    else:
        depth = np.linspace(32000.0, -32000.0, 1281)
    steps = np.abs(np.gradient(depth))

    def one(start: int, stop: int) -> np.ndarray:
        out = np.zeros((stop - start, columns, 3))
        for i in range(start, stop):
            seen = np.ones((columns, 3))
            total = np.zeros((columns, 3))
            for d, ds in zip(depth, steps, strict=True):
                if face_on:
                    points = np.column_stack(
                        (R0 + across, np.full(columns, up[i]), np.full(columns, d - Z0))
                    )
                else:
                    points = np.column_stack(
                        (R0 + across, np.full(columns, d), np.full(columns, up[i] - Z0))
                    )
                dust = sky_map.density(nest, points).astype(np.float64) * ds
                depth_rgb = dust[:, None] * light.K_RGB[None, :]
                through = 10.0 ** (-0.4 * depth_rgb)
                emission = sources_of_light(points) * ds
                mean = np.where(
                    depth_rgb > 1e-4,
                    (1 - through) / np.maximum(0.4 * np.log(10) * depth_rgb, 1e-12),
                    1.0,
                )
                total += emission * seen * mean
                seen *= through
            out[i - start] = total
        return out

    _render = one
    chunk = 4
    jobs = [(s, min(s + chunk, rows)) for s in range(0, rows, chunk)]
    image = np.concatenate(list(forked_stream(_render_rows, jobs, workers)))
    _render = None
    return image


def tone(image: np.ndarray, white: float) -> np.ndarray:
    """asinh on luminance, colour kept, then sRGB."""
    lum = image @ LUMA
    scale = np.arcsinh(lum / white) / np.maximum(lum / white, 1e-12) / np.arcsinh(50.0)
    rgb = np.clip(image / white * scale[..., None] * 1.0, 0, 1)
    return np.where(rgb <= 0.0031308, 12.92 * rgb, 1.055 * rgb ** (1 / 2.4) - 0.055)


def looks(workers: int = 8, model_dir: Path = MODEL, tag: str = "") -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    nest = sky_map.load_nest()
    model = Model.load(model_dir / calibrate.CALIBRATION)
    stored = residual.StoredResidual.load(model_dir, "high")
    grid = residual.CatalogueGrid.load(GLOW, "high")
    _use_fade(model_dir)

    def model_light(points):
        return model.rgb(*points.T)

    def render_light(points):
        weight = residual.catalogue_weight(np.linalg.norm(points, axis=1))[:, None]
        return grid.read(points) * weight + stored.read(points)

    face = (
        _kpc(NGC6744_FOV_ARCMIN[0], NGC6744_MPC) * 1000,
        _kpc(NGC6744_FOV_ARCMIN[1], NGC6744_MPC) * 1000,
    )
    edge = (
        _kpc(NGC891_FOV_ARCMIN[0], NGC891_MPC) * 1000,
        _kpc(NGC891_FOV_ARCMIN[1], NGC891_MPC) * 1000,
    )
    images = {}
    for name, (w, h), face_on, pixel in (
        ("face", face, True, 100.0),
        ("edge", edge, False, 50.0),
    ):
        for kind, fn in (("model", model_light), ("render", render_light)):
            path = model_dir / f"look_{name}_{kind}{tag}.npy"
            if path.exists():
                images[(name, kind)] = np.load(path)
                continue
            image = render(w, h, pixel, face_on, fn, nest, workers)
            np.save(path, image)
            images[(name, kind)] = image
    references = {
        "face": np.asarray(Image.open(REFERENCES / "eso1118a_ngc6744.jpg").reduce(4)),
        # North is 90 deg right of vertical; the disc runs across, as in our view.
        "edge": np.asarray(Image.open(REFERENCES / "iotw2023a_ngc891.jpg").reduce(4)),
    }
    for name in ("face", "edge"):
        fig, axes = plt.subplots(
            1, 3, figsize=(24, 7.6), facecolor="#101114", layout="constrained"
        )
        model_image = images[(name, "model")]
        white = np.percentile(model_image @ LUMA, 99.0)
        w, h = face if name == "face" else edge
        ext = (-w / 2000, w / 2000, -h / 2000, h / 2000)
        for ax, image, title in (
            (axes[0], model_image, "model light through the nest (no catalogue)"),
            (
                axes[1],
                images[(name, "render")],
                "catalogue grid + residual through the nest",
            ),
        ):
            ax.imshow(tone(image, white), extent=ext, origin="upper")
            ax.set_title(title, color="white")
            ax.set_xlabel("kpc", color="white")
            ax.tick_params(colors="white")
        reference = references[name]
        ref_title = (
            f"NGC 6744, ESO (CC BY 4.0), {NGC6744_MPC:.2f} Mpc"
            if name == "face"
            else f"NGC 891, KPNO/NOIRLab/NSF/AURA (CC BY 4.0), {NGC891_MPC:.2f} Mpc"
        )
        axes[2].imshow(reference, extent=ext)
        axes[2].set_title(ref_title + ", same kpc", color="white")
        axes[2].tick_params(colors="white")
        if name == "face":
            for ax in axes[:2]:
                ax.plot(-R0 / 1000, 0, marker="*", color="cyan", ms=8)
        fig.savefig(OUT / f"model_look_{name}{tag}.png", dpi=80)
        plt.close(fig)


def zoom(workers: int = 8, model_dir: Path = MODEL) -> None:
    """The edge-on disc close up, for the dust lane: model light and the render's
    light through the nest, 32 x 5 kpc at 20 pc."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    nest = sky_map.load_nest()
    model = Model.load(model_dir / calibrate.CALIBRATION)
    stored = residual.StoredResidual.load(model_dir, "high")
    grid = residual.CatalogueGrid.load(GLOW, "high")
    _use_fade(model_dir)

    def render_light(points):
        weight = residual.catalogue_weight(np.linalg.norm(points, axis=1))[:, None]
        return grid.read(points) * weight + stored.read(points)

    images = {}
    for kind, fn in (("model", lambda p: model.rgb(*p.T)), ("render", render_light)):
        path = model_dir / f"zoom_edge_{kind}.npy"
        if not path.exists():
            np.save(path, render(32000.0, 5000.0, 20.0, False, fn, nest, workers))
        images[kind] = np.load(path)
    fig, axes = plt.subplots(
        2, 1, figsize=(22, 8.4), facecolor="#101114", layout="constrained"
    )
    white = np.percentile(images["model"] @ LUMA, 99.5)
    for ax, kind in zip(axes, ("model", "render"), strict=True):
        ax.imshow(tone(images[kind], white), extent=(-16, 16, -2.5, 2.5), aspect="auto")
        ax.set_title(
            f"edge-on from +y, {kind} light through the nest; Galactic centre at 0, the Sun at -8.3",
            color="white",
        )
        ax.tick_params(colors="white")
    fig.savefig(OUT / "model_zoom_edge.png", dpi=80)
    plt.close(fig)


# ---------------------------------------------------------------------- excess


def excess(model_dir: Path = MODEL) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    box = volumes.TIERS["high"]["inner"]
    baked = np.load(model_dir / model_build.bake_name("inner"), mmap_mode="r")
    heights = box.heights
    model_col = (np.asarray(baked[..., :3]).sum(-1) * heights).sum(-1)
    cat_col = (np.asarray(baked[..., 3:6]).sum(-1) * heights).sum(-1)
    residual_col = (
        np.maximum(
            np.asarray(baked[..., :3]).sum(-1) - np.asarray(baked[..., 3:6]).sum(-1), 0
        )
        * heights
    ).sum(-1)
    over = np.load(model_dir / "gates" / "excess.inner.npy").sum(-1)
    ext = (-24 - R0 / 1000, 24 - R0 / 1000, -24, 24)
    ext = (ext[0] + R0 / 1000 * 2, ext[1] + R0 / 1000 * 2, -24, 24)
    fig, axes = plt.subplots(
        2, 2, figsize=(16, 15), facecolor="#101114", layout="constrained"
    )
    centre_x = R0 / 1000
    ext = (centre_x - 24, centre_x + 24, -24, 24)
    for ax, values, title, cmap, kw in (
        (
            axes[0, 0],
            np.log10(model_col.T + 1e-9),
            "model, R+G+B column (log)",
            "magma",
            {"vmin": -4, "vmax": 0.5},
        ),
        (
            axes[0, 1],
            np.log10(cat_col.T + 1e-9),
            "catalogue grid, all stars (log)",
            "magma",
            {"vmin": -4, "vmax": 0.5},
        ),
        (
            axes[1, 0],
            np.log10(cat_col.T / np.maximum(model_col.T, 1e-9)),
            "log10 catalogue / model",
            "RdBu_r",
            {"vmin": -1.5, "vmax": 1.5},
        ),
        (
            axes[1, 1],
            np.log10(over.T / (box.size[0] and 1) + 1e-6),
            "excess of catalogue over 1.5 x model (log, flux per column)",
            "viridis",
            {"vmin": -3, "vmax": 3},
        ),
    ):
        image = ax.imshow(values, origin="lower", extent=ext, cmap=cmap, **kw)
        ax.set_title(title, color="white")
        ax.plot(0, 0, "c*", ms=10)
        ax.plot(centre_x, 0, "w+", ms=12)
        ax.tick_params(colors="white")
        ax.set_xlabel("x from the Sun (kpc), Galactic centre at +8.3", color="white")
        bar = fig.colorbar(image, ax=ax, fraction=0.04, pad=0.01)
        bar.ax.tick_params(colors="white")
    fig.savefig(OUT / "model_excess.png", dpi=80)
    plt.close(fig)
    np.save(
        model_dir / "gates" / "columns.npy",
        np.stack((model_col, cat_col, residual_col)),
    )


# ---------------------------------------------------------------------- lanes


def _nest_at(root: Path):
    return sky_map.load_nest(root=root)


def lanes(workers: int = 8, model_dir: Path = MODEL) -> None:
    """Gate 7: the rest layer's face-on column on the young arms, and the far side."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from space_map_data.dust.merge import merged_dir
    from space_map_data.dust.nest import LEVELS

    level = LEVELS[0]
    rest = np.load(merged_dir("open") / "l0.rest.npy", mmap_mode="r")
    observed = np.load(merged_dir("open") / "l0.observed.npy", mmap_mode="r")
    dz = level.voxel[2]
    rest_col = np.asarray(rest).sum(axis=2) * dz
    obs_col = np.asarray(observed).sum(axis=2) * dz
    n = 600
    X = np.linspace(-20000, 20000, n)
    gx, gy = np.meshgrid(X, X, indexing="xy")
    R, beta, _ = geometry.galactocentric(gx.ravel(), gy.ravel(), np.zeros(n * n))
    field = geometry.arm_field(R, beta).reshape(n, n)
    fig, axes = plt.subplots(
        1, 2, figsize=(18, 8.6), facecolor="#101114", layout="constrained"
    )
    ext = (-20, 20, -20, 20)
    for ax, values, title in (
        (axes[0], rest_col.T, "rest layer (layer 4) A0 column, level 0"),
        (axes[1], (rest_col + obs_col).T, "all layers A0 column, level 0"),
    ):
        image = ax.imshow(
            np.log10(values + 1e-4),
            origin="lower",
            extent=ext,
            cmap="magma",
            vmin=-2,
            vmax=1.5,
        )
        ax.contour(
            X / 1000, X / 1000, field, levels=[0.6], colors="cyan", linewidths=0.6
        )
        ax.plot(0, 0, "w*", ms=10)
        ax.plot(R0 / 1000, 0, "w+", ms=12)
        ax.set_title(title + "; cyan: young arm ridges (field 0.6)", color="white")
        ax.tick_params(colors="white")
        bar = fig.colorbar(image, ax=ax, fraction=0.04, pad=0.01)
        bar.ax.tick_params(colors="white")
    fig.savefig(OUT / "model_lanes.png", dpi=80)
    plt.close(fig)
    # The far side: columns from the Sun past the centre, before and after.
    roots = {"now": EXTRASOLAR_DIR, "before": MODEL / "backup-phase3" / "root"}
    lon = np.radians(np.linspace(-30, 30, 121))
    lat = np.radians(np.linspace(-2, 2, 9))
    L, B = np.meshgrid(lon, lat)
    rays = np.stack(
        (np.cos(B) * np.cos(L), np.cos(B) * np.sin(L), np.sin(B)), -1
    ).reshape(-1, 3)
    result = {}
    for name, root in roots.items():
        nest = _nest_at(root)
        distance = np.linspace(5, 20000, 4000)
        ds = distance[1] - distance[0]
        near = np.zeros(len(rays))
        far = np.zeros(len(rays))
        for d in distance:
            a = sky_map.density(nest, rays * d).astype(np.float64) * ds
            if d < R0:
                near += a
            else:
                far += a
        result[name] = {
            "near_side_median_mag": float(np.median(near)),
            "far_side_median_mag": float(np.median(far)),
            "far_share_median": float(np.median(far / np.maximum(near + far, 1e-9))),
        }
    (model_dir / "gates" / "far_side_column.json").write_text(
        json.dumps(result, indent=1)
    )
    print(json.dumps(result, indent=1))


# ---------------------------------------------------------------------- maps


def maps(model_dir: Path = MODEL) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    box = volumes.TIERS["high"]["inner"]
    stored = residual.StoredResidual.load(model_dir, "high")
    table = stored.table
    n = 480
    X = np.linspace(-24000, 24000, n)
    gx, gy = np.meshgrid(X + R0, X, indexing="xy")
    heights = np.concatenate(
        (-np.geomspace(5, 3000, 60)[::-1], np.geomspace(5, 3000, 60))
    )
    dz = np.gradient(heights)
    face = np.zeros((n * n, 3))
    for h, step in zip(heights, dz, strict=True):
        points = np.column_stack((gx.ravel(), gy.ravel(), np.full(n * n, h - Z0)))
        face += stored.read(points) * step
    face = face.reshape(n, n, 3)
    xe = np.linspace(-24000, 24000, 960)
    ze = np.linspace(-3000, 3000, 240)
    ex, ez = np.meshgrid(xe + R0, ze, indexing="xy")
    edge = np.zeros((240 * 960, 3))
    ys = np.linspace(-24000, 24000, 241)
    for y in ys:
        points = np.column_stack((ex.ravel(), np.full(ex.size, y), ez.ravel() - Z0))
        edge += stored.read(points) * (ys[1] - ys[0])
    edge = edge.reshape(240, 960, 3)
    fig = plt.figure(figsize=(18, 14), facecolor="#101114", layout="constrained")
    grid_spec = fig.add_gridspec(3, 2, height_ratios=(6, 2, 2))
    ax = fig.add_subplot(grid_spec[0, 0])
    white = np.percentile(face @ LUMA, 99.5)
    ax.imshow(tone(face[::-1], white), extent=(-24, 24, -24, 24))
    ax.set_title("residual, face-on, no dust (centre at 0)", color="white")
    ax.tick_params(colors="white")
    ax = fig.add_subplot(grid_spec[0, 1])
    rgb = table[: residual.TABLE_RADII * residual.TABLE_HEIGHTS].reshape(
        residual.TABLE_HEIGHTS, residual.TABLE_RADII, 3
    )
    ax.imshow(
        rgb / rgb.max(axis=-1, keepdims=True), aspect="auto", extent=(0, 30, 2, 0)
    )
    ax.set_title(
        "colour table: radius (kpc) by height node (0, 1 kpc); shells: "
        + ", ".join(f"{c}" for c in np.round(table[-3:], 3).tolist()),
        color="white",
        fontsize=8,
    )
    ax.tick_params(colors="white")
    ax = fig.add_subplot(grid_spec[1, :])
    white = np.percentile(edge @ LUMA, 99.5)
    ax.imshow(tone(edge[::-1], white), extent=(-24, 24, -3, 3), aspect="auto")
    ax.set_title("residual, edge-on from +y, no dust", color="white")
    ax.tick_params(colors="white")
    ax = fig.add_subplot(grid_spec[2, :])
    gal = json.loads((model_dir / "gates" / "galaxy.json").read_text())
    ax.axis("off")
    ax.text(
        0,
        0.5,
        json.dumps({k: gal[k] for k in ("half_light_pc", "galaxy")}, indent=None)[:600],
        color="white",
        fontsize=8,
        wrap=True,
    )
    fig.savefig(OUT / "model_residual.png", dpi=80)
    plt.close(fig)
    del box


if __name__ == "__main__":
    steps = sys.argv[1:]
    model_dir = MODEL
    tag = ""
    for step in steps:
        if step.startswith("--build="):
            model_dir = Path(step.split("=", 1)[1])
        if step.startswith("--tag="):
            tag = step.split("=", 1)[1]
    for step in steps:
        if step == "join":
            join(model_dir=model_dir, tag=tag)
        elif step == "looks":
            looks(model_dir=model_dir, tag=tag)
        elif step == "zoom":
            zoom(model_dir=model_dir)
        elif step == "excess":
            excess(model_dir)
        elif step == "tiers":
            join(model_dir=model_dir, tag=tag, tier="low")
            tiers(model_dir, tag)
        elif step == "lanes":
            lanes(model_dir=model_dir)
        elif step == "maps":
            maps(model_dir)
