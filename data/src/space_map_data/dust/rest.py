"""The rest layer: a flagged model for the dust past the observed maps.

It copies the method of Drimmel et al. 2003. Each sightline holds the Planck total
minus the observed column, clipped at zero, along a dust disc with arms. The disc
shares the young light's arms, warp and flare (`galaxy.geometry`), so lanes sit on
the arms of the model light.

The scale of a sightline has two parts. A base, smooth on the sky, holds the far
part of its room. The sightline's own factor holds the near part of its room, so
the column from the Sun is still that of the sightline. From outside, the far disc
then shows no radial spokes. The spokes stay near the edge of the observed maps.
"""

import json
import logging

import numpy as np
from astropy import units as u
from astropy.coordinates import Latitude, Longitude
from cdshealpix import nested
from scipy.ndimage import gaussian_filter, map_coordinates

from space_map_data.dust import nest
from space_map_data.dust.march import Stack, integrate, segments
from space_map_data.dust.merge import build_observed, merged_dir
from space_map_data.dust.nest import LEVELS, fade_out
from space_map_data.dust.parallel import forked_map
from space_map_data.dust.resample import fill
from space_map_data.dust.sky import SKY_DIR
from space_map_data.dust.sources import BUILD_DIR, atomic_npy
from space_map_data.galaxy import geometry

logger = logging.getLogger(__name__)

SHAPE_DIR = BUILD_DIR / "rest-shape"
SHAPE_POINTS = 4
RAY_DEPTH = 8
SIGHTLINE_DEPTH = 7
# A sightline may hold up to this many times the Planck total scaled to the whole
# shape. Off the plane the shape has no room, and the remainder there is noise.
MAX_OVER_PLANCK_SCALE = 3.0
RAY_CHUNK = 20000
# The base is a fit of the sightline columns in log, smooth with a Gaussian of this
# sigma in l and in b (deg). Narrower keeps broad spokes on the far disc.
BASE_SIGMA_DEG = (10.0, 1.0)
BASE_FIT_STEPS = 12
SKY_GRID_DEG = 0.25
# The sightline's factor holds its room up to the first share of the room and fades
# out by the second. Nearer windows hold the factor in fewer pc and so need more
# contrast there.
NEAR_ROOM = (0.25, 0.5)
MAX_NEAR_FACTOR = 20.0
PROFILE_BIN_PC = 100.0
PROFILE_BINS = 300
FIELD_FILE = "sky.rest_field.npy"


def _shape_sampler(x, y, z):
    return geometry.dust_shape(x, y, z), np.ones(len(x), np.float32)


def build_shape(workers: int) -> None:
    for level in LEVELS:
        fill(level, SHAPE_DIR, _shape_sampler, SHAPE_POINTS, workers)


def _stack(directory, suffix: str) -> Stack:
    return Stack(
        {
            level.index: np.load(
                directory / f"l{level.index}.{suffix}.npy", mmap_mode="r"
            )
            for level in LEVELS
        }
    )


def _columns(job: tuple[str, np.ndarray]) -> np.ndarray:
    variant, directions = job
    directory = merged_dir(variant)
    stacks = (
        _stack(directory, "observed"),
        _stack(directory, "rest_weight"),
        _stack(SHAPE_DIR, "value"),
    )
    return integrate(stacks, np.zeros(3), directions)


def _directions(depth: int) -> np.ndarray:
    pixels_all = np.arange(12 * 4**depth, dtype=np.uint64)
    lon, lat = nested.healpix_to_lonlat(pixels_all, depth)
    return nest.directions(lon.to_value(u.rad), lat.to_value(u.rad))


def sky_columns(variant: str, workers: int) -> np.ndarray:
    """Columns on Nside 256 rays: observed, shape in the rest share, whole shape."""
    directions = _directions(RAY_DEPTH)
    jobs = [
        (variant, directions[start : start + RAY_CHUNK])
        for start in range(0, len(directions), RAY_CHUNK)
    ]
    return np.concatenate(forked_map(_columns, jobs, workers), axis=1)


def _profiles(job: tuple[str, np.ndarray]) -> np.ndarray:
    """The rest weight along each ray, summed in bins of distance."""
    variant, directions = job
    stack = _stack(merged_dir(variant), "rest_weight")
    out = np.zeros((len(directions), PROFILE_BINS), np.float32)
    for index, start, stop in segments(np.zeros(3), directions):
        length = stop - start
        used = np.flatnonzero(length > 0)
        if len(used) == 0:
            continue
        step = float(LEVELS[index].voxel.min()) / 2.0
        count = int(np.ceil(length[used].max() / step))
        ds = length[used] / count
        for i in range(count):
            t = start[used] + (i + 0.5) * ds
            at = np.minimum((t // PROFILE_BIN_PC).astype(np.int64), PROFILE_BINS - 1)
            points = directions[used] * t[:, None]
            out[used, at] += stack.read(index, points) * ds
    return out


def room_profiles(variant: str, workers: int) -> np.ndarray:
    """The rest weight per bin of distance on Nside 128 sightlines, (sightlines, bins)."""
    directions = _directions(SIGHTLINE_DEPTH)
    jobs = [
        (variant, directions[start : start + RAY_CHUNK // 8])
        for start in range(0, len(directions), RAY_CHUNK // 8)
    ]
    return np.concatenate(forked_map(_profiles, jobs, workers))


def sightline_scale(
    total: np.ndarray, seen: np.ndarray, room: np.ndarray, whole: np.ndarray
) -> np.ndarray:
    """The density at the solar circle that holds the remainder of each sightline."""
    remainder = np.maximum(total - seen, 0.0)
    wanted = np.divide(remainder, room, out=np.zeros_like(room), where=room > 0)
    limit = MAX_OVER_PLANCK_SCALE * total / whole
    return np.minimum(wanted, limit)


def _sky_grid(step: float) -> tuple[np.ndarray, np.ndarray]:
    """Longitudes and latitudes (deg) of a grid on the sky, [l, b]."""
    lon = np.arange(round(360.0 / step)) * step
    lat = -90.0 + np.arange(round(180.0 / step) + 1) * step
    return np.meshgrid(lon, lat, indexing="ij")


def sky_smooth(values: np.ndarray, sigma_deg: tuple[float, float]) -> np.ndarray:
    """A Gaussian of a Nside 128 map in l and b, back at the pixel centres. It runs
    on a grid in (l, b), which wraps in l."""
    step = SKY_GRID_DEG
    lon, lat = _sky_grid(step)
    grid = _bilinear(values, np.radians(lon.ravel()), np.radians(lat.ravel()))
    grid = gaussian_filter(
        grid.reshape(lon.shape),
        (sigma_deg[0] / step, sigma_deg[1] / step),
        mode=("wrap", "nearest"),
    )
    pixel_lon, pixel_lat = nested.healpix_to_lonlat(
        np.arange(len(values), dtype=np.uint64), SIGHTLINE_DEPTH
    )
    closed = np.concatenate([grid, grid[:1]])
    at = [pixel_lon.to_value(u.deg) / step, (pixel_lat.to_value(u.deg) + 90.0) / step]
    return map_coordinates(closed, at, order=1, mode="nearest")


def smooth_base(scale: np.ndarray, seen: np.ndarray, room: np.ndarray) -> np.ndarray:
    """A scale smooth on the sky whose columns fit those of `scale` in log."""
    target = seen + scale * room
    base = np.maximum(sky_smooth(scale, BASE_SIGMA_DEG), 1e-12)
    weight = (room > 0).astype(np.float64)
    for _ in range(BASE_FIT_STEPS):
        column = seen + base * room
        misfit = np.log(np.maximum(target, 1e-12) / np.maximum(column, 1e-12))
        gain = base * room / np.maximum(column, 1e-12)
        num = sky_smooth(weight * gain * misfit, BASE_SIGMA_DEG)
        den = sky_smooth(weight * gain * gain, BASE_SIGMA_DEG)
        step = np.divide(num, den, out=np.zeros_like(num), where=den > 1e-6)
        base = base * np.exp(np.clip(step, -1.0, 1.0))
    return base


def at_share(profiles: np.ndarray, share: float) -> np.ndarray:
    """The distance (pc) along each sightline where its room reaches `share`."""
    cumulative = np.cumsum(profiles, axis=1, dtype=np.float64)
    wanted = share * cumulative[:, -1:]
    k = np.minimum((cumulative < wanted).sum(axis=1), profiles.shape[1] - 1)
    rows = np.arange(len(profiles))
    before = cumulative[rows, k] - profiles[rows, k]
    inside = np.divide(
        wanted[:, 0] - before,
        profiles[rows, k],
        out=np.zeros(len(rows)),
        where=profiles[rows, k] > 0,
    )
    return (k + np.clip(inside, 0.0, 1.0)) * PROFILE_BIN_PC


def split_field(
    scale: np.ndarray, seen: np.ndarray, room: np.ndarray, profiles: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Base, near factor and the near window's start and end (pc) per sightline,
    shape (4, sightlines), and the column each sightline holds. That column is the
    one of `scale`, or more where the base alone holds more."""
    base = smooth_base(scale, seen, room)
    start, end = at_share(profiles, NEAR_ROOM[0]), at_share(profiles, NEAR_ROOM[1])
    end = np.maximum(end, start + 1.0)
    centres = (np.arange(PROFILE_BINS) + 0.5) * PROFILE_BIN_PC
    window = fade_out(centres[None, :], start[:, None], end[:, None])
    share = np.divide(
        (profiles * window).sum(axis=1),
        profiles.sum(axis=1),
        out=np.zeros(len(room)),
        where=profiles.sum(axis=1) > 0,
    )
    near = room * share
    factor = np.divide(
        scale * room - base * (room - near),
        base * near,
        out=np.ones_like(room),
        where=base * near > 0,
    )
    factor = np.clip(factor, 0.0, MAX_NEAR_FACTOR)
    placed = base * (room - near) + base * factor * near
    return np.stack((base, factor, start, end)).astype(np.float32), placed


def build_rest(variant: str, workers: int) -> None:
    build_observed(variant)
    directory = merged_dir(variant)
    for level in LEVELS:
        share = np.load(directory / f"l{level.index}.rest_share.npy")
        shape = np.load(SHAPE_DIR / f"l{level.index}.value.npy")
        atomic_npy(directory / f"l{level.index}.rest_weight.npy", share * shape)
    observed, weighted, whole = sky_columns(variant, workers)
    atomic_npy(directory / "sky.observed.npy", observed.astype("f4"))

    per_sightline = 4 ** (RAY_DEPTH - SIGHTLINE_DEPTH)
    total = np.load(SKY_DIR / "planck.total.npy")
    total = total.reshape(-1, per_sightline).mean(axis=1)
    seen = observed.reshape(-1, per_sightline).mean(axis=1)
    room = weighted.reshape(-1, per_sightline).mean(axis=1)
    whole = whole.reshape(-1, per_sightline).mean(axis=1)
    scale = sightline_scale(total, seen, room, whole)
    atomic_npy(directory / "sky.rest_scale.npy", scale.astype("f4"))
    field, placed = split_field(scale, seen, room, room_profiles(variant, workers))
    atomic_npy(directory / FIELD_FILE, field)
    factor = field[1]
    remainder = np.maximum(total - seen, 0.0)
    report = {
        "remainder_mag_mean": float(remainder.mean()),
        "placed_mag_mean": float(placed.mean()),
        "unplaced_share": float(1.0 - placed.sum() / max(remainder.sum(), 1e-30)),
        "sightlines": len(scale),
        "near_factor_p5_p50_p95": [
            float(v) for v in np.percentile(factor[room > 0], (5, 50, 95))
        ],
    }
    (directory / "rest.json").write_text(json.dumps(report, indent=1))
    logger.info("rest %s: %s", variant, report)

    for level in LEVELS:
        weight = np.load(directory / f"l{level.index}.rest_weight.npy")
        atomic_npy(
            directory / f"l{level.index}.rest.npy",
            _level_scale(level, field) * weight,
        )


def _bilinear(values: np.ndarray, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """Bilinear on the Nside 128 sky. `values` may hold maps on its first axes."""
    out = np.zeros(values.shape[:-1] + lon.shape, np.float64)
    keep = np.abs(lat) < np.pi / 2
    corners, weights = nested.bilinear_interpolation(
        Longitude(lon[keep], u.rad), Latitude(lat[keep], u.rad), SIGHTLINE_DEPTH
    )
    corners = np.ma.getdata(corners).astype(np.int64)
    weights = np.ma.getdata(weights)
    out[..., keep] = (values[..., corners] * weights).sum(axis=-1)
    return out


def scale_at(
    field: np.ndarray, x: np.ndarray, y: np.ndarray, z: np.ndarray
) -> np.ndarray:
    """The rest scale at points on nest axes: the base, times the near factor in the
    near window of the sightline, faded out by its end."""
    lon, lat, r = nest.lonlat(x, y, z)
    base, factor, start, end = _bilinear(field, lon, lat)
    window = fade_out(r, start, np.maximum(end, start + 1.0))
    return (base * (1.0 + (factor - 1.0) * window)).astype(np.float32)


def _level_scale(level, field: np.ndarray) -> np.ndarray:
    """The rest scale at each voxel centre of a level."""
    out = np.zeros(level.shape, np.float32)
    y, z = np.meshgrid(level.centres(1), level.centres(2), indexing="ij")
    for ix, x in enumerate(level.centres(0)):
        out[ix] = scale_at(field, np.full(y.shape, x), y, z)
    return out
