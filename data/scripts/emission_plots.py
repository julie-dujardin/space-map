"""Images of the emission build, beside the Phase 5 note.

    uv run --with matplotlib python scripts/emission_plots.py halpha sun outside wise bands

`halpha` maps Finkbeiner, what is placed, McCallum unscaled, the factor and what is
left unplaced. `sun` draws the Sun's sky with and without H-alpha and scattered
light beside Mellinger 2009 (private), and their ratio. `outside` renders the
Galaxy from 30 kpc face-on and edge-on with and without scattered light beside
NGC 6744 and NGC 891 (private references). `wise` maps the far regions by source,
with their luminosity function. `bands` charts scattered over direct light by band
against Leinert 1998. Run the gates first: the images read their caches.
"""

import json
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from astropy.io import fits
from PIL import Image

from space_map_data.emission import (
    build,
    gates,
    lines,
    local,
    sky,
    views,
)
from space_map_data.galaxy import volumes
from space_map_data.utils.paths import CACHE_DIR

OUT = CACHE_DIR / "milky-way-3d"
B = build.BUILD_DIR
REF = OUT / "references"
MELLINGER = REF / "mellinger2009_mwpan2_RGB_3600.fits"
# Half the width of the outside views, pc.
HALF_VIEW_PC = 19_000.0
# One S10(V): a V = 10 star per square degree, in flux of m = 0 per sr.
S10 = 1e-4 / np.radians(1.0) ** 2
DARK = "#0b0b0d"
INK = "#d8d8d2"
# The reference categorical slots (dataviz palette, light surface).
OURS, PUBLISHED, THIRD = "#2a78d6", "#eb6834", "#1baf7a"


def car_pixels(nside: int, width: int = 720) -> np.ndarray:
    """HEALPix pixels of a plate carree grid, l = 180 at the left edge, 0 in the
    middle, b = 90 on top."""
    height = width // 2
    l = 180.0 - (np.arange(width) + 0.5) / width * 360.0
    b = 90.0 - (np.arange(height) + 0.5) / height * 180.0
    lg, bg = np.meshgrid(np.radians(l), np.radians(b))
    d = np.stack((np.cos(bg) * np.cos(lg), np.cos(bg) * np.sin(lg), np.sin(bg)), -1)
    return sky.pixel_of(d.reshape(-1, 3), nside).reshape(height, width)


def car(values: np.ndarray, width: int = 720) -> np.ndarray:
    nside = int(np.sqrt(len(values) / 12))
    return values[car_pixels(nside, width)]


def _axes_style(ax, title: str) -> None:
    ax.set_title(title, color=INK, fontsize=10)
    ax.set_xticks([0, 180, 360, 540, 719], ["180", "90", "0", "270", "180"])
    ax.set_yticks([0, 90, 180, 270, 359], ["90", "45", "0", "-45", "-90"])
    ax.tick_params(colors=INK, labelsize=7)
    for spine in ax.spines.values():
        spine.set_color("#444")


def _log_panel(fig, ax, values, title, low, high, unit) -> None:
    image = ax.imshow(
        np.log10(np.clip(car(values), low, high)),
        cmap="magma",
        vmin=np.log10(low),
        vmax=np.log10(high),
        interpolation="nearest",
    )
    _axes_style(ax, title)
    bar = fig.colorbar(image, ax=ax, fraction=0.025, pad=0.01)
    bar.set_label(unit, color=INK, fontsize=8)
    bar.ax.tick_params(colors=INK, labelsize=7)


def halpha() -> None:
    shipped = np.load(B / gates.SHIPPED)
    found = build.read_regions(B)
    observed = local.finkbeiner(local.SKY_NSIDE)
    placed = shipped + found["sky"]
    bare = np.load(B / "sun.seen.npy")
    factor = np.load(B / "scale.factor.npy")
    wanted = local.target(observed, found["sky"])
    fig, axes = plt.subplots(5, 1, figsize=(11, 25), facecolor=DARK)
    _log_panel(
        fig, axes[0], observed, "Finkbeiner 2003, observed H-alpha", 0.3, 300, "log10 R"
    )
    _log_panel(
        fig,
        axes[1],
        placed,
        "Placed, seen from the Sun: scaled McCallum + WISE regions, through the nest",
        0.3,
        300,
        "log10 R",
    )
    _log_panel(
        fig,
        axes[2],
        bare,
        "McCallum 2025 unscaled, through the nest",
        0.3,
        300,
        "log10 R",
    )
    image = axes[3].imshow(
        np.log2(car(factor)), cmap="RdBu_r", vmin=-2, vmax=2, interpolation="nearest"
    )
    _axes_style(
        axes[3], "Scale factor per sightline (2 deg Gaussian, held to 1/4 to 4)"
    )
    bar = fig.colorbar(image, ax=axes[3], fraction=0.025, pad=0.01)
    bar.set_label("log2 factor", color=INK, fontsize=8)
    bar.ax.tick_params(colors=INK, labelsize=7)
    left = np.maximum(wanted - shipped, 0) / np.maximum(observed, 1e-3)
    image = axes[4].imshow(
        car(left), cmap="viridis", vmin=0, vmax=1, interpolation="nearest"
    )
    _axes_style(
        axes[4],
        "Unplaced share of the observed H-alpha (past the factor limit, or beyond 1.25 kpc)",
    )
    bar = fig.colorbar(image, ax=axes[4], fraction=0.025, pad=0.01)
    bar.set_label("share of Finkbeiner", color=INK, fontsize=8)
    bar.ax.tick_params(colors=INK, labelsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "emission_halpha.png", dpi=90, facecolor=DARK)


def _mellinger(width: int = 720) -> np.ndarray:
    """Mellinger's sky in S10(V), [row, column, (R, G, B)], on the grid of `car`."""
    with fits.open(MELLINGER, memmap=True) as handle:
        cube = np.asarray(handle[0].data, np.float64)
    # Planes are B, G, R (plane 2 is brightest on the Rosette); columns run l = 180
    # down at 0.1 deg, rows b = -90 up.
    rgb = np.stack((cube[2], cube[1], cube[0]), axis=-1)[::-1]
    factor = cube.shape[2] // width
    h, w = rgb.shape[0] // factor, rgb.shape[1] // factor
    return (
        rgb[: h * factor, : w * factor]
        .reshape(h, factor, w, factor, 3)
        .mean(axis=(1, 3))
    )


def _tone(rgb: np.ndarray, soft: float = 40.0, top: float = 4000.0) -> np.ndarray:
    """An asinh stretch of S10 values, the same for every panel."""
    out = np.arcsinh(np.maximum(rgb, 0) / soft) / np.arcsinh(top / soft)
    return np.clip(out, 0, 1) ** (1 / 1.4)


def sun() -> None:
    nside = 128
    parts = gates.sun_parts(B, "high", 8, nside)
    without = parts["direct"]
    with_ = without + parts["scattered"] + parts["halpha"] + parts["regions"]
    mell = _mellinger()
    ours_without = np.stack([car(without[:, c]) for c in range(3)], -1) / S10
    ours_with = np.stack([car(with_[:, c]) for c in range(3)], -1) / S10
    fig, axes = plt.subplots(4, 1, figsize=(11, 22), facecolor=DARK)
    for ax, image, title in (
        (
            axes[0],
            ours_without,
            "From the Sun without: all stars (no cut) and the model, through the nest",
        ),
        (
            axes[1],
            ours_with,
            "With H-alpha (scaled McCallum + WISE) and scattered starlight",
        ),
        (axes[2], mell, "Mellinger 2009, private reference (S10(V) per channel)"),
    ):
        ax.imshow(_tone(image), interpolation="nearest")
        _axes_style(ax, title)
    gain = (with_ @ gates.LUMA) / (without @ gates.LUMA)
    image = axes[3].imshow(
        car(gain), cmap="magma", vmin=1.0, vmax=1.6, interpolation="nearest"
    )
    _axes_style(axes[3], "With over without, luma")
    bar = fig.colorbar(image, ax=axes[3], fraction=0.025, pad=0.01)
    bar.ax.tick_params(colors=INK, labelsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "emission_sun_sky.png", dpi=90, facecolor=DARK)


def _render(scene, origin, u, v, n: int):
    centre = np.array(volumes.CENTRE)
    q = (np.arange(n) + 0.5) / n * 2 - 1
    a, b = np.meshgrid(q * HALF_VIEW_PC, -q * HALF_VIEW_PC, indexing="xy")
    targets = centre + a.reshape(-1, 1) * u + b.reshape(-1, 1) * v
    rays = targets - origin
    rays /= np.linalg.norm(rays, axis=1)[:, None]
    mids, lengths = views.box_rays(origin, rays, volumes.INNER_HIGH, 1536)
    got = views.march_all(scene, origin, rays, mids, lengths, 8, size=512)
    # The regions as sprites through their column from the camera.
    found = build.read_regions(B)
    column = views.column_between(scene.field, origin, found["position"])
    painted = np.zeros((n * n, 3))
    offset = found["position"] - origin
    distance = np.linalg.norm(offset, axis=1)
    seen = (
        found["display"][:, None]
        * lines.COLOUR
        * 10.0 ** (-0.4 * lines.K_EMISSION * column[:, None])
    )
    # Pixel of each region: its point on the target plane.
    depth = np.linalg.norm(centre - origin)
    pa = (offset @ u) / (offset @ ((centre - origin) / depth)) * depth
    pb = (offset @ v) / (offset @ ((centre - origin) / depth)) * depth
    ix = np.clip(((pa / HALF_VIEW_PC + 1) / 2 * n).astype(int), 0, n - 1)
    iy = np.clip(((-pb / HALF_VIEW_PC + 1) / 2 * n).astype(int), 0, n - 1)
    pixel_sr = (2 * HALF_VIEW_PC / n / depth) ** 2
    np.add.at(
        painted, iy * n + ix, seen * views.AT_TEN_PC / distance[:, None] ** 2 / pixel_sr
    )
    return {k: x.reshape(n, n, 3) for k, x in got.items()}, painted.reshape(n, n, 3)


def outside() -> None:
    scene = gates.scene(B, "high")
    centre = np.array(volumes.CENTRE)
    n = 256
    face, face_regions = _render(
        scene,
        centre + np.array([0, 0, 30_000.0]),
        np.array([0, 1.0, 0]),
        np.array([1.0, 0, 0]),
        n,
    )
    edge, edge_regions = _render(
        scene,
        centre + np.array([0, -30_000.0, 0]),
        np.array([-1.0, 0, 0]),
        np.array([0, 0, 1.0]),
        n,
    )
    np.savez(
        B / "explore" / "outside_render.npz",
        **{f"face_{k}": v for k, v in face.items()},
        **{f"edge_{k}": v for k, v in edge.items()},
        face_regions=face_regions,
        edge_regions=edge_regions,
    )
    refs = {
        "NGC 6744 (ESO), private": Image.open(REF / "eso1118a_ngc6744.jpg"),
        "NGC 891 (KPNO/NOIRLab), private": Image.open(REF / "iotw2023a_ngc891.jpg"),
    }
    fig, axes = plt.subplots(2, 4, figsize=(24, 12), facecolor=DARK)
    for row, (got, painted, name) in enumerate(
        ((face, face_regions, "face-on"), (edge, edge_regions, "edge-on"))
    ):
        without = got["direct"]
        extra = got["scattered"] + got["halpha"] + painted
        with_ = without + extra
        top = np.percentile((with_ @ gates.LUMA), 99.7)
        extra_top = np.percentile(extra @ gates.LUMA, 99.7)
        panels = (
            (without, top, f"{name}, 30 kpc: starlight only"),
            (with_, top, f"{name}: + scattered light, H-alpha, WISE regions"),
            (
                extra,
                extra_top,
                f"{name}: scattered light and H-alpha alone, own stretch",
            ),
        )
        for col, (image, scale, title) in enumerate(panels):
            shown = np.clip(np.arcsinh(image / (scale / 30)) / np.arcsinh(30), 0, 1)
            axes[row, col].imshow(shown, interpolation="nearest")
            axes[row, col].set_title(title, color=INK, fontsize=10)
            axes[row, col].axis("off")
        ref_name, ref = list(refs.items())[row]
        axes[row, 3].imshow(ref)
        axes[row, 3].set_title(ref_name, color=INK, fontsize=10)
        axes[row, 3].axis("off")
    fig.tight_layout()
    fig.savefig(OUT / "emission_outside.png", dpi=80, facecolor=DARK)


def wise() -> None:
    found = build.read_regions(B)
    g = found["position"] - np.array(volumes.CENTRE)
    fig, axes = plt.subplots(1, 2, figsize=(15, 7), facecolor="white")
    names = ("radio", "infrared", "size")
    for i, (name, colour) in enumerate(
        zip(names, (OURS, PUBLISHED, THIRD), strict=True)
    ):
        m = found["source"] == i
        axes[0].scatter(
            g[m, 1] / 1e3,
            g[m, 0] / 1e3,
            s=4 + 3 * np.log10(found["rate"][m] / 1e46).clip(0),
            c=colour,
            label=f"{name} ({m.sum()})",
            alpha=0.8,
            linewidths=0,
        )
    axes[0].scatter(
        [0], [-geometry_r0() / 1e3], marker="*", s=120, c="#111", label="Sun"
    )
    axes[0].set_aspect("equal")
    axes[0].set_xlabel("y (kpc), to l = 90")
    axes[0].set_ylabel("x (kpc) from the centre, to the Sun at -8.3")
    axes[0].set_title(
        "WISE V3.0 regions with a distance, outside 1.25 kpc: luminosity source"
    )
    axes[0].legend(frameon=False)
    axes[0].grid(color="#e6e6e6", linewidth=0.6)
    l_deg = (
        np.degrees(np.arctan2(found["position"][:, 1], found["position"][:, 0])) % 360
    )
    first = (found["source"] == 0) & (l_deg > 18) & (l_deg < 65)
    rate = found["rate"][first]
    bins = np.arange(45, 51.01, 0.25)
    counts, edges = np.histogram(np.log10(rate), bins)
    centres = 0.5 * (edges[1:] + edges[:-1])
    axes[1].step(
        centres,
        counts,
        where="mid",
        color=OURS,
        linewidth=2,
        label="this build, radio, 18 < l < 65",
    )
    raw = json.loads((B / gates.GATES_DIR / "wise.json").read_text())[
        "luminosity_function"
    ]
    lowest = 10.0**gates.MASCOOP_COMPLETE_LOG
    own = raw["above_own_peak"]
    fits = (
        (
            raw["alpha"],
            gates.MASCOOP_COMPLETE_LOG,
            OURS,
            f"fit above 47.6: {raw['alpha']:.2f}",
        ),
        (
            own["alpha"],
            own["log_rate"],
            THIRD,
            f"fit above own peak {own['log_rate']:.2f}: {own['alpha']:.2f}",
        ),
        (
            gates.MASCOOP_ALPHA[0],
            gates.MASCOOP_COMPLETE_LOG,
            PUBLISHED,
            "Mascoop 2021: -1.75",
        ),
    )
    for alpha, start, colour, label in fits:
        above = counts[centres >= start].sum()
        # dN/dlogL ~ L^(alpha + 1), normalised to the count above completeness.
        x = np.linspace(start, 51, 50)
        shape = 10 ** ((alpha + 1) * (x - start))
        width = bins[1] - bins[0]
        norm = above / (shape.sum() * (x[1] - x[0]) / width)
        axes[1].plot(
            x,
            shape * norm,
            color=colour,
            linewidth=2,
            linestyle="--" if colour == PUBLISHED else "-",
            label=label,
        )
    axes[1].axvline(np.log10(lowest), color="#999", linewidth=1)
    axes[1].set_yscale("log")
    axes[1].set_xlabel("log10 Lyman continuum rate (s^-1)")
    axes[1].set_ylabel("regions per 0.25 dex")
    axes[1].set_title("Luminosity function above completeness (grey line)")
    axes[1].legend(frameon=False)
    axes[1].grid(color="#e6e6e6", linewidth=0.6)
    fig.tight_layout()
    fig.savefig(OUT / "emission_wise.png", dpi=90)


def geometry_r0() -> float:
    from space_map_data.galaxy.geometry import R0

    return R0


def bands() -> None:
    raw = json.loads((B / gates.GATES_DIR / "scatter.json").read_text())["leinert"]
    names = list(raw)
    x = np.arange(len(names))
    fig, ax = plt.subplots(figsize=(10, 5), facecolor="white")
    ours = [raw[k]["blue_464nm"] for k in names]
    theirs = [raw[k]["leinert_440nm"] for k in names]
    errors = [raw[k]["leinert_error"] or 0 for k in names]
    ax.plot(
        x,
        ours,
        color=OURS,
        linewidth=2,
        marker="o",
        markersize=8,
        label="this build, 464 nm channel, from the Sun",
    )
    ax.errorbar(
        x,
        theirs,
        yerr=errors,
        color=PUBLISHED,
        linewidth=2,
        marker="s",
        markersize=8,
        capsize=4,
        label="Leinert 1998 Table 39, 440 nm",
    )
    ax.set_xticks(x, [k.replace("abs(b) ", "|b| ") for k in names])
    ax.set_ylabel("scattered over direct starlight")
    ax.set_ylim(0, max(max(ours), max(theirs)) * 1.25)
    ax.set_title("Diffuse Galactic light over line-of-sight starlight, by latitude")
    ax.grid(axis="y", color="#e6e6e6", linewidth=0.6)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(OUT / "emission_scatter_bands.png", dpi=100)


# Lanes (l, b, radius) and the ring about each that they are compared with.
LANES = {
    "Aquila rift": (30.0, 3.0, 3.0),
    "Ophiuchus / Pipe": (0.0, 8.0, 3.0),
    "Taurus": (172.0, -15.0, 4.0),
    "Coalsack": (301.0, -1.0, 2.0),
}


def mellinger_gate() -> None:
    """Gate 6, private: the Sun's sky against Mellinger for structure, colour ratio
    and lane contrast. Mellinger's channels are each calibrated to V on catalogue
    stars, so an A0 star reads equal in all three; ours are compared relative to
    the display colour of an A0 star."""
    from space_map_data.glow.colour import planckian_rgb

    nside = 128
    parts = gates.sun_parts(B, "high", 8, nside)
    without = parts["direct"]
    with_ = without + parts["scattered"] + parts["halpha"] + parts["regions"]
    mell = _mellinger(720)
    a0 = planckian_rgb(np.array([9600.0]))[0]
    pix = car_pixels(nside, 720)
    lat = 90.0 - (np.arange(360) + 0.5) / 360 * 180.0
    absb = np.abs(lat)[:, None] * np.ones((1, 720))
    lon = (180.0 - (np.arange(720) + 0.5) / 720 * 360.0) % 360
    lon = np.ones((360, 1)) * lon[None, :]
    maps = {
        "ours without": without[pix] / S10,
        "ours with": with_[pix] / S10,
        "Mellinger": mell,
    }
    result = {"bands": {}, "lanes": {}, "structure": {}}
    for lo, hi in ((0, 5), (5, 10), (10, 30), (30, 60), (60, 90)):
        m = (absb >= lo) & (absb < hi)
        row = {}
        for name, image in maps.items():
            mean = image[m].mean(axis=0)
            ref = np.ones(3) if name == "Mellinger" else a0
            row[name] = {
                "g_s10": round(float(mean[1]), 1),
                "b_over_r_vs_a0": round(
                    float((mean[2] / mean[0]) / (ref[2] / ref[0])), 3
                ),
            }
        result["bands"][f"abs(b) {lo}-{hi}"] = row
    for name, (l0, b0, r) in LANES.items():
        dl = (lon - l0 + 180) % 360 - 180
        db = np.ones((1, 720)) * lat[:, None] - b0
        dist = np.hypot(dl * np.cos(np.radians(b0)), db)
        inside, ring = dist <= r, (dist > 1.5 * r) & (dist <= 2.5 * r)
        result["lanes"][name] = {
            label: round(
                float(
                    (image[inside] @ gates.LUMA).mean()
                    / (image[ring] @ gates.LUMA).mean()
                ),
                3,
            )
            for label, image in maps.items()
        }
    # How red the bright nebulae are against their surroundings: R/G in a disc over
    # R/G in a ring at 1.5 to 2.5 radii, less 1.
    result["nebula_red_excess"] = {}
    for name, (l0, b0, r) in {**gates.NAMED, "M8": (5.97, -1.18, 0.75)}.items():
        if r > 5:
            continue
        dl = (lon - l0 + 180) % 360 - 180
        db = np.ones((1, 720)) * lat[:, None] - b0
        dist = np.hypot(dl * np.cos(np.radians(b0)), db)
        r = max(r, 0.75)
        inside, ring = dist <= r, (dist > 1.5 * r) & (dist <= 2.5 * r)
        row = {}
        for label, image in maps.items():
            disc, around = image[inside].mean(axis=0), image[ring].mean(axis=0)
            row[label] = round(
                float((disc[0] / disc[1]) / (around[0] / around[1]) - 1), 3
            )
        result["nebula_red_excess"][name] = row
    for name in ("ours without", "ours with"):
        for lo, hi in ((0, 30), (30, 90)):
            m = (absb >= lo) & (absb < hi)
            a = np.log10(np.maximum(maps[name][m] @ gates.LUMA, 1e-3))
            b = np.log10(np.maximum(mell[m] @ gates.LUMA, 1e-3))
            result["structure"][f"{name}, abs(b) {lo}-{hi}"] = round(
                float(np.corrcoef(a, b)[0, 1]), 3
            )
    (B / gates.GATES_DIR / "mellinger.json").write_text(json.dumps(result, indent=1))
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    steps = {
        "halpha": halpha,
        "sun": sun,
        "outside": outside,
        "wise": wise,
        "bands": bands,
        "mellinger": mellinger_gate,
    }
    for name in sys.argv[1:]:
        steps[name]()
