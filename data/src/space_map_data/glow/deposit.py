"""Stream the tree once: the light of every star into the grid, by magnitude.

Each worker reads a batch of nodes and returns the sums of its voxels. The sums join
in batch order, so a rerun gives the same floats whatever the worker count.
"""

import zlib
from dataclasses import dataclass, field

import numpy as np

from space_map_data.dust.parallel import forked_stream
from space_map_data.dust.resample import points_pixels
from space_map_data.glow import colour, form, light, sky_map, tree
from space_map_data.glow.grid import SkyGrid

BATCH_NODES = 256
# Stars this bright stay in the sample, and a share of the rest.
SAMPLE_BRIGHT = -2.0
SAMPLE_KEEP = 8
# The limit near the Sun, and the sky of the gate that reads it: about 0.9 deg.
SUN_LIMIT = 7.5
SKY_DEPTH = 6
SKY_PIXELS = 12 * 4**SKY_DEPTH


@dataclass
class Totals:
    """Sums over all stars, in display flux per channel at 10 pc."""

    rows: int = 0
    light: np.ndarray = field(default_factory=lambda: np.zeros(3))
    observed: np.ndarray = field(default_factory=lambda: np.zeros(3))
    capped_rows: int = 0
    capped_light: np.ndarray = field(default_factory=lambda: np.zeros(3))
    no_colour_rows: int = 0

    def add(self, other: Totals) -> None:
        self.rows += other.rows
        self.light += other.light
        self.observed += other.observed
        self.capped_rows += other.capped_rows
        self.capped_light += other.capped_light
        self.no_colour_rows += other.no_colour_rows


# Forked workers read these.
_grids: list[SkyGrid] = []
_edges: np.ndarray | None = None
_sky: np.ndarray | None = None
_rotation: np.ndarray | None = None
_skip: dict[str, np.ndarray] = {}


@dataclass(frozen=True)
class Batch:
    # For each grid, the sorted flat indices of [voxel, bin], and their light.
    voxels: tuple[tuple[np.ndarray, np.ndarray], ...]
    totals: Totals
    # float32 rows: position (3), mag, colour, column, weight.
    sample: np.ndarray
    # The light of all stars by curve bin, per channel.
    curve: np.ndarray
    # Observed flux per sky pixel and channel of stars fainter than the Sun's limit.
    observed: np.ndarray


def _sums(index: np.ndarray, flux: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    unique, inverse = np.unique(index, return_inverse=True)
    sums = np.stack(
        [np.bincount(inverse, flux[:, c], len(unique)) for c in range(3)], axis=1
    )
    return unique, sums


def _batch(names: list[str]) -> Batch:
    assert _edges is not None and _sky is not None and _rotation is not None
    bins = len(_edges) + 1
    indices: list[list[np.ndarray]] = [[] for _ in _grids]
    fluxes = []
    samples = []
    totals = Totals()
    origin = np.zeros(3)
    curve = np.zeros((len(form.curve_points()) - 1, 3))
    observed = np.zeros((SKY_PIXELS, 3))
    for name in names:
        node = tree.read_node(name)
        keep = np.ones(len(node.mag), bool)
        if name in _skip:
            keep[_skip[name]] = False
        points = node.position[keep] @ _rotation
        mag = node.mag[keep]
        bp_rp = node.colour[keep]
        column = sky_map.read_map(_sky, origin, points).astype(np.float64)
        taken = light.taken_out(column, bp_rp, mag)
        m0 = light.dust_free_magnitude(mag, taken)
        tint = colour.star_colours(bp_rp)
        flux = light.star_flux(mag, tint, taken)
        capped = column > taken
        totals.rows += len(mag)
        totals.light += flux.sum(axis=0)
        totals.observed += (tint * 10.0 ** (-0.4 * mag)[:, None]).sum(axis=0)
        totals.capped_rows += int(capped.sum())
        totals.capped_light += flux[capped].sum(axis=0)
        totals.no_colour_rows += int(np.isnan(bp_rp).sum())
        for g, grid in enumerate(_grids):
            indices[g].append(
                grid.voxel_of(points) * bins + np.searchsorted(_edges, m0)
            )
        fluxes.append(flux)
        k = form.curve_bin(m0)
        for c in range(3):
            curve[:, c] += np.bincount(k, flux[:, c], len(curve))
        faint, pixel, seen = _seen_from_sun(points, mag, tint)
        if faint:
            for c in range(3):
                observed[:, c] += np.bincount(pixel, seen[:, c], SKY_PIXELS)
        rng = np.random.default_rng(zlib.crc32(name.encode()))
        bright = m0 < SAMPLE_BRIGHT
        chosen = bright | (rng.random(len(m0)) < 1 / SAMPLE_KEEP)
        samples.append(
            np.column_stack(
                (
                    points[chosen],
                    mag[chosen],
                    bp_rp[chosen],
                    column[chosen],
                    np.where(bright[chosen], 1.0, float(SAMPLE_KEEP)),
                )
            ).astype(np.float32)
        )
    flux = np.concatenate(fluxes)
    voxels = tuple(_sums(np.concatenate(part), flux) for part in indices)
    return Batch(voxels, totals, np.concatenate(samples), curve, observed)


def _seen_from_sun(
    points: np.ndarray, mag: np.ndarray, tint: np.ndarray
) -> tuple[int, np.ndarray, np.ndarray]:
    """The pixel and observed flux of stars the tree leaves out at the Sun's limit."""
    r = np.linalg.norm(points, axis=1)
    apparent = mag + 5 * np.log10(np.maximum(r, 1e-6) / 10)
    faint = apparent > SUN_LIMIT
    return (
        int(faint.sum()),
        points_pixels(points[faint], SKY_DEPTH),
        tint[faint] * 10.0 ** (-0.4 * apparent[faint])[:, None],
    )


@dataclass
class Deposit:
    # For each grid, the light of each voxel by bin of M0, in flux at 10 pc, shape
    # (*grid.shape, bins, 3). Bin k holds M0 in (edge[k - 1], edge[k]].
    cubes: list[np.ndarray]
    totals: Totals
    sample: np.ndarray
    curve: np.ndarray
    observed: np.ndarray


def deposit(
    grids: list[SkyGrid],
    edges: np.ndarray,
    sky: np.ndarray,
    rotation: np.ndarray,
    workers: int,
    skip: dict[str, np.ndarray] | None = None,
    names: list[str] | None = None,
) -> Deposit:
    """One pass over the tree into every grid. `skip` gives rows of a node that are
    left out."""
    global _grids, _edges, _sky, _rotation, _skip
    bins = len(edges) + 1
    all_names = tree.node_names() if names is None else names
    batches = [
        all_names[at : at + BATCH_NODES] for at in range(0, len(all_names), BATCH_NODES)
    ]
    cubes = [np.zeros((int(np.prod(g.shape)), bins, 3)) for g in grids]
    totals = Totals()
    sample = []
    curve = np.zeros((len(form.curve_points()) - 1, 3))
    observed = np.zeros((SKY_PIXELS, 3))
    _grids, _edges, _sky, _rotation = grids, edges, sky, rotation
    _skip = skip or {}
    try:
        for batch in forked_stream(_batch, batches, workers):
            for cube, (index, flux) in zip(cubes, batch.voxels, strict=True):
                voxel, k = np.divmod(index, bins)
                cube[voxel, k] += flux
            totals.add(batch.totals)
            sample.append(batch.sample)
            curve += batch.curve
            observed += batch.observed
    finally:
        _grids, _edges, _sky, _rotation, _skip = [], None, None, None, {}
    return Deposit(
        [c.reshape(*g.shape, bins, 3) for c, g in zip(cubes, grids, strict=True)],
        totals,
        np.concatenate(sample),
        curve,
        observed,
    )
