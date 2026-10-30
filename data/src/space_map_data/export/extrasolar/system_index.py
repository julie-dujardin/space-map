"""The index of the star systems that search finds, and of their held stars.

`systems/index.json.gz` lists each root that holds a held star, a drawn
orbit or a planet host: its ID, name, class, star count and its named held
stars. These are the systems that a page draws up close. Search makes an
object document of each root and of each held star in it
(`search.indices.extrasolar`), as it does of a planet host.

The names and classes come from the Metadata rows, which the Metadata tiles
read (`tiles.UnitJob.names`). The file has the token of its section in its
`token` field, as the planet files do.
"""

import gzip
import hashlib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow as pa

from space_map_data.export.extrasolar import container
from space_map_data.export.extrasolar.container import Written
from space_map_data.export.extrasolar.systems import HELD, Systems
from space_map_data.extrasolar.ids import CELL_MASK
from space_map_data.extrasolar.sky import region_of
from space_map_data.utils.arrays import find_sorted

SECTION = "systems"
INDEX_FILE = f"{SECTION}/index.json.gz"
ZERO_TOKEN = "0" * container.TOKEN_SIZE


@dataclass(frozen=True)
class Listed:
    """The listed roots, sorted, with their star counts, and the held stars,
    sorted, with the root of each."""

    roots: np.ndarray
    stars: np.ndarray
    held: np.ndarray
    held_roots: np.ndarray

    @property
    def ids(self) -> np.ndarray:
        """The IDs whose names the index takes, sorted."""
        return np.union1d(self.roots, self.held)


def listed(systems: Systems, planet_keys: np.ndarray) -> Listed:
    """The roots that hold a held star, a drawn orbit or a planet host, and
    the held stars. `planet_keys` are the keys of the planet files."""
    held = (systems.member_kind == HELD) & (systems.member_id > 0)
    held_ids = systems.member_id[held]
    held_roots = systems.root[find_sorted(systems.id, systems.member_node[held])]
    keys = systems.id[(systems.parent == 0) & np.isin(systems.id, planet_keys)]
    roots = np.unique(
        np.concatenate([held_roots, systems.root[systems.has_orbit], keys])
    )
    order = np.argsort(held_ids, kind="stable")
    return Listed(
        roots,
        systems.stars[find_sorted(systems.id, roots)],
        held_ids[order],
        held_roots[order],
    )


def ids_by_unit(ids: np.ndarray, units: list[tuple[int, ...]]) -> list[np.ndarray]:
    """The IDs of each unit, a run of regions, sorted."""
    regions = region_of(ids & CELL_MASK)
    return [ids[(regions >= unit[0]) & (regions <= unit[-1])] for unit in units]


def write(listed: Listed, names: pa.Table, out: Path) -> tuple[Written, dict]:
    """Write INDEX_FILE below `out`. Returns it and its section of
    metadata.json. A held star with no name is left out."""
    found = {row["id"]: (row["name"], row["class"]) for row in names.to_pylist()}
    held_of: dict[int, list[dict]] = defaultdict(list)
    for id_, root in zip(listed.held.tolist(), listed.held_roots.tolist()):
        name = found.get(id_, (None, None))[0]
        if name:
            held_of[root].append({"id": id_, "name": name})
    systems = []
    for root, stars in zip(listed.roots.tolist(), listed.stars.tolist()):
        name, cls = found.get(root, (None, None))
        systems.append(
            {
                "id": root,
                "name": name,
                "class": cls,
                "stars": stars,
                "held": held_of.get(root, []),
            }
        )
    content: dict = {"token": ZERO_TOKEN, "systems": systems}
    digest = hashlib.sha256(container.json_payload(content)).digest()
    token = container.token_of([Written(INDEX_FILE, digest, 0, 0)])
    content["token"] = token
    data = gzip.compress(container.json_payload(content), compresslevel=9, mtime=0)
    target = out / INDEX_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    held = sum(len(system["held"]) for system in systems)
    entry = {
        "token": token,
        "index": INDEX_FILE,
        "systems": len(systems),
        "held": held,
    }
    return Written(INDEX_FILE, digest, len(systems), len(data)), entry
