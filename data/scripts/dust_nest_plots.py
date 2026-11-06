"""Render the gate images of the dust nest.

Run with: uv run --with matplotlib python scripts/dust_nest_plots.py <what> ...
"""

import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from astropy import units as u
from astropy.coordinates import Latitude, Longitude
from cdshealpix import nested
from matplotlib.colors import LogNorm
from matplotlib.patches import Circle, Rectangle

from space_map_data.dust.encode import encoded_dir, read_encodings
from space_map_data.dust.gates import GATE_DIR
from space_map_data.dust.nest import LEVELS, LOCAL_FADE, REGIONAL_FADE
from space_map_data.dust.sky import SKY_DIR
from space_map_data.dust.sources import BUILD_DIR

OUT = BUILD_DIR.parent
DENSITY = {"norm": LogNorm(1e-5, 0.1), "cmap": "magma"}


def decoded(variant: str, index: int, tier: str = "high") -> np.ndarray:
    codes = np.load(encoded_dir(variant) / f"l{index}.{tier}.npy")
    return read_encodings(variant)[index].decode(codes)


def slice_image(ax, variant, index, axis, at=0.0, tier="high", window=None):
    """Draw a plane through a level. `axis` 2 is z = at, axis 1 is y = at."""
    level = LEVELS[index]
    grid = decoded(variant, index, tier)
    position = int((at + level.half[axis]) / (2 * level.half[axis]) * grid.shape[axis])
    plane = np.take(grid, position, axis=axis)
    keep = [i for i in range(3) if i != axis]
    extent = (
        -level.half[keep[0]],
        level.half[keep[0]],
        -level.half[keep[1]],
        level.half[keep[1]],
    )
    image = ax.imshow(
        np.maximum(plane.T, 1e-6),
        origin="lower",
        extent=extent,
        aspect="equal",
        **DENSITY,
    )
    if window:
        ax.set_xlim(*window[:2])
        ax.set_ylim(*window[2:])
    ax.tick_params(labelsize=7)
    return image


def rings(ax, radii, colour="cyan"):
    for r in radii:
        ax.add_patch(Circle((0, 0), r, fill=False, ec=colour, lw=0.4, ls=":"))


def levels_figure(variant: str) -> None:
    fig, axes = plt.subplots(4, 2, figsize=(11, 16), width_ratios=(1, 1))
    for level, (top, edge) in zip(LEVELS, axes):
        image = slice_image(top, variant, level.index, 2)
        top.set_title(f"level {level.index}, z = 0 ({variant}, high)", fontsize=9)
        slice_image(edge, variant, level.index, 1)
        edge.set_title(f"level {level.index}, y = 0", fontsize=9)
        if level.index:
            edge.set_aspect("equal")
        else:
            edge.set_aspect(5.0)
        rings(top, (*LOCAL_FADE, *REGIONAL_FADE))
    fig.colorbar(image, ax=axes, shrink=0.4, label="A0 at 550 nm, mag/pc")
    fig.savefig(OUT / f"nest_levels_{variant}.png", dpi=130, bbox_inches="tight")


def seams_figure(variant: str) -> None:
    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    a = axes[0]
    slice_image(a[0], variant, 2, 2, window=(-1250, 1250, -1250, 1250))
    a[0].set_title(f"level 2, z = 0: local to regional, {LOCAL_FADE} pc", fontsize=9)
    rings(a[0], LOCAL_FADE)
    slice_image(a[1], variant, 1, 2, window=(-2600, 2600, -2600, 2600))
    a[1].set_title(f"level 1, z = 0: regional to disc, {REGIONAL_FADE} pc", fontsize=9)
    rings(a[1], REGIONAL_FADE)
    slice_image(a[2], variant, 0, 2, window=(-20000, 20000, -20000, 20000))
    a[2].set_title("level 0, z = 0", fontsize=9)
    b = axes[1]
    slice_image(b[0], variant, 2, 1, window=(-1250, 1250, -1250, 1250))
    b[0].set_title("level 2, y = 0", fontsize=9)
    rings(b[0], LOCAL_FADE)
    slice_image(b[1], variant, 1, 1, window=(-2600, 2600, -2600, 2600))
    b[1].set_title("level 1, y = 0", fontsize=9)
    rings(b[1], REGIONAL_FADE)
    slice_image(b[2], variant, 1, 2, 100.0, window=(-3000, 3000, -3000, 3000))
    b[2].set_title("level 1, z = +100 pc", fontsize=9)
    rings(b[2], (*LOCAL_FADE, *REGIONAL_FADE))
    fig.savefig(OUT / f"nest_seams_{variant}.png", dpi=130, bbox_inches="tight")


def face_figure(variant: str) -> None:
    """Level faces: the finer level drawn inside the coarser one, on one scale."""
    fig, axes = plt.subplots(1, 3, figsize=(16, 5.6))
    for ax, coarse in zip(axes, (0, 1, 2)):
        fine = coarse + 1
        half = LEVELS[fine].half[0]
        window = (-1.6 * half, 1.6 * half, -1.6 * half, 1.6 * half)
        slice_image(ax, variant, coarse, 2, window=window)
        slice_image(ax, variant, fine, 2, window=window)
        ax.add_patch(
            Rectangle((-half, -half), 2 * half, 2 * half, fill=False, ec="cyan", lw=0.5)
        )
        ax.set_title(f"level {fine} inside level {coarse}, z = 0", fontsize=9)
    fig.savefig(OUT / f"nest_faces_{variant}.png", dpi=130, bbox_inches="tight")


def mollweide(values: np.ndarray, width: int = 1200):
    """Project a nested HEALPix map, l = 0 at the centre and l growing to the left."""
    height = width // 2
    depth = int(np.log2(np.sqrt(len(values) / 12)))
    x = (np.arange(width) + 0.5) / width * 2 - 1
    y = (np.arange(height) + 0.5) / height * 2 - 1
    x, y = np.meshgrid(x, y)
    inside = x * x + y * y < 1
    theta = np.arcsin(y[inside])
    lat = np.arcsin((2 * theta + np.sin(2 * theta)) / np.pi)
    lon = -np.pi * x[inside] / np.cos(theta)
    pixel = nested.lonlat_to_healpix(Longitude(lon, u.rad), Latitude(lat, u.rad), depth)
    out = np.full(x.shape, np.nan)
    out[inside] = values[pixel.astype(np.int64)]
    return out


def sky_panel(ax, values, title, **style):
    image = ax.imshow(mollweide(values), origin="lower", **style)
    ax.set_title(title, fontsize=9)
    ax.axis("off")
    return image


def sky_figure(variant: str) -> None:
    directory = GATE_DIR / variant
    column = np.load(directory / "sky.nest.npy")
    observed = np.load(directory / "sky.observed.npy")
    planck = np.load(SKY_DIR / "planck.total.npy").reshape(-1, 4).mean(axis=1)
    tge = np.load(SKY_DIR / "tge.a0_550.npy")
    fig, axes = plt.subplots(3, 2, figsize=(14, 12.5))
    columns = {"norm": LogNorm(0.03, 30), "cmap": "magma"}
    logratio = {"vmin": -0.6, "vmax": 0.6, "cmap": "RdBu_r"}
    bar = sky_panel(
        axes[0, 0], column, f"Sun-view column of the nest ({variant}), mag", **columns
    )
    fig.colorbar(bar, ax=axes[0, 0], shrink=0.7)
    bar = sky_panel(axes[0, 1], planck, "Planck total, mag", **columns)
    fig.colorbar(bar, ax=axes[0, 1], shrink=0.7)
    bar = sky_panel(
        axes[1, 0], np.log10(column / planck), "log10 nest / Planck", **logratio
    )
    fig.colorbar(bar, ax=axes[1, 0], shrink=0.7)
    bar = sky_panel(
        axes[1, 1],
        np.log10(observed / planck),
        "log10 observed layers / Planck",
        **logratio,
    )
    fig.colorbar(bar, ax=axes[1, 1], shrink=0.7)
    bar = sky_panel(
        axes[2, 0],
        np.log10(column / tge),
        "log10 nest / Gaia TGE (at 550 nm)",
        **logratio,
    )
    fig.colorbar(bar, ax=axes[2, 0], shrink=0.7)
    bar = sky_panel(
        axes[2, 1],
        (column - observed) / column,
        "rest layer share of the column",
        vmin=0,
        vmax=1,
        cmap="viridis",
    )
    fig.colorbar(bar, ax=axes[2, 1], shrink=0.7)
    fig.savefig(OUT / f"nest_sky_{variant}.png", dpi=130, bbox_inches="tight")


def variants_figure() -> None:
    fig, axes = plt.subplots(2, 3, figsize=(16, 11))
    for row, variant in zip(axes, ("open", "vergely")):
        slice_image(row[0], variant, 1, 2)
        row[0].set_title(f"{variant}: level 1, z = 0", fontsize=9)
        rings(row[0], (*LOCAL_FADE, *REGIONAL_FADE))
        slice_image(row[1], variant, 1, 1)
        row[1].set_title(f"{variant}: level 1, y = 0", fontsize=9)
        slice_image(row[2], variant, 0, 2, window=(-7000, 7000, -7000, 7000))
        row[2].set_title(f"{variant}: level 0, z = 0, inner 7 kpc", fontsize=9)
    fig.savefig(OUT / "nest_variants.png", dpi=130, bbox_inches="tight")


def bubble_figure(variant: str) -> None:
    directory = GATE_DIR / variant
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.2))
    for ax, name in zip(axes, ("nest", "source")):
        values = np.load(directory / f"bubble.{name}.npy")
        bar = sky_panel(
            ax,
            values,
            f"first peak distance, {name}, pc",
            vmin=70,
            vmax=400,
            cmap="viridis",
        )
        fig.colorbar(bar, ax=ax, shrink=0.7)
    fig.savefig(OUT / f"nest_bubble_{variant}.png", dpi=130, bbox_inches="tight")


FIGURES = {
    "levels": levels_figure,
    "seams": seams_figure,
    "faces": face_figure,
    "sky": sky_figure,
    "bubble": bubble_figure,
}


if __name__ == "__main__":
    for what in sys.argv[1:]:
        if what == "variants":
            variants_figure()
            continue
        name, variant = what.split(":")
        FIGURES[name](variant)
