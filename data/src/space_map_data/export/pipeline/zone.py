"""Per-zone export driver: build object data once, write element parts per snapshot."""

import math
from dataclasses import dataclass, field
from pathlib import Path

from space_map_data.export.objects.writer import (
    ChunkObjectData,
    build_chunk_object_data,
)
from space_map_data.export.pipeline.snapshots import ZoneSnapshots
from space_map_data.export.position import CHUNK_SIZE, write_chunk
from space_map_data.export.position.format import (
    UNBOUNDED_END_JD,
    UNBOUNDED_START_JD,
)
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.wikidata import WikidataEntity, WikidataEntityCache
from space_map_data.models.object import Object, OrbitalSource


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
    probe_kernel_sources: dict[int, str]
    nomenclature_body_ids: set[str]


@dataclass
class SnapshotResult:
    """Per-snapshot stats produced by :func:`export_zone`.

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
        probe_kernel_sources=ctx.probe_kernel_sources,
        nomenclature_body_ids=ctx.nomenclature_body_ids,
    )


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
    :func:`build_zone_object_data`; each chunk's slice rides in the binary's
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
