"""The steps of the emission build. Each writes to the build directory and the next
reads it, so a step can run again alone.

    local     McCallum's cube on the level 2 box, both tiers, bare
    regions   the far H II regions and their light through the nest
    sun       the bare cube's projection from the Sun through the nest
    scale     the factor per sightline, the scaled cube
    scatter   the mean intensity of the glow's light, for scattered starlight
    shield    how much less of it reaches dust than the grid holds, by density
    encode    the codes and half floats, and `encoding.json`

Each step records the nest (and, for `scatter`, the glow and model builds) it read,
and the digests of the sources and step files it read, and the next refuses an input
that another run wrote or a source that changed since. The served nest is read, as
the render reads it, with the export held off.
"""

import json
import logging
from pathlib import Path

import numpy as np

from space_map_data.dust.far import StoredFar
from space_map_data.dust.sources import atomic_npy, file_digest
from space_map_data.emission import (
    encode,
    lines,
    local,
    project,
    regions,
    scatter,
    sky,
    sources,
)
from space_map_data.export.extrasolar.build import served
from space_map_data.export.swap import ExportRefused
from space_map_data.extrasolar.store import write_json
from space_map_data.galaxy import build as model_build
from space_map_data.galaxy import volumes
from space_map_data.galaxy.residual import StoredResidual
from space_map_data.glow import build as glow_build
from space_map_data.glow import gates as glow_gates
from space_map_data.glow import sky_map
from space_map_data.utils.paths import CACHE_DIR, EXTRASOLAR_DIR

logger = logging.getLogger(__name__)

BUILD_DIR = CACHE_DIR / "milky-way-3d" / "emission-build"
TIERS = ("high", "low")
LOCAL_FILE = "local.json"
REGIONS_FILE = "regions.json"
REGIONS_DATA = "regions.npz"
REGIONS_TABLE = "regions.table.npz"
SUN_FILE = "sun.json"
SCALE_FILE = "scale.json"
SCATTER_FILE = "scatter.json"
# Directions and steps of a J ray: p90 4 to 5% against 12,288 directions and 512
# steps over 64 test points, median 0.5%.
J_LONGITUDES = 32
J_LATITUDES = 24
J_STEPS = 96


class StaleEmission(ExportRefused):
    """An input of a step that another run wrote."""


def bare_name(tier: str) -> str:
    return f"local.bare.{tier}.npy"


def scaled_name(tier: str) -> str:
    return f"local.scaled.{tier}.npy"


def nest_token(root: Path = EXTRASOLAR_DIR) -> str:
    return sky_map.nest_metadata(root)["token"]


def _source_key() -> dict:
    stat = sources.CUBE_FILE.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _check(record: dict, key: str, value: object, step: str) -> None:
    if record.get(key) != value:
        raise StaleEmission(f"{key} changed since the last run: run {step}")


def build_local(out: Path, workers: int) -> None:
    """McCallum's cube as block means on the `high` box, and `low` from it."""
    cube = local.bare_cube()
    atomic_npy(out / bare_name("high"), cube)
    atomic_npy(out / bare_name("low"), local.block_mean(cube))
    write_json(
        out / LOCAL_FILE,
        {
            "source": _source_key(),
            "digests": {t: file_digest(out / bare_name(t)) for t in TIERS},
            "light": {t: float(np.load(out / bare_name(t)).sum()) for t in TIERS},
        },
    )


def _served(root: Path = EXTRASOLAR_DIR):
    """The served nest and far dust. The export is held off for the read, so both
    are from one export."""
    with served(root):
        return sky_map.load_nest("high", root), StoredFar.load(root, "high")


def build_regions(out: Path, workers: int) -> None:
    """The far regions, the column from the Sun to each, and their sky from the Sun."""
    wise = file_digest(sources.WISE_FILE)
    found, summary = regions.load()
    nest, far = _served()
    column = project.column_to(nest, far, found.position)
    seen = found.halpha_erg_s * 10.0 ** (-0.4 * lines.K_LINE["halpha"] * column)
    painted = regions.paint(found, seen, local.SKY_NSIDE)
    np.savez(
        out / REGIONS_DATA,
        names=np.array(found.names),
        position=found.position,
        sigma_pc=found.sigma_pc,
        rate=found.rate,
        source=found.source,
        halpha_erg_s=found.halpha_erg_s,
        display=found.display,
        column=column,
        seen_erg_s=seen,
        sky=painted,
    )
    write_json(
        out / REGIONS_FILE,
        summary
        | {"nest": nest.token, "wise": wise, "data": file_digest(out / REGIONS_DATA)},
    )


def read_regions(out: Path) -> dict[str, np.ndarray]:
    record = json.loads((out / REGIONS_FILE).read_text())
    _check(record, "data", file_digest(out / REGIONS_DATA), "regions")
    _check(record, "nest", nest_token(), "regions")
    _check(record, "wise", file_digest(sources.WISE_FILE), "regions")
    with np.load(out / REGIONS_DATA) as data:
        return dict(data)


def build_sun(out: Path, workers: int) -> None:
    """The bare cube from the Sun, dimmed and bare, in rayleighs of H-alpha."""
    record = json.loads((out / LOCAL_FILE).read_text())
    _check(record, "source", _source_key(), "local")
    cube = np.load(out / bare_name("high"))
    nest, far = _served()
    seen, bare, column = project.from_sun(
        nest,
        far,
        project.cube_fetch(cube, local.HALF_PC),
        sky.directions(local.SKY_NSIDE),
        local.END_PC,
        local.STEP_PC,
        workers,
    )
    to_r = lines.column_to_rayleigh(lines.display_to_emissivity(1.0))
    np.save(out / "sun.seen.npy", seen * to_r)
    np.save(out / "sun.bare.npy", bare * to_r)
    np.save(out / "sun.column.npy", column)
    write_json(
        out / SUN_FILE,
        {
            "nest": nest.token,
            "cube": record["digests"]["high"],
            "step_pc": local.STEP_PC,
        },
    )


def build_scale(out: Path, workers: int) -> None:
    """The factor per sightline and the scaled cube of both tiers."""
    sun = json.loads((out / SUN_FILE).read_text())
    record = json.loads((out / LOCAL_FILE).read_text())
    _check(sun, "cube", record["digests"]["high"], "sun")
    _check(sun, "nest", nest_token(), "sun")
    found = read_regions(out)
    seen = np.load(out / "sun.seen.npy")
    finkbeiner = file_digest(sources.FINKBEINER_FILE)
    observed = local.finkbeiner()
    wanted = local.target(observed, found["sky"])
    factor = local.factor_map(seen, wanted)
    np.save(out / "scale.factor.npy", factor)
    cube = local.apply_factor(np.load(out / bare_name("high")), factor)
    atomic_npy(out / scaled_name("high"), cube)
    atomic_npy(out / scaled_name("low"), local.block_mean(cube))
    # The factor as each sightline's light weighs it.
    seen64 = sky.degrade(seen, local.FACTOR_NSIDE)
    w = seen64 / seen64.sum()
    order = np.argsort(factor)
    cumulative = np.cumsum(w[order])
    weighted = {
        f"p{q}": float(factor[order][np.searchsorted(cumulative, q / 100)])
        for q in (5, 25, 50, 75, 95)
    }
    write_json(
        out / SCALE_FILE,
        {
            "sun": sun,
            "regions": json.loads((out / REGIONS_FILE).read_text())["data"],
            "finkbeiner": finkbeiner,
            "smooth_deg": local.SMOOTH_DEG,
            "limit": local.FACTOR_LIMIT,
            "scattered_share": local.SCATTERED_SHARE,
            "factor_by_pixel": {
                f"p{q}": float(np.percentile(factor, q)) for q in (5, 25, 50, 75, 95)
            },
            "factor_by_light": weighted,
            "at_limit_share": {
                "high": float((factor >= local.FACTOR_LIMIT * 0.999).mean()),
                "low": float((factor <= 1.001 / local.FACTOR_LIMIT).mean()),
            },
            "light": {
                "bare": float(np.load(out / bare_name("high")).sum()),
                "scaled": float(cube.sum()),
            },
            "digests": {t: file_digest(out / scaled_name(t)) for t in TIERS},
        },
    )


SHIELD_FILE = "shield.json"
# The boxes the shielding points are drawn in: the local volume, where the Sun's
# scattered light is made, the disc, and the nearby clouds.
SHIELD_BOXES = {
    "local": (1250.0, 1250.0, 1250.0),
    "disc": (20_000.0, 20_000.0, 600.0),
    "clouds": (500.0, 500.0, 300.0),
}


def build_shield(out: Path, workers: int) -> None:
    """Exact J at dust-weighted points against the grid's J there, and the curve of
    their ratio in local density."""
    record = json.loads((out / SCATTER_FILE).read_text())
    _check(record["digests"], "high", file_digest(out / j_name("high")), "scatter")
    field = light_field()
    grid = scatter.StoredJ(
        scatter.JForm(3, 1.0), np.load(out / j_name("high")), j_box("high")
    )
    d, w = scatter.direction_set(J_LONGITUDES, J_LATITUDES)
    edges = scatter.step_edges(J_STEPS)
    rng = np.random.default_rng(0)
    densities, ratios, rows = [], [], {}
    for name, half in SHIELD_BOXES.items():
        # Clouds: keep only dense points, which the other draws hold few of.
        accept = 0.5 if name == "clouds" else 0.05
        points = scatter.dust_weighted_points(
            field, np.array(half), scatter.SHIELD_POINTS, rng, accept
        )
        # The grid's J is 0 outside its box, so a ratio there is not valid.
        points = points[grid.box.inside(points)]
        exact = scatter.mean_intensity_all(field, points, d, w, edges, workers, 4)
        rho = field.dust(points)
        ratio = exact.sum(axis=1) / np.maximum(grid.read(points).sum(axis=1), 1e-30)
        densities.append(rho)
        ratios.append(ratio)
        rows[name] = {
            "points": len(points),
            "dust_weighted_ratio": float((rho * ratio).sum() / rho.sum()),
            "median_density": float(np.median(rho)),
        }
    density, ratio = np.concatenate(densities), np.concatenate(ratios)
    curve = scatter.shield_curve(density, ratio)
    residual = np.log(ratio / np.interp(np.log10(density), scatter.SHIELD_NODES, curve))
    write_json(
        out / SHIELD_FILE,
        {
            "scatter": record["digests"]["high"],
            "factor": [round(float(v), 4) for v in curve],
            "boxes": rows,
            "residual_ln_median_abs": float(np.median(np.abs(residual))),
            "residual_ln_p90_abs": float(np.quantile(np.abs(residual), 0.9)),
        },
    )


def read_shield(out: Path) -> tuple[float, ...]:
    record = json.loads((out / SHIELD_FILE).read_text())
    _check(record, "scatter", file_digest(out / j_name("high")), "shield")
    return tuple(record["factor"])


def j_name(tier: str) -> str:
    return f"j.{tier}.npy"


def light_inputs(
    glow_dir: Path = glow_build.BUILD_DIR, model_dir: Path = model_build.BUILD_DIR
) -> dict:
    """What the scattered light was made from: the glow's grid and the model's
    residual, as their builds record them."""
    return {
        "glow": model_build.glow_inputs(glow_dir),
        "model": file_digest(model_dir / model_build.ENCODING_FILE),
    }


def light_field(
    glow_dir: Path = glow_build.BUILD_DIR, model_dir: Path = model_build.BUILD_DIR
) -> scatter.Field:
    """The glow's light with no cut, through the served nest."""
    encoding = model_build.read_encoding(model_dir, glow_dir)
    fade = encoding["catalogue_fade_pc"]
    nest, far = _served()
    return scatter.Field(
        glow_gates.textures(glow_dir, "high"),
        StoredResidual.load(model_dir, "high"),
        nest,
        far,
        tuple(fade) if fade is not None else None,
    )


def j_box(tier: str) -> volumes.Box:
    return volumes.Box(scatter.J_BOX.half, scatter.J_SIZES[tier], scatter.J_BOX.z_scale)


def build_scatter(out: Path, workers: int) -> None:
    """J per channel at the voxel centres of the `high` grid, `low` its block mean."""
    field = light_field()
    box = j_box("high")
    points = scatter.voxel_centres(box, box.size).reshape(-1, 3)
    d, w = scatter.direction_set(J_LONGITUDES, J_LATITUDES)
    edges = scatter.step_edges(J_STEPS)
    j = scatter.mean_intensity_all(field, points, d, w, edges, workers)
    grid = j.reshape(*box.size, 3).astype(np.float32)
    atomic_npy(out / j_name("high"), grid)
    atomic_npy(out / j_name("low"), volumes.block_mean(grid, box))
    write_json(
        out / SCATTER_FILE,
        {
            "nest": field.nest.token,
            "light": light_inputs(),
            "directions": [J_LONGITUDES, J_LATITUDES],
            "steps": J_STEPS,
            "digests": {t: file_digest(out / j_name(t)) for t in TIERS},
        },
    )


ENCODING_FILE = "encoding.json"
REGION_COLUMNS = ("x", "y", "z", "sigma_pc", "light", "source")


def halpha_name(tier: str) -> str:
    return f"halpha.{tier}.npy"


def j_bits_name(tier: str) -> str:
    return f"j.{tier}.bits.npy"


def _read_scale(out: Path) -> dict:
    record = json.loads((out / SCALE_FILE).read_text())
    for tier in TIERS:
        _check(record["digests"], tier, file_digest(out / scaled_name(tier)), "scale")
    _check(record["sun"], "nest", nest_token(), "sun scale")
    _check(record, "regions", file_digest(out / REGIONS_DATA), "scale")
    _check(record, "finkbeiner", file_digest(sources.FINKBEINER_FILE), "scale")
    return record


def _read_scatter(out: Path) -> dict:
    record = json.loads((out / SCATTER_FILE).read_text())
    for tier in TIERS:
        _check(record["digests"], tier, file_digest(out / j_name(tier)), "scatter")
    _check(record, "nest", nest_token(), "scatter")
    _check(record, "light", light_inputs(), "scatter")
    return record


def build_encoded(out: Path, workers: int) -> None:
    """R8 codes of the scaled H-alpha cube, half floats of J with its colour table,
    the region table, and `encoding.json` with their digests and the inputs."""
    scale_record = _read_scale(out)
    scatter_record = _read_scatter(out)
    found = read_regions(out)
    j_high = np.load(out / j_name("high"))
    # The colour is fitted where the light is scattered: dust times J.
    weight = scatter.voxel_dust(light_field(), j_box("high")) * j_high.sum(axis=-1)
    weight *= scatter.voxel_volumes(j_box("high"))
    write_encoding(out, scale_record, scatter_record, found, weight, read_shield(out))


def write_encoding(
    out: Path,
    scale_record: dict,
    scatter_record: dict,
    found: dict[str, np.ndarray],
    weight: np.ndarray,
    shield: tuple[float, ...],
) -> None:
    """The shipped files from the scaled cubes and the J grids in `out` and from the
    regions, and `encoding.json` with every value the export describes them by."""
    top = float(np.load(out / scaled_name("high")).max())
    halpha = {}
    for tier in TIERS:
        codes, encoding = encode.halpha_codes(np.load(out / scaled_name(tier)), top)
        atomic_npy(out / halpha_name(tier), codes)
        halpha[tier] = {"floor": float(encoding.floor), "top": float(encoding.top)}
    form = scatter.store_j(np.load(out / j_name("high")), 1, weight, shield)
    for tier in TIERS:
        grid = np.load(out / j_name(tier))
        atomic_npy(out / j_bits_name(tier), scatter.j_bits(grid, form))
    np.savez(
        out / REGIONS_TABLE,
        x=found["position"][:, 0].astype(np.float32),
        y=found["position"][:, 1].astype(np.float32),
        z=found["position"][:, 2].astype(np.float32),
        sigma_pc=found["sigma_pc"].astype(np.float32),
        light=found["display"].astype(np.float32),
        source=found["source"].astype(np.uint8),
    )
    names = [halpha_name(t) for t in TIERS] + [j_bits_name(t) for t in TIERS]
    names.append(REGIONS_TABLE)
    regions_record = json.loads((out / REGIONS_FILE).read_text())
    write_json(
        out / ENCODING_FILE,
        {
            "nest": scatter_record["nest"],
            "light": scatter_record["light"],
            "sources": {
                "wise": regions_record["wise"],
                "finkbeiner": scale_record["finkbeiner"],
            },
            "lines": {
                "colour": lines.COLOUR.round(6).tolist(),
                "k_rgb": lines.K_EMISSION.round(4).tolist(),
            },
            "halpha": halpha,
            "halpha_half_extent_pc": [local.HALF_PC] * 3,
            "j": form.record(),
            "j_box": {
                "centre_pc": list(volumes.CENTRE),
                "half_extent_pc": list(scatter.J_BOX.half),
                "z_scale_pc": scatter.J_BOX.z_scale,
            },
            "albedo": scatter.ALBEDO.round(4).tolist(),
            "tau_per_mag": scatter.TAU_PER_MAG,
            "region_sources": list(regions.SOURCES),
            "scale": {
                k: scale_record[k] for k in ("smooth_deg", "limit", "scattered_share")
            },
            "factor_by_light": scale_record["factor_by_light"],
            "regions": regions_record,
            "digests": {name: file_digest(out / name) for name in names},
            "shapes": {
                name: list(np.load(out / name, mmap_mode="r").shape)
                for name in names
                if name.endswith(".npy")
            },
        },
    )


def read_encoding(
    out: Path,
    glow_dir: Path = glow_build.BUILD_DIR,
    model_dir: Path = model_build.BUILD_DIR,
    root: Path = EXTRASOLAR_DIR,
) -> dict:
    """The encoding. It refuses files it does not list, an emission made on another
    nest or another glow or model build (H-alpha is scaled through that dust, and the
    scattered light is defined against that light and dust), and one made from a
    WISE catalogue or a Finkbeiner map that has changed since."""
    raw = json.loads((out / ENCODING_FILE).read_text())
    for name, digest in raw["digests"].items():
        if file_digest(out / name) != digest:
            raise StaleEmission(
                f"{out / name} is not the file {ENCODING_FILE} lists: run encode"
            )
    if raw["nest"] != nest_token(root):
        raise StaleEmission("the emission is from another nest: rebuild it from sun")
    if raw["light"] != light_inputs(glow_dir, model_dir):
        raise StaleEmission(
            "the scattered light is from another glow or model: run scatter encode"
        )
    found = raw["sources"]
    _check(found, "wise", file_digest(sources.WISE_FILE), "regions scale encode")
    _check(found, "finkbeiner", file_digest(sources.FINKBEINER_FILE), "scale encode")
    return raw
