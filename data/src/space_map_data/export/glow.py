"""Export the catalogue light grid to `v1/glow/`, beside the star tree and the dust,
with the model light the catalogue lacks.

Each tier is two volume files of the grid and two of the model (an inner box about
the Galactic centre and an outer one for the halo and the Magellanic Clouds), in the
extrasolar container; `metadata.json` holds the rest under `model`. One token covers
all of them: the model's residual is defined against this grid, so the two are never
served apart. Sizes and extents come from each build's `encoding.json`, so the
metadata describes the files as they were encoded. The metadata holds no time, so a
rerun on the same inputs gives the same bytes.
"""

import json
import logging
import math
from collections.abc import Iterable, Mapping
from pathlib import Path

import numpy as np
import pyarrow as pa

from space_map_data.dust.nest import galactic_to_icrs
from space_map_data.export import swap
from space_map_data.export.extrasolar import container
from space_map_data.export.extrasolar.render import TREE
from space_map_data.export.extrasolar.skycultures import UNDECIDED, combined
from space_map_data.galaxy import build as model_build
from space_map_data.galaxy import calibrate, geometry
from space_map_data.galaxy.credits import PAPERS, paper_credits
from space_map_data.glow import build, form, light, sky_map
from space_map_data.utils.paths import EXTRASOLAR_DIR

logger = logging.getLogger(__name__)

TEXTURES = ("a", "b")
# The model's boxes, by texture index of the container's volume info.
MODEL_BOXES = {"inner": 2, "outer": 3}


def volume_payload(bits: np.ndarray, texture: int, tier: str) -> bytes:
    """One RGBA16F texture in the order of `texImage3D`, one uint16 column of texels.
    Interleaved, because the edges of a voxel often repeat: gzip finds that, and it
    takes 40% off these files against a column per channel."""
    shells, rows, columns, _ = bits.shape
    flat = np.ascontiguousarray(bits).reshape(-1)
    column = container.Column("texels", "uint16", pa.array(flat))
    return container.volume_payload(column, (columns, rows, shells), texture, tier)


def model_payload(bits: np.ndarray, texture: int, tier: str) -> bytes:
    """One R16F model volume, stored [x, y, z], in the order of `texImage3D`."""
    nx, ny, nz = bits.shape
    flat = np.ascontiguousarray(bits.transpose(2, 1, 0)).reshape(-1)
    column = container.Column("texels", "uint16", pa.array(flat))
    return container.volume_payload(column, (nx, ny, nz), texture, tier)


def _box_entry(box: dict) -> dict:
    return {
        "half_extent_pc": box["half_extent_pc"],
        "z_map": "asinh" if box["z_scale_pc"] else "linear",
        "z_scale_pc": box["z_scale_pc"],
    }


def _model_metadata(
    files: Mapping[tuple[str, str], container.Written],
    model: dict,
    tiers: Iterable[str],
) -> dict:
    """The model block, with boxes and sizes as the model's `encoding.json` records
    them."""
    encoding, calibration, table = (
        model["encoding"],
        model["calibration"],
        model["table"],
    )
    return {
        "quantity": "max(0, model - catalogue) of all stars per voxel: summed R + G + B display flux density per pc^3, in flux of M = 0 at 10 pc, no dust; one channel, coloured by `colour`",
        "model": True,
        "texture_scale": encoding["scale"],
        "centre_pc": encoding["centre_pc"],
        "boxes": {name: _box_entry(encoding["boxes"][name]) for name in MODEL_BOXES},
        "tiers": {
            tier: {
                name: {
                    "size": encoding["shapes"][model_build.bits_name(name, tier)],
                    "path": files[(tier, f"model-{name}")].path,
                    "bytes": files[(tier, f"model-{name}")].size,
                }
                for name in MODEL_BOXES
            }
            for tier in tiers
        },
        "colour": table,
        "catalogue_fade_pc": encoding["catalogue_fade_pc"],
        "far_side_arms": encoding["far_side"],
        "components": {
            "g_flux": calibration["flux"],
            "bp_rp": calibration["bp_rp"],
            "lian_scale": calibration["fit"]["lian_scale"],
        },
        "frame": {"sun_radius_pc": geometry.R0, "sun_height_pc": geometry.Z0},
    }


def _grid_entry(
    raw: dict, files: Mapping[tuple[str, str], container.Written], tier: str
) -> dict:
    """A tier as `encoding.json` records it: the shape of its texels and its extent."""
    shape = raw["shapes"][build.bits_name(tier)]
    shells, size = shape[0], shape[1]
    extent = raw["extents"][tier]
    return {
        "size": size,
        "shells": shells,
        "scale_pc": extent["scale_pc"],
        "reach_pc": extent["reach_pc"],
        # Two bytes a half float.
        "mebibytes": math.prod(shape) * 2 / 2**20,
        "files": {
            name: {"path": files[(tier, name)].path, "bytes": files[(tier, name)].size}
            for name in TEXTURES
        },
    }


def _metadata(
    files: Mapping[tuple[str, str], container.Written],
    token: str,
    raw: dict,
    table: form.Table,
    totals: dict,
    model: dict | None,
    distribution: str,
) -> dict:
    return {
        "format": container.VERSION,
        "token": token,
        "inputs": {"tree": raw["tree"], "dust": raw["nest"]},
        "distribution": distribution,
        "quantity": "summed R + G + B display flux density of the stars fainter than each edge, per pc^3, in flux of M = 0 at 10 pc, the Sun's dust taken out",
        "frame": {
            "origin": "the Sun",
            "unit": "pc",
            "axes": "x to the Galactic centre, y to l = 90 deg, z to the north Galactic pole",
            "rotation_to_icrs": galactic_to_icrs().round(10).tolist(),
        },
        "texture_scale": raw["scale"],
        "edges": [None, *form.EDGES],
        "tint_edge": form.EDGES[form.TINT_EDGE],
        "neutral_tint": table.neutral_tint,
        "extinction": {
            "k_g": light.K_G,
            "k_rgb": light.K_RGB.tolist(),
            "bluest_bp_rp": light.BLUEST,
            "reddening": light.REDDENING,
            "brightest_m0": light.BRIGHTEST_M0,
        },
        "table": {
            "magnitudes": table.magnitudes.round(3).tolist(),
            "place": table.place.round(5).tolist(),
            "place_soft": table.place_soft.round(5).tolist(),
            "colour": table.colour.round(5).tolist(),
        },
        "tiers": {tier: _grid_entry(raw, files, tier) for tier in raw["extents"]},
        "stars": {
            "rows": totals["rows"],
            "light": totals["light"],
            "observed": totals["observed"],
            "past_the_cap_rows": totals["capped_rows"],
            "past_the_cap_light": totals["capped_light"],
            "no_colour_rows": totals["no_colour_rows"],
        },
        **(
            {"model": _model_metadata(files, model, raw["extents"])}
            if model is not None
            else {}
        ),
        # Only the model's sources. The tree and the nest hold their own credits.
        "credits": paper_credits(PAPERS) if model is not None else [],
    }


def _distribution(root: Path) -> str:
    """The strictest tier of the tree and the nest below `root`. An `undecided`
    tier is refused at the served root."""
    tree, dust = build.tree_metadata(root), sky_map.nest_metadata(root)
    distribution = combined(tree["trees"][TREE]["distribution"], dust["distribution"])
    if distribution == UNDECIDED and root.resolve() == EXTRASOLAR_DIR.resolve():
        raise swap.ExportRefused(
            f"the glow is {UNDECIDED}: name a root other than {EXTRASOLAR_DIR}"
        )
    return distribution


def export_glow(
    root: Path,
    build_dir: Path = build.BUILD_DIR,
    model_dir: Path = model_build.BUILD_DIR,
) -> dict:
    """Write `root/v1/glow/` and return its metadata. Every export holds one lock.

    The model goes with the grid when its build holds an encoding, and one from
    another grid is refused. With no model build the grid goes alone, and a client
    draws the catalogue only. An `undecided` tier may not reach the served root.
    """
    with swap.locked(root):
        return _write(root, build_dir, model_dir)


def read_model(model_dir: Path, build_dir: Path) -> dict | None:
    """The model's encoding, calibration and colour table, or None with no build."""
    if not (model_dir / model_build.ENCODING_FILE).exists():
        logger.warning("glow: no model build in %s, the grid goes alone", model_dir)
        return None
    try:
        encoding = model_build.read_encoding(model_dir, build_dir)
    except model_build.StaleModel as e:
        raise swap.ExportRefused(str(e)) from e
    return {
        "encoding": encoding,
        "calibration": json.loads((model_dir / calibrate.CALIBRATION).read_text()),
        "table": json.loads((model_dir / model_build.TABLE_FILE).read_text()),
    }


Inputs = tuple[dict, form.Table, dict, dict | None, str]


def _write(root: Path, build_dir: Path, model_dir: Path) -> dict:
    def read() -> Inputs:
        return (
            build.read_encoding(build_dir, root),
            form.make_table(np.load(build_dir / build.CURVE)),
            json.loads((build_dir / build.TOTALS).read_text()),
            read_model(model_dir, build_dir),
            _distribution(root),
        )

    def write_files(
        staging: Path, inputs: Inputs
    ) -> dict[tuple[str, str], container.Written]:
        files = {}
        for tier in inputs[0]["extents"]:
            bits = np.load(build_dir / build.bits_name(tier))
            for texture, name in enumerate(TEXTURES):
                part = bits[..., 4 * texture : 4 * texture + 4]
                payload = volume_payload(part, texture, tier)
                path = f"{tier}/{name}.bin.gz"
                files[(tier, name)] = container.write(staging, path, payload)
            if inputs[3] is None:
                continue
            for box, texture in MODEL_BOXES.items():
                bits = np.load(model_dir / model_build.bits_name(box, tier))
                payload = model_payload(bits, texture, tier)
                path = f"{tier}/model-{box}.bin.gz"
                files[(tier, f"model-{box}")] = container.write(staging, path, payload)
        return files

    def metadata_of(
        files: Mapping[tuple[str, str], container.Written],
        token: str,
        inputs: Inputs,
    ) -> dict:
        return _metadata(files, token, *inputs)

    return swap.publish(root, "glow", read, write_files, metadata_of)


def export_glow_only(
    root: Path = EXTRASOLAR_DIR,
    build_dir: Path = build.BUILD_DIR,
    model_dir: Path = model_build.BUILD_DIR,
) -> None:
    metadata = export_glow(root, build_dir, model_dir)
    sizes = {
        tier: sum(entry["bytes"] for entry in metadata["tiers"][tier]["files"].values())
        + sum(
            entry["bytes"]
            for entry in metadata.get("model", {})
            .get("tiers", {})
            .get(tier, {})
            .values()
        )
        for tier in metadata["tiers"]
    }
    logger.info(
        "glow: %s, %s bytes by tier, token %s",
        metadata["distribution"],
        sizes,
        metadata["token"],
    )
