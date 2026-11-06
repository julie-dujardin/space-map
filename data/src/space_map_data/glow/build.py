"""The steps of the light grid. Each writes to the build directory, and the next reads
it, so a step can run again alone. The tree and the nest are read as exported."""

import json
import logging
from dataclasses import asdict
from pathlib import Path

import numpy as np

from space_map_data.dust.encode import file_digest
from space_map_data.dust.sources import atomic_npy
from space_map_data.export.extrasolar.build import served
from space_map_data.export.extrasolar.render import TREE
from space_map_data.export.swap import ExportRefused
from space_map_data.extrasolar.registry import Registry
from space_map_data.extrasolar.store import write_json
from space_map_data.glow import deposit, duplicates, encode, form, sky_map
from space_map_data.glow.grid import SkyGrid
from space_map_data.utils.paths import CACHE_DIR, EXTRASOLAR_DIR

logger = logging.getLogger(__name__)

BUILD_DIR = CACHE_DIR / "milky-way-3d" / "glow-build"
# A cell is about 0.8 deg on `high` and 1.6 deg on `low`. A shell is 17% of its radius
# past 1 kpc, about the distance error of a star there, so a finer shell draws the
# error. The reach holds the Magellanic stars and the last rows of the tree.
SCALE_PC = 20.0
REACH_PC = 400_000.0
GRIDS = {
    "high": SkyGrid(256, 60, SCALE_PC, REACH_PC),
    "low": SkyGrid(128, 60, SCALE_PC, REACH_PC),
}
ENCODING_FILE = "encoding.json"
SUN_MAP = "sun_map.npy"
SAMPLE = "sample.npy"
CURVE = "curve.npy"
OBSERVED = "observed.npy"
TOTALS = "totals.json"
DUPLICATES = "duplicates.npz"


class StaleBuild(ExportRefused):
    """A file of the build, or a served input, that another run wrote."""


def tree_metadata(root: Path = EXTRASOLAR_DIR) -> dict:
    return json.loads((root / "v1" / "x" / "metadata.json").read_text())


def tree_token(root: Path = EXTRASOLAR_DIR) -> str:
    return tree_metadata(root)["trees"][TREE]["token"]


def nest_token(root: Path = EXTRASOLAR_DIR) -> str:
    return sky_map.nest_metadata(root)["token"]


def values_name(tier: str) -> str:
    return f"values.{tier}.npy"


def bits_name(tier: str) -> str:
    return f"bits.{tier}.npy"


def channels_name(tier: str) -> str:
    return f"channels.{tier}.npy"


def build_sun_map(build: Path, workers: int) -> None:
    """The column to each star, as the shader reads it from the Sun's map."""
    with served(EXTRASOLAR_DIR):
        nest = sky_map.load_nest()
        atomic_npy(build / SUN_MAP, sky_map.build_map(nest, np.zeros(3), workers))
        write_json(build / "sun_map.json", {"nest": nest.token})


def build_duplicates(build: Path, workers: int) -> None:
    """The rows the grid leaves out, because another row holds the same star. The
    registry says which rows have Gaia astrometry, so it must be the one that the
    tree was exported from."""
    with served(EXTRASOLAR_DIR):
        metadata = tree_metadata()
        token = metadata["trees"][TREE]["token"]
        ingest = metadata["registry"]["ingest"]
        with Registry().reader() as registry:
            if registry.last_ingest != ingest:
                raise StaleBuild(
                    f"the tree is from ingest {ingest}, the registry is at ingest"
                    f" {registry.last_ingest}: export the tree again"
                )
            nodes, rows, report = duplicates.find_duplicates(registry, workers)
    np.savez(build / DUPLICATES, node=nodes.astype(str), row=rows)
    write_json(build / "duplicates.json", report | {"tree": token, "ingest": ingest})


def read_skip(build: Path, token: str) -> dict[str, np.ndarray]:
    """Rows of the tree that the grid leaves out, by node. The row numbers are those
    of the tree with this token."""
    held = json.loads((build / "duplicates.json").read_text())["tree"]
    if held != token:
        raise StaleBuild(
            f"{DUPLICATES} is from tree {held}, the export has {token}: run duplicates"
        )
    with np.load(build / DUPLICATES) as data:
        names, rows = data["node"], data["row"]
    return {str(n): rows[names == n] for n in np.unique(names)}


def densities(grid: SkyGrid, cube: np.ndarray, neutral: float) -> np.ndarray:
    """The eight values of each voxel, as flux density per pc^3, with the ring."""
    values = form.voxel_values(cube)
    volumes = grid.volumes()
    used = volumes > 0
    values[..., :-1][used] /= volumes[used, None]
    values[..., -1] = np.nan_to_num(values[..., -1], nan=neutral)
    grid.fill_ring(values)
    return values.astype(np.float32)


def channel_densities(grid: SkyGrid, cube: np.ndarray) -> np.ndarray:
    """The light of all stars of each voxel per channel, as flux density per pc^3,
    with the ring. The model's residual subtracts it."""
    light = cube.sum(axis=-2)
    volumes = grid.volumes()
    used = volumes > 0
    light[used] /= volumes[used, None]
    light[~used] = 0.0
    grid.fill_ring(light)
    return light.astype(np.float32)


def build_deposit(build: Path, workers: int) -> None:
    """One pass over the tree: the values of each tier, their light per channel, the
    sample and the sums. The export is held off for the pass, and the tokens are
    those it ran on."""
    with served(EXTRASOLAR_DIR):
        token = tree_token()
        nest = sky_map.nest_metadata()
        stored = json.loads((build / "sun_map.json").read_text())
        if stored["nest"] != nest["token"]:
            raise StaleBuild(f"{SUN_MAP} is from nest {stored['nest']}: run sun-map")
        result = deposit.deposit(
            list(GRIDS.values()),
            np.array(form.EDGES),
            np.load(build / SUN_MAP),
            sky_map.nest_rotation(nest),
            workers,
            read_skip(build, token),
        )
    atomic_npy(build / CURVE, result.curve)
    atomic_npy(build / OBSERVED, result.observed)
    atomic_npy(build / SAMPLE, result.sample)
    table = form.make_table(result.curve)
    for (tier, grid), cube in zip(GRIDS.items(), result.cubes, strict=True):
        summed = cube.sum(axis=(0, 1, 2, 3))
        off = float(np.abs(summed / result.totals.light - 1).max())
        logger.info("%s: light in the grid against the stars: %.3g", tier, off)
        atomic_npy(build / values_name(tier), densities(grid, cube, table.neutral_tint))
        atomic_npy(build / channels_name(tier), channel_densities(grid, cube))
    write_json(
        build / TOTALS,
        {
            **asdict(result.totals)
            | {
                "light": result.totals.light.tolist(),
                "observed": result.totals.observed.tolist(),
                "capped_light": result.totals.capped_light.tolist(),
            },
            "tree": token,
            "nest": nest["token"],
        },
    )


def build_encoded(build: Path) -> None:
    """Write the textures of both tiers, then `encoding.json` with their digests and
    shapes and the extent of each grid. The export reads sizes from it alone."""
    high = np.load(build / values_name("high"), mmap_mode="r")
    scale = encode.scale_of(high[..., 0])
    digests, shapes = {}, {}
    for tier in GRIDS:
        values = np.load(build / values_name(tier))
        path = build / bits_name(tier)
        bits = encode.encode_values(values, scale)
        atomic_npy(path, bits)
        digests[path.name] = file_digest(path)
        shapes[path.name] = list(bits.shape)
    totals = json.loads((build / TOTALS).read_text())
    write_json(
        build / ENCODING_FILE,
        {
            "scale": scale,
            "digests": digests,
            "shapes": shapes,
            "extents": {
                tier: {"scale_pc": grid.scale, "reach_pc": grid.reach}
                for tier, grid in GRIDS.items()
            },
            "tree": totals["tree"],
            "nest": totals["nest"],
        },
    )


def read_encoding(build: Path, root: Path = EXTRASOLAR_DIR) -> dict:
    """The encoding. It refuses textures it does not list, or a tree or nest that the
    export below `root` has since replaced: the grid holds their stars and their
    dust."""
    raw = json.loads((build / ENCODING_FILE).read_text())
    for name, digest in raw["digests"].items():
        if file_digest(build / name) != digest:
            raise StaleBuild(f"{build / name} is not the file of {ENCODING_FILE}")
    current = {"tree": tree_token(root), "nest": nest_token(root)}
    for key, token in current.items():
        if raw[key] != token:
            raise StaleBuild(f"the grid holds {key} {raw[key]}, the export has {token}")
    return raw
