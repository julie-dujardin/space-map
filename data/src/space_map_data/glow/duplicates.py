"""Rows of the tree that repeat a star, so the grid counts it once.

For a bright star Gaia can hold two sources. Hipparcos or SIMBAD may then claim the one
with no 5 sigma parallax, and the other stays a row of its own, so the star has two
rows and the tree draws both. Such a pair is a row with no Gaia astrometry beside a Gaia
row of about the same magnitude. The Gaia row stays: its distance is the better one.
A row the app draws on its own path has no such list: that is the Sun, which has no
row, and the exact stars, which hide their row by rows at run time.
"""

import logging

import cdshealpix
import numpy as np
from scipy.spatial import KDTree

from space_map_data.dust.parallel import forked_stream
from space_map_data.dust.resample import points_pixels
from space_map_data.extrasolar.placement import GAIA_ASTROMETRY
from space_map_data.extrasolar.registry import Registry
from space_map_data.extrasolar.sky import REGION_COUNT
from space_map_data.glow import tree

logger = logging.getLogger(__name__)

# A close pair at this separation is unresolved in the catalogues that make a row.
MATCH_ARCSEC = 1.5
MATCH_MAG = 0.75
# About 26 arcsec. A match lies in a cell or in one of its neighbours.
CELL_DEPTH = 13
BATCH_NODES = 256
# The faintest row a pair can hold: a Gaia row near a Hipparcos or SIMBAD star.
FAINTEST = 16.0

# Forked workers read these.
_registry: Registry | None = None
_ids: np.ndarray | None = None
_cells: np.ndarray | None = None


def _other_ids(region: int) -> np.ndarray:
    assert _registry is not None
    table = _registry.read_table("point-source", region, ["id", "astrometry_source"])
    if table is None:
        return np.zeros(0, np.int64)
    source = table["astrometry_source"].to_numpy(zero_copy_only=False)
    return table["id"].to_numpy()[~np.isin(source.astype(str), GAIA_ASTROMETRY)]


def _apparent(mag: np.ndarray, position: np.ndarray) -> np.ndarray:
    return mag + 5 * np.log10(np.maximum(np.linalg.norm(position, axis=1), 1e-6) / 10)


def _others(names: list[str]) -> list[tuple[str, np.ndarray, np.ndarray, np.ndarray]]:
    """In each node, the rows with no Gaia astrometry: row, unit vector, magnitude."""
    assert _ids is not None
    out = []
    for name in names:
        ids = tree.read_ids(name)
        at = np.searchsorted(_ids, ids)
        hit = _ids[np.minimum(at, len(_ids) - 1)] == ids
        if hit.any():
            node = tree.read_node(name)
            position = node.position[hit]
            out.append(
                (
                    name,
                    np.flatnonzero(hit),
                    position / np.linalg.norm(position, axis=1, keepdims=True),
                    _apparent(node.mag[hit], position),
                )
            )
    return out


def _neighbours(names: list[str]) -> list[tuple[np.ndarray, np.ndarray]]:
    """Gaia rows in the cells of the other rows: unit vector, magnitude."""
    assert _ids is not None and _cells is not None
    out = []
    for name in names:
        node = tree.read_node(name)
        apparent = _apparent(node.mag, node.position)
        cell = points_pixels(node.position, CELL_DEPTH)
        at = np.searchsorted(_cells, cell)
        near = _cells[np.minimum(at, len(_cells) - 1)] == cell
        near &= apparent < FAINTEST
        if not near.any():
            continue
        ids = tree.read_ids(name)[near]
        where = np.searchsorted(_ids, ids)
        gaia = _ids[np.minimum(where, len(_ids) - 1)] != ids
        position = node.position[near][gaia]
        out.append(
            (
                position / np.linalg.norm(position, axis=1, keepdims=True),
                apparent[near][gaia],
            )
        )
    return out


def repeated_rows(
    vectors: np.ndarray,
    magnitudes: np.ndarray,
    gaia_vectors: np.ndarray,
    gaia_magnitudes: np.ndarray,
) -> np.ndarray:
    """Which rows have a Gaia row close by, of about the same magnitude."""
    chord = 2 * np.sin(np.radians(MATCH_ARCSEC / 3600) / 2)
    matches = KDTree(gaia_vectors).query_ball_point(vectors, chord)
    return np.array(
        [
            bool(at)
            and bool((np.abs(gaia_magnitudes[at] - magnitudes[i]) < MATCH_MAG).any())
            for i, at in enumerate(matches)
        ],
        bool,
    )


def find_duplicates(
    registry: Registry, workers: int
) -> tuple[np.ndarray, np.ndarray, dict]:
    """The node and row of each row the grid leaves out, and a report. The caller
    holds the registry's reader lock and has checked that the tree is from it."""
    global _registry, _ids, _cells
    _registry = registry
    try:
        other = list(forked_stream(_other_ids, range(REGION_COUNT), workers))
        _ids = np.sort(np.concatenate(other))
        names = tree.node_names()
        batches = [
            names[at : at + BATCH_NODES] for at in range(0, len(names), BATCH_NODES)
        ]
        found = [
            hit for part in forked_stream(_others, batches, workers) for hit in part
        ]
        nodes = np.concatenate([np.full(len(hit[1]), hit[0]) for hit in found])
        rows = np.concatenate([hit[1] for hit in found])
        vectors = np.concatenate([hit[2] for hit in found])
        magnitudes = np.concatenate([hit[3] for hit in found])
        cells = points_pixels(vectors, CELL_DEPTH).astype(np.uint64)
        around = cdshealpix.neighbours(cells, CELL_DEPTH).astype(np.int64)
        _cells = np.unique(
            np.concatenate((around[around >= 0], cells.astype(np.int64)))
        )
        near = [
            hit for part in forked_stream(_neighbours, batches, workers) for hit in part
        ]
    finally:
        _registry = _ids = _cells = None
    gaia_vectors = np.concatenate([hit[0] for hit in near])
    gaia_magnitudes = np.concatenate([hit[1] for hit in near])
    repeated = repeated_rows(vectors, magnitudes, gaia_vectors, gaia_magnitudes)
    report = {
        "rows_without_gaia_astrometry": len(rows),
        "repeated": int(repeated.sum()),
        "match_arcsec": MATCH_ARCSEC,
        "match_mag": MATCH_MAG,
    }
    logger.info("duplicates: %s", report)
    return nodes[repeated], rows[repeated].astype(np.int64), report
