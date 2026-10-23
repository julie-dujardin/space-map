"""The Milky Way render tree.

An octree by visibility range. The root is a cube centred at ROOT_CENTRE, near
the solar system barycentre, HALF_SIZE parsecs from its centre to each face.
Positions are in ICRS equatorial axes from the barycentre: x to RA 0° Dec 0°,
y to RA 90° Dec 0°, z to Dec +90°. A
node keeps the NODE_ROWS objects with the largest visibility range of the
objects in its box that no ancestor keeps, and passes the rest to its eight
children. Ties go by the order of the Point source table (cell, then ID).

A node is named "r" for the root, and a child adds its octant digit k to the
name of its parent: bit 0 of k is set when the child is on the +x side of the
centre, bit 1 the +y side, bit 2 the +z side. A node file lists which children
exist and the largest visibility range in each child's subtree, which is the
largest in the child itself.

The visibility range of a light source is the distance at which its apparent
magnitude reaches RANGE_LIMIT_MAG. The rows of a node file are in order of
range, the largest first, then by ID.

The build works in three steps with scratch files on disk: render rows per
region, the node of each row from the whole sky, then the node files in
batches of nodes.
"""

import logging
import struct
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from space_map_data.export.extrasolar import container
from space_map_data.export.extrasolar.container import Column, Written
from space_map_data.extrasolar.registry import Registry
from space_map_data.extrasolar.sources.hipparcos import g_estimate, propagate
from space_map_data.extrasolar.tables import POINT_SOURCE

logger = logging.getLogger(__name__)

TREE = "mw"
HALF_SIZE = float(2**18)
# The root centre is off the barycentre. So the Sun is about a third of a node
# from each face of its node at every depth, because 1/3 is 0.0101... in binary.
# At the barycentre, the Sun is on a corner of 8 nodes at every depth, and all
# of them load from the solar system. The offset is HALF_SIZE / 3 to the
# nearest 1/256 pc, so every node centre is exact in float64.
ROOT_CENTRE = (round(HALF_SIZE / 3 * 256) / 256,) * 3
NODE_ROWS = 10_000
# Octree levels that the keys resolve. A node at this depth keeps all its rows.
KEY_LEVELS = 21
# Naked-eye limit for a dark sky. A client that draws fainter stars scales
# every range by 10^((its limit - RANGE_LIMIT_MAG) / 5).
RANGE_LIMIT_MAG = 6.5
EPOCH = 2016.0
MIN_PARALLAX_SNR = 5.0
MIN_FIDELITY = 0.5
CLASS_STAR = 1
# Magnitudes and colours in the render tree are rounded to this step. The
# step is too small to see, and rounded values compress better.
MAG_STEP = 1 / 1024
CLASSES = {"star": CLASS_STAR}
# Gaia BP - RP from the Hipparcos V - I (Riello et al. 2021, A&A 649, A3,
# Table C.2), valid for V - I from -0.5 to 3.5 with a scatter of 0.082 mag.
BP_RP_FROM_V_I = (-0.01612, 1.274, -0.08143)
V_I_RANGE = (-0.5, 3.5)
NODE_INFO = struct.Struct("<4d2f8fBB6x")
BATCH_ROWS = 4_000_000

COLUMNS = (
    "id",
    "ra",
    "dec",
    "parallax",
    "parallax_error",
    "pmra",
    "pmdec",
    "epoch",
    "phot_g_mean_mag",
    "phot_bp_mean_mag",
    "phot_rp_mean_mag",
    "hp_mag",
    "v_mag",
    "b_v",
    "v_i",
    "fidelity_v2",
    "astrometry_source",
    "hipparcos_photometry_source",
)
# Arrays of one render row, in the scratch files.
ROW_ARRAYS = {
    "id": np.int64,
    "x": np.float64,
    "y": np.float64,
    "z": np.float64,
    "range": np.float32,
    "mag": np.float32,
    "colour": np.float32,
    "class": np.uint8,
    "key": np.uint64,
}
# The row arrays of a batch file. Only `assign` reads the key.
BATCH_ARRAYS = tuple(name for name in ROW_ARRAYS if name != "key")
NODE_COLUMNS = (
    ("x", "float32"),
    ("y", "float32"),
    ("z", "float32"),
    ("range", "float32"),
    ("mag", "float32"),
    ("colour", "float32"),
    ("class", "uint8"),
)
ID_COLUMNS = (("id", "id"),)


def node_path(name: str) -> str:
    return f"{TREE}/node/{name}.bin.gz"


def ids_path(name: str) -> str:
    return f"{TREE}/id/{name}.bin.gz"


def bp_rp_from_v_i(v_i: np.ndarray) -> np.ndarray:
    return np.polynomial.polynomial.polyval(np.clip(v_i, *V_I_RANGE), BP_RP_FROM_V_I)


def visibility_range(abs_mag: np.ndarray) -> np.ndarray:
    """Parsecs at which an object of absolute magnitude `abs_mag` reaches
    RANGE_LIMIT_MAG."""
    return 10.0 ** ((RANGE_LIMIT_MAG - abs_mag) / 5 + 1)


def _part1by2(v: np.ndarray) -> np.ndarray:
    v = v & np.uint64(0x1FFFFF)
    for shift, mask in (
        (32, 0x1F00000000FFFF),
        (16, 0x1F0000FF0000FF),
        (8, 0x100F00F00F00F00F),
        (4, 0x10C30C30C30C30C3),
        (2, 0x1249249249249249),
    ):
        v = (v | (v << np.uint64(shift))) & np.uint64(mask)
    return v


def morton_keys(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> np.ndarray:
    """The octant digits of each position at every depth, the root's first."""
    scale = 2**KEY_LEVELS / (2 * HALF_SIZE)
    key = np.zeros(len(x), np.uint64)
    for axis, values in enumerate((x, y, z)):
        low = ROOT_CENTRE[axis] - HALF_SIZE
        cell = np.clip(np.floor((values - low) * scale), 0, 2**KEY_LEVELS - 1)
        key |= _part1by2(cell.astype(np.uint64)) << np.uint64(axis)
    return key


def _round(values: np.ndarray) -> np.ndarray:
    return np.round(values / MAG_STEP) * MAG_STEP


def _floats(table: pa.Table, name: str) -> np.ndarray:
    return table[name].to_numpy().astype(np.float64)


def render_rows(table: pa.Table) -> tuple[dict[str, np.ndarray], Counter]:
    """The render rows of Point source rows, and what was dropped and why."""
    counts: Counter = Counter()
    counts["rows"] = table.num_rows
    parallax = _floats(table, "parallax")
    snr = parallax / _floats(table, "parallax_error")
    positioned = snr > MIN_PARALLAX_SNR
    hipparcos = (
        table["hipparcos_photometry_source"].is_valid().to_numpy(zero_copy_only=False)
    )
    fidelity = _floats(table, "fidelity_v2")
    trusted = ~(fidelity < MIN_FIDELITY) | hipparcos
    gaia = pc.equal(table["astrometry_source"], "gaia-dr3").to_numpy(
        zero_copy_only=False
    )
    counts["no 5-sigma parallax, Gaia"] = int((~positioned & gaia).sum())
    counts["no 5-sigma parallax, Hipparcos only"] = int((~positioned & ~gaia).sum())
    counts["flagged by fidelity"] = int((positioned & ~trusted).sum())
    counts["flagged by fidelity, kept for a Hipparcos match"] = int(
        (positioned & (fidelity < MIN_FIDELITY) & hipparcos).sum()
    )

    g = _floats(table, "phot_g_mean_mag")
    estimate = g_estimate(
        _floats(table, "v_mag"), _floats(table, "b_v"), _floats(table, "hp_mag")
    )
    mag = np.where(np.isfinite(g), g, estimate)
    counts["G estimated from Hipparcos"] = int(
        (positioned & trusted & ~np.isfinite(g) & np.isfinite(mag)).sum()
    )
    bright = np.isfinite(mag)
    counts["no magnitude"] = int((positioned & trusted & ~bright).sum())
    keep = positioned & trusted & bright
    table = table.filter(pa.array(keep))

    ra, dec = _floats(table, "ra"), _floats(table, "dec")
    years = EPOCH - _floats(table, "epoch")
    moving = (years != 0) & np.isfinite(_floats(table, "pmra"))
    if moving.any():
        moved = propagate(
            ra[moving],
            dec[moving],
            _floats(table, "pmra")[moving],
            _floats(table, "pmdec")[moving],
            years[moving],
        )
        ra[moving], dec[moving] = moved
    counts[f"moved to J{EPOCH}"] = int(moving.sum())

    distance = 1000.0 / _floats(table, "parallax")
    ra_rad, dec_rad = np.radians(ra), np.radians(dec)
    x = distance * np.cos(dec_rad) * np.cos(ra_rad)
    y = distance * np.cos(dec_rad) * np.sin(ra_rad)
    z = distance * np.sin(dec_rad)
    offsets = [np.abs(v - c) for v, c in zip((x, y, z), ROOT_CENTRE)]
    inside = np.maximum.reduce(offsets) < HALF_SIZE
    counts["outside the root cube"] = int((~inside).sum())

    abs_mag = _round(mag[keep] + 5 * np.log10(_floats(table, "parallax")) - 10)
    bp_rp = _floats(table, "phot_bp_mean_mag") - _floats(table, "phot_rp_mean_mag")
    from_v_i = bp_rp_from_v_i(_floats(table, "v_i"))
    colour = _round(np.where(np.isfinite(bp_rp), bp_rp, from_v_i))
    counts["BP - RP from Hipparcos V - I"] = int(
        (~np.isfinite(bp_rp) & np.isfinite(from_v_i))[inside].sum()
    )
    counts["no colour"] = int((~np.isfinite(colour))[inside].sum())

    rows = {
        "id": table["id"].to_numpy(),
        "x": x,
        "y": y,
        "z": z,
        "range": visibility_range(abs_mag).astype(np.float32),
        "mag": abs_mag.astype(np.float32),
        "colour": colour.astype(np.float32),
        "class": np.full(len(x), CLASS_STAR, np.uint8),
    }
    rows = {name: values[inside] for name, values in rows.items()}
    rows["key"] = morton_keys(rows["x"], rows["y"], rows["z"])
    counts["rendered"] = int(inside.sum())
    return rows, counts


def scratch_file(scratch: Path, region: int, name: str) -> Path:
    return scratch / "rows" / f"{region:03d}.{name}.npy"


@dataclass(frozen=True)
class RowsJob:
    registry: Registry
    region: int
    scratch: Path


def region_rows(job: RowsJob) -> tuple[int, Counter]:
    """Write the render rows of one region to the scratch directory."""
    columns = list(COLUMNS)
    table = job.registry.read_table("point-source", job.region, columns)
    if table is None:
        table = POINT_SOURCE.schema.empty_table().select(columns)
    rows, counts = render_rows(table)
    for name, values in rows.items():
        path = scratch_file(job.scratch, job.region, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.save(path, np.ascontiguousarray(values, ROW_ARRAYS[name]))
    return job.region, counts


@dataclass
class Node:
    name: str
    depth: int
    centre: tuple[float, float, float]
    half: float
    rows: int = 0
    min_range: float = 0.0
    max_range: float = 0.0
    child_range: list[float] = field(default_factory=lambda: [0.0] * 8)

    @property
    def child_mask(self) -> int:
        return sum(1 << k for k, r in enumerate(self.child_range) if r > 0)

    def info(self) -> bytes:
        return NODE_INFO.pack(
            *self.centre,
            self.half,
            self.min_range,
            self.max_range,
            *self.child_range,
            self.depth,
            self.child_mask,
        )


def _range_of(prio: np.ndarray) -> float:
    return float(np.array([prio >> np.uint64(32)], np.uint32).view(np.float32)[0])


def _priorities(ranges: np.ndarray, order: np.ndarray) -> np.ndarray:
    """Range bits over the inverted table position, so a larger range or an
    earlier row comes first, and no two rows tie."""
    prio = np.empty(order.size, np.uint64)
    step = 1 << 24
    for at in range(0, order.size, step):
        part = order[at : at + step]
        prio[at : at + step] = ranges.view(np.uint32)[part].astype(
            np.uint64
        ) << np.uint64(32)
        prio[at : at + step] |= np.uint64(0xFFFFFFFF) - part.astype(np.uint64)
    return prio


def assign(keys: np.ndarray, ranges: np.ndarray) -> tuple[np.ndarray, list[Node]]:
    """The node of each row, and the nodes in pre-order.

    `keys` and `ranges` are in table order. `keys` is sorted in place.
    """
    count = keys.size
    if count >= 2**32:
        raise ValueError("over 2^32 render rows")
    order = np.argsort(keys, kind="stable")
    keys[:] = keys[order]
    prio = _priorities(ranges, order)
    node_of = np.full(count, -1, np.int32)
    nodes: list[Node] = []
    full = 0

    def visit(lo, hi, depth, centre, half, name) -> Node | None:
        nonlocal full
        segment = node_of[lo:hi]
        free = segment < 0
        n = int(np.count_nonzero(free))
        if not n:
            return None
        node = Node(name, depth, centre, half)
        index = len(nodes)
        nodes.append(node)
        weights = prio[lo:hi]
        if n <= NODE_ROWS or depth == KEY_LEVELS:
            take = free
            if n > NODE_ROWS:
                full += 1
        else:
            candidates = weights[free]
            candidates.partition(n - NODE_ROWS)
            take = free & (weights >= candidates[n - NODE_ROWS])
            del candidates
        segment[take] = index
        kept = weights[take]
        node.rows = int(kept.size)
        node.min_range = _range_of(kept.min())
        node.max_range = _range_of(kept.max())
        del free, take, kept
        if n == node.rows:
            return node
        # Keys of a node share their digits down to its depth, so each child
        # is the run of keys from its own digit on.
        shift = 3 * (KEY_LEVELS - 1 - depth)
        base = (int(keys[lo]) >> (shift + 3)) << (shift + 3)
        starts = np.array([base + (k << shift) for k in range(8)], np.uint64)
        bounds = np.r_[lo + np.searchsorted(keys[lo:hi], starts), hi]
        quarter = half / 2
        for k in range(8):
            child_centre = tuple(
                c + (quarter if (k >> axis) & 1 else -quarter)
                for axis, c in enumerate(centre)
            )
            child = visit(
                int(bounds[k]),
                int(bounds[k + 1]),
                depth + 1,
                child_centre,
                quarter,
                name + str(k),
            )
            if child is not None:
                node.child_range[k] = child.max_range
        return node

    visit(0, count, 0, ROOT_CENTRE, HALF_SIZE, "r")
    if full:
        logger.warning(
            "%d nodes at depth %d hold over %d rows", full, KEY_LEVELS, NODE_ROWS
        )
    out = np.empty(count, np.int32)
    out[order] = node_of
    return out, nodes


def batches(nodes: list[Node]) -> list[range]:
    """Runs of nodes in pre-order with at most BATCH_ROWS rows, or one node."""
    out = []
    start, rows = 0, 0
    for index, node in enumerate(nodes):
        if rows and rows + node.rows > BATCH_ROWS:
            out.append(range(start, index))
            start, rows = index, 0
        rows += node.rows
    out.append(range(start, len(nodes)))
    return out


def batch_file(scratch: Path, batch: int, region: int) -> Path:
    return scratch / "batch" / f"{batch:04d}" / f"{region:03d}.npz"


@dataclass(frozen=True)
class SplitJob:
    scratch: Path
    region: int
    # The first node of each batch, and the end of the last.
    edges: tuple[int, ...]


def split_region(job: SplitJob) -> None:
    """Move the rows of one region to the batches of their nodes."""
    node = np.load(scratch_file(job.scratch, job.region, "node"))
    if not node.size:
        return
    rows = {
        name: np.load(scratch_file(job.scratch, job.region, name))
        for name in BATCH_ARRAYS
    }
    batch = np.searchsorted(np.array(job.edges), node, side="right") - 1
    for b in np.unique(batch).tolist():
        pick = batch == b
        path = batch_file(job.scratch, b, job.region)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, node=node[pick], **{name: v[pick] for name, v in rows.items()})


@dataclass(frozen=True)
class BatchJob:
    scratch: Path
    batch: int
    out: Path
    first: int
    nodes: tuple[Node, ...]


def node_payloads(node: Node, rows: dict[str, np.ndarray]) -> tuple[bytes, bytes]:
    centre = node.centre
    values = {
        "x": (rows["x"] - centre[0]).astype(np.float32),
        "y": (rows["y"] - centre[1]).astype(np.float32),
        "z": (rows["z"] - centre[2]).astype(np.float32),
        "range": rows["range"],
        "mag": rows["mag"],
        "colour": rows["colour"],
        "class": rows["class"],
    }
    n = len(rows["id"])
    columns = [
        Column(name, kind, pa.array(values[name])) for name, kind in NODE_COLUMNS
    ]
    node_payload = container.encode(container.KIND_NODE, n, columns, node.info())
    id_payload = container.encode(
        container.KIND_IDS, n, [Column("id", "id", pa.array(rows["id"]))]
    )
    return node_payload, id_payload


def _load(path: Path) -> dict[str, np.ndarray]:
    with np.load(path) as piece:
        return {name: piece[name] for name in piece.files}


def build_batch(job: BatchJob) -> list[Written]:
    """Write the node and ID files of one batch of nodes."""
    pieces = sorted((job.scratch / "batch" / f"{job.batch:04d}").glob("*.npz"))
    # A batch has a piece per region, so each file closes after its read.
    loaded = [_load(path) for path in pieces]
    # pop frees the arrays of a piece once the batch holds them.
    rows = {
        name: np.concatenate([piece.pop(name) for piece in loaded])
        for name in ("node", *BATCH_ARRAYS)
    }
    # In a node, the largest range first.
    order = np.lexsort((rows["id"], -rows["range"], rows["node"]))
    rows = {name: values[order] for name, values in rows.items()}
    bounds = np.searchsorted(
        rows["node"], np.arange(job.first, job.first + len(job.nodes) + 1)
    )
    files = []
    for k, node in enumerate(job.nodes):
        part = {name: v[bounds[k] : bounds[k + 1]] for name, v in rows.items()}
        if len(part["id"]) != node.rows:
            raise RuntimeError(
                f"node {node.name}: {len(part['id'])} rows, not {node.rows}"
            )
        node_payload, id_payload = node_payloads(node, part)
        files.append(container.write(job.out, node_path(node.name), node_payload))
        files.append(container.write(job.out, ids_path(node.name), id_payload))
    return files
