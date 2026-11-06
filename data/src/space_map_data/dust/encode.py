"""R8 codes for the mean density of a level.

The code is logarithmic, so steps stay relative over the whole range. One
(floor, top) serves both tiers, so `low` can be the first mip of `high`.

A texture filters codes before the shader decodes them, and the decode is convex,
so a filtered fetch of plain codes reads low. `compensate` moves the codes to
cancel this. A fetch with no filter then reads a little high.

`encoding.json` holds the digest and shape of every codes file, the extent of each
level, and what the export needs from the rest of the build. A read refuses codes
that belong to another run, and the export reads nothing else from the build, so
its metadata cannot come from another run than its codes.
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from space_map_data.dust.disc import CALIBRATION_FILE
from space_map_data.dust.merge import merged_dir
from space_map_data.dust.nest import LEVELS
from space_map_data.dust.parallel import forked_map
from space_map_data.dust.sources import BUILD_DIR, atomic_npy
from space_map_data.export.swap import ExportRefused
from space_map_data.extrasolar.store import write_json

ENCODED_DIR = BUILD_DIR / "encoded"
TIERS = ("high", "low")
FLOORS = {0: 1e-6, 1: 1e-6, 2: 1e-6, 3: 1e-6}
COMPENSATE_STEPS = 3
ENCODING_FILE = "encoding.json"
DIGEST_BLOCK = 1 << 20


class StaleCodes(ExportRefused):
    """Codes on disk that `encoding.json` does not list."""


@dataclass(frozen=True)
class Encoding:
    floor: float
    top: float

    @property
    def span(self) -> float:
        return float(np.log1p(self.top / self.floor))

    def scaled(self, density: np.ndarray) -> np.ndarray:
        """The code of a density, before rounding."""
        return np.log1p(density / self.floor) / self.span * 255.0

    def encode(self, density: np.ndarray) -> np.ndarray:
        return np.clip(np.rint(self.scaled(density)), 0, 255).astype(np.uint8)

    def decode(self, codes: np.ndarray) -> np.ndarray:
        return (self.floor * np.expm1(codes / 255.0 * self.span)).astype("f4")


@dataclass(frozen=True)
class Recorded:
    """What `encoding.json` holds."""

    levels: dict[int, Encoding]
    # The half extent of each level in pc, and the shape of each codes file.
    half_extents: dict[int, tuple[float, ...]]
    shapes: dict[str, tuple[int, ...]]
    # The fitted gain of each disc map.
    gains: dict[str, float]
    # The share of the Sun-view column that the rest layer holds, by level.
    rest_share: dict[str, float]
    # The share of the Planck remainder that the nest leaves unplaced.
    unplaced_share: float


def block_mean(density: np.ndarray) -> np.ndarray:
    """The `low` tier: the mean over each 2 x 2 x 2 block."""
    nx, ny, nz = density.shape
    return (
        density.reshape(nx // 2, 2, ny // 2, 2, nz // 2, 2)
        .mean(axis=(1, 3, 5), dtype="f8")
        .astype("f4")
    )


def encoded_dir(variant: str):
    return ENCODED_DIR / variant


def _toward(grid: np.ndarray, axis: int, sign: int) -> np.ndarray:
    """The linear filter a quarter of a voxel off each centre, clamped at the edge."""
    size = grid.shape[axis]
    neighbour = np.take(grid, np.clip(np.arange(size) + sign, 0, size - 1), axis=axis)
    return 0.75 * grid + 0.25 * neighbour


def filtered_mean(grid: np.ndarray, read) -> np.ndarray:
    """The mean of `read` of the filtered grid, at eight points around each voxel."""
    total = np.zeros(grid.shape, "f8")
    for x in (-1, 1):
        along_x = _toward(grid, 0, x)
        for y in (-1, 1):
            along_y = _toward(along_x, 1, y)
            for z in (-1, 1):
                total += read(_toward(along_y, 2, z))
    return (total / 8.0).astype("f4")


def compensate(density: np.ndarray, encoding: Encoding) -> np.ndarray:
    """Codes whose filtered fetch keeps the mean of the linear filter."""
    wanted = encoding.scaled(filtered_mean(density, lambda grid: grid))
    codes = encoding.scaled(density).astype("f4")
    for _ in range(COMPENSATE_STEPS):
        got = encoding.scaled(filtered_mean(codes, encoding.decode))
        codes = np.clip(codes + wanted - got, 0.0, 255.0)
    return np.rint(codes).astype(np.uint8)


def _encode_job(job: tuple[str, int, str, Encoding]) -> None:
    variant, index, tier, encoding = job
    density = np.load(merged_dir(variant) / f"l{index}.density.npy")
    if tier == "low":
        density = block_mean(density)
    codes = compensate(density, encoding)
    atomic_npy(encoded_dir(variant) / codes_name(index, tier), codes)


def codes_name(index: int, tier: str) -> str:
    return f"l{index}.{tier}.npy"


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(DIGEST_BLOCK):
            digest.update(block)
    return digest.hexdigest()


def build_encoded(variant: str, floors: dict[int, float], workers: int) -> None:
    """Write the codes of both tiers, then `encoding.json` with their digests and
    the figures that the export takes from the build."""
    directory = encoded_dir(variant)
    encodings = {}
    for level in LEVELS:
        top = float(np.load(merged_dir(variant) / f"l{level.index}.density.npy").max())
        encodings[level.index] = Encoding(floors[level.index], top)
    jobs = [
        (variant, level.index, tier, encodings[level.index])
        for level in LEVELS
        for tier in TIERS
    ]
    forked_map(_encode_job, jobs, min(workers, 4))
    names = [codes_name(level.index, tier) for level in LEVELS for tier in TIERS]
    merged = merged_dir(variant)
    write_json(
        directory / ENCODING_FILE,
        {
            "levels": {
                str(level.index): asdict(encodings[level.index])
                | {"half_extent_pc": list(level.half)}
                for level in LEVELS
            },
            "codes": {name: file_digest(directory / name) for name in names},
            "shapes": {
                name: list(np.load(directory / name, mmap_mode="r").shape)
                for name in names
            },
            "gains": json.loads(CALIBRATION_FILE.read_text())["gains"],
            "rest_share": json.loads((merged / "rest_share.json").read_text()),
            "unplaced_share": json.loads((merged / "rest.json").read_text())[
                "unplaced_share"
            ],
        },
    )


def read_recorded(variant: str) -> Recorded:
    """Everything `encoding.json` holds. It refuses codes that the file does not list."""
    directory = encoded_dir(variant)
    raw = json.loads((directory / ENCODING_FILE).read_text())
    for name, digest in raw["codes"].items():
        if file_digest(directory / name) != digest:
            raise StaleCodes(
                f"{directory / name} is not the file that {ENCODING_FILE} was"
                " written for: run encode again"
            )
    levels = {int(index): values for index, values in raw["levels"].items()}
    return Recorded(
        {index: Encoding(v["floor"], v["top"]) for index, v in levels.items()},
        {index: tuple(v["half_extent_pc"]) for index, v in levels.items()},
        {name: tuple(shape) for name, shape in raw["shapes"].items()},
        raw["gains"],
        raw["rest_share"],
        raw["unplaced_share"],
    )


def read_encodings(variant: str) -> dict[int, Encoding]:
    """The encoding of each level, from codes that `encoding.json` lists."""
    return read_recorded(variant).levels
