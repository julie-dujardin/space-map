"""When the map can place each object, from the position files that ship.

The frontend places an object at a clock date when the file it loads for that
date holds the object, and the row passes the file's validity window and its
own launch or discovery gate. This module reads those numbers back from the
written files. A part the export skipped as unchanged then counts for the
rows it holds on disk, not for the rows the database would give it now.

Each object's windows go on its global bundle entry as ``coverage.windows``.
Probes keep the block their own writer builds.
"""

import logging
import math
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, MutableMapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
from sqlalchemy.orm import Session

from space_map_data.constants.earth_sats.satcat import OrbitCenter
from space_map_data.constants.providers import ID_TYPES, make_object_id
from space_map_data.export.position.format import ID_TYPE_ORDINAL, VERSION
from space_map_data.export.position.layout import position_zone_dir
from space_map_data.export.position.reader import (
    ChebyshevFile,
    ElementsFile,
    read_chebyshev_file,
    read_elements_file,
)
from space_map_data.models.object import Object, ObjectType, Satcat
from space_map_data.utils.convert import date_to_julian
from space_map_data.utils.time import J2000_JD, S_PER_DAY

logger = logging.getLogger(__name__)

# Two windows this close are one. Chunk bounds meet to within a rounding error.
_TOUCH_DAYS = 1e-6

# How far inside a window edge the self-check tests the snapshot selection.
_CHECK_INSET_DAYS = 60.0 / S_PER_DAY

_ID_TYPE_BY_ORDINAL = {ordinal: id_type for id_type, ordinal in ID_TYPE_ORDINAL.items()}

# Bodies SATCAT can name as the centre of an orbit. The other centres
# (Lagrange points, an unnamed asteroid, escape) have no object to point at.
_CENTRE_NAIF_ID: dict[OrbitCenter, int] = {
    OrbitCenter.SUN: 10,
    OrbitCenter.MERCURY: 199,
    OrbitCenter.VENUS: 299,
    OrbitCenter.EARTH: 399,
    OrbitCenter.MOON: 301,
    OrbitCenter.EARTH_MOON_BARYCENTER: 3,
    OrbitCenter.MARS: 499,
    OrbitCenter.JUPITER: 599,
    OrbitCenter.SATURN: 699,
    OrbitCenter.URANUS: 799,
    OrbitCenter.NEPTUNE: 899,
    OrbitCenter.PLUTO: 999,
}

# Reasons a row gives no window, as counted per layer for the log.
_MISSING_ELEMENT = "rows with a missing element"
_NO_DATE_LEFT = "rows with no date left after the gates"
_REPEATED = "rows that repeat an object in one snapshot"
_NO_ID_TYPE = "bodies with no id type"

# Windows as parallel arrays: object key, start JD, end JD. An infinite bound
# means the window has no limit on that side.
type _Rows = tuple[np.ndarray, np.ndarray, np.ndarray]


@dataclass(frozen=True)
class CoverageIndex:
    """The placement windows of every object.

    Rows are sorted by object, then by start. The windows of one object do
    not touch or overlap.
    """

    keys: np.ndarray
    starts: np.ndarray
    ends: np.ndarray

    def objects(self) -> Iterator[tuple[str, list[list[float | None]]]]:
        """Yield `(Object.id, windows)`, with None for an unlimited bound."""
        if not len(self.keys):
            return
        firsts = np.flatnonzero(np.r_[True, self.keys[1:] != self.keys[:-1]]).tolist()
        for first, after in zip(firsts, [*firsts[1:], len(self.keys)]):
            yield (
                _object_id(int(self.keys[first])),
                [
                    [_bound(start), _bound(end)]
                    for start, end in zip(
                        self.starts[first:after].tolist(),
                        self.ends[first:after].tolist(),
                    )
                ],
            )


def _bound(jd: float) -> float | None:
    return None if math.isinf(jd) else jd


def _pack_keys(id_type: int, values: np.ndarray) -> np.ndarray:
    """One sortable int64 per object: the id-type ordinal above the int32 id."""
    return (np.int64(id_type) << 32) | (values.astype(np.int64) & 0xFFFFFFFF)


def _object_id(key: int) -> str:
    value = key & 0xFFFFFFFF
    if value >= 1 << 31:
        value -= 1 << 32
    return make_object_id(_ID_TYPE_BY_ORDINAL[key >> 32], value)


@dataclass(frozen=True)
class _Slice:
    """The clock dates, from `lo` to `hi`, for which the frontend loads `files`."""

    lo: float
    hi: float
    files: tuple[Path, ...]


@dataclass(frozen=True)
class _Decay:
    """Re-entry dates as parallel arrays, sorted by object key."""

    keys: np.ndarray
    jds: np.ndarray


def _part_files(directory: Path, parts: int) -> tuple[Path, ...]:
    return tuple(directory / f"{part}.bin.gz" for part in range(parts))


def _label_jds(labels: list[str]) -> np.ndarray:
    return np.array([date_to_julian(date.fromisoformat(label)) for label in labels])


def _snapshot_slices(
    zone_dir: Path, parts_by_date: Mapping[str, int], labels: list[str]
) -> list[_Slice]:
    """One slice per snapshot of a date-labelled layer, oldest first.

    The frontend loads the snapshot whose label is nearest the clock, and the
    earlier one on a tie. A slice thus runs from the midpoint with the label
    before, excluded, to the midpoint with the label after, included. The
    first and the last snapshot also serve every date beyond them.
    """
    jds = _label_jds(labels)
    mids = ((jds[:-1] + jds[1:]) / 2).tolist()
    return [
        _Slice(lo, hi, _part_files(zone_dir / label, parts_by_date[label]))
        for label, lo, hi in zip(labels, [-math.inf, *mids], [*mids, math.inf])
    ]


def _grid_slices(
    layer: Mapping, files_of: Callable[[int], tuple[Path, ...]]
) -> list[_Slice]:
    """One slice per chunk of a layer on a fixed grid, oldest first.

    The frontend clamps the chunk index, so the first and the last chunk also
    serve every date beyond the grid.
    """
    start_jd, chunk_days, chunks = (
        layer["start_jd"],
        layer["chunk_days"],
        layer["chunks"],
    )
    return [
        _Slice(
            -math.inf if chunk == 0 else start_jd + chunk * chunk_days,
            math.inf if chunk == chunks - 1 else start_jd + (chunk + 1) * chunk_days,
            files_of(chunk),
        )
        for chunk in range(chunks)
    ]


def _read_elements(path: Path) -> ElementsFile | None:
    """Read an elements file, or None when the frontend could not use it."""
    if not path.exists():
        logger.warning("coverage: %s is in the manifest but not on disk", path)
        return None
    file = read_elements_file(path)
    if file.version != VERSION:
        logger.warning(
            "coverage: %s has format version %d, not %d; its rows get no window",
            path,
            file.version,
            VERSION,
        )
        return None
    if file.id_type not in _ID_TYPE_BY_ORDINAL:
        if len(file.ids):
            logger.warning(
                "coverage: %s has no id type; its %d rows get no window",
                path,
                len(file.ids),
            )
        return None
    return file


def _read_chebyshev(path: Path) -> ChebyshevFile | None:
    """Read a chebyshev file, or None when the frontend could not use it."""
    if not path.exists():
        # The writer makes no file for a chunk that no body reaches.
        logger.debug("coverage: no chebyshev chunk at %s", path)
        return None
    file = read_chebyshev_file(path)
    if file.version != VERSION:
        logger.warning(
            "coverage: %s has format version %d, not %d; its bodies get no window",
            path,
            file.version,
            VERSION,
        )
        return None
    return file


def _concat(rows: list[_Rows]) -> _Rows:
    if not rows:
        return np.empty(0, np.int64), np.empty(0), np.empty(0)
    keys, starts, ends = zip(*rows)
    return np.concatenate(keys), np.concatenate(starts), np.concatenate(ends)


def _element_rows(piece: _Slice, dropped: Counter) -> _Rows:
    """The window of each row in a slice: its clock dates, cut to the file's
    validity window and to the row's own gate."""
    rows: list[_Rows] = []
    for path in piece.files:
        file = _read_elements(path)
        if file is None:
            continue
        # A NaN gate means the row has none; fmax then keeps the other bound.
        gates = J2000_JD + file.visible_from_days.astype(np.float64)
        starts = np.fmax(max(piece.lo, file.start_jd), gates)
        ends = np.full(len(starts), min(piece.hi, file.end_jd))
        keep = file.placeable
        dropped[_MISSING_ELEMENT] += int(len(keep) - keep.sum())
        rows.append(
            (_pack_keys(file.id_type, file.ids[keep]), starts[keep], ends[keep])
        )
    return _concat(rows)


def _drop_empty(rows: _Rows, dropped: Counter) -> _Rows:
    """Remove the rows whose gates leave no date in the slice."""
    keys, starts, ends = rows
    keep = starts < ends
    dropped[_NO_DATE_LEFT] += int(len(keep) - keep.sum())
    return keys[keep], starts[keep], ends[keep]


def _one_row_per_key(rows: _Rows, dropped: Counter) -> _Rows:
    """Sort a slice by key. An object two parts both hold keeps only the
    dates on which both rows pass, because the frontend may use either."""
    keys, starts, ends = rows
    unique, first, inverse = np.unique(keys, return_index=True, return_inverse=True)
    if len(unique) == len(keys):
        return unique, starts[first], ends[first]
    dropped[_REPEATED] += len(keys) - len(unique)
    shared_starts = np.full(len(unique), -np.inf)
    shared_ends = np.full(len(unique), np.inf)
    np.maximum.at(shared_starts, inverse, starts)
    np.minimum.at(shared_ends, inverse, ends)
    return unique, shared_starts, shared_ends


class _RunMerger:
    """Joins the windows of each object into runs.

    Feed it the slices of a layer in time order. A window that touches the
    run its object has open extends it; any other window starts a new run.
    """

    def __init__(self) -> None:
        self._keys = np.empty(0, np.int64)
        self._starts = np.empty(0)
        self._ends = np.empty(0)
        self._open = np.empty(0, dtype=bool)
        self._closed: list[_Rows] = []

    def add(self, rows: _Rows) -> None:
        """Add one window per object. `rows` must be sorted by key."""
        keys, starts, ends = rows
        at = self._positions(keys)
        joins = self._open[at] & (starts <= self._ends[at] + _TOUCH_DAYS)
        self._close(at[self._open[at] & ~joins])
        grown = at[joins]
        self._ends[grown] = np.maximum(self._ends[grown], ends[joins])
        fresh = at[~joins]
        self._starts[fresh] = starts[~joins]
        self._ends[fresh] = ends[~joins]
        self._open[fresh] = True

    def finish(self) -> _Rows:
        """Close every run and return them all."""
        self._close(np.flatnonzero(self._open))
        return _concat(self._closed)

    def _positions(self, keys: np.ndarray) -> np.ndarray:
        """Index of each key in the sorted state arrays, with new keys added."""
        at = np.searchsorted(self._keys, keys)
        known = np.zeros(len(keys), dtype=bool)
        inside = at < len(self._keys)
        known[inside] = self._keys[at[inside]] == keys[inside]
        if known.all():
            return at
        new = ~known
        self._starts = np.insert(self._starts, at[new], 0.0)
        self._ends = np.insert(self._ends, at[new], 0.0)
        self._open = np.insert(self._open, at[new], False)
        self._keys = np.insert(self._keys, at[new], keys[new])
        return np.searchsorted(self._keys, keys)

    def _close(self, at: np.ndarray) -> None:
        self._closed.append((self._keys[at], self._starts[at], self._ends[at]))
        self._open[at] = False


def _decay_table(decay_jd: Mapping[int, float]) -> _Decay:
    norads = np.array(sorted(decay_jd), dtype=np.int64)
    return _Decay(
        keys=_pack_keys(ID_TYPE_ORDINAL[ID_TYPES.NORAD_SATCAT], norads),
        jds=np.array([decay_jd[norad] for norad in norads.tolist()], dtype=np.float64),
    )


def _decay_of(keys: np.ndarray, decay: _Decay) -> np.ndarray:
    """Re-entry JD of each key, infinite for an object that has none."""
    out = np.full(len(keys), np.inf)
    if len(decay.keys):
        at = np.minimum(np.searchsorted(decay.keys, keys), len(decay.keys) - 1)
        found = decay.keys[at] == keys
        out[found] = decay.jds[at[found]]
    return out


def _snapshot_layer(slices: list[_Slice], decay: _Decay, dropped: Counter) -> _Rows:
    """Windows of a date-labelled layer.

    A window stops at the object's re-entry date. A run that reaches the last
    snapshot, and has no re-entry inside that snapshot's validity, gets no
    end: a later export extends the zone but may leave the bundles as they
    are, and the frontend knows where the zone stops.
    """
    merger = _RunMerger()
    for index, piece in enumerate(slices):
        keys, starts, ends = _one_row_per_key(_element_rows(piece, dropped), dropped)
        clipped = np.minimum(ends, _decay_of(keys, decay))
        if index == len(slices) - 1:
            clipped = np.where(clipped < ends, clipped, np.inf)
        merger.add(_drop_empty((keys, starts, clipped), dropped))
    return merger.finish()


def _chunk_layer(slices: list[_Slice], dropped: Counter) -> _Rows:
    """Windows of an elements layer cut into chunks on a fixed grid."""
    merger = _RunMerger()
    for piece in slices:
        rows = _one_row_per_key(_element_rows(piece, dropped), dropped)
        merger.add(_drop_empty(rows, dropped))
    return merger.finish()


def _segment_runs(starts: np.ndarray, ends: np.ndarray) -> list[tuple[float, float]]:
    """Spans that a body's segments cover without a hole, in time order."""
    if not len(starts):
        return []
    breaks = np.flatnonzero(starts[1:] > ends[:-1] + _TOUCH_DAYS) + 1
    firsts = [0, *breaks.tolist()]
    lasts = [*(breaks - 1).tolist(), len(starts) - 1]
    return [(float(starts[a]), float(ends[b])) for a, b in zip(firsts, lasts)]


def _chebyshev_layer(slices: list[_Slice], dropped: Counter) -> _Rows:
    """Windows of a chebyshev layer: where a body's segments in the chunk the
    frontend loads cover the clock, after the discovery gate."""
    runs: dict[int, list[list[float]]] = {}
    for piece in slices:
        file = _read_chebyshev(piece.files[0])
        if file is None:
            continue
        for body in file.bodies:
            if body.id_type not in _ID_TYPE_BY_ORDINAL:
                dropped[_NO_ID_TYPE] += 1
                continue
            key = (body.id_type << 32) | (body.obj_id_value & 0xFFFFFFFF)
            gate = (
                -math.inf
                if math.isnan(body.visible_from_days)
                else J2000_JD + body.visible_from_days
            )
            for seg_start, seg_end in _segment_runs(body.starts, body.ends):
                start = max(piece.lo, gate, seg_start)
                end = min(piece.hi, seg_end)
                if start >= end:
                    dropped[_NO_DATE_LEFT] += 1
                    continue
                windows = runs.setdefault(key, [])
                if windows and start <= windows[-1][1] + _TOUCH_DAYS:
                    windows[-1][1] = max(windows[-1][1], end)
                else:
                    windows.append([start, end])
    spans = [(key, *window) for key, windows in runs.items() for window in windows]
    return (
        np.array([span[0] for span in spans], dtype=np.int64),
        np.array([span[1] for span in spans], dtype=np.float64),
        np.array([span[2] for span in spans], dtype=np.float64),
    )


def _nearest_label(label_jds: np.ndarray, jds: np.ndarray) -> np.ndarray:
    """Index of the snapshot the frontend loads at each clock date.

    Mirrors `snapshotDate` in the frontend: the nearest label, the earlier
    one on a tie, and the first or last label beyond them.
    """
    if len(label_jds) == 1:
        return np.zeros(len(jds), dtype=np.int64)
    after = np.clip(np.searchsorted(label_jds, jds, side="left"), 1, len(label_jds) - 1)
    before = after - 1
    picked = np.where(jds - label_jds[before] <= label_jds[after] - jds, before, after)
    picked = np.where(jds <= label_jds[0], 0, picked)
    return np.where(jds >= label_jds[-1], len(label_jds) - 1, picked)


def check_snapshot_windows(
    name: str, label_jds: np.ndarray, slices: list[_Slice], rows: _Rows
) -> int:
    """Self-check of a date-labelled layer, from the files on disk.

    Just inside each window edge, the snapshot the frontend selects must hold
    the object. A window with no end is tested at the last label. Logs an
    error for the edges that fail and returns their count.
    """
    keys, starts, ends = rows
    if not len(keys):
        return 0
    late = np.where(
        np.isinf(ends),
        np.maximum(label_jds[-1], starts + _CHECK_INSET_DAYS),
        ends - _CHECK_INSET_DAYS,
    )
    early = np.where(
        np.isinf(starts), np.minimum(label_jds[0], late), starts + _CHECK_INSET_DAYS
    )
    # A window shorter than two insets is tested at its middle.
    short = early > late
    early = np.where(short, (starts + ends) / 2, early)
    late = np.where(short, early, late)

    jds = np.concatenate([early, late])
    who = np.concatenate([keys, keys])
    picked = _nearest_label(label_jds, jds)
    order = np.argsort(picked, kind="stable")
    bounds = np.searchsorted(picked[order], np.arange(len(slices) + 1))
    failed: list[np.ndarray] = []
    for index, piece in enumerate(slices):
        tested = order[bounds[index] : bounds[index + 1]]
        if not len(tested):
            continue
        held = [
            _pack_keys(file.id_type, file.ids)
            for path in piece.files
            if (file := _read_elements(path)) is not None
        ]
        present = np.isin(who[tested], np.concatenate(held) if held else [])
        failed.append(tested[~present])
    bad = np.concatenate(failed) if failed else np.empty(0, np.int64)
    if len(bad):
        logger.error(
            "coverage: %s self-check failed on %d of %d window edges, for %d "
            "objects: the snapshot selected there does not hold the object. "
            "First cases (object, JD): %s",
            name,
            len(bad),
            len(jds),
            len(np.unique(who[bad])),
            [(_object_id(int(who[i])), float(jds[i])) for i in bad[:10].tolist()],
        )
    else:
        logger.info("coverage: %s self-check passed on %d window edges", name, len(jds))
    return len(bad)


def _layer_rows(zone_dir: Path, name: str, layer: Mapping, decay: _Decay) -> _Rows:
    """Windows of one manifest layer, by the rule its shape gives the frontend."""
    dropped: Counter = Counter()
    shape = layer["shape"]
    if shape == "parted":
        always = _Slice(-math.inf, math.inf, _part_files(zone_dir, layer["parts"]))
        rows = _drop_empty(_element_rows(always, dropped), dropped)
    elif shape == "chunked":
        slices = _grid_slices(layer, lambda chunk: (zone_dir / f"{chunk}.bin.gz",))
        rows = _chebyshev_layer(slices, dropped)
    elif layer["label"] == "index":
        slices = _grid_slices(
            layer, lambda chunk: _part_files(zone_dir / str(chunk), layer["parts"])
        )
        rows = _chunk_layer(slices, dropped)
    else:
        labels = sorted(layer["parts_by_date"])
        slices = _snapshot_slices(zone_dir, layer["parts_by_date"], labels)
        rows = _snapshot_layer(slices, decay, dropped)
        check_snapshot_windows(name, _label_jds(labels), slices, rows)
    logger.debug(
        "coverage: %s gives %d windows to %d objects",
        name,
        len(rows[0]),
        len(np.unique(rows[0])),
    )
    for reason, count in sorted(dropped.items()):
        if count:
            # Parts of one snapshot must not share an object; the other drops
            # are the gates and the writers doing their work.
            log = logger.warning if reason == _REPEATED else logger.debug
            log("coverage: %s has %d %s", name, count, reason)
    return rows


def _merge_overlaps(rows: _Rows) -> _Rows:
    """Sort all windows by object and start, and join the ones that touch.

    Each layer already joined its own, so only an object that ships in more
    than one layer has work left here.
    """
    keys, starts, ends = rows
    order = np.lexsort((starts, keys))
    keys, starts, ends = keys[order], starts[order], ends[order]
    joins = (keys[1:] == keys[:-1]) & (starts[1:] <= ends[:-1] + _TOUCH_DAYS)
    if not joins.any():
        return keys, starts, ends
    keep = np.ones(len(keys), dtype=bool)
    for key in np.unique(keys[1:][joins]).tolist():
        first = int(np.searchsorted(keys, key, side="left"))
        after = int(np.searchsorted(keys, key, side="right"))
        head = first
        for row in range(first + 1, after):
            if starts[row] <= ends[head] + _TOUCH_DAYS:
                ends[head] = max(ends[head], ends[row])
                keep[row] = False
            else:
                head = row
    return keys[keep], starts[keep], ends[keep]


def build_coverage(
    out_dir: Path, zones: Mapping[str, Mapping], decay_jd: Mapping[int, float]
) -> CoverageIndex:
    """Read every position file the manifest lists and return the windows.

    `zones` is `position.zones` as metadata.json publishes it, so the files
    read are the files the frontend can ask for. `decay_jd` maps a NORAD
    number to its re-entry JD. Probe zones are left out.
    """
    decay = _decay_table(decay_jd)
    layers: list[_Rows] = []
    for zone, entry in zones.items():
        zooms = entry["zooms"] if "zooms" in entry else {"0": entry}
        for zoom, layer in zooms.items():
            if layer["shape"] == "probes":
                continue
            name = f"{zone}/{zoom}" if "zooms" in entry else zone
            zone_dir = position_zone_dir(out_dir, zone, int(zoom))
            layers.append(_layer_rows(zone_dir, name, layer, decay))
    keys, starts, ends = _merge_overlaps(_concat(layers))
    logger.info(
        "coverage: %d windows for %d objects, %d with no end",
        len(keys),
        len(np.unique(keys)),
        int(np.isinf(ends).sum()),
    )
    return CoverageIndex(keys, starts, ends)


def stamp_coverage(
    global_data: MutableMapping[str, dict], index: CoverageIndex
) -> None:
    """Write each object's windows on its global bundle entry."""
    unknown: list[str] = []
    for obj_id, windows in index.objects():
        entry = global_data.get(obj_id)
        if entry is None:
            unknown.append(obj_id)
            continue
        entry["coverage"] = {"windows": windows}
        # A CompactMap keeps a read entry decoded; this stores it as bytes again.
        global_data[obj_id] = entry
    if unknown:
        logger.warning(
            "coverage: %d objects are in a position file but have no bundle "
            "entry; their windows are dropped. First: %s",
            len(unknown),
            unknown[:10],
        )


def load_hosts(session: Session) -> dict[str, str]:
    """Map an object to what the catalogue says it sits at or orbits.

    A moon gives its primary. An object with a SATCAT row gives the craft it
    is docked to, else the centre of its orbit when that is a body.
    """
    hosts: dict[str, str] = {}
    for obj_id, parent_id in session.query(Object.id, Object.parent_id).filter(
        Object.object_type == ObjectType.moon.value, Object.parent_id.is_not(None)
    ):
        hosts[obj_id] = parent_id
    for obj_id, centre, docked_to in session.query(
        Object.id, Satcat.orbit_center, Satcat.orbit_center_docked_to
    ).join(Satcat, Object.satcat_norad_cat_id == Satcat.NORAD_CAT_ID):
        if docked_to is not None:
            hosts[obj_id] = make_object_id(ID_TYPES.NORAD_SATCAT, docked_to)
        elif centre in _CENTRE_NAIF_ID:
            hosts[obj_id] = make_object_id(ID_TYPES.NAIF, _CENTRE_NAIF_ID[centre])
    return hosts


def stamp_hosts(
    global_data: MutableMapping[str, dict], hosts: Mapping[str, str]
) -> None:
    """Write `host_id` on each object that has no coverage and a known host."""
    stamped = 0
    no_entry = 0
    unknown: list[tuple[str, str]] = []
    for obj_id, host_id in hosts.items():
        entry = global_data.get(obj_id)
        if entry is None:
            no_entry += 1
            continue
        if "coverage" not in entry:
            if host_id in global_data:
                entry["host_id"] = host_id
                stamped += 1
            else:
                unknown.append((obj_id, host_id))
        # A CompactMap keeps a read entry decoded; this stores it as bytes again.
        global_data[obj_id] = entry
    logger.info("coverage: %d objects with no coverage name their host", stamped)
    if no_entry:
        logger.debug(
            "coverage: %d objects with a known host have no bundle entry", no_entry
        )
    if unknown:
        logger.warning(
            "coverage: %d objects name a host that has no bundle entry; no "
            "host_id for them. First (object, host): %s",
            len(unknown),
            unknown[:10],
        )
