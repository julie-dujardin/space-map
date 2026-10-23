"""Read an extrasolar export with the steps that a client takes.

For an ID: check it against the table numbers in metadata.json, take the cell
and the home table from it, find the leaf of the cell in the split tables of
Metadata and of the home table, read both tiles, check their tokens, and find
the row by binary search on the ID column. An alias row sends the lookup on to
its target. The mask names the other tables with a row, at the same cell.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from space_map_data.export.extrasolar import container, render, tiles
from space_map_data.export.extrasolar.container import Container
from space_map_data.export.extrasolar.tiles import Split
from space_map_data.extrasolar.ids import cell_of, parse, table_of
from space_map_data.extrasolar.tables import METADATA


class TokenMismatch(Exception):
    pass


@dataclass
class Lookup:
    id: int
    metadata: dict
    rows: dict[str, dict] = field(default_factory=dict)
    redirected_from: int | None = None


@dataclass(frozen=True)
class NodeInfo:
    centre: tuple[float, float, float]
    half: float
    min_range: float
    max_range: float
    child_range: tuple[float, ...]
    depth: int
    child_mask: int

    @classmethod
    def of(cls, node: Container) -> NodeInfo:
        values = render.NODE_INFO.unpack(node.info)
        return cls(
            tuple(values[0:3]),
            values[3],
            values[4],
            values[5],
            tuple(values[6:14]),
            values[14],
            values[15],
        )


class ExportReader:
    def __init__(self, root: Path) -> None:
        """`root` is the `v1/x` directory."""
        self.root = root
        self.metadata = json.loads((root / "metadata.json").read_text())
        self._splits: dict[str, Split] = {}

    @property
    def numbers(self) -> dict[int, str]:
        return {
            entry["number"]: slug
            for slug, entry in self.metadata["tables"].items()
            if entry["number"] is not None
        }

    def read(self, path: str, token: str) -> Container:
        file = container.read(self.root / path)
        if file.token != token:
            raise TokenMismatch(f"{path}: token {file.token}, expected {token}")
        return file

    def split(self, slug: str) -> Split:
        if slug not in self._splits:
            entry = self.metadata["tables"][slug]
            bits = self.read(entry["split"], entry["token"]).numpy("split")
            self._splits[slug] = Split.from_bits(bits, entry["split"])
        return self._splits[slug]

    def tile(self, slug: str, cell: int) -> tuple[str, Container]:
        split = self.split(slug)
        leaf = int(split.leaf_of(np.array([cell]))[0])
        path = tiles.tile_path(slug, int(split.level[leaf]), int(split.pixel[leaf]))
        return path, self.read(path, self.metadata["tables"][slug]["token"])

    def row(self, slug: str, id_: int) -> dict | None:
        _, tile = self.tile(slug, cell_of(id_))
        ids = tile.numpy("id")
        at = int(np.searchsorted(ids, id_))
        if at == ids.size or ids[at] != id_:
            return None
        return tile.table().slice(at, 1).to_pylist()[0]

    def lookup(self, text: str) -> Lookup | None:
        """The records of the ID in a URL segment, or None for a 404."""
        id_ = parse(text, set(self.numbers))
        if id_ is None:
            return None
        meta = self.row(METADATA.slug, id_)
        if meta is None:
            return None
        if meta["alias_target"] is not None:
            target = self.lookup(str(meta["alias_target"]))
            if target is not None:
                target.redirected_from = id_
            return target
        found = Lookup(id_, meta)
        home = self.numbers[table_of(id_)]
        for number, slug in self.numbers.items():
            if meta["mask"] >> number & 1 or slug == home:
                row = self.row(slug, id_)
                if row is not None:
                    found.rows[slug] = row
        return found

    # The render tree

    @property
    def tree(self) -> dict:
        return self.metadata["trees"][render.TREE]

    def node(self, name: str) -> Container:
        return self.read(render.node_path(name), self.tree["token"])

    def node_ids(self, name: str) -> np.ndarray:
        ids = self.read(render.ids_path(name), self.tree["token"])
        return ids.numpy("id")

    def find_render(
        self, id_: int, position: tuple[float, float, float]
    ) -> tuple[str, int] | None:
        """The node and row of `id_`, walking down from the root to the octant
        that holds `position` (parsecs)."""
        name = "r"
        while True:
            ids = self.node_ids(name)
            hits = np.flatnonzero(ids == id_)
            if hits.size:
                return name, int(hits[0])
            info = NodeInfo.of(self.node(name))
            k = sum(
                1 << axis for axis in range(3) if position[axis] >= info.centre[axis]
            )
            if not info.child_mask >> k & 1:
                return None
            name += str(k)
