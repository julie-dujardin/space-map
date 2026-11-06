"""Images of the dust from outside the Galaxy.

    uv run --with matplotlib python scripts/outside_plots.py far
    uv run --with matplotlib python scripts/outside_plots.py looks:before:<root> spokes

`far` renders the disc edge-on through the nest, with and without the far volume,
as `outside_far_dust_edge.png`. `looks:<tag>:<root>` renders the light of the
current builds through the nest and far volume below `root`, face-on from 30 kpc
and from 8 kpc above the Sun, and keeps the images in `outside-build/`. Render
`before` ahead of a rebuild; `spokes` renders `after` from the served nest and
draws `outside_spokes_*.png`, with the rest layer's face-on column of the backup
and of the build.
"""

import sys
from pathlib import Path

import numpy as np

from space_map_data.dust.far import StoredFar
from space_map_data.dust.parallel import forked_stream
from space_map_data.galaxy import build as model_build
from space_map_data.galaxy import residual
from space_map_data.galaxy.geometry import R0, Z0
from space_map_data.glow import build, light, sky_map
from space_map_data.utils.paths import CACHE_DIR, EXTRASOLAR_DIR

OUT = CACHE_DIR / "milky-way-3d"
WORK = OUT / "outside-build"
MODEL = model_build.BUILD_DIR
BACKUP = MODEL / "backup-phase4b"
LUMA = np.array((0.2126, 0.7152, 0.0722))

_render = None


def _rows(job: tuple[int, int]) -> np.ndarray:
    assert _render is not None
    return _render(*job)


def render(
    points_of, depth, sources_of_light, dusts, rows, columns, workers=8, slant_of=None
):
    """Images (len(dusts), rows, columns, 3) in flux per sr.

    `points_of(i, d)` gives the (columns, 3) points of row i at depth d, and the ray
    runs through `depth` in order. `slant_of(i)` is the path per unit of depth of
    each ray of row i, 1 for parallel rays. Each dust reader dims the same light."""
    global _render
    steps = np.abs(np.gradient(depth))

    def one(start: int, stop: int) -> np.ndarray:
        out = np.zeros((len(dusts), stop - start, columns, 3))
        for i in range(start, stop):
            seen = np.ones((len(dusts), columns, 3))
            total = np.zeros((len(dusts), columns, 3))
            slant = np.ones(columns) if slant_of is None else slant_of(i)
            for d, step in zip(depth, steps, strict=True):
                points = points_of(i, d)
                ds = (step * slant)[:, None]
                emission = sources_of_light(points) * ds
                for k, dust in enumerate(dusts):
                    tau = dust(points).astype(np.float64)[:, None] * ds * light.K_RGB
                    through = 10.0 ** (-0.4 * tau)
                    mean = np.where(
                        tau > 1e-4,
                        (1 - through) / np.maximum(0.4 * np.log(10) * tau, 1e-12),
                        1.0,
                    )
                    total[k] += emission * seen[k] * mean
                    seen[k] *= through
            out[:, i - start] = total
        return out

    _render = one
    jobs = [(s, min(s + 2, rows)) for s in range(0, rows, 2)]
    image = np.concatenate(list(forked_stream(_rows, jobs, workers)), axis=1)
    _render = None
    return image


def tone(image: np.ndarray, white: float) -> np.ndarray:
    """asinh on luminance, colour kept, then sRGB."""
    lum = image @ LUMA
    scale = np.arcsinh(lum / white) / np.maximum(lum / white, 1e-12) / np.arcsinh(50.0)
    rgb = np.clip(image / white * scale[..., None], 0, 1)
    return np.where(rgb <= 0.0031308, 12.92 * rgb, 1.055 * rgb ** (1 / 2.4) - 0.055)


def render_light():
    raw = model_build.read_encoding(MODEL, build.BUILD_DIR)
    fade = raw.get("catalogue_fade_pc")
    residual.CATALOGUE_FADE_PC = tuple(fade) if fade else None
    stored = residual.StoredResidual.load(MODEL, "high")
    grid = residual.CatalogueGrid.load(build.BUILD_DIR, "high")

    def read(points):
        weight = residual.catalogue_weight(np.linalg.norm(points, axis=1))[:, None]
        return grid.read(points) * weight + stored.read(points)

    return read


def dust_readers(root: Path):
    nest = sky_map.load_nest(root=root)
    stored = StoredFar.load(root)

    def nest_only(points):
        return sky_map.density(nest, points)

    def with_far(points):
        return sky_map.density(nest, points) + stored.read(points)

    return nest_only, with_far, stored


def far(workers: int = 8) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pixel = 25.0
    x0, x1 = -16000.0, 24000.0
    columns = round((x1 - x0) / pixel)
    rows = round(5000.0 / pixel)
    across = x0 + (np.arange(columns) + 0.5) * pixel
    up = 2500.0 - (np.arange(rows) + 0.5) * pixel
    depth = np.linspace(32000.0, -32000.0, 1281)

    def points_of(i, d):
        return np.column_stack(
            (R0 + across, np.full(columns, d), np.full(columns, up[i] - Z0))
        )

    path = WORK / "far_edge.npy"
    nest_only, with_far, stored = dust_readers(EXTRASOLAR_DIR)
    if path.exists():
        images = np.load(path)
    else:
        images = render(
            points_of,
            depth,
            render_light(),
            (nest_only, with_far),
            rows,
            columns,
            workers,
        )
        np.save(path, images)
    # The column through y of the far volume alone, for the third panel.
    column = np.zeros((rows, columns))
    for i in range(rows):
        for d in depth:
            column[i] += stored.read(points_of(i, d)) * 50.0
    fig, axes = plt.subplots(
        3, 1, figsize=(22, 9.6), facecolor="#101114", layout="constrained"
    )
    white = np.percentile(images[0] @ LUMA, 99.5)
    ext = (x0 / 1000, x1 / 1000, -2.5, 2.5)
    titles = (
        "before: render light through the nest",
        "after: render light through the nest and the far volume",
    )
    for ax, image, title in zip(axes[:2], images, titles, strict=True):
        ax.imshow(tone(image, white), extent=ext, aspect="auto")
        ax.axvline((20000.0 - R0) / 1000, color="cyan", lw=0.6, ls=":")
        ax.set_title(
            title + "; edge-on from +y, Galactic centre at 0, the Sun at -8.3,"
            " cyan: face of level 0",
            color="white",
        )
        ax.tick_params(colors="white")
    shown = axes[2].imshow(
        np.log10(column + 1e-4),
        extent=ext,
        aspect="auto",
        cmap="magma",
        vmin=-3,
        vmax=0.5,
    )
    axes[2].set_title("log10 A0 through y of the far volume alone (mag)", color="white")
    axes[2].tick_params(colors="white")
    bar = fig.colorbar(shown, ax=axes[2], fraction=0.02, pad=0.01)
    bar.ax.tick_params(colors="white")
    fig.savefig(OUT / "outside_far_dust_edge.png", dpi=80)
    plt.close(fig)


FACE = (58_000.0, 49_000.0, 100.0)
ABOVE_PC = 8000.0
ABOVE_HALF_ANGLE = np.radians(55.0)
ABOVE_PIXELS = 480


def _face_view():
    width, height, pixel = FACE
    columns, rows = round(width / pixel), round(height / pixel)
    across = (np.arange(columns) + 0.5) * pixel - width / 2
    up = height / 2 - (np.arange(rows) + 0.5) * pixel
    depth = 2.0 * np.sinh(np.linspace(np.arcsinh(7500.0), -np.arcsinh(7500.0), 361))

    def points_of(i, d):
        return np.column_stack(
            (R0 + across, np.full(columns, up[i]), np.full(columns, d - Z0))
        )

    return points_of, depth, rows, columns


def _above_view():
    """A camera 8 kpc above the Sun looking down. Depth is the drop below the
    camera, fine near the plane. Image up is +x, toward the centre."""
    n = ABOVE_PIXELS
    t = np.tan(ABOVE_HALF_ANGLE) * ((np.arange(n) + 0.5) / n * 2.0 - 1.0)
    heights = 50.0 * np.sinh(
        np.linspace(np.arcsinh(7950.0 / 50.0), np.arcsinh(-7950.0 / 50.0), 401)
    )
    depth = ABOVE_PC - heights

    def points_of(i, d):
        return np.column_stack(
            (np.full(n, t[n - 1 - i] * d), -t * d, np.full(n, ABOVE_PC - d))
        )

    def slant_of(i):
        return np.sqrt(1.0 + t[n - 1 - i] ** 2 + t * t)

    return points_of, depth, n, n, slant_of


def looks(tag: str, root: Path, workers: int = 8) -> None:
    _, with_far, _ = dust_readers(root)
    light_of = render_light()
    points_of, depth, rows, columns = _face_view()
    face = render(points_of, depth, light_of, (with_far,), rows, columns, workers)
    np.save(WORK / f"look_face_{tag}.npy", face[0])
    points_of, depth, rows, columns, slant_of = _above_view()
    above = render(
        points_of, depth, light_of, (with_far,), rows, columns, workers, slant_of
    )
    np.save(WORK / f"look_above_{tag}.npy", above[0])


def _face_column(directory: Path) -> np.ndarray:
    from space_map_data.dust.nest import LEVELS

    rest = np.load(directory / "l0.rest.npy", mmap_mode="r")
    return np.asarray(rest).sum(axis=2) * LEVELS[0].voxel[2]


def spokes() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from space_map_data.dust.merge import merged_dir
    from space_map_data.galaxy import geometry

    if not (WORK / "look_face_after.npy").exists():
        looks("after", EXTRASOLAR_DIR)
    before_column = np.load(WORK / "face.current.npy")
    after_column = _face_column(merged_dir("open"))
    n = 600
    grid = np.linspace(-20000, 20000, n)
    gx, gy = np.meshgrid(grid, grid, indexing="xy")
    R, beta, _ = geometry.galactocentric(gx.ravel(), gy.ravel(), np.zeros(n * n))
    field = geometry.arm_field(R, beta).reshape(n, n)
    fig, axes = plt.subplots(
        1, 2, figsize=(18, 8.6), facecolor="#101114", layout="constrained"
    )
    for ax, values, title in (
        (axes[0], before_column, "before"),
        (axes[1], after_column, "after"),
    ):
        shown = ax.imshow(
            np.log10(values.T + 1e-4),
            origin="lower",
            extent=(-20, 20, -20, 20),
            cmap="magma",
            vmin=-2,
            vmax=1.5,
        )
        ax.contour(
            grid / 1000, grid / 1000, field, levels=[0.6], colors="cyan", linewidths=0.6
        )
        ax.plot(0, 0, "w*", ms=10)
        ax.plot(R0 / 1000, 0, "w+", ms=12)
        ax.set_title(
            f"{title}: rest layer A0 column face-on, level 0 (log10 mag); cyan: young arm ridges",
            color="white",
        )
        ax.tick_params(colors="white")
        bar = fig.colorbar(shown, ax=ax, fraction=0.04, pad=0.01)
        bar.ax.tick_params(colors="white")
    fig.savefig(OUT / "outside_spokes_column.png", dpi=80)
    plt.close(fig)
    width, height, _ = FACE
    for view, extent, marker in (
        (
            "face",
            (-width / 2000, width / 2000, -height / 2000, height / 2000),
            (-R0 / 1000, 0.0),
        ),
        ("above", None, None),
    ):
        images = [
            np.load(WORK / f"look_{view}_{tag}.npy") for tag in ("before", "after")
        ]
        white = np.percentile(images[0] @ LUMA, 99.0)
        fig, axes = plt.subplots(
            1, 2, figsize=(18, 8.6), facecolor="#101114", layout="constrained"
        )
        for ax, image, tag in zip(axes, images, ("before", "after"), strict=True):
            ax.imshow(tone(image, white), extent=extent, origin="upper")
            if marker is not None:
                ax.plot(*marker, marker="*", color="cyan", ms=8)
                ax.set_xlabel("kpc", color="white")
            title = (
                "face-on from 30 kpc, render light through nest and far volume"
                if view == "face"
                else "from 8 kpc above the Sun, 110 deg, centre up"
            )
            ax.set_title(f"{tag}: {title}", color="white")
            ax.tick_params(colors="white")
        fig.savefig(OUT / f"outside_spokes_{view}.png", dpi=80)
        plt.close(fig)


if __name__ == "__main__":
    for step in sys.argv[1:]:
        if step == "far":
            far()
        elif step.startswith("looks:"):
            _, tag, root = step.split(":", 2)
            looks(tag, Path(root))
        elif step == "spokes":
            spokes()
