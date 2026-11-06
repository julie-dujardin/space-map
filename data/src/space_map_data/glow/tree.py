"""Read the Milky Way render tree as it was exported, one node at a time."""

import struct
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from space_map_data.export.extrasolar import container
from space_map_data.export.extrasolar.render import NODE_INFO, TREE
from space_map_data.utils.paths import EXTRASOLAR_DIR

NODE_DIR = EXTRASOLAR_DIR / "v1" / "x" / TREE / "node"
ID_DIR = EXTRASOLAR_DIR / "v1" / "x" / TREE / "id"
SUFFIX = ".bin.gz"
_CENTRE = struct.Struct("<3d")


@dataclass(frozen=True)
class NodeRows:
    """The rows of a node. `position` is ICRS in pc, shape (n, 3)."""

    name: str
    position: np.ndarray
    mag: np.ndarray
    colour: np.ndarray


def node_names(directory: Path = NODE_DIR) -> list[str]:
    """Every node, sorted, so a run visits them in the same order."""
    return sorted(path.name.removesuffix(SUFFIX) for path in directory.iterdir())


def read_node(name: str, directory: Path = NODE_DIR) -> NodeRows:
    node = container.read(directory / f"{name}{SUFFIX}")
    if len(node.info) != NODE_INFO.size:
        raise container.FormatError(f"{name}: not a tree node")
    centre = np.array(_CENTRE.unpack_from(node.info), np.float64)
    position = np.stack([node.numpy(axis) for axis in "xyz"], axis=1).astype(np.float64)
    return NodeRows(
        name,
        position + centre,
        node.numpy("mag").astype(np.float64),
        node.numpy("colour").astype(np.float64),
    )


def read_ids(name: str, directory: Path = ID_DIR) -> np.ndarray:
    return container.read(directory / f"{name}{SUFFIX}").numpy("id")


def rows_of(names: list[str], directory: Path = NODE_DIR) -> Iterator[NodeRows]:
    for name in names:
        yield read_node(name, directory)
