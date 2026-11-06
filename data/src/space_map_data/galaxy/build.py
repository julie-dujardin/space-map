"""The steps of the model volumes. Each writes to the build directory and the next
reads it, so a step can run again alone. The catalogue terms are those of the glow
build, so the model follows a rebuilt grid: `column calibrate bake residual encode`.

Each step records what it read, and the next refuses inputs that another run wrote:
`bake.json` names the glow build and the calibration, `residual.json` the bake, and
`encoding.json` all of them, with the digest and shape of every texture.
"""

import json
import logging
from pathlib import Path

import numpy as np

from space_map_data.dust.encode import file_digest
from space_map_data.dust.sources import atomic_npy
from space_map_data.extrasolar.store import write_json
from space_map_data.galaxy import calibrate, residual, volumes
from space_map_data.galaxy.model import Model
from space_map_data.glow import build as glow_build
from space_map_data.glow import encode as glow_encode
from space_map_data.utils.paths import CACHE_DIR

logger = logging.getLogger(__name__)

BUILD_DIR = CACHE_DIR / "milky-way-3d" / "model-build"
BOXES = ("inner", "outer")
CAT_TIERS = ("high", "low")
BAKE_FILE = "bake.json"
RESIDUAL_FILE = "residual.json"
ENCODING_FILE = "encoding.json"
TABLE_FILE = "colour_table.json"


class StaleModel(Exception):
    pass


def glow_inputs(glow_dir: Path) -> dict:
    """What the model takes from the glow build: its tokens and texture digests."""
    raw = json.loads((glow_dir / glow_build.ENCODING_FILE).read_text())
    return {"tree": raw["tree"], "nest": raw["nest"], "grid": raw["digests"]}


def build_column(out: Path, glow_dir: Path, far_side: float) -> None:
    column = calibrate.catalogue_column(glow_dir / glow_build.SAMPLE)
    write_json(out / calibrate.COLUMN, column | {"glow": glow_inputs(glow_dir)})


def build_calibration(out: Path, glow_dir: Path, far_side: float) -> None:
    column = json.loads((out / calibrate.COLUMN).read_text())
    if column["glow"] != glow_inputs(glow_dir):
        raise StaleModel(f"{calibrate.COLUMN} is from another glow build: run column")
    calibrate.calibrate(column, out)


def bake_name(box: str) -> str:
    return f"bake.{box}.npy"


def build_bake(out: Path, glow_dir: Path, far_side: float, workers: int = 8) -> None:
    """Model RGB and each tier's catalogue RGB, as voxel means of the high boxes."""
    calibration = file_digest(out / calibrate.CALIBRATION)
    model = Model.load(out / calibrate.CALIBRATION, far_side)
    grids = {tier: residual.CatalogueGrid.load(glow_dir, tier) for tier in CAT_TIERS}
    read = residual.sampler(model, grids)
    digests = {}
    for box in BOXES:
        shape = volumes.TIERS["high"][box]
        baked = volumes.bake(shape, read, 3 + 3 * len(CAT_TIERS), workers)
        atomic_npy(out / bake_name(box), baked)
        digests[bake_name(box)] = file_digest(out / bake_name(box))
        logger.info("bake %s: %s", box, baked.shape)
    write_json(
        out / BAKE_FILE,
        {
            "glow": glow_inputs(glow_dir),
            "far_side": far_side,
            "catalogue_fade_pc": residual.CATALOGUE_FADE_PC,
            "calibration": calibration,
            "digests": digests,
        },
    )


def read_listed(out: Path, record: dict, step: str) -> None:
    """Refuse files that are not those whose digests `record` lists."""
    for name, digest in record["digests"].items():
        if file_digest(out / name) != digest:
            raise StaleModel(f"{out / name} is not the file of its record: run {step}")


def tier_terms(baked: np.ndarray, box, tier: str) -> tuple[np.ndarray, np.ndarray]:
    """Model and catalogue RGB of a tier, shape (nx, ny, nz, 3) each."""
    cat_at = 3 + 3 * CAT_TIERS.index(tier)
    model_rgb, cat_rgb = baked[..., :3], baked[..., cat_at : cat_at + 3]
    if tier == "low":
        model_rgb = volumes.block_mean(model_rgb, box)
        cat_rgb = volumes.block_mean(cat_rgb, box)
    return model_rgb, cat_rgb


def residual_name(box: str, tier: str) -> str:
    return f"residual.{box}.{tier}.npy"


# The scale, in voxels of `high`, over which model and catalogue are compared. Near
# the Sun a voxel holds a few bright stars, and max(0, model - catalogue) per voxel
# turns their scatter into light: 10 to 13% of the model within 2 kpc.
COMPARE_SIGMA = {"inner": 2.0, "outer": 1.0}


def voxel_volumes(box: volumes.Box) -> np.ndarray:
    return (
        np.diff(box.edges(0))[:, None, None]
        * np.diff(box.edges(1))[None, :, None]
        * box.heights[None, None, :]
    )


def catalogue_ratio(
    model_light: np.ndarray,
    cat_light: np.ndarray,
    box: volumes.Box,
    sigma: float | tuple[float, ...],
) -> np.ndarray:
    """The catalogue's share of the model's light, both summed over a Gaussian of
    `sigma` voxels. Light, not density, so thin slices weigh by their volume."""
    from scipy.ndimage import gaussian_filter

    vol = voxel_volumes(box)
    model_sum = gaussian_filter(model_light * vol, sigma, mode="constant")
    cat_sum = gaussian_filter(cat_light * vol, sigma, mode="constant")
    return np.divide(
        cat_sum, model_sum, out=np.zeros_like(cat_sum), where=model_sum > 0
    )


def residual_light(
    model_rgb: np.ndarray, cat_rgb: np.ndarray, box: volumes.Box, sigma: float
) -> np.ndarray:
    """max(0, model - catalogue) on the compare scale, in the model's shape: the
    model's light times one less the catalogue's share where that is under 1."""
    model_light = model_rgb.sum(-1)
    ratio = catalogue_ratio(model_light, cat_rgb.sum(-1), box, sigma)
    return model_light * np.maximum(1.0 - ratio, 0.0)


def build_residual(out: Path, glow_dir: Path, far_side: float) -> None:
    """The residual light of each box and tier, the colour table, and
    `residual.json` with the bake they come from."""
    held = json.loads((out / BAKE_FILE).read_text())
    fade = residual.CATALOGUE_FADE_PC
    if (
        held["glow"] != glow_inputs(glow_dir)
        or held["far_side"] != far_side
        or held["catalogue_fade_pc"] != (list(fade) if fade else None)
    ):
        raise StaleModel("the bake is from another glow build, far side or fade: bake")
    read_listed(out, held, "bake")
    rows = []
    digests = {}
    for box in BOXES:
        high = volumes.TIERS["high"][box]
        baked = np.load(out / bake_name(box), mmap_mode="r")
        for tier in CAT_TIERS:
            model_rgb, cat_rgb = tier_terms(np.asarray(baked), high, tier)
            shape = volumes.TIERS[tier][box]
            sigma = COMPARE_SIGMA[box] * shape.size[0] / high.size[0]
            light = residual_light(model_rgb, cat_rgb, shape, sigma)
            path = out / residual_name(box, tier)
            atomic_npy(path, light.astype(np.float32))
            digests[path.name] = file_digest(path)
            if tier == "high":
                centres = residual.voxel_centres(high)
                weight = light.reshape(-1)[:, None]
                chroma = model_rgb.reshape(-1, 3) / np.maximum(
                    model_rgb.reshape(-1, 3).sum(1, keepdims=True), 1e-30
                )
                rows.append((centres, chroma * weight, model_rgb.reshape(-1, 3)))
    centres = np.concatenate([r[0] for r in rows])
    table = residual.colour_table(
        centres,
        np.concatenate([r[1] for r in rows]),
        np.concatenate([r[2] for r in rows]),
    )
    write_json(
        out / TABLE_FILE,
        {
            "radius_step_pc": residual.TABLE_RADIUS_STEP_PC,
            "radii": residual.TABLE_RADII,
            "height_step_pc": residual.TABLE_HEIGHT_STEP_PC,
            "heights": residual.TABLE_HEIGHTS,
            "reach_pc": residual.TABLE_REACH_PC,
            "shells_pc": list(residual.TABLE_SHELLS_PC),
            "rgb": np.round(table, 6).tolist(),
        },
    )
    digests[TABLE_FILE] = file_digest(out / TABLE_FILE)
    write_json(out / RESIDUAL_FILE, {"bake": held, "digests": digests})


def bits_name(box: str, tier: str) -> str:
    return f"bits.{box}.{tier}.npy"


# Mantissa bits kept of the half floats. Seven of ten halve the wire on `high` (12.3
# to 6.4 MB for the inner box) for a mean error of 0.14% in light.
MANTISSA_BITS = 7


def rounded_bits(bits: np.ndarray, keep: int = MANTISSA_BITS) -> np.ndarray:
    """Half floats rounded to `keep` mantissa bits, to nearest. A carry moves into the
    exponent, as it should; values are positive and stay finite."""
    drop = 10 - keep
    if drop <= 0:
        return bits
    wide = bits.astype(np.uint32) + (1 << (drop - 1))
    return np.minimum((wide >> drop) << drop, 0x7BFF).astype(np.uint16)


def _box_record(box: volumes.Box) -> dict:
    return {"half_extent_pc": list(box.half), "z_scale_pc": box.z_scale}


def build_encoded(out: Path, glow_dir: Path, far_side: float) -> None:
    """Half floats of every residual, one scale for all, and `encoding.json` with
    their digests and shapes, the boxes, and the bake and calibration they come
    from. It refuses residuals of another bake, and a bake of another calibration."""
    bake = json.loads((out / BAKE_FILE).read_text())
    made = json.loads((out / RESIDUAL_FILE).read_text())
    if made["bake"] != bake:
        raise StaleModel("the residual is from another bake: run residual")
    read_listed(out, made, "residual")
    calibration = file_digest(out / calibrate.CALIBRATION)
    if bake["calibration"] != calibration:
        raise StaleModel(f"the bake is from another {calibrate.CALIBRATION}: run bake")
    top = max(
        float(np.load(out / residual_name(box, "high"), mmap_mode="r").max())
        for box in BOXES
    )
    scale = glow_encode.scale_of(np.array([top]))
    digests, shapes = {}, {}
    for box in BOXES:
        for tier in CAT_TIERS:
            light = np.load(out / residual_name(box, tier))
            bits = rounded_bits(glow_encode.half_bits(light.astype(np.float64) * scale))
            path = out / bits_name(box, tier)
            atomic_npy(path, bits)
            digests[path.name] = file_digest(path)
            shapes[path.name] = list(bits.shape)
    write_json(
        out / ENCODING_FILE,
        {
            "scale": scale,
            "digests": digests,
            "shapes": shapes,
            "centre_pc": list(volumes.CENTRE),
            "boxes": {box: _box_record(volumes.TIERS["high"][box]) for box in BOXES},
            "glow": bake["glow"],
            "far_side": far_side,
            "catalogue_fade_pc": bake["catalogue_fade_pc"],
            "table": file_digest(out / TABLE_FILE),
            "calibration": calibration,
        },
    )


def read_encoding(out: Path, glow_dir: Path) -> dict:
    """The encoding. It refuses textures it does not list, a colour table or a
    calibration that has changed since, or a glow build that has: the residual is
    defined against that grid."""
    raw = json.loads((out / ENCODING_FILE).read_text())
    read_listed(out, raw, "encode")
    if raw["glow"] != glow_inputs(glow_dir):
        raise StaleModel("the model is from another glow build: rebuild it")
    if raw["table"] != file_digest(out / TABLE_FILE):
        raise StaleModel(f"{TABLE_FILE} changed: run encode")
    if raw["calibration"] != file_digest(out / calibrate.CALIBRATION):
        raise StaleModel(f"{calibrate.CALIBRATION} changed: run bake residual encode")
    return raw
