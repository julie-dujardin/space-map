"""Snapshot streams: produce one ``Snapshot`` per time slice of a zone."""

import logging
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from space_map_data.constants.providers import PROVIDERS
from space_map_data.export.position.elements.celestrak_source import CelesTrakElements
from space_map_data.export.position.format import (
    UNBOUNDED_END_JD,
    UNBOUNDED_START_JD,
)
from space_map_data.models.object import Horizons, Object

logger = logging.getLogger(__name__)


@dataclass
class Snapshot:
    """One emission from a zone's snapshot stream.

    `label` is the path component inserted between zoom and part — None for
    untimed zones, an ISO date for Earth sats, a numeric index for the
    time-chunked moons zone. `validity_start_jd` / `validity_end_jd` go into
    the binary header so consumers know when to draw and propagate.
    `chunk_years` is set by zones that fan out as a fixed-cadence chunk grid
    (moons) and unset for date-segmented zones (Earth) — it tells the
    manifest builder to emit a chunk-indexed shape rather than a date-range
    shape, regardless of label format.
    """

    label: str | None
    objects: list[Object]
    validity_start_jd: float = UNBOUNDED_START_JD
    validity_end_jd: float = UNBOUNDED_END_JD
    chunk_years: float | None = None


@dataclass
class ZoneSnapshots:
    """A zone's snapshot stream over a shared underlying object list.

    `base` is the underlying list whose Object instances may be mutated
    in-place by per-snapshot overlays (e.g. CelesTrak elements for Earth or
    per-chunk Method C fits for moons). `iterate` returns a fresh iterator of
    `Snapshot` records each call — required because the snapshot driver makes
    two passes (collect union of IDs, then write per-snapshot parts).
    """

    base: list[Object]
    iterate: Callable[[], Iterator[Snapshot]]


def _overlay_celestrak_elements(
    objects: list[Object],
    elements_by_norad: dict[int, CelesTrakElements],
    log_dropped: bool = True,
) -> list[Object]:
    """Replace each Earth Object's orbital elements with the latest from disk.

    Drops objects whose NORAD ID has no row on disk — without fresh elements
    we can't propagate them, so shipping stale DB values would just produce
    broken positions in the frontend. ``log_dropped=False`` silences the
    drop count, used during the snapshot driver's union-collection pass to
    avoid duplicating the message on the subsequent write pass.

    Kepler elements (epoch_jd, a, e, i, om, w, ma, n) are attached as a
    transient ``_daily_kepler`` dict on the Object — celestrak-source objects
    don't persist these fields anywhere (the daily snapshot is authoritative),
    so the writer reads them off this attribute. SGP4 extras (BSTAR,
    MEAN_MOTION_DOT/DDOT, ELEMENT_SET_NO, REV_AT_EPOCH) overwrite the
    CelesTrak sub-table row in-place since the writer reads them through that
    relation.
    """
    kept: list[Object] = []
    dropped = 0
    for obj in objects:
        elements = (
            elements_by_norad.get(obj.norad_cat_id)
            if obj.norad_cat_id is not None
            else None
        )
        if elements is None:
            dropped += 1
            continue
        obj._daily_kepler = elements  # type: ignore[attr-defined]
        # Earth-zone Objects come from the CelesTrak ingest path, which inserts
        # an Object + CelesTrak row in lockstep — the relation is invariant-
        # non-None here, even though the schema doesn't enforce it.
        ct = obj.celestrak
        assert ct is not None, f"{obj.id}: missing celestrak relation"
        ct.BSTAR = elements["BSTAR"]
        ct.MEAN_MOTION_DOT = elements["MEAN_MOTION_DOT"]
        ct.MEAN_MOTION_DDOT = elements["MEAN_MOTION_DDOT"]
        ct.ELEMENT_SET_NO = elements["ELEMENT_SET_NO"]
        ct.REV_AT_EPOCH = elements["REV_AT_EPOCH"]
        kept.append(obj)
    if dropped and log_dropped:
        logger.info(
            "Dropped %d Earth satellites with no matching elements on disk",
            dropped,
        )
    return kept


def single_snapshot(objects: list[Object]) -> ZoneSnapshots:
    """Snapshot stream for a zone without time segmentation."""
    return ZoneSnapshots(
        base=objects,
        iterate=lambda: iter([Snapshot(label=None, objects=objects)]),
    )


def earth_snapshots(
    base: list[Object],
    celestrak_days: Mapping[str, dict[int, CelesTrakElements]],
) -> ZoneSnapshots:
    """Snapshot stream for Earth: one snapshot per CelesTrak day on disk.

    The snapshot driver iterates twice (union pass, write pass); both passes
    re-apply the same overlays. Suppress the per-day "Dropped N satellites"
    log on pass 1 so the user only sees one entry per date.
    """
    pass_count = [0]

    def iterate() -> Iterator[Snapshot]:
        pass_count[0] += 1
        log = pass_count[0] >= 2
        for date_iso, day_elements in celestrak_days.items():
            kept = _overlay_celestrak_elements(base, day_elements, log_dropped=log)
            if kept:
                # Validity window comes from the SGP4 epoch spread inside the
                # chunk writer, so we don't pre-compute it here.
                yield Snapshot(label=date_iso, objects=kept)

    return ZoneSnapshots(base=base, iterate=iterate)


def moons_snapshots(
    base: list[Object],
    download_dir: Path,
) -> ZoneSnapshots:
    """Snapshot stream for moons: one snapshot per Method C time chunk.

    Reads pre-computed `moon_chunks/<naif_id>.npz` sidecars from the SPICE
    download directory and applies each chunk's secular elements as an
    overlay before the chunk is written. Whitelisted moons (those without a
    sidecar — they're covered by Chebyshev) keep their single-epoch DB
    elements unchanged across all chunks; the overlay is a no-op for them.

    Chunk grid is read from the first .npz file's `chunk_midpoints_jd`; all
    moons share the same grid (built in `_extract_moon_chunks`).
    """
    cheb_dir = download_dir / PROVIDERS.SPICE / "moon_chunks"
    if not cheb_dir.exists():
        logger.info(
            "No moon_chunks dir at %s; falling back to single snapshot", cheb_dir
        )
        return single_snapshot(base)

    overlays: dict[int, np.ndarray] = {}
    midpoints_jd: np.ndarray | None = None
    for path in cheb_dir.glob("*.npz"):
        data = np.load(path)
        meta = data["meta"]
        naif_id = int(meta[0])
        overlays[naif_id] = np.asarray(data["elements"], dtype=np.float64)
        if midpoints_jd is None:
            midpoints_jd = np.asarray(data["chunk_midpoints_jd"], dtype=np.float64)
    if midpoints_jd is None or not overlays:
        logger.info("No moon_chunks sidecars found; falling back to single snapshot")
        return single_snapshot(base)

    n_chunks = midpoints_jd.shape[0]
    # Half-width of each chunk's validity window. Uniform grid → constant.
    half_width_jd = float(
        (midpoints_jd[1] - midpoints_jd[0]) / 2 if n_chunks > 1 else 365.25 / 4
    )
    chunk_years = (2 * half_width_jd) / 365.25

    # Moons are spice/horizons-source — kepler elements live on the Horizons
    # sub-table, so the overlay mutates ``h.*`` in place. The query path
    # eager-loads ``Object.horizons`` for the moons zone; if a row somehow
    # has no horizons relation we'd silently render at the SSB instead of
    # the parent body, so raise loud rather than swallow.
    base_by_naif: dict[int, tuple[Object, Horizons]] = {}
    for o in base:
        if o.naif_id is None:
            continue
        if o.horizons is None:
            raise ValueError(f"{o.id}: missing horizons relation for moon overlay")
        base_by_naif[o.naif_id] = (o, o.horizons)
    base_snapshot: dict[int, dict[str, float | None]] = {
        nid: {
            "JDTDB": h.JDTDB,
            "A": h.A,
            "EC": h.EC,
            "IN_": h.IN_,
            "OM": h.OM,
            "W": h.W,
            "MA": h.MA,
            "N": h.N,
            "om_dot": h.om_dot,
            "w_dot": h.w_dot,
        }
        for nid, (_o, h) in base_by_naif.items()
    }

    def apply_overlay(chunk_idx: int) -> list[Object]:
        for nid, (_o, h) in base_by_naif.items():
            row = overlays.get(nid)
            if row is None:
                # Whitelisted moon — keep DB single-epoch elements as-is.
                snap = base_snapshot[nid]
                h.JDTDB = snap["JDTDB"]
                h.A = snap["A"]
                h.EC = snap["EC"]
                h.IN_ = snap["IN_"]
                h.OM = snap["OM"]
                h.W = snap["W"]
                h.MA = snap["MA"]
                h.N = snap["N"]
                h.om_dot = snap["om_dot"]
                h.w_dot = snap["w_dot"]
                continue
            elements = row[chunk_idx]
            h.JDTDB = float(midpoints_jd[chunk_idx])
            h.A = float(elements[0])
            h.EC = float(elements[1])
            h.IN_ = float(elements[2])
            h.OM = float(elements[3])
            h.W = float(elements[4])
            h.MA = float(elements[5])
            h.N = float(elements[6])
            h.om_dot = float(elements[7])
            h.w_dot = float(elements[8])
        return [o for o, _h in base_by_naif.values()]

    def iterate() -> Iterator[Snapshot]:
        for chunk_idx in range(n_chunks):
            kept = apply_overlay(chunk_idx)
            mid = float(midpoints_jd[chunk_idx])
            yield Snapshot(
                label=str(chunk_idx),
                objects=kept,
                validity_start_jd=mid - half_width_jd,
                validity_end_jd=mid + half_width_jd,
                chunk_years=chunk_years,
            )

    return ZoneSnapshots(base=base, iterate=iterate)
