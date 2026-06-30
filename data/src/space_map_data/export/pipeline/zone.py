"""Per-zone export driver: build object data once, write element parts per snapshot."""

import logging
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from space_map_data.export.earth_sat_filter import is_docked
from space_map_data.export.objects.writer import (
    ChunkObjectData,
    build_chunk_object_data,
)
from space_map_data.export.position import CHUNK_SIZE, write_chunk
from space_map_data.export.position.elements import sidecar
from space_map_data.export.position.elements.celestrak_source import CelesTrakElements
from space_map_data.export.position.elements.spacetrack_source import (
    archive_source_groups,
    archive_zip_fingerprints,
    load_archive_weeks,
)
from space_map_data.export.position.format import (
    UNBOUNDED_END_JD,
    UNBOUNDED_START_JD,
)
from space_map_data.export.position.format import VERSION as BINARY_VERSION
from space_map_data.export.position.layout import position_zone_dir
from space_map_data.export.pipeline.snapshots import (
    ZoneSnapshots,
    _overlay_celestrak_elements,
)
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.wikidata import WikidataEntity, WikidataEntityCache
from space_map_data.models.object import Object, OrbitalSource

logger = logging.getLogger(__name__)

_DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class ObjectDataContext:
    """Inputs needed to build per-object metadata for a zone.

    Bundled because `build_zone_object_data` and `export_zone` always take
    this same set as a unit. Loaded once at the start of an export and
    threaded through the per-zone pipeline.
    """

    wikidata_entities: WikidataEntityCache
    units: UnitConverter
    nasa_science_urls: dict[str, str]
    orientation: dict[int, dict]
    radii: dict[int, dict]
    gms: dict[int, float]
    nut_prec: dict[int, dict[str, list[float]]]
    texture_metadata: dict[str, dict]
    clouds_metadata: dict[str, dict]
    displacement_metadata: dict[str, dict]
    probe_kernel_sources: dict[int, str | None]
    nomenclature_body_ids: set[str]
    # parent Object.id -> display name, for moons whose parent may live in
    # another chunk (lets the frontend breadcrumb name the host without the
    # parent body being resident in the scene).
    parent_names: dict[str, str]


@dataclass
class SnapshotResult:
    """Per-snapshot stats produced by :func:`export_zone`.

    `chunk_days` carries through from the source `Snapshot` so the manifest
    builder can choose a chunk-indexed shape (`{chunks, chunk_days, …}`)
    versus the date-segmented shape (`{start_date, end_date, …}`) without
    parsing label strings — one explicit field, set per snapshot.
    """

    time: str | None
    count: int
    num_parts: int
    chunk_days: float | None = None
    validity_start_jd: float = UNBOUNDED_START_JD
    validity_end_jd: float = UNBOUNDED_END_JD


@dataclass
class ZoneExportResult:
    """Output of :func:`export_zone`: the once-built zone data + per-snapshot stats."""

    zone_data: ChunkObjectData
    snapshots: list[SnapshotResult] = field(default_factory=list)
    parent_id_type: str | None = None


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


def build_zone_object_data(
    objects: list[Object],
    ctx: ObjectDataContext,
) -> ChunkObjectData:
    """Build globals/localized/flags for a flat zone-wide object list (no I/O).

    Distinct from the chunk-level write path: a single zone has one set of
    per-object data regardless of how many time-snapshots it ships. For
    snapshot zones the union of objects across snapshots is built once,
    using each object's most-recent in-place state.
    """
    return build_chunk_object_data(
        objects,
        ctx.wikidata_entities,
        _entities_for(objects, ctx.wikidata_entities),
        ctx.units,
        ctx.nasa_science_urls,
        orientation=ctx.orientation,
        radii=ctx.radii,
        gms=ctx.gms,
        nut_prec=ctx.nut_prec,
        texture_metadata=ctx.texture_metadata,
        clouds_metadata=ctx.clouds_metadata,
        displacement_metadata=ctx.displacement_metadata,
        probe_kernel_sources=ctx.probe_kernel_sources,
        nomenclature_body_ids=ctx.nomenclature_body_ids,
        parent_names=ctx.parent_names,
    )


def _chunk_source(chunk: list[Object], zone: str, part_idx: int) -> OrbitalSource:
    """Pick the chunk's declared orbital source from its first tagged object.

    The writer asserts every other row matches. Zone queries are single-source
    by construction (the pipeline filters per-zone), so any object with a
    source is representative. A transient ``_source_override`` (set per Earth
    snapshot to distinguish CelesTrak dailies from Space-Track archive weeks)
    wins over the DB column.
    """
    for o in chunk:
        source = getattr(o, "_source_override", None) or o.orbital_source
        if source is not None:
            return source
    raise ValueError(f"No object in {zone!r} part {part_idx} carries an orbital_source")


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
    part_offset: int = 0,
) -> int:
    """Chunk and write element binary files for one (zone, zoom, snapshot).

    `has_localized` is the prebuilt has-any-language-data map from
    :func:`build_zone_object_data`; each chunk's slice rides in the binary's
    last column so the frontend can skip detail-bundle fetches for objects
    with no Wikidata. `validity_start_jd`/`validity_end_jd` ride into the
    file header so consumers can hide bodies outside the chunk's time window.
    `part_offset` shifts the written part indices, so a zone streamed in
    CHUNK_SIZE-aligned batches lands a contiguous `0..N-1` run across batches.
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
            part_offset + part_idx,
            chunk_entities,
            has_localized,
            units,
            _chunk_source(chunk, zone, part_idx),
            time=time,
            validity_start_jd=validity_start_jd,
            validity_end_jd=validity_end_jd,
        )
    return num_parts


def _derive_parent_id_type(zone: str, objects: list[Object]) -> str | None:
    """Pick the col-2 parent prefix for ``zone``, asserting uniformity.

    Frontend rebuilds parent ids as ``f"{prefix}-{col2}"`` per zone, so a
    mixed-prefix zone would route some parents to the wrong bucket. Returns
    None when no object has a parent (zones containing only the SSB itself —
    not currently a thing, but the reader treats None as legacy ``"naif"``).
    """
    first: str | None = None
    for o in objects:
        if o.parent_id is None:
            continue
        pos = o.parent_id.find("-")
        prefix = o.parent_id[:pos] if pos != -1 else None
        if prefix is None:
            continue
        if first is None:
            first = prefix
        elif prefix != first:
            raise ValueError(
                f"{zone}: mixed parent id-types ({first!r} vs {prefix!r} "
                f"on {o.id!r}); each zone must have a single parent prefix"
            )
    return first


def export_zone(
    zone: str,
    zoom: int,
    snapshots: ZoneSnapshots,
    out_dir: Path,
    ctx: ObjectDataContext,
    part_offset: int = 0,
) -> ZoneExportResult:
    """Build per-object data once for the zone; write element parts per snapshot.

    `part_offset` shifts written part indices and is only meaningful for
    single-snapshot zones streamed in batches (SBDB) — multi-snapshot zones
    keep the default 0 since each snapshot writes into its own subdir.

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
    zone_data = build_zone_object_data(union_objs, ctx)

    result = ZoneExportResult(
        zone_data=zone_data,
        parent_id_type=_derive_parent_id_type(zone, union_objs),
    )
    for snap in snapshots.iterate():
        num_parts = _write_element_parts(
            snap.objects,
            out_dir,
            zone,
            zoom,
            zone_data.has_localized,
            ctx.wikidata_entities,
            ctx.units,
            time=snap.label,
            validity_start_jd=snap.validity_start_jd,
            validity_end_jd=snap.validity_end_jd,
            part_offset=part_offset,
        )
        result.snapshots.append(
            SnapshotResult(
                time=snap.label,
                count=len(snap.objects),
                num_parts=num_parts,
                chunk_days=snap.chunk_days,
                validity_start_jd=snap.validity_start_jd,
                validity_end_jd=snap.validity_end_jd,
            )
        )
    return result


def _archive_group_marker(out_dir: Path, label: str) -> Path:
    """Sidecar path marking an archive source group fully exported."""
    return sidecar.mirror_path(
        position_zone_dir(out_dir, "earth", 0) / f".archive-{label}.meta.json"
    )


def _archive_group_signature(years: list[int]) -> dict:
    return {
        "format_version": sidecar.FORMAT_VERSION,
        "binary_version": BINARY_VERSION,
        "archive_years": years,
        "archive_inputs": archive_zip_fingerprints(years),
    }


def _scan_date_snapshots(out_dir: Path, zone: str, zoom: int) -> list[SnapshotResult]:
    """Build the date-segmented snapshot list from the on-disk part dirs.

    Years skipped by the per-year cache aren't re-parsed, so their weeks never
    pass through the write loop — the manifest reads their part counts straight
    off disk instead. ``count`` is left 0 (rows aren't re-decoded); only
    ``num_parts`` feeds the date-segmented manifest entry.
    """
    zdir = position_zone_dir(out_dir, zone, zoom)
    out: list[SnapshotResult] = []
    if not zdir.exists():
        return out
    for d in sorted(zdir.iterdir()):
        if not (d.is_dir() and _DATE_DIR_RE.match(d.name)):
            continue
        num_parts = sum(1 for _ in d.glob("*.bin.gz"))
        if num_parts:
            out.append(SnapshotResult(time=d.name, count=0, num_parts=num_parts))
    return out


def export_earth_zone(
    base: list[Object],
    celestrak_days: Mapping[str, dict[int, CelesTrakElements]],
    archive_years: Iterable[int],
    out_dir: Path,
    ctx: ObjectDataContext,
) -> ZoneExportResult:
    """Stream the Earth zone: the archive is parsed one source group at a time.
    Most groups are a single year; the pre-2004 group distils the whole 2004
    mega-dump in one pass (~5 GB peak), the price of not re-reading the ~2 GB
    dump per historical year.

    Unlike the generic two-pass :func:`export_zone`, object metadata is built
    from the full base rather than the snapshot union — every Earth Object
    appears in some week, so the union *is* the base, and skipping the union
    pass lets the archive parse lazily. An archive group whose zip
    fingerprints match its on-disk marker is skipped without parsing; its parts
    stay and the manifest is rebuilt from a disk scan so they still ship. The
    result: a steady-state daily CelesTrak refresh re-parses zero archive groups.
    Recent dailies are stamped CELESTRAK, historical weeks SPACETRACK — same
    SGP4 wire format, distinct provenance for attribution.
    """
    # The per-object global bundle ships one "current" orbit block the frontend
    # reads to place a URL-navigated sat before (or in lieu of) its element
    # chunk. The Kepler fields come from the transient `_daily_kepler` overlay,
    # so overlay the recent dailies onto the base *before* building the
    # metadata — otherwise Earth sats ship with no orbit block and URL
    # navigation hides them (redirecting to the Sun). Apply oldest→newest so
    # each sat keeps its most recent elements while a sat absent from the very
    # latest day still gets placed from an earlier one. The per-date write loop
    # below re-overlays each snapshot independently.
    if celestrak_days:
        for iso in sorted(celestrak_days):
            _overlay_celestrak_elements(base, celestrak_days[iso])
    else:
        logger.warning(
            "export_earth_zone: no daily elements available — Earth-sat global "
            "bundles ship without an orbit block, so URL navigation will hide them"
        )
    zone_data = build_zone_object_data(base, ctx)
    parent_id_type = _derive_parent_id_type("earth", base)
    built: dict[str, SnapshotResult] = {}

    # Docked craft keep their object bundle (built from the full base above) but
    # are dropped from the rendered position chunks below, so the scene never
    # draws a marker on top of the host they're docked to.
    docked_ids = {o.id for o in base if is_docked(o)}
    if docked_ids:
        logger.info(
            "export_earth_zone: %d docked craft kept in bundles but not rendered",
            len(docked_ids),
        )

    def write(
        date_iso: str,
        elements: dict[int, CelesTrakElements],
        source: OrbitalSource,
    ) -> None:
        kept = _overlay_celestrak_elements(base, elements)
        if docked_ids:
            kept = [o for o in kept if o.id not in docked_ids]
        if not kept:
            return
        for obj in kept:
            obj._source_override = source  # type: ignore[attr-defined]  # transient
        num_parts = _write_element_parts(
            kept,
            out_dir,
            "earth",
            0,
            zone_data.has_localized,
            ctx.wikidata_entities,
            ctx.units,
            time=date_iso,
        )
        built[date_iso] = SnapshotResult(
            time=date_iso, count=len(kept), num_parts=num_parts
        )

    # Recent CelesTrak dailies — already materialised, small.
    for date_iso, elements in celestrak_days.items():
        write(date_iso, elements, OrbitalSource.celestrak)

    # Historical archive: parse each source group once. Pre-2004 history all
    # lives in the 2004 mega-dump, so those years form one group streamed in a
    # single pass rather than re-read per year.
    for label, group_years in archive_source_groups(archive_years):
        signature = _archive_group_signature(group_years)
        if sidecar.matches(_archive_group_marker(out_dir, label), signature):
            continue  # unchanged zip + already built — don't parse; disk scan re-adds it
        for date_iso, elements in load_archive_weeks(group_years).items():
            write(date_iso, elements, OrbitalSource.spacetrack)
        sidecar.write_sidecar(_archive_group_marker(out_dir, label), signature)

    # Built weeks carry real counts; skipped years (not re-parsed) come off disk
    # with count 0 so they still ship in the date-segmented manifest.
    snapshots = list(built.values())
    for snap in _scan_date_snapshots(out_dir, "earth", 0):
        if snap.time not in built:
            snapshots.append(snap)
    snapshots.sort(key=lambda s: s.time or "")
    return ZoneExportResult(
        zone_data=zone_data,
        snapshots=snapshots,
        parent_id_type=parent_id_type,
    )
