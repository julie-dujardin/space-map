"""The disc layer: Bayestar19 north, and DECaPS (Zucker 2025) where it has data.

Both maps give a cumulative E at 120 distances per pixel. DECaPS is float16, so
some differences between neighbouring distances come out negative. The layer
averages the signed differences to Nside 256 before it clips at zero, so the
rounding noise cancels. A fit to the Edenhofer maps in the overlap converts each
map to A0 at 550 nm.

A fine pixel counts only in its reliable range. Below `DM_reliable_min` a map has
too few stars to place the dust, and past `DM_reliable_max` too few to measure it.
The fit takes the mean column of the same pixels, so the gain and the layer use one
share.
"""

import json
import logging
import os
from pathlib import Path

import h5py
import numpy as np
from cdshealpix import nested

from space_map_data.dust import nest
from space_map_data.dust.nest import LEVELS, fade_out, smoothstep
from space_map_data.dust.resample import fill, pixels
from space_map_data.dust.sources import BUILD_DIR, NSIDE_EDENHOFER, SOURCE_DIR
from space_map_data.utils.paths import SOURCES_DUST_MAPS_DIR

logger = logging.getLogger(__name__)

DISC_DIR = BUILD_DIR / "disc"
# The levels the layer is built for. At level 3 it holds no dust.
DISC_LEVELS = LEVELS[:3]
REDUCED_DIR = DISC_DIR / "reduced"
CALIBRATION_FILE = DISC_DIR / "calibration.json"
DEPTH = int(np.log2(NSIDE_EDENHOFER))
PIXELS = 12 * NSIDE_EDENHOFER**2
NODES_DM = 4.0 + 0.125 * np.arange(120)
NODES_PC = 10.0 ** (NODES_DM / 5.0 + 1.0)
BINS = len(NODES_DM) - 1
# DM over which a fine pixel fades in above its reliable minimum, and out up to
# its reliable maximum.
RELIABLE_BAND = 0.5
# A reliable minimum that is not finite comes with no reliable range.
NO_RANGE_DM = 99.0
# Rings of Nside 256 pixels, about 1 deg, over which a footprint fades at its edge.
FOOTPRINT_RINGS = 5
BAYESTAR_BLOCK = 16462 * 8
DECAPS_BLOCK = 200842
POINTS = {0: 4, 1: 4, 2: 4}
# The reference map, then the shell in distance modulus. DM 4.0 is the first node
# of the disc maps.
SHELLS = (
    ("e24", 4.0, 9.0),
    ("e24", 4.0, 10.0),
    ("e24", 4.0, 10.375),
    ("e2k", 4.0, 10.0),
    ("e2k", 4.0, 11.0),
    ("e2k", 4.0, 11.375),
    ("e2k", 10.0, 11.375),
)
# A star gives a column to its distance, so a column from the first node holds the
# scale. This one ends at the hand-over.
FIT_SHELL = "e2k DM 4.0-11.375"
FIT_LATITUDE = 20.0
# Edenhofer's reliable extinction range, in mag.
FIT_COLUMNS = (0.05, 4.0)
MIN_COVER = 0.9
LATITUDE_BANDS = ((0, 2), (2, 5), (5, 10), (10, 20), (20, 40), (40, 90))
COLUMN_BANDS = ((0.05, 0.2), (0.2, 0.5), (0.5, 1), (1, 2), (2, 4))


def reliable_share(dm_min: np.ndarray, dm_max: np.ndarray) -> np.ndarray:
    """The weight of each bin, shape (pixels, BINS), for one reliable range per
    pixel: 0 below the minimum and past the maximum, 1 a band inside both."""
    low = np.where(np.isfinite(dm_min), dm_min, NO_RANGE_DM)[:, None]
    high = np.where(np.isfinite(dm_max), dm_max, -1.0)[:, None]
    middles = (NODES_DM[:-1] + 0.0625)[None, :]
    rise = smoothstep((middles - low) / RELIABLE_BAND)
    return (rise * fade_out(middles, high - RELIABLE_BAND, high)).astype("f4")


def density_bins(cumulative: np.ndarray) -> np.ndarray:
    """Differences per bin of cumulative arrays, with the sign kept."""
    return np.diff(np.asarray(cumulative, dtype="f8"), axis=-1)


def clipped_density(delta: np.ndarray, widths: np.ndarray) -> np.ndarray:
    """Density per pc from differences per bin. Negative differences are noise."""
    return np.maximum(delta, 0.0) / widths


# What the reduction writes per map: the mean difference per bin, the share of
# reliable area, and the mean column from the first node to the end of each bin.
REDUCED = ("delta", "cover", "column")


def _accumulators(stem: str) -> tuple[list[np.memmap], list[Path]]:
    REDUCED_DIR.mkdir(parents=True, exist_ok=True)
    paths = [REDUCED_DIR / f"{stem}.{name}.tmp" for name in REDUCED]
    sums = [
        np.lib.format.open_memmap(path, mode="w+", dtype="f4", shape=(PIXELS, BINS))
        for path in paths
    ]
    return sums, paths


def _finish(stem: str, sums: list[np.memmap], paths: list[Path]) -> None:
    """Turn the sums into means over the reliable area, and that area's share."""
    delta, cover, column = sums
    for weighted in (delta, column):
        weighted[:] = np.divide(
            weighted, cover, out=np.zeros_like(weighted), where=cover > 0
        )
    for array in sums:
        array.flush()
    for path, name in zip(paths, REDUCED):
        os.replace(path, REDUCED_DIR / f"{stem}.{name}.npy")


def column_bins(cumulative: np.ndarray) -> np.ndarray:
    """The column from the first node to the end of each bin."""
    cumulative = np.asarray(cumulative, dtype="f8")
    return cumulative[..., 1:] - cumulative[..., :1]


def reduce_bayestar() -> None:
    path = SOURCES_DUST_MAPS_DIR / "bayestar19" / "bayestar2019.h5"
    sums, paths = _accumulators("bayestar")
    with h5py.File(path, "r") as handle:
        info = handle["pixel_info"][...]
        rows = len(info)
        for start in range(0, rows, BAYESTAR_BLOCK):
            part = info[start : start + BAYESTAR_BLOCK]
            cumulative = handle["samples"][start : start + BAYESTAR_BLOCK].mean(axis=1)
            differences = density_bins(cumulative).astype("f4")
            weights = reliable_share(part["DM_reliable_min"], part["DM_reliable_max"])
            weights[part["converged"] == 0] = 0.0
            values = (differences, column_bins(cumulative).astype("f4"))
            for nside in np.unique(part["nside"]):
                _add_bayestar(part, nside, values, weights, sums)
            logger.info("bayestar: %d of %d", start, rows)
    _finish("bayestar", sums, paths)


def _add_bayestar(part, nside, values, weights, sums) -> None:
    delta, cover, column = sums
    chosen = part["nside"] == nside
    index = part["healpix_index"][chosen].astype(np.int64)
    w = weights[chosen]
    d, c = (value[chosen] * w for value in values)
    if nside >= NSIDE_EDENHOFER:
        shift = 2 * int(np.log2(nside / NSIDE_EDENHOFER))
        area = (NSIDE_EDENHOFER / nside) ** 2
        np.add.at(delta, index >> shift, d * area)
        np.add.at(cover, index >> shift, w * area)
        np.add.at(column, index >> shift, c * area)
        return
    shift = 2 * int(np.log2(NSIDE_EDENHOFER / nside))
    for i, parent in enumerate(index):
        children = np.arange(parent << shift, (parent + 1) << shift)
        delta[children] += d[i]
        cover[children] += w[i]
        column[children] += c[i]


def reduce_decaps() -> None:
    path = SOURCES_DUST_MAPS_DIR / "decaps-2025" / "decaps_mean.h5"
    sums, paths = _accumulators("decaps")
    shift = 2 * int(np.log2(8192 / NSIDE_EDENHOFER))
    area = (NSIDE_EDENHOFER / 8192) ** 2
    with h5py.File(path, "r") as handle:
        info = handle["pixel_info"]
        index = info["healpix_index"][...].astype(np.int64)
        converged = info["converged"][...] != 0
        low = info["DM_reliable_min"][...]
        high = info["DM_reliable_max"][...]
        rows = len(index)
        for start in range(0, rows, DECAPS_BLOCK):
            stop = min(start + DECAPS_BLOCK, rows)
            cumulative = handle["mean"][start:stop, 0, :].astype("f4")
            differences = np.diff(cumulative, axis=1)
            columns = column_bins(cumulative).astype("f4")
            weights = reliable_share(low[start:stop], high[start:stop])
            weights[~converged[start:stop]] = 0.0
            bad = ~(np.isfinite(differences) & np.isfinite(columns))
            weights[bad] = 0.0
            differences[bad] = 0.0
            columns[bad] = 0.0
            parent = index[start:stop] >> shift
            first = np.flatnonzero(np.r_[True, parent[1:] != parent[:-1]])
            at = parent[first]
            # A parent may start two runs in a block when the file is not sorted.
            for target, value in zip(
                sums, (differences * weights, weights, columns * weights)
            ):
                np.add.at(
                    target,
                    at,
                    np.add.reduceat(value.astype("f8"), first, axis=0) * area,
                )
            logger.info("decaps: %d of %d", start, rows)
    _finish("decaps", sums, paths)


def footprint_edge(inside: np.ndarray, rings: int = FOOTPRINT_RINGS) -> np.ndarray:
    """A weight that falls from 1, `rings` pixels inside, to 0 at the footprint edge."""
    neighbours = nested.neighbours(np.arange(len(inside), dtype=np.uint64), DEPTH)
    # cdshealpix marks a missing neighbour with -1.
    neighbours = np.where(neighbours < 0, np.arange(len(inside))[:, None], neighbours)
    depth = np.zeros(len(inside), np.float32)
    now = inside.copy()
    for _ in range(rings):
        depth += now
        now = now & now[neighbours.astype(np.int64)].all(axis=1)
    return depth / rings


def _shell_column(stem: str, inner: float, outer: float) -> np.ndarray:
    """The Edenhofer column between two distances, per pixel."""
    edges = np.load(SOURCE_DIR / f"{stem}.edges.npy")
    mean = np.load(SOURCE_DIR / f"{stem}.mean.npy", mmap_mode="r")
    lengths = np.minimum(edges[1:], outer) - np.maximum(edges[:-1], inner)
    total = np.zeros(PIXELS)
    for ring in np.flatnonzero(lengths > 0):
        total += np.asarray(mean[ring], dtype="f8") * lengths[ring]
    return total


def ratio_stats(ratio: np.ndarray) -> dict:
    """The count, median and 16th and 84th percentiles of the finite ratios."""
    ratio = ratio[np.isfinite(ratio)]
    if len(ratio) == 0:
        return {"rays": 0}
    low, middle, high = np.percentile(ratio, (16, 50, 84))
    return {
        "rays": len(ratio),
        "median": round(float(middle), 4),
        "p16": round(float(low), 4),
        "p84": round(float(high), 4),
    }


def _fit_shell(reference, columns, cover, first, last, latitude) -> dict:
    """The ratio of the Edenhofer column over the map column, with its trends. A
    column counts where the layer's share is reliable at both of its ends."""
    column = columns[:, last - 1] - (columns[:, first - 1] if first else 0.0)
    reliable = cover[:, last - 1] >= MIN_COVER
    if first:
        reliable &= cover[:, first - 1] >= MIN_COVER
    used = reliable & (reference >= FIT_COLUMNS[0]) & (reference <= FIT_COLUMNS[1])
    used &= column > 0
    ratio = reference[used] / column[used]
    fit = ratio_stats(ratio)
    if not fit["rays"]:
        return fit
    near_plane = np.abs(latitude[used]) < FIT_LATITUDE
    fit["gain"] = ratio_stats(ratio[near_plane])["median"]
    fit["log_correlation"] = round(
        float(np.corrcoef(np.log(reference[used]), np.log(column[used]))[0, 1]), 4
    )
    b = np.abs(latitude[used])
    fit["by_latitude"] = {
        f"{low}-{high}": ratio_stats(ratio[(b >= low) & (b < high)])
        for low, high in LATITUDE_BANDS
    }
    y = reference[used]
    fit["by_column"] = {
        f"{low}-{high}": ratio_stats(ratio[(y >= low) & (y < high)])
        for low, high in COLUMN_BANDS
    }
    return fit


def calibrate() -> None:
    """Fit each map to the Edenhofer maps in the overlap and write the gains."""
    all_pixels = np.arange(PIXELS, dtype=np.uint64)
    _, latitude = nested.healpix_to_lonlat(all_pixels, DEPTH)
    latitude = latitude.to_value("deg")
    report: dict = {"maps": {}}
    gains = {}
    for stem in ("bayestar", "decaps"):
        columns = np.load(REDUCED_DIR / f"{stem}.column.npy")
        cover = np.load(REDUCED_DIR / f"{stem}.cover.npy")
        shells = {}
        for reference_stem, inner, outer in SHELLS:
            first, last = (
                int((dm - NODES_DM[0]) / 0.125 + 0.5) for dm in (inner, outer)
            )
            reference = _shell_column(reference_stem, NODES_PC[first], NODES_PC[last])
            name = f"{reference_stem} DM {inner}-{outer}"
            shells[name] = _fit_shell(reference, columns, cover, first, last, latitude)
            logger.info("%s %s: %s", stem, name, shells[name].get("median"))
        report["maps"][stem] = shells
        gains[stem] = shells[FIT_SHELL]["gain"]
    report["gains"] = gains
    report["fit_shell"] = FIT_SHELL
    CALIBRATION_FILE.write_text(json.dumps(report, indent=1))


class DiscSampler:
    """The disc density at a point, and the share of the disc at that point."""

    def __init__(self, gain_bayestar: float, gain_decaps: float):
        self.widths = np.diff(NODES_PC).astype("f4")
        self.maps = []
        for stem, gain in (("decaps", gain_decaps), ("bayestar", gain_bayestar)):
            delta = np.load(REDUCED_DIR / f"{stem}.delta.npy", mmap_mode="r")
            cover = np.load(REDUCED_DIR / f"{stem}.cover.npy", mmap_mode="r")
            edge = np.load(REDUCED_DIR / f"{stem}.edge.npy")
            self.maps.append((delta, cover, edge, gain))

    def __call__(self, x, y, z):
        lon, lat, r = nest.lonlat(x, y, z)
        pixel = pixels(lon, lat, DEPTH)
        rung = np.floor((5.0 * np.log10(r / 10.0) - NODES_DM[0]) / 0.125).astype(
            np.int32
        )
        inside = (rung >= 0) & (rung < BINS)
        before = nest.local_weight(r)
        before = (1.0 - before) * (1.0 - nest.regional_weight(r))
        value = np.zeros(len(x), np.float32)
        share = np.zeros(len(x), np.float32)
        left = np.ones(len(x), np.float32)
        p, b = pixel[inside], rung[inside]
        widths = self.widths[b]
        for delta, cover, edge, gain in self.maps:
            here = np.asarray(cover[p, b]) * edge[p] * left[inside]
            value[inside] += here * gain * clipped_density(delta[p, b], widths)
            share[inside] += here
            left[inside] -= here
        return before * value, before * share


def build_edges() -> None:
    """Write the edge weight of each footprint, from the area each map covers."""
    for stem in ("bayestar", "decaps"):
        cover = np.load(REDUCED_DIR / f"{stem}.cover.npy", mmap_mode="r")
        inside = np.asarray(cover.max(axis=1)) >= 0.5
        np.save(REDUCED_DIR / f"{stem}.edge.npy", footprint_edge(inside))


def build_disc(workers: int) -> None:
    gains = json.loads(CALIBRATION_FILE.read_text())["gains"]
    build_edges()
    sampler = DiscSampler(gains["bayestar"], gains["decaps"])
    reach = (nest.REGIONAL_FADE[0], np.inf)
    for level in DISC_LEVELS:
        fill(level, DISC_DIR, sampler, POINTS[level.index], workers, reach)
        logger.info("disc: level %d done", level.index)
