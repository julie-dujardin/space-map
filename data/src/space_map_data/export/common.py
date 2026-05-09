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
from sqlalchemy import case, or_, true as sa_true
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, joinedload

from space_map_data.export.credits import write_credits
from space_map_data.export.position import CHUNK_SIZE, write_chebyshev, write_chunk
from space_map_data.export.position.chebyshev.writer import _object_for_naif_id
from space_map_data.export.position.elements.celestrak_source import (
    CelesTrakElements,
    load_all_days,
)
from space_map_data.export.position.format import (
    UNBOUNDED_END_JD,
    UNBOUNDED_START_JD,
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
    load_gms,
    load_nut_prec,
    load_nut_prec_angles,
    load_orientation,
    load_radii,
    load_texture_metadata,
    write_system_metadata,
    write_systems_global,
)
from space_map_data.export.wikidata import WikidataEntity, WikidataEntityCache
from space_map_data.download.providers.wikidata.id_resolver import (
    CONSTELLATION_PREFIXES,
)
from space_map_data.models.object import (
    Horizons,
    Object,
    ObjectType,
    OrbitalSource,
    SBDB,
)
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
    `_build_position_metadata`'s output shape lives entirely in the snapshots — empty
    means a hole, one with ``time is None`` is the static case, otherwise the
    list is the chunk-indexed or date-segmented stream depending on
    `SnapshotResult.chunk_years`.
    """

    snapshots: list["SnapshotResult"] = field(default_factory=list)


def _build_position_zoom(snaps: list["SnapshotResult"], zone: str, zoom: int) -> dict:
    """Build one position/zones/{zone}/zooms/{zoom} entry from its snapshots.

    Three shapes, dispatched on the snapshot stream:

    * ``parted`` — single snapshot with ``time is None``. URL:
      ``position/{zone}/{zoom}/{part}.bin.gz``. Entry: ``{shape, parts}``.
    * ``chunked-parted`` with ``label="index"`` — chunk-indexed elements
      (the moons elements zone). URL:
      ``position/{zone}/{zoom}/{chunk_idx}/{part}.bin.gz``. Entry:
      ``{shape, label, chunks, chunk_years, start_jd, parts}``.
    * ``chunked-parted`` with ``label="date"`` — date-segmented elements
      (the earth zone). URL: ``position/{zone}/{zoom}/{date}/{part}.bin.gz``.
      Entry: ``{shape, label, start_date, end_date, parts}``.

    The chebyshev-only shape (``chunked``, no parts axis) is folded in
    separately by the caller — it doesn't go through the snapshot pipeline.
    """
    if len(snaps) == 1 and snaps[0].time is None:
        return {"shape": "parted", "parts": snaps[0].num_parts}
    # Multi-snapshot zooms only carry timestamped streams. A bare `None`-time
    # entry mixed with timed ones means the producer is confused about shape.
    if any(s.time is None for s in snaps):
        raise ValueError(
            f"{zone} zoom={zoom} mixes timed snapshots with a None-time "
            f"snapshot; one zoom must be all-timed or single-static"
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
            f"{chunk_years_set}; one snapshot stream must use a single cadence"
        )
    chunk_years = next(iter(chunk_years_set))
    if chunk_years is not None:
        # Chunk-indexed: derive start_jd from the earliest snapshot's
        # validity window. Sorting by validity_start_jd avoids relying on
        # label format.
        snaps_sorted = sorted(snaps, key=lambda s: s.validity_start_jd)
        return {
            "shape": "chunked-parted",
            "label": "index",
            "chunks": len(snaps_sorted),
            "chunk_years": chunk_years,
            "start_jd": snaps_sorted[0].validity_start_jd,
            "parts": parts,
        }
    # Date-segmented: labels are ISO dates, sort lexicographically.
    dated = sorted(s.time for s in snaps if s.time is not None)
    return {
        "shape": "chunked-parted",
        "label": "date",
        "start_date": dated[0],
        "end_date": dated[-1],
        "parts": parts,
    }


def _build_position_metadata(
    zone_structure: Mapping[str, Mapping[int, ZoomSnapshots]],
    chebyshev_zones: Mapping[str, dict],
) -> dict:
    """Build the unified ``position.zones`` metadata block.

    Folds the elements-side `zone_structure` (one entry per zone+zoom that
    emitted snapshots) and the chebyshev-side `chebyshev_zones` (one entry
    per zone that emitted chebyshev chunks; always at zoom 0) into a single
    map keyed by zone name. Each zoom carries a `shape` discriminator so
    consumers can build URLs without sniffing field presence:

    * ``parted`` — `{zone}/{zoom}/{part}.bin.gz`
    * ``chunked-parted`` — `{zone}/{zoom}/{label}/{part}.bin.gz`
    * ``chunked`` — `{zone}/{zoom}/{chunk}.bin.gz` (chebyshev)
    """
    zones: dict[str, dict] = {}
    for zone, zoom_map in zone_structure.items():
        zooms: dict[str, dict] = {}
        for zoom, zoom_snaps in zoom_map.items():
            zooms[str(zoom)] = _build_position_zoom(zoom_snaps.snapshots, zone, zoom)
        if zooms:
            zones[zone] = {"zooms": zooms}
    for zone, params in chebyshev_zones.items():
        # Chebyshev always sits at zoom 0; nothing else can land at the same
        # zone+zoom, so there's no collision to resolve.
        zone_entry = zones.setdefault(zone, {"zooms": {}})
        if "0" in zone_entry["zooms"]:
            raise ValueError(
                f"{zone}: chebyshev tried to claim zoom 0 but elements already "
                f"emitted there; one format per zone+zoom"
            )
        zone_entry["zooms"]["0"] = {
            "shape": "chunked",
            "chunks": params["chunks"],
            "chunk_years": params["chunk_years"],
            "start_jd": params["start_jd"],
            "end_jd": params["end_jd"],
        }
    return {"zones": dict(sorted(zones.items()))}


def _remove_old_outputs(out_dir: Path) -> None:
    """Remove all chunk output directories before a fresh export."""
    for d in ("position", "objects"):
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
    gms: dict[int, float],
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
        gms=gms,
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
    gms: dict[int, float],
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
        gms,
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


def _chebyshev_coverage(session: Session, download_dir: Path) -> set[str]:
    """Object IDs covered by the chebyshev export.

    Used to filter cheb-covered bodies out of the elements zones so the same
    body's positions don't ship in two formats. The frontend can derive
    osculating Kepler elements from chebyshev positions when needed, so a
    duplicated kepler row is just dead bytes.

    Walks `download_dir/spice/chebyshev/*.npz` and resolves each file's
    `naif_id` against the DB (with the SPK-ID fallback used by the cheb
    writer). Returns a set of `Object.id` strings (e.g. `naif-499`,
    `spkid-20134340`) so callers can filter on the prefixed form.
    """
    cheb_dir = download_dir / PROVIDERS.SPICE / "chebyshev"
    if not cheb_dir.exists():
        return set()
    ids: set[str] = set()
    for path in sorted(cheb_dir.glob("*.npz")):
        try:
            data = np.load(path)
            naif_id = int(data["meta"][0])
        except Exception as exc:
            logger.warning("Couldn't read cheb npz %s: %s", path, exc)
            continue
        obj = _object_for_naif_id(session, naif_id)
        if obj is not None:
            ids.add(obj.id)
    return ids


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
    gms = load_gms(DOWNLOAD_DIR)
    nut_prec = load_nut_prec(DOWNLOAD_DIR)
    nut_prec_angles = load_nut_prec_angles(DOWNLOAD_DIR)
    texture_metadata = load_texture_metadata(out_dir)

    write_systems_global(out_dir, gms, nut_prec_angles)

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
        # Bodies covered by chebyshev (Sun/planets/dwarves, perturber asteroids,
        # whitelisted moons) are excluded from the elements zones. Two-format
        # ride-along would just bloat the export — the frontend can derive
        # osculating elements from chebyshev positions if it needs them.
        cheb_covered_ids = _chebyshev_coverage(session, DOWNLOAD_DIR)
        if cheb_covered_ids:
            logger.info(
                "Chebyshev covers %d bodies; dropping them from elements zones",
                len(cheb_covered_ids),
            )

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
            # Major bodies — chebyshev claims zoom 0 (Sun, planets, Pluto,
            # Ceres), so kepler fallbacks live at higher zooms. Split by
            # source to keep each file single-provider (the file-level source
            # byte forbids mixed origins):
            #   zoom 1 = horizons-sourced majors not covered by chebyshev —
            #            in practice this catches dwarf planets that have
            #            Horizons ephemerides but no SPK kernel.
            #   zoom 2 = SBDB-only dwarves (Eris, Makemake, Quaoar, …) that
            #            aren't in any SPK kernel either
            # Major bodies + moons + deep-space spacecraft are horizons- or
            # spice-source, so eager-load Object.horizons (kepler elements
            # live there). SBDB-source majors join sbdb instead.
            _major_base = session.query(Object).options(
                joinedload(Object.sbdb), joinedload(Object.horizons)
            )
            non_sbdb = [
                (
                    "major",
                    1,
                    _major_base.filter(
                        Object.object_type.in_(_SUN_MAJOR_TYPE_VALUES),
                        Object.orbital_source != OrbitalSource.sbdb,
                        Object.id.notin_(cheb_covered_ids)
                        if cheb_covered_ids
                        else sa_true(),
                    ),
                ),
                (
                    "major",
                    2,
                    _major_base.filter(
                        Object.object_type.in_(_SUN_MAJOR_TYPE_VALUES),
                        Object.orbital_source == OrbitalSource.sbdb,
                    ),
                ),
                (
                    "moons",
                    0,
                    session.query(Object)
                    .options(joinedload(Object.horizons))
                    .filter(
                        Object.spkid.is_(None),
                        Object.object_type == ObjectType.moon.value,
                        Object.id.notin_(cheb_covered_ids)
                        if cheb_covered_ids
                        else sa_true(),
                    ),
                ),
                (
                    "spacecraft",
                    0,
                    session.query(Object)
                    .options(joinedload(Object.satcat), joinedload(Object.horizons))
                    .filter(
                        Object.spkid.is_(None),
                        Object.object_type.in_(_SAT_TYPE_VALUES),
                        Object.parent_naif_id != _EARTH_NAIF_ID,
                        Object.id.notin_(cheb_covered_ids)
                        if cheb_covered_ids
                        else sa_true(),
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
                    gms,
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
                # SPICE-sourced bodies (DE441 perturbers like Ceres, Pallas, …)
                # ship via the chebyshev export and are filtered out here both
                # to enforce the one-provider-per-file invariant and to avoid
                # shipping duplicate position data for bodies that already
                # appear in a chebyshev zone.
                sbdb_q = (
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
                        or_(
                            Object.orbital_source.is_(None),
                            Object.orbital_source == OrbitalSource.sbdb,
                        ),
                    )
                )
                if cheb_covered_ids:
                    sbdb_q = sbdb_q.filter(Object.id.notin_(cheb_covered_ids))
                objects = sbdb_q.order_by(Object.random_int).limit(limit_per_zone).all()
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
                    gms,
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
                    gms,
                    nut_prec,
                    texture_metadata,
                )
                _record("earth", zoom_label, result)
            # executor joins here — session still open so ORM objects remain valid

        write_system_metadata(
            session, out_dir, orientation, radii, nut_prec, texture_metadata
        )
        write_credits(session, out_dir, texture_metadata)

        # Aggregate has_localized from elements futures before writing chebyshev
        # — the cheb body header carries one bit per body, gated on the same
        # union map the elements files use.
        for f in as_completed(futures):
            zone, zoom = futures[f]
            _record(zone, zoom, f.result())

        # Chebyshev-covered bodies are excluded from the elements zones (no
        # double-shipping), so they never run through `_export_zone` and their
        # per-object metadata never lands in `all_objects`. Build it explicitly
        # here so they show up in object bundles, labels, and trigger the
        # large-scale unit ladder entries (solar_mass, earth_mass, …) that
        # only get pulled in via `units.convert` on those bodies' values.
        if cheb_covered_ids:
            cheb_objs = (
                session.query(Object)
                .options(
                    joinedload(Object.sbdb),
                    joinedload(Object.satcat),
                    joinedload(Object.celestrak),
                )
                .filter(Object.id.in_(cheb_covered_ids))
                .all()
            )
            cheb_data = _build_zone_object_data(
                cheb_objs,
                wikidata_entities,
                units,
                nasa_science_urls,
                orientation,
                radii,
                gms,
                nut_prec,
                texture_metadata,
            )
            all_objects.global_data.update(cheb_data.global_data)
            for lang, by_id in cheb_data.localized_data.items():
                all_objects.localized_data[lang].update(by_id)
            all_objects.has_localized.update(cheb_data.has_localized)
            logger.info(
                "Built object data for %d chebyshev-covered bodies", len(cheb_objs)
            )

        chebyshev_zones = write_chebyshev(
            session, DOWNLOAD_DIR, out_dir, radii, all_objects.has_localized
        )

    bundle_ns = write_object_bundles(
        out_dir, all_objects.global_data, all_objects.localized_data
    )
    write_global_labels(out_dir, all_objects, cheb_covered_ids)

    # --- Other outputs ---
    write_messages(wikidata_entities, units.used_units)

    position_metadata = _build_position_metadata(zone_structure, chebyshev_zones)
    metadata = {"position": position_metadata, "object_bundles": bundle_ns}
    (out_dir / "metadata.json").write_bytes(
        orjson.dumps(metadata, option=orjson.OPT_INDENT_2)
    )

    total = sum(object_counts.values())
    elapsed = time.monotonic() - t0
    logger.info("Export complete: %d objects to %s in %.1fs", total, out_dir, elapsed)
