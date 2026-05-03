"""Export orchestrator: query DB, write chunked output files."""

import logging
import math
import orjson
import shutil
import time

import numpy as np
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from space_map_data.constants.providers import PROVIDERS
from space_map_data.models.object.sbdb import CometPrefix
from sqlalchemy import case, or_
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, joinedload

from space_map_data.export.chebyshev import write_chebyshev
from space_map_data.export.credits import write_credits
from space_map_data.export.elements import CHUNK_SIZE, write_chunk
from space_map_data.export.elements.format import (
    UNBOUNDED_END_JD,
    UNBOUNDED_START_JD,
)
from space_map_data.export.elements.celestrak_source import (
    CelesTrakElements,
    load_all_days,
)
from space_map_data.export.labels import write_global_labels
from space_map_data.export.objects.writer import (
    ChunkObjectData,
    build_chunk_object_data,
    write_object_bundles,
)
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.localization import write_messages
from space_map_data.export.systems import (
    load_nut_prec,
    load_nut_prec_angles,
    load_orientation,
    load_radii,
    load_texture_metadata,
    write_system_metadata,
)
from space_map_data.export.wikidata import WikidataEntity, WikidataEntityCache
from space_map_data.download.providers.wikidata.id_resolver import (
    CONSTELLATION_PREFIXES,
)
from space_map_data.models.object import Object, ObjectType, OrbitalSource, SBDB
from space_map_data.utils.paths import DOWNLOAD_DIR, EXPORT_DIR

logger = logging.getLogger(__name__)

_EARTH_NAIF_ID = 399

_SAT_CONTEXT_TYPES = {ObjectType.spacecraft, ObjectType.debris}
_SAT_TYPE_VALUES = [t.value for t in _SAT_CONTEXT_TYPES]

_SUN_MAJOR_TYPES = {
    ObjectType.star,
    ObjectType.barycenter,
    ObjectType.lagrange_point,
    ObjectType.planet,
    ObjectType.dwarf_planet,
}
_SUN_MAJOR_TYPE_VALUES = [t.value for t in _SUN_MAJOR_TYPES]

_DEFAULT_ZONE_LIMIT = 10_000


@dataclass
class ZoomSnapshots:
    """All snapshots produced for one (zone, zoom). The discriminator on
    `_build_metadata`'s output shape lives entirely in the snapshots — empty
    means a hole, one with ``time is None`` is the static case, otherwise the
    list is the chunk-indexed or date-segmented stream depending on
    `SnapshotResult.chunk_years`.
    """

    snapshots: list["SnapshotResult"] = field(default_factory=list)


def _build_metadata(zone_structure: Mapping[str, Mapping[int, ZoomSnapshots]]) -> dict:
    """Build the ``zones`` metadata block.

    Three shapes per zoom, dispatched on the snapshot stream:

    * Static (single snapshot with ``time is None``): ``{parts}``.
    * Chunk-indexed (snapshots carry ``chunk_years``): ``{chunks, chunk_years,
      start_jd, parts}``. Clients compute ``chunk_idx = floor((jd - start_jd)
      / (chunk_years * 365.25))`` and load
      ``elements/{zone}/{zoom}/{chunk_idx}/{part}.bin.gz``. Used by the
      time-chunked moons zone where Method C secular elements are re-fitted
      per 6-month window.
    * Date-segmented (snapshots have ISO-date labels and no ``chunk_years``):
      ``{start_date, end_date, parts}``. Clients clamp the simulated date
      into the window and assume daily contiguity. Used by the Earth-sat
      zone where each snapshot is one CelesTrak GP day.

    The discriminator is `Snapshot.chunk_years` — set by the producing
    snapshot stream — not the label format. Choosing this explicitly avoids
    fragile heuristics (e.g. zero-padding numeric labels so they sort
    lexicographically the same as numerically).
    """
    zones = {}
    for zone, zoom_map in sorted(zone_structure.items()):
        zooms = {}
        for zoom, zoom_snaps in sorted(zoom_map.items()):
            snaps = zoom_snaps.snapshots
            if len(snaps) == 1 and snaps[0].time is None:
                zooms[str(zoom)] = {"parts": snaps[0].num_parts}
                continue
            # Multi-snapshot zooms only carry timestamped streams. A bare
            # `None`-time entry mixed with timed ones means the producer is
            # confused about the zone's shape.
            if any(s.time is None for s in snaps):
                raise ValueError(
                    f"{zone} zoom={zoom} mixes timed snapshots with a "
                    f"None-time snapshot; one zoom must be all-timed or "
                    f"single-static"
                )
            parts_set = {s.num_parts for s in snaps}
            if len(parts_set) != 1:
                raise ValueError(
                    f"{zone} zoom={zoom} has uneven parts across snapshots "
                    f"{parts_set}; the slim metadata shape assumes uniform parts"
                )
            parts = next(iter(parts_set))
            chunk_years_set = {s.chunk_years for s in snaps}
            if len(chunk_years_set) > 1:
                raise ValueError(
                    f"{zone} zoom={zoom} mixes chunk_years values "
                    f"{chunk_years_set}; one snapshot stream must use a single "
                    f"cadence"
                )
            chunk_years = next(iter(chunk_years_set))
            if chunk_years is not None:
                # Chunk-indexed: derive start_jd from the earliest snapshot's
                # validity window. Sorting by validity_start_jd avoids relying
                # on label format.
                snaps_sorted = sorted(snaps, key=lambda s: s.validity_start_jd)
                zooms[str(zoom)] = {
                    "chunks": len(snaps_sorted),
                    "chunk_years": chunk_years,
                    "start_jd": snaps_sorted[0].validity_start_jd,
                    "parts": parts,
                }
            else:
                # Date-segmented: labels are ISO dates, sort lexicographically.
                dated = sorted(s.time for s in snaps if s.time is not None)
                zooms[str(zoom)] = {
                    "start_date": dated[0],
                    "end_date": dated[-1],
                    "parts": parts,
                }
        zones[zone] = {"zooms": zooms}
    return {"zones": zones}


def _remove_old_outputs(out_dir: Path) -> None:
    """Remove all chunk output directories before a fresh export."""
    for d in ("elements", "objects", "chebyshev"):
        p = out_dir / d
        if p.exists():
            shutil.rmtree(p)
    # System metadata is regenerated each export (individual textures are not)
    for d in ("textures/systems", "systems"):
        p = out_dir / d
        if p.exists():
            shutil.rmtree(p)
    # Legacy image layout before the per-filename bundle refactor. Deleting
    # unconditionally is safe: the new layout writes to ``images/<filename>/``
    # dirs alongside these (never inside them), so this never hits new output.
    for d in ("images/thumb", "images/full", "images/metadata"):
        p = out_dir / d
        if p.exists():
            shutil.rmtree(p)


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
        obj.epoch_jd = elements["epoch_jd"]
        obj.a = elements["a"]
        obj.e = elements["e"]
        obj.i = elements["i"]
        obj.om = elements["om"]
        obj.w = elements["w"]
        obj.ma = elements["ma"]
        obj.n = elements["n"]
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


def _chunk_source(chunk: list[Object], zone: str, part_idx: int) -> OrbitalSource:
    """Pick the chunk's declared orbital source from its first tagged object.

    The writer asserts every other row matches. Zone queries are single-source
    by construction (the pipeline filters per-zone), so any object with a
    source is representative.
    """
    for o in chunk:
        if o.orbital_source is not None:
            return o.orbital_source
    raise ValueError(f"No object in {zone!r} part {part_idx} carries an orbital_source")


def _resolve_qid(obj: Object) -> str | None:
    """Pick the wikidata QID we want for an object, falling back to satcat."""
    return obj.wikidata_qid or (
        obj.satcat.wikidata_qid if obj.norad_cat_id is not None and obj.satcat else None
    )


def _entities_for(
    objects: list[Object],
    wikidata_entities: WikidataEntityCache,
) -> dict[str, WikidataEntity | None]:
    """Resolve every object's QID against the cache once, into a dict."""
    return {
        qid: wikidata_entities.get_entity(qid)
        for obj in objects
        if (qid := _resolve_qid(obj))
    }


def _build_zone_object_data(
    objects: list[Object],
    wikidata_entities: WikidataEntityCache,
    units: UnitConverter,
    nasa_science_urls: dict[str, str],
    orientation: dict[int, dict],
    radii: dict[int, dict],
    nut_prec: dict[int, dict[str, list[float]]],
    texture_metadata: dict[str, dict],
) -> ChunkObjectData:
    """Build globals/localized/flags for a flat zone-wide object list (no I/O).

    Distinct from the chunk-level write path: a single zone has one set of
    per-object data regardless of how many time-snapshots it ships. For
    snapshot zones the union of objects across snapshots is built once,
    using each object's most-recent in-place state.
    """
    return build_chunk_object_data(
        objects,
        wikidata_entities,
        _entities_for(objects, wikidata_entities),
        units,
        nasa_science_urls,
        orientation=orientation,
        radii=radii,
        nut_prec=nut_prec,
        texture_metadata=texture_metadata,
    )


def _write_element_parts(
    objects: list[Object],
    out_dir: Path,
    zone: str,
    zoom: int,
    has_localized: dict[str, bool],
    wikidata_entities: WikidataEntityCache,
    units: UnitConverter,
    time: str | None,
    validity_start_jd: float = UNBOUNDED_START_JD,
    validity_end_jd: float = UNBOUNDED_END_JD,
) -> int:
    """Chunk and write element binary files for one (zone, zoom, snapshot).

    `has_localized` is the prebuilt has-any-language-data map from
    :func:`_build_zone_object_data`; each chunk's slice rides in the binary's
    last column so the frontend can skip detail-bundle fetches for objects
    with no Wikidata. `validity_start_jd`/`validity_end_jd` ride into the
    file header so consumers can hide bodies outside the chunk's time window.
    Returns the number of parts written.
    """
    num_parts = max(1, math.ceil(len(objects) / CHUNK_SIZE))
    for part_idx in range(num_parts):
        chunk = objects[part_idx * CHUNK_SIZE : (part_idx + 1) * CHUNK_SIZE]
        chunk_entities = _entities_for(chunk, wikidata_entities)
        write_chunk(
            chunk,
            out_dir,
            zone,
            zoom,
            part_idx,
            chunk_entities,
            has_localized,
            units,
            _chunk_source(chunk, zone, part_idx),
            time=time,
            validity_start_jd=validity_start_jd,
            validity_end_jd=validity_end_jd,
        )
    return num_parts


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


def _single_snapshot(objects: list[Object]) -> ZoneSnapshots:
    """Snapshot stream for a zone without time segmentation."""
    return ZoneSnapshots(
        base=objects,
        iterate=lambda: iter([Snapshot(label=None, objects=objects)]),
    )


def _earth_snapshots(
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


def _moons_snapshots(
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
        return _single_snapshot(base)

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
        return _single_snapshot(base)

    n_chunks = midpoints_jd.shape[0]
    # Half-width of each chunk's validity window. Uniform grid → constant.
    half_width_jd = float(
        (midpoints_jd[1] - midpoints_jd[0]) / 2 if n_chunks > 1 else 365.25 / 4
    )
    chunk_years = (2 * half_width_jd) / 365.25

    # Capture each Object's untouched single-epoch elements so the iterator
    # can restore them between chunks (otherwise the previous overlay would
    # bleed into the next iteration).
    base_by_naif: dict[int, Object] = {
        o.naif_id: o for o in base if o.naif_id is not None
    }
    base_snapshot: dict[int, dict[str, float | None]] = {
        nid: {
            "epoch_jd": o.epoch_jd,
            "a": o.a,
            "e": o.e,
            "i": o.i,
            "om": o.om,
            "w": o.w,
            "ma": o.ma,
            "n": o.n,
            "om_dot": o.om_dot,
            "w_dot": o.w_dot,
        }
        for nid, o in base_by_naif.items()
    }

    def apply_overlay(chunk_idx: int) -> list[Object]:
        for nid, o in base_by_naif.items():
            row = overlays.get(nid)
            if row is None:
                # Whitelisted moon — keep DB single-epoch elements as-is.
                snap = base_snapshot[nid]
                o.epoch_jd = snap["epoch_jd"]
                o.a = snap["a"]
                o.e = snap["e"]
                o.i = snap["i"]
                o.om = snap["om"]
                o.w = snap["w"]
                o.ma = snap["ma"]
                o.n = snap["n"]
                o.om_dot = snap["om_dot"]
                o.w_dot = snap["w_dot"]
                continue
            elements = row[chunk_idx]
            o.epoch_jd = float(midpoints_jd[chunk_idx])
            o.a = float(elements[0])
            o.e = float(elements[1])
            o.i = float(elements[2])
            o.om = float(elements[3])
            o.w = float(elements[4])
            o.ma = float(elements[5])
            o.n = float(elements[6])
            o.om_dot = float(elements[7])
            o.w_dot = float(elements[8])
        return list(base_by_naif.values())

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


@dataclass
class SnapshotResult:
    """Per-snapshot stats produced by :func:`_export_zone`.

    `chunk_years` carries through from the source `Snapshot` so the manifest
    builder can choose a chunk-indexed shape (`{chunks, chunk_years, …}`)
    versus the date-segmented shape (`{start_date, end_date, …}`) without
    parsing label strings — one explicit field, set per snapshot.
    """

    time: str | None
    count: int
    num_parts: int
    chunk_years: float | None = None
    validity_start_jd: float = UNBOUNDED_START_JD
    validity_end_jd: float = UNBOUNDED_END_JD


@dataclass
class ZoneExportResult:
    """Output of :func:`_export_zone`: the once-built zone data + per-snapshot stats."""

    zone_data: ChunkObjectData
    snapshots: list[SnapshotResult] = field(default_factory=list)


def _export_zone(
    zone: str,
    zoom: int,
    snapshots: ZoneSnapshots,
    out_dir: Path,
    wikidata_entities: WikidataEntityCache,
    units: UnitConverter,
    nasa_science_urls: dict[str, str],
    orientation: dict[int, dict],
    radii: dict[int, dict],
    nut_prec: dict[int, dict[str, list[float]]],
    texture_metadata: dict[str, dict],
) -> ZoneExportResult:
    """Build per-object data once for the zone; write element parts per snapshot.

    Two-pass over `snapshots.iterate`:

    1. Collect the union of object IDs across all snapshots. Overlays mutate
       `snapshots.base` in-place; after pass 1, each surviving object reflects
       whichever snapshot's overlay ran last on it.
    2. Re-iterate snapshots (overlays re-apply per snapshot) and write
       elements/labels using the prebuilt flags from the union build.

    Globals built in step 2's interlude reflect the most-recent overlay state
    of each object — the same data the previous N×-rebuild design landed on
    after last-write-wins aggregation, but at 1× cost.
    """
    union_ids: set[str] = set()
    for snap in snapshots.iterate():
        union_ids.update(o.id for o in snap.objects)

    if not union_ids:
        return ZoneExportResult(zone_data=ChunkObjectData())

    union_objs = [o for o in snapshots.base if o.id in union_ids]
    zone_data = _build_zone_object_data(
        union_objs,
        wikidata_entities,
        units,
        nasa_science_urls,
        orientation,
        radii,
        nut_prec,
        texture_metadata,
    )

    result = ZoneExportResult(zone_data=zone_data)
    for snap in snapshots.iterate():
        num_parts = _write_element_parts(
            snap.objects,
            out_dir,
            zone,
            zoom,
            zone_data.has_localized,
            wikidata_entities,
            units,
            time=snap.label,
            validity_start_jd=snap.validity_start_jd,
            validity_end_jd=snap.validity_end_jd,
        )
        result.snapshots.append(
            SnapshotResult(
                time=snap.label,
                count=len(snap.objects),
                num_parts=num_parts,
                chunk_years=snap.chunk_years,
                validity_start_jd=snap.validity_start_jd,
                validity_end_jd=snap.validity_end_jd,
            )
        )
    return result


def export(engine: Engine, limit_per_zone: int = _DEFAULT_ZONE_LIMIT) -> None:
    """Run the full export pipeline."""
    t0 = time.monotonic()
    out_dir = EXPORT_DIR / "v1"
    out_dir.mkdir(parents=True, exist_ok=True)
    _remove_old_outputs(out_dir)

    wikidata_entities = WikidataEntityCache()
    units = UnitConverter(wikidata_entities)

    nasa_science_url_file = DOWNLOAD_DIR / "nasa-science-urls" / "pk-to-url.json"
    if nasa_science_url_file.exists():
        nasa_science_urls: dict[str, str] = orjson.loads(
            nasa_science_url_file.read_bytes()
        )
        logger.info("Loaded %d NASA Science URLs", len(nasa_science_urls))
    else:
        nasa_science_urls = {}
        logger.warning("NASA Science URL file not found: %s", nasa_science_url_file)

    orientation = load_orientation(DOWNLOAD_DIR)
    radii = load_radii(DOWNLOAD_DIR)
    nut_prec = load_nut_prec(DOWNLOAD_DIR)
    nut_prec_angles = load_nut_prec_angles(DOWNLOAD_DIR)
    texture_metadata = load_texture_metadata(out_dir)

    # Single global file fetched once by the frontend; bodies derive their owner
    # as `naif_id // 100` (or `naif_id` itself when < 100). Tiny — not gzipped.
    if nut_prec_angles:
        (out_dir / "nut_prec_angles.json").write_bytes(
            orjson.dumps(
                {str(owner): vals for owner, vals in sorted(nut_prec_angles.items())}
            )
        )
        logger.info("Wrote nut_prec_angles.json (%d owners)", len(nut_prec_angles))

    celestrak_days = load_all_days(DOWNLOAD_DIR)

    zone_structure: defaultdict[str, defaultdict[int, ZoomSnapshots]] = defaultdict(
        lambda: defaultdict(ZoomSnapshots)
    )
    object_counts: defaultdict[tuple[str, int, str | None], int] = defaultdict(int)
    all_objects = ChunkObjectData()

    def _record(zone: str, zoom: int, result: ZoneExportResult) -> None:
        all_objects.global_data.update(result.zone_data.global_data)
        for lang, by_id in result.zone_data.localized_data.items():
            all_objects.localized_data[lang].update(by_id)
        all_objects.has_localized.update(result.zone_data.has_localized)
        for snap in result.snapshots:
            object_counts[(zone, zoom, snap.time)] += snap.count
            zone_structure[zone][zoom].snapshots.append(snap)
            if snap.time is None:
                logger.info(
                    "  %s zoom=%d: %d objects, %d parts",
                    zone,
                    zoom,
                    snap.count,
                    snap.num_parts,
                )
            else:
                logger.info(
                    "  %s zoom=%d %s: %d objects, %d parts",
                    zone,
                    zoom,
                    snap.time,
                    snap.count,
                    snap.num_parts,
                )

    futures: dict = {}

    with Session(engine) as session:
        with ThreadPoolExecutor() as executor:
            # Non-SBDB zones: (zone, zoom, query)
            _earth_base = (
                session.query(Object)
                .options(joinedload(Object.satcat), joinedload(Object.celestrak))
                .filter(
                    Object.spkid.is_(None),
                    Object.object_type.in_(_SAT_TYPE_VALUES),
                    Object.parent_naif_id == _EARTH_NAIF_ID,
                )
            )
            _is_constellation = or_(
                *(Object.name.startswith(p) for p in CONSTELLATION_PREFIXES)
            )
            # Major bodies split by source — SPICE-sourced (planets + Pluto/Ceres)
            # at zoom=0, SBDB-only dwarf planets (Eris, Makemake, Quaoar, …) at
            # zoom=1. Keeps each chunk single-source so the file-level source
            # byte is unambiguous; frontend iterates every zoom per zone.
            _major_base = session.query(Object).options(joinedload(Object.sbdb))
            non_sbdb = [
                (
                    "major",
                    0,
                    _major_base.filter(
                        Object.object_type.in_(_SUN_MAJOR_TYPE_VALUES),
                        Object.orbital_source != OrbitalSource.sbdb,
                    ),
                ),
                (
                    "major",
                    1,
                    _major_base.filter(
                        Object.object_type.in_(_SUN_MAJOR_TYPE_VALUES),
                        Object.orbital_source == OrbitalSource.sbdb,
                    ),
                ),
                (
                    "moons",
                    0,
                    session.query(Object).filter(
                        Object.spkid.is_(None),
                        Object.object_type == ObjectType.moon.value,
                    ),
                ),
                (
                    "spacecraft",
                    0,
                    session.query(Object)
                    .options(joinedload(Object.satcat))
                    .filter(
                        Object.spkid.is_(None),
                        Object.object_type.in_(_SAT_TYPE_VALUES),
                        Object.parent_naif_id != _EARTH_NAIF_ID,
                    ),
                ),
            ]
            for zone, zoom, q in non_sbdb:
                objects = q.order_by(Object.random_int).limit(limit_per_zone).all()
                if not objects:
                    logger.info("  %s zoom=%d: empty, skipping", zone, zoom)
                    continue
                if zone == "major":
                    # Parents must come before children so positions resolve during chunk load.
                    # Barycenters (incl. SSB) → stars (Sun) → everything else.
                    def _major_sort_key(o: Object) -> int:
                        if o.object_type == ObjectType.barycenter:
                            return 0
                        if o.object_type == ObjectType.star:
                            return 1
                        return 2

                    objects.sort(key=_major_sort_key)
                if zone == "moons":
                    snapshots = _moons_snapshots(objects, DOWNLOAD_DIR)
                else:
                    snapshots = _single_snapshot(objects)
                f = executor.submit(
                    _export_zone,
                    zone,
                    zoom,
                    snapshots,
                    out_dir,
                    wikidata_entities,
                    units,
                    nasa_science_urls,
                    orientation,
                    radii,
                    nut_prec,
                    texture_metadata,
                )
                futures[f] = (zone, zoom)

            # SBDB: one query per (class, zoom)
            named_col = case((SBDB.name.is_not(None), 1), else_=0).label("named")
            sbdb_combos = (
                session.query(SBDB.class_, named_col)
                .group_by(SBDB.class_, named_col)
                .all()
            )
            for cls, named in sbdb_combos:
                zoom = 0 if named else 1
                name_filter = SBDB.name.is_not(None) if named else SBDB.name.is_(None)
                objects = (
                    session.query(Object)
                    .options(joinedload(Object.sbdb))
                    .join(Object.sbdb)
                    .filter(
                        SBDB.class_ == cls,
                        name_filter,
                        Object.object_type.not_in(_SUN_MAJOR_TYPE_VALUES),
                        SBDB.prefix.is_distinct_from(
                            CometPrefix.D
                        ),  # TODO: handle defunct comets - figure out last display date
                        # Bodies whose orbit came from SPICE kernels (e.g. DE441
                        # perturbers like Ceres) ship via the chebyshev export;
                        # including them here would mix sources in one chunk
                        # and violate the one-provider-per-file invariant.
                        or_(
                            Object.orbital_source.is_(None),
                            Object.orbital_source == OrbitalSource.sbdb,
                        ),
                    )
                    .order_by(Object.random_int)
                    .limit(limit_per_zone)
                    .all()
                )
                if not objects:
                    continue
                zone = cls.name
                f = executor.submit(
                    _export_zone,
                    zone,
                    zoom,
                    _single_snapshot(objects),
                    out_dir,
                    wikidata_entities,
                    units,
                    nasa_science_urls,
                    orientation,
                    radii,
                    nut_prec,
                    texture_metadata,
                )
                futures[f] = (zone, zoom)

            # Earth zones run inline: per-day overlays mutate the same Object
            # instances in-place, so multiple days can't be shipped to threads
            # simultaneously without cloning. Main-thread work still overlaps
            # with the executor pool processing other zones.
            for zoom_label, zoom_filter in (
                (0, ~_is_constellation),
                (1, _is_constellation),
            ):
                base_objects = (
                    _earth_base.filter(zoom_filter)
                    .order_by(Object.random_int)
                    .limit(limit_per_zone)
                    .all()
                )
                if not base_objects:
                    logger.info("  earth zoom=%d: empty, skipping", zoom_label)
                    continue
                result = _export_zone(
                    "earth",
                    zoom_label,
                    _earth_snapshots(base_objects, celestrak_days),
                    out_dir,
                    wikidata_entities,
                    units,
                    nasa_science_urls,
                    orientation,
                    radii,
                    nut_prec,
                    texture_metadata,
                )
                _record("earth", zoom_label, result)
            # executor joins here — session still open so ORM objects remain valid

        write_system_metadata(
            session, out_dir, orientation, radii, nut_prec, texture_metadata
        )
        write_credits(session, out_dir, texture_metadata)
        chebyshev_manifest = write_chebyshev(session, DOWNLOAD_DIR, out_dir, radii)

    for f in as_completed(futures):
        zone, zoom = futures[f]
        _record(zone, zoom, f.result())

    bundle_ns = write_object_bundles(
        out_dir, all_objects.global_data, all_objects.localized_data
    )
    write_global_labels(out_dir, all_objects)

    # --- Other outputs ---
    write_messages(wikidata_entities, units.used_units)

    metadata = _build_metadata(zone_structure)
    metadata["object_bundles"] = bundle_ns
    if chebyshev_manifest:
        metadata["chebyshev"] = chebyshev_manifest
    (out_dir / "metadata.json").write_bytes(
        orjson.dumps(metadata, option=orjson.OPT_INDENT_2)
    )

    total = sum(object_counts.values())
    elapsed = time.monotonic() - t0
    logger.info("Export complete: %d objects to %s in %.1fs", total, out_dir, elapsed)
