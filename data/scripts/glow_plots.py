"""The band gate of the light grid, and its images.

    uv run --with matplotlib --with py360convert python scripts/glow_plots.py band maps sky

`band` compares drawn stars plus glow with the sky cube at the Sun. `maps` draws the
grid from outside, `sky` the Sun's sky from the grid against the stars.
"""

import json
import sys

import cdshealpix
import numpy as np
from astropy import units as u

from space_map_data.dust import gates as dust_gates
from space_map_data.dust.parallel import forked_stream
from space_map_data.dust.resample import points_pixels
from space_map_data.glow import (
    build,
    colour,
    deposit,
    form,
    gates,
    march,
    sky_map,
    tree,
)
from space_map_data.glow.march import View
from space_map_data.utils.paths import CACHE_DIR, EXPORT_DIR

BUILD = build.BUILD_DIR
OUT = CACHE_DIR / "milky-way-3d"
CUBE_DIR = EXPORT_DIR / "v1" / "textures" / "stars"
CUBE_KEYS = {"R": "px", "L": "nx", "U": "py", "D": "ny", "F": "pz", "B": "nz"}
ICRS_TO_GALACTIC = np.array(
    [
        [-0.0548755604, -0.8734370902, -0.4838350155],
        [0.4941094279, -0.4448296300, 0.7469822445],
        [-0.8676661490, -0.1980763734, 0.4559837762],
    ]
)
LUMA = np.array((0.2126, 0.7152, 0.0722))
DEPTH = deposit.SKY_DEPTH
PIXELS = 12 * 4**DEPTH
OMEGA = 4 * np.pi / PIXELS
# The camera of the app, and a reference window. A dot's light does not change with
# the field of view, and a pixel's solid angle does, so a surface brightness needs both.
FOV_DEG = 60.0
VIEWPORT_CSS = 900.0
OMEGA_CSS = (2 * np.tan(np.radians(FOV_DEG / 2)) / VIEWPORT_CSS) ** 2
# Of `material.ts`.
CORE_AT_LIMIT = 0.06
DOT_PX = 2.5
MAX_DOT_PX = 14.0
CONTRAST = 0.75
FADE_MAG = 1.0
LIMIT = deposit.SUN_LIMIT


def dot_area(size: np.ndarray) -> np.ndarray:
    """The integral of exp(-5 r^2 / R^2) over a dot, in CSS px^2."""
    radius = size / 2
    return np.pi * radius * radius / 5 * (1 - np.exp(-5.0))


LINEAR_GAIN = (
    CORE_AT_LIMIT * dot_area(np.array(DOT_PX)) * OMEGA_CSS * 10.0 ** (0.4 * LIMIT)
)


def linear_cube(depth: int = DEPTH) -> np.ndarray:
    """The cube's scene-linear luminance per HEALPix pixel: sRGB faces, decoded."""
    import py360convert
    from PIL import Image

    faces = {
        key: np.asarray(Image.open(CUBE_DIR / f"low_{name}.webp").convert("RGB"))
        for key, name in CUBE_KEYS.items()
    }
    image = (
        py360convert.c2e(faces, 2048, 4096, mode="bilinear", cube_format="dict").astype(
            np.float64
        )
        / 255
    )
    linear = np.where(image <= 0.04045, image / 12.92, ((image + 0.055) / 1.055) ** 2.4)
    lum = linear @ LUMA
    height, width = lum.shape
    dec = np.radians(90 - (np.arange(height) + 0.5) * 180 / height)
    column = (np.arange(width) + 0.5) / width
    best = None
    for ra in (
        (180 - column * 360) % 360,
        (column * 360 - 180) % 360,
        column * 360,
        (360 - column * 360) % 360,
    ):
        r = np.radians(ra)[None, :]
        d = dec[:, None]
        v = np.stack(
            (np.cos(d) * np.cos(r), np.cos(d) * np.sin(r), np.sin(d) * np.ones_like(r)),
            axis=-1,
        )
        g = v @ ICRS_TO_GALACTIC.T
        lat = np.arcsin(np.clip(g[..., 2], -1, 1))
        lon = np.arctan2(g[..., 1], g[..., 0]) % (2 * np.pi)
        near = np.abs(lat) < np.radians(5)
        centre = near & ((lon < np.radians(15)) | (lon > np.radians(345)))
        anti = near & (np.abs(lon - np.pi) < np.radians(15))
        score = np.median(lum[near]) / np.median(
            lum[np.abs(lat) > np.radians(60)]
        ) + np.median(lum[centre]) / np.median(lum[anti])
        if best is None or score > best[0]:
            best = (score, lon, lat)
    _, lon, lat = best
    pixel = cdshealpix.lonlat_to_healpix(
        lon.ravel() * u.rad, lat.ravel() * u.rad, depth
    ).astype(np.int64)
    weight = np.cos(np.broadcast_to(dec[:, None], lum.shape)).ravel()
    pixels = 12 * 4**depth
    return np.bincount(pixel, lum.ravel() * weight, pixels) / np.maximum(
        np.bincount(pixel, weight, pixels), 1e-12
    )


_rotation: np.ndarray | None = None


def _drawn_job(names: list[str]) -> np.ndarray:
    """Per pixel: drawn star energy (star law), and the same stars under a linear law."""
    assert _rotation is not None
    out = np.zeros((2, PIXELS))
    for name in names:
        node = tree.read_node(name)
        points = node.position @ _rotation
        r = np.maximum(np.linalg.norm(points, axis=1), 1e-6)
        above = LIMIT - (node.mag + 5 * np.log10(r / 10))
        lit = above > 0
        if not lit.any():
            continue
        a = above[lit]
        t = np.clip(a / FADE_MAG, 0, 1)
        fade = t * t * (3 - 2 * t)
        energy = CORE_AT_LIMIT * 10.0 ** (0.4 * CONTRAST * a)
        core = np.minimum(energy, 1.0)
        size = np.minimum(DOT_PX * np.sqrt(np.maximum(energy, 1.0)), MAX_DOT_PX)
        luma = colour.star_colours(node.colour[lit]) @ LUMA
        pixel = points_pixels(points[lit], DEPTH)
        out[0] += np.bincount(pixel, core * fade * dot_area(size) * luma, PIXELS)
        linear = CORE_AT_LIMIT * 10.0 ** (0.4 * a) * dot_area(np.array(DOT_PX))
        out[1] += np.bincount(pixel, linear * fade * luma, PIXELS)
    return out


def drawn_stars(nest: sky_map.Nest, workers: int) -> np.ndarray:
    global _rotation
    _rotation = nest.rotation
    names = tree.node_names()
    batches = [names[at : at + 256] for at in range(0, len(names), 256)]
    total = sum(forked_stream(_drawn_job, batches, workers))
    return total * OMEGA_CSS / OMEGA


def band(workers: int = 8) -> None:
    nest = sky_map.load_nest()
    tex = gates.textures(BUILD, "high")
    view = View(np.zeros(3), LIMIT)
    sharp = np.load(BUILD / "sun_sky.high.npy")

    def soft_read(points: np.ndarray, m_cut: np.ndarray) -> np.ndarray:
        return form.read_values(tex.filtered(points), m_cut, tex.table, True)

    rays, _ = dust_gates.rays(DEPTH + 1)
    seen = march.march_all(soft_read, nest, view, rays, workers)
    of_pixel = np.arange(len(rays)) // 4
    soft = (
        np.stack(
            [np.bincount(of_pixel, seen[:, c], PIXELS) / 4 for c in range(3)], axis=1
        )
        * OMEGA
    )
    np.save(BUILD / "sun_sky_soft.high.npy", soft)
    glow_sharp = sharp @ LUMA / OMEGA * LINEAR_GAIN
    glow_soft = soft @ LUMA / OMEGA * LINEAR_GAIN
    drawn, drawn_linear = drawn_stars(nest, workers)
    cube = linear_cube()
    np.savez(
        BUILD / "band.npz",
        cube=cube,
        drawn=drawn,
        drawn_linear=drawn_linear,
        glow_sharp=glow_sharp,
        glow_soft=glow_soft,
    )
    lon, lat = cdshealpix.healpix_to_lonlat(np.arange(PIXELS, dtype=np.uint64), DEPTH)
    lon, lat = lon.to_value(u.deg), np.abs(lat.to_value(u.deg))
    total = drawn + glow_soft

    def row(name: str, mask: np.ndarray) -> dict:
        return {
            "name": name,
            "pixels": int(mask.sum()),
            "cube_median": float(np.median(cube[mask])),
            "cube_mean": float(cube[mask].mean()),
            "drawn_mean": float(drawn[mask].mean()),
            "glow_sharp_mean": float(glow_sharp[mask].mean()),
            "glow_soft_mean": float(glow_soft[mask].mean()),
            "total_median": float(np.median(total[mask])),
            "total_mean": float(total[mask].mean()),
            "ratio_of_means": float(total[mask].mean() / cube[mask].mean()),
            "ratio_of_medians": float(np.median(total[mask]) / np.median(cube[mask])),
            "median_of_ratios": float(np.median(total[mask] / cube[mask])),
            "glow_only_ratio_of_medians": float(
                np.median(glow_soft[mask]) / np.median(cube[mask])
            ),
        }

    rows = [row("whole sky", lat <= 90)]
    for low, high in gates.BANDS:
        rows.append(row(f"|b| {low}-{high}", (lat >= low) & (lat < high)))
    rows.append(row("|b| < 5", lat < 5))
    for low, high in (
        (350, 10),
        (10, 40),
        (40, 90),
        (90, 150),
        (150, 210),
        (210, 270),
        (270, 320),
        (320, 350),
    ):
        sel = (
            ((lon >= low) | (lon < high))
            if low > high
            else ((lon >= low) & (lon < high))
        )
        rows.append(row(f"|b| < 2, l {low}-{high}", sel & (lat < 2)))
    rows.append(row("|b| < 5, centre l +-15", ((lon < 15) | (lon > 345)) & (lat < 5)))
    rows.append(row("|b| < 5, Carina l 280-295", (lon > 280) & (lon < 295) & (lat < 5)))
    rows.append(row("|b| < 5, anticentre", (np.abs(lon - 180) < 15) & (lat < 5)))
    rows.append(row("poles |b| > 60", lat > 60))
    result = {
        "reference": {
            "fov_deg": FOV_DEG,
            "viewport_css_px": VIEWPORT_CSS,
            "omega_css_sr": OMEGA_CSS,
            "dot_area_css_px2": float(dot_area(np.array(DOT_PX))),
            "linear_gain": float(LINEAR_GAIN),
        },
        "rows": rows,
    }
    (BUILD / "gates" / "band.json").write_text(json.dumps(result, indent=1))
    for r in rows:
        print(
            f"{r['name']:28s} cube med {r['cube_median']:.5f} mean {r['cube_mean']:.5f} | drawn {r['drawn_mean']:.5f} glow {r['glow_soft_mean']:.5f} | total med {r['total_median']:.5f} mean {r['total_mean']:.5f} | ratio means {r['ratio_of_means']:.3f} medians {r['ratio_of_medians']:.3f}"
        )


def equirect(values: np.ndarray, width: int = 1440) -> np.ndarray:
    """A HEALPix map as an image: l = 180 at the left, centre at the middle."""
    height = width // 2
    lon = np.radians(180 - (np.arange(width) + 0.5) * 360 / width) % (2 * np.pi)
    lat = np.radians(90 - (np.arange(height) + 0.5) * 180 / height)
    x, y = np.meshgrid(lon, lat)
    pixel = cdshealpix.lonlat_to_healpix(
        x.ravel() * u.rad, y.ravel() * u.rad, DEPTH
    ).astype(np.int64)
    return values[pixel].reshape(height, width)


def _pad_axes(fig) -> None:
    fig.get_layout_engine().set(w_pad=0.25)


def _colourbar(fig, image, ax, label: str, fraction: float = 0.025) -> None:
    bar = fig.colorbar(image, ax=ax, fraction=fraction, pad=0.01)
    bar.set_label(label, color="white")
    bar.ax.tick_params(colors="white", labelsize=8)


def sky() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    observed = np.load(BUILD / build.OBSERVED) @ LUMA
    grid = np.load(BUILD / "sun_sky.high.npy") @ LUMA
    grid_low = np.load(BUILD / "sun_sky.low.npy") @ LUMA
    floor = np.percentile(observed[observed > 0], 1)
    top = np.percentile(observed, 99.9)
    ext = (180, -180, -90, 90)
    fig, axes = plt.subplots(
        4, 1, figsize=(10.5, 21), facecolor="#101114", layout="constrained"
    )
    for ax, values, title in (
        (
            axes[0],
            observed,
            "Observed flux of stars fainter than m = 7.5, summed per pixel (0.9 deg)",
        ),
        (
            axes[1],
            grid,
            "The grid and the nest from the Sun, stars fainter than m = 7.5, high",
        ),
    ):
        im = ax.imshow(
            np.log10(np.maximum(equirect(values), floor)),
            extent=ext,
            cmap="gray",
            vmin=np.log10(floor),
            vmax=np.log10(top),
            aspect="equal",
        )
        ax.set_title(title, color="white", fontsize=11)
        _colourbar(fig, im, ax, "log10 flux")
    for ax, values, title in (
        (axes[2], grid / np.maximum(observed, 1e-300), "Grid over observed, high"),
        (axes[3], grid_low / np.maximum(observed, 1e-300), "Grid over observed, low"),
    ):
        im = ax.imshow(
            np.log2(np.clip(equirect(values), 0.25, 4)),
            extent=ext,
            cmap="RdBu_r",
            vmin=-1,
            vmax=1,
            aspect="equal",
        )
        ax.set_title(title, color="white", fontsize=11)
        _colourbar(fig, im, ax, "log2 ratio")
    for ax in axes:
        ax.set_xlabel("Galactic longitude (deg)", color="white")
        ax.set_ylabel("latitude (deg)", color="white")
        ax.tick_params(colors="white")
    _pad_axes(fig)
    fig.savefig(OUT / "glow_data_sun_sky.png", dpi=110, facecolor=fig.get_facecolor())

    data = np.load(BUILD / "band.npz")
    total = data["drawn"] + data["glow_soft"]
    fig, axes = plt.subplots(
        4, 1, figsize=(10.5, 21), facecolor="#101114", layout="constrained"
    )
    low, high = np.percentile(data["cube"], 1), np.percentile(data["cube"], 99.9)
    for ax, values, title in (
        (axes[0], data["cube"], "Sky cube, scene-linear luminance"),
        (
            axes[1],
            data["drawn"],
            "Drawn stars at uLimit 7.5, the star law, per 60 deg / 900 px",
        ),
        (
            axes[2],
            total,
            "Drawn stars plus catalogue glow, the fade complement, at the same scale",
        ),
    ):
        im = ax.imshow(
            np.log10(np.clip(equirect(values), low, None)),
            extent=ext,
            cmap="gray",
            vmin=np.log10(low),
            vmax=np.log10(high),
            aspect="equal",
        )
        ax.set_title(title, color="white", fontsize=11)
        _colourbar(fig, im, ax, "log10 linear")
    im = axes[3].imshow(
        np.log2(np.clip(equirect(total / data["cube"]), 0.125, 8)),
        extent=ext,
        cmap="RdBu_r",
        vmin=-3,
        vmax=3,
        aspect="equal",
    )
    axes[3].set_title("Drawn plus glow over the cube", color="white", fontsize=11)
    _colourbar(fig, im, axes[3], "log2 ratio")
    for ax in axes:
        ax.set_xlabel("Galactic longitude (deg)", color="white")
        ax.set_ylabel("latitude (deg)", color="white")
        ax.tick_params(colors="white")
    fig.savefig(
        OUT / "glow_data_cube_ratio.png", dpi=110, facecolor=fig.get_facecolor()
    )


def plane_map(
    tex,
    axes_of: tuple[int, int],
    half: float,
    depth: float,
    cells: int,
    layers: int,
    value: int,
):
    """The integral of one value over `depth` pc across the plane of `axes_of`."""
    edge = (np.arange(cells) + 0.5) / cells * 2 * half - half
    across = (np.arange(layers) + 0.5) / layers * 2 * depth - depth
    a, b = np.meshgrid(edge, edge, indexing="xy")
    other = 3 - axes_of[0] - axes_of[1]
    out = np.zeros(a.shape)
    for level in across:
        points = np.zeros((a.size, 3))
        points[:, axes_of[0]] = a.ravel()
        points[:, axes_of[1]] = b.ravel()
        points[:, other] = level
        out += tex.filtered(points)[:, value].reshape(a.shape)
    return out * (2 * depth / layers)


def maps() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    tex = gates.textures(BUILD, "high")
    names = {0: "all stars", 2: "M0 > -2", 4: "M0 > 1", 6: "M0 > 5"}
    for title, axes_of, depth, file in (
        ("face-on, x to the centre", (0, 1), 4000.0, "glow_data_face_on.png"),
        ("side-on, x to the centre, z up", (0, 2), 12000.0, "glow_data_side_on.png"),
    ):
        fig, axes = plt.subplots(2, 4, figsize=(17, 9), facecolor="#101114")
        for row, half in enumerate((14000.0, 1600.0)):
            for column, (value, name) in enumerate(names.items()):
                image = plane_map(
                    tex, axes_of, half, min(depth, half * 2), 560, 48, value
                )
                used = image[image > 0]
                low, high = np.percentile(used, 3), np.percentile(used, 99.8)
                ax = axes[row, column]
                im = ax.imshow(
                    np.log10(np.clip(image, low, None)),
                    origin="lower",
                    extent=(-half, half, -half, half),
                    cmap="gray",
                    vmin=np.log10(low),
                    vmax=np.log10(high),
                )
                ax.set_title(
                    f"{name}, +-{half / 1000:g} kpc", color="white", fontsize=10
                )
                ax.tick_params(colors="white", labelsize=8)
                _colourbar(fig, im, ax, "log10 surface flux", 0.046)
        fig.suptitle(
            f"Catalogue light, {title}: a Sun-centred view of the catalogue, not of the Galaxy",
            color="white",
        )
        fig.tight_layout()
        fig.savefig(OUT / file, dpi=95, facecolor=fig.get_facecolor())


if __name__ == "__main__":
    for step in sys.argv[1:]:
        {"band": band, "sky": sky, "maps": maps}[step]()
