"""Export orchestrator: query DB, drive zone exports, write global outputs."""

import hashlib
import logging
import shutil
import time
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import (
    FIRST_COMPLETED,
    Future,
    ThreadPoolExecutor,
    wait,
)
from dataclasses import dataclass, field
from pathlib import Path

import orjson
from sqlalchemy import case, or_, true as sa_true
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, joinedload

from space_map_data.download.providers.wikidata.id_resolver import (
    CONSTELLATION_PREFIXES,
)
from space_map_data.export.credits import write_credits
from space_map_data.export.ephemeris import load_probe_kernel_sources
from space_map_data.export.groups import run_groups_tier
from space_map_data.export.labels import write_global_labels
from space_map_data.export.localization import write_messages
from space_map_data.export.nomenclature.writer import (
    build_feature_details,
    build_nomenclature,
    write_feature_detail_bundles,
    write_nomenclature_labels,
    write_nomenclature_positions,
)
from space_map_data.export.objects.fragments import attach_comet_fragments
from space_map_data.export.objects.missions import attach_probe_missions
from space_map_data.export.objects.moons import attach_notable_moons
from space_map_data.export.objects.satellites import attach_featured_satellites
from space_map_data.export.objects.writer import (
    ChunkObjectData,
    write_object_bundles,
)
from space_map_data.export.pipeline import incremental
from space_map_data.export.pipeline.cleanup import (
    precheck_tables,
    prune_small_bodies,
    remove_old_outputs,
)
from space_map_data.export.pipeline.manifest import (
    ZoomSnapshots,
    build_position_metadata,
)
from space_map_data.export.pipeline.snapshots import (
    ZoneSnapshots,
    earth_snapshots,
    moons_snapshots,
    single_snapshot,
)
from space_map_data.export.pipeline.zone import (
    ObjectDataContext,
    SnapshotResult,
    ZoneExportResult,
    build_zone_object_data,
    export_zone,
)
from space_map_data.export.position import CHUNK_SIZE, write_chebyshev
from space_map_data.export.position.chebyshev.coverage import chebyshev_coverage
from space_map_data.export.position.elements.celestrak_source import (
    CelesTrakElements,
    load_all_days,
)
from space_map_data.export.position.probes import write_probes
from space_map_data.export.position.probes.attitude.orchestrator import (
    write_attitude,
)
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.systems import (
    load_clouds_metadata,
    load_gms,
    load_model_metadata,
    load_night_metadata,
    load_nut_prec,
    load_nut_prec_angles,
    load_orientation,
    load_radii,
    load_ring_metadata,
    load_skybox_metadata,
    load_specular_metadata,
    load_texture_metadata,
    skybox_block,
    write_system_metadata,
    write_systems_global,
)
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.models.object import (
    Object,
    ObjectType,
    OrbitalSource,
    SBDB,
    SBDBMoon,
)
from space_map_data.models.object.sbdb import CometPrefix
from space_map_data.utils.paths import (
    DOWNLOAD_DIR,
    EXPORT_DIR,
    SOURCES_METADATA_DIR,
)

logger = logging.getLogger(__name__)

_EARTH_OBJECT_ID = "naif-399"

_SAT_CONTEXT_TYPES = {ObjectType.spacecraft, ObjectType.debris}
_SAT_TYPE_VALUES = [t.value for t in _SAT_CONTEXT_TYPES]

_SUN_MAJOR_TYPES = {
    ObjectType.star,
    ObjectType.barycenter,
    ObjectType.planet,
    ObjectType.dwarf_planet,
}
_SUN_MAJOR_TYPE_VALUES = [t.value for t in _SUN_MAJOR_TYPES]

_DEFAULT_ZONE_LIMIT = 10_000

# SBDB combos are uncapped (see comment in `_iter_sbdb_zone_snapshots`);
# MBA-unnamed alone is ~hundreds of thousands of ORM Objects. With an
# unbounded executor every combo's `.all()` landed in RAM before any worker
# drained, and the session's identity map pinned them all — that's the 30-40
# GB blow-up. Cap concurrent zone exports so peak memory ≈ MAX_IN_FLIGHT ×
# largest-batch size. Big combos are split into row-capped batches
# (see `_SBDB_BATCH_ROWS`) so no single work item materializes more than the
# batch cap, keeping this knob about parallelism rather than the memory floor.
_MAX_ZONE_IN_FLIGHT = 8

# Rows per SBDB work item. The giant combos (MBA-unnamed is ~hundreds of
# thousands of rows) used to materialize in one `.all()` — the multi-GB
# transient. Streaming a combo in CHUNK_SIZE-aligned batches caps any single
# work item at this many ORM rows; each batch writes a contiguous part range
# at its offset so the on-disk output stays identical to a one-shot combo.
# Must be a multiple of CHUNK_SIZE so batch boundaries land on part boundaries.
_SBDB_BATCH_ROWS = 50_000
assert _SBDB_BATCH_ROWS % CHUNK_SIZE == 0


@dataclass
class _Aggregators:
    """Mutable accumulators populated as zone exports complete."""

    zone_structure: defaultdict[str, defaultdict[int, ZoomSnapshots]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(ZoomSnapshots))
    )
    object_counts: defaultdict[tuple[str, int, str | None], int] = field(
        default_factory=lambda: defaultdict(int)
    )
    all_objects: ChunkObjectData = field(default_factory=ChunkObjectData)


def _merge_object_data(target: ChunkObjectData, source: ChunkObjectData) -> None:
    """Fold one source's per-object data into the accumulator."""
    target.global_data.update(source.global_data)
    for lang, by_id in source.localized_data.items():
        target.localized_data[lang].update(by_id)
    target.has_localized.update(source.has_localized)


def _record(zone: str, zoom: int, result: ZoneExportResult, agg: _Aggregators) -> None:
    """Fold one zone export's result into the aggregators + log per snapshot."""
    _merge_object_data(agg.all_objects, result.zone_data)
    agg.zone_structure[zone][zoom].parent_id_type = result.parent_id_type
    for snap in result.snapshots:
        agg.object_counts[(zone, zoom, snap.time)] += snap.count
        agg.zone_structure[zone][zoom].snapshots.append(snap)
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


def _record_cached(zone: str, zoom: int, meta: dict, agg: _Aggregators) -> None:
    """Fold a skipped zone's cached stats into the aggregators.

    Only valid when tier B is clean: the zone's per-object data is not
    rebuilt, so `agg.all_objects` stays untouched — every consumer of it is
    skipped under the same gate.
    """
    agg.zone_structure[zone][zoom].parent_id_type = meta["parent_id_type"]
    count = 0
    for kwargs in incremental.decode_snapshots(meta["snapshots"]):
        snap = SnapshotResult(**kwargs)
        agg.object_counts[(zone, zoom, snap.time)] += snap.count
        agg.zone_structure[zone][zoom].snapshots.append(snap)
        count += snap.count
    logger.info(
        "  %s zoom=%d: inputs unchanged, skipped (%d objects, %d snapshots cached)",
        zone,
        zoom,
        count,
        len(meta["snapshots"]),
    )


def _zone_is_cached(
    out_dir: Path, zone: str, zoom: int, signature: dict
) -> dict | None:
    """Return the zone's cached meta iff its signature matches and parts exist."""
    meta = incremental.read_zone_meta(out_dir, zone, zoom)
    if meta is None or meta.get("signature") != signature:
        return None
    if not incremental.zone_parts_exist(out_dir, zone, zoom, meta["snapshots"]):
        return None
    return meta


def _build_object_data_for(
    label: str,
    objects: list[Object],
    ctx: ObjectDataContext,
    all_objects: ChunkObjectData,
) -> None:
    """Build per-object data for an out-of-band object list and merge it in.

    Out-of-band = bodies that don't ride through a zone export but still need
    bundle/label coverage so the frontend can resolve them.
    """
    if not objects:
        return
    _merge_object_data(all_objects, build_zone_object_data(objects, ctx))
    logger.info("Built object data for %d %s", len(objects), label)


def _major_sort_key(o: Object) -> int:
    """Parents-before-children sort for the `major` zone: barycenters, stars, then rest."""
    if o.object_type == ObjectType.barycenter:
        return 0
    if o.object_type == ObjectType.star:
        return 1
    return 2


def _iter_non_sbdb_zone_snapshots(
    session: Session,
    cheb_covered_ids: set[str],
    limit_per_zone: int,
) -> Iterator[tuple[str, int, ZoneSnapshots]]:
    """Yield (zone, zoom, snapshots) for the major/moons/small_body_moons zones."""
    # Major bodies — chebyshev claims zoom 0 (Sun, planets, Pluto, Ceres), so
    # kepler fallbacks live at higher zooms. Split by source to keep each file
    # single-provider (the file-level source byte forbids mixed origins):
    #   zoom 1 = horizons-sourced majors not covered by chebyshev — in practice
    #            this catches dwarf planets that have Horizons ephemerides but
    #            no SPK kernel.
    #   zoom 2 = SBDB-only dwarves (Eris, Makemake, Quaoar, …) that aren't in
    #            any SPK kernel either.
    # Major bodies + moons are horizons- or spice-source, so eager-load
    # Object.horizons (kepler elements live there). SBDB-source majors join
    # sbdb instead. (Deep-space spacecraft used to ride here in a `spacecraft`
    # zone — they're now in the dedicated probes export with proper SPICE
    # trajectories.)
    major_base = session.query(Object).options(
        joinedload(Object.sbdb), joinedload(Object.horizons)
    )
    specs = [
        (
            "major",
            1,
            major_base.filter(
                Object.object_type.in_(_SUN_MAJOR_TYPE_VALUES),
                Object.orbital_source != OrbitalSource.sbdb,
                Object.id.notin_(cheb_covered_ids) if cheb_covered_ids else sa_true(),
            ),
        ),
        (
            "major",
            2,
            major_base.filter(
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
                Object.orbital_source.is_distinct_from(OrbitalSource.sbdb_moon),
                Object.id.notin_(cheb_covered_ids) if cheb_covered_ids else sa_true(),
            ),
        ),
        (
            "small_body_moons",
            0,
            session.query(Object)
            .options(joinedload(Object.sbdb_moon))
            .filter(
                Object.orbital_source == OrbitalSource.sbdb_moon,
                Object.has_position == True,  # noqa: E712
            ),
        ),
    ]
    for zone, zoom, q in specs:
        # Model-pointed Objects first (see _run_earth_zones for rationale).
        objects = (
            q.order_by(Object.model_name.is_(None), Object.random_int)
            .limit(limit_per_zone)
            .all()
        )
        if not objects:
            logger.info("  %s zoom=%d: empty, skipping", zone, zoom)
            continue
        if zone == "major":
            objects.sort(key=_major_sort_key)
        if zone == "moons":
            snapshots = moons_snapshots(objects, DOWNLOAD_DIR)
        else:
            snapshots = single_snapshot(objects)
        yield zone, zoom, snapshots


def _moon_host_ids(session: Session) -> set[str]:
    """Object ids that parent at least one asteroid moon (SBDBMoon rows)."""
    return {
        pid
        for (pid,) in session.query(SBDBMoon.parent_object_id)
        .filter(SBDBMoon.parent_object_id.is_not(None))
        .distinct()
    }


def _iter_sbdb_zone_snapshots(
    session: Session,
    cheb_covered_ids: set[str],
    out_dir: Path,
    agg: _Aggregators,
    tier_b_clean: bool,
) -> Iterator[tuple[str, int, ZoneSnapshots, int]]:
    """Yield (zone, zoom, snapshots, part_offset) per CHUNK_SIZE-aligned batch.

    Each (SBDB class, named) combo is streamed in `_SBDB_BATCH_ROWS` batches
    rather than materialized whole, so the giant classes don't land a
    multi-GB `.all()` in RAM. A combo emits one batch per slice; `part_offset`
    places each batch's parts in a contiguous `0..N-1` run, so the on-disk
    layout matches a one-shot combo. The caller tallies the batches back into
    a single zone result.

    Combos whose zone signature matches their cached meta (and tier B is
    clean) are folded into `agg` from the cache and never queried — the ORM
    load and per-object build are the expensive part of a no-change run.

    Generator pauses after each yield so the caller can submit the snapshots
    to the executor before we move on. Resuming detaches the batch's objects
    one at a time (not ``expunge_all()``, which would kill the identity map
    the live cursor still feeds) — workers keep them alive via their own
    refs, so no lazy load can fire.
    """
    # Moon hosts join the named bodies in the eager (zoom 0) tier so an
    # asteroid-moon's parent loads early enough for the frontend to resolve the
    # moon's position (its position is anchored on the parent). Without this the
    # parent often sits in the deferred zoom-1 tail and the moon never appears.
    host_ids = _moon_host_ids(session)
    sbdb_sig = incremental.sbdb_zone_signature(cheb_covered_ids, host_ids)
    is_eager = or_(SBDB.name.is_not(None), SBDB.object_id.in_(host_ids))
    eager_col = case((is_eager, 1), else_=0).label("eager")
    combos = (
        session.query(SBDB.class_, eager_col).group_by(SBDB.class_, eager_col).all()
    )
    for cls, eager in combos:
        zoom = 0 if eager else 1
        if tier_b_clean:
            meta = _zone_is_cached(out_dir, f"small_bodies/{cls.name}", zoom, sbdb_sig)
            if meta is not None:
                _record_cached(f"small_bodies/{cls.name}", zoom, meta, agg)
                continue
        name_filter = is_eager if eager else ~is_eager
        # SPICE-sourced bodies (DE441 perturbers like Ceres, Pallas, …) ship
        # via the chebyshev export and are filtered out here both to enforce
        # the one-provider-per-file invariant and to avoid shipping duplicate
        # position data for bodies that already appear in a chebyshev zone.
        q = (
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
            q = q.filter(Object.id.notin_(cheb_covered_ids))
        # SBDB zones are uncapped: incremental per-part sidecars (see
        # elements/sidecar.build_sbdb_part_signature) mean a no-op re-export
        # costs a sidecar scan rather than re-encoding every asteroid. The
        # first-export and post-refresh cost still scales with row count, but
        # that's amortized across re-runs.
        #
        # Stream in CHUNK_SIZE-aligned batches so a giant class never lands
        # whole in RAM. yield_per keeps the single-query random_int order, so
        # each batch's part range matches the slice a one-shot `.all()` would
        # have chunked — the output is byte-identical, just written piecewise.
        # All SBDB classes ship under one parent dir so the prune pass and
        # incremental wipe rules can target them as a group.
        zone = f"small_bodies/{cls.name}"
        batch: list[Object] = []
        part_offset = 0
        for obj in q.order_by(Object.random_int).yield_per(CHUNK_SIZE):
            batch.append(obj)
            if len(batch) == _SBDB_BATCH_ROWS:
                yield zone, zoom, single_snapshot(batch), part_offset
                part_offset += _SBDB_BATCH_ROWS // CHUNK_SIZE
                # Detach the submitted batch one row at a time — workers hold
                # their refs, so no lazy load can fire. `expunge_all()` would
                # kill the identity map the live yield_per cursor is still
                # feeding rows into, so it has to be per-object here.
                for done in batch:
                    session.expunge(done)
                batch = []
        if batch:
            yield zone, zoom, single_snapshot(batch), part_offset
            for done in batch:
                session.expunge(done)


def _run_earth_zones(
    session: Session,
    out_dir: Path,
    ctx: ObjectDataContext,
    celestrak_loader: Callable[[], Mapping[str, dict[int, CelesTrakElements]]],
    agg: _Aggregators,
    tier_b_clean: bool,
) -> None:
    """Run Earth-zone exports inline (synchronous).

    Zooms whose zone signature matches the cached meta (and tier B is clean)
    skip the DB load and per-day overlays entirely; the CelesTrak CSVs are
    only parsed (`celestrak_loader`) when at least one zoom runs.

    Per-day overlays mutate the same Object instances in-place, so multiple
    days can't be shipped to threads simultaneously without cloning.
    Main-thread work still overlaps with the executor pool processing other
    zones.
    """
    earth_sig = incremental.earth_zone_signature()
    earth_base = (
        session.query(Object)
        .options(joinedload(Object.satcat), joinedload(Object.celestrak))
        .filter(
            Object.spkid.is_(None),
            Object.object_type.in_(_SAT_TYPE_VALUES),
            Object.parent_id == _EARTH_OBJECT_ID,
        )
    )
    is_constellation = or_(*(Object.name.startswith(p) for p in CONSTELLATION_PREFIXES))
    for zoom_label, zoom_filter in (
        (0, ~is_constellation),
        (1, is_constellation),
    ):
        if tier_b_clean:
            meta = _zone_is_cached(out_dir, "earth", zoom_label, earth_sig)
            if meta is not None:
                _record_cached("earth", zoom_label, meta, agg)
                continue
        # Earth zones are uncapped: per-day CelesTrak sidecars (see
        # `build_earth_part_signature`) make re-export incremental. random_int
        # ordering is kept for deterministic chunking.
        base_objects = earth_base.filter(zoom_filter).order_by(Object.random_int).all()
        if not base_objects:
            logger.info("  earth zoom=%d: empty, skipping", zoom_label)
            continue
        result = export_zone(
            "earth",
            zoom_label,
            earth_snapshots(base_objects, celestrak_loader()),
            out_dir,
            ctx,
        )
        _record("earth", zoom_label, result, agg)
        incremental.write_zone_meta(
            out_dir,
            "earth",
            zoom_label,
            earth_sig,
            result.parent_id_type,
            result.snapshots,
        )


def _drive_zone_exports(
    session: Session,
    out_dir: Path,
    ctx: ObjectDataContext,
    celestrak_loader: Callable[[], Mapping[str, dict[int, CelesTrakElements]]],
    limit_per_zone: int,
    cheb_covered_ids: set[str],
    agg: _Aggregators,
    tier_b_clean: bool,
) -> None:
    """Submit threaded zone exports, run Earth zones inline, fold all results.

    Zones whose cached signature still matches are folded into `agg` here
    and never submitted (see `_iter_sbdb_zone_snapshots` / `_run_earth_zones`).

    Each zone export is drained into `agg` the moment it completes, so only
    the in-flight zones' per-object data stays resident — not the whole
    export's. Returns once every result has been folded in.
    """
    sbdb_sig = incremental.sbdb_zone_signature(
        cheb_covered_ids, _moon_host_ids(session)
    )
    futures: dict[Future, tuple[str, int]] = {}
    # SBDB combos arrive as several batch futures; tally their per-batch stats
    # back into one untimed snapshot per (zone, zoom) so the zone meta and
    # manifest see a single combo, exactly as the pre-streaming path produced.
    sbdb_tally: dict[tuple[str, int], SnapshotResult] = {}
    sbdb_parent: dict[tuple[str, int], str | None] = {}

    def drain(done: set[Future]) -> None:
        """Fold completed zone exports into `agg` and drop their results.

        SBDB batches merge their object data eagerly (freeing it) but only
        accumulate counts here — the zone meta is written once per combo in
        :func:`_finalize_sbdb_zones` after every batch has landed.
        """
        for f in done:
            zone, zoom = futures.pop(f)
            result = f.result()
            if zone.startswith("small_bodies/"):
                _merge_object_data(agg.all_objects, result.zone_data)
                key = (zone, zoom)
                tally = sbdb_tally.setdefault(
                    key, SnapshotResult(time=None, count=0, num_parts=0)
                )
                sbdb_parent[key] = result.parent_id_type
                for snap in result.snapshots:
                    tally.count += snap.count
                    tally.num_parts += snap.num_parts
            else:
                _record(zone, zoom, result, agg)

    def _finalize_sbdb_zones() -> None:
        """Fold each combo's tallied snapshot into `agg` and write its meta."""
        for (zone, zoom), tally in sbdb_tally.items():
            agg.object_counts[(zone, zoom, None)] += tally.count
            agg.zone_structure[zone][zoom].parent_id_type = sbdb_parent[(zone, zoom)]
            agg.zone_structure[zone][zoom].snapshots.append(tally)
            logger.info(
                "  %s zoom=%d: %d objects, %d parts",
                zone,
                zoom,
                tally.count,
                tally.num_parts,
            )
            incremental.write_zone_meta(
                out_dir, zone, zoom, sbdb_sig, sbdb_parent[(zone, zoom)], [tally]
            )

    with ThreadPoolExecutor(max_workers=_MAX_ZONE_IN_FLIGHT) as executor:
        in_flight: set[Future] = set()

        def gate() -> None:
            """Block until a slot frees up, draining whatever completed.

            Without this the loop would queue every batch's loaded ORM
            objects in the executor's work queue, defeating max_workers as a
            memory bound. The expunge after each SBDB submit only frees
            memory once *all* refs to those objects drop — including the
            queued future's — so we have to keep the queue short too.
            """
            while len(in_flight) >= _MAX_ZONE_IN_FLIGHT:
                done, _pending = wait(in_flight, return_when=FIRST_COMPLETED)
                in_flight.difference_update(done)
                drain(done)

        def submit_zone(
            zone: str, zoom: int, snapshots: ZoneSnapshots, part_offset: int = 0
        ) -> None:
            gate()
            f = executor.submit(
                export_zone, zone, zoom, snapshots, out_dir, ctx, part_offset
            )
            futures[f] = (zone, zoom)
            in_flight.add(f)

        for zone, zoom, snapshots in _iter_non_sbdb_zone_snapshots(
            session, cheb_covered_ids, limit_per_zone
        ):
            submit_zone(zone, zoom, snapshots)
        for zone, zoom, snapshots, part_offset in _iter_sbdb_zone_snapshots(
            session, cheb_covered_ids, out_dir, agg, tier_b_clean
        ):
            submit_zone(zone, zoom, snapshots, part_offset)
        _run_earth_zones(session, out_dir, ctx, celestrak_loader, agg, tier_b_clean)
        # Drain the tail: batches still running plus those that finished while
        # earth ran inline. Session stays open so ORM objects remain valid.
        while in_flight:
            done, _pending = wait(in_flight, return_when=FIRST_COMPLETED)
            in_flight.difference_update(done)
            drain(done)

    _finalize_sbdb_zones()


def _build_non_zone_object_data(
    session: Session,
    ctx: ObjectDataContext,
    cheb_covered_ids: set[str],
    all_objects: ChunkObjectData,
) -> set[str]:
    """Build per-object data for bodies that don't ride through `export_zone`.

    Three sources, all merged into `all_objects`:

    * **Chebyshev-covered** majors/perturbers — excluded from the elements
      zones (no double-shipping), so their per-object metadata never lands in
      `all_objects` through the zone path. Building it here also triggers the
      large-scale unit ladder entries (solar_mass, earth_mass, …) that only
      get pulled in via `units.convert` on those bodies' values.
    * **Orbit-less SBDB satellites** — publication placeholders with no orbit
      (~95% of rows) or a partial Kepler set. Never appear in the
      small_body_moons position zone but still need bundles + a detail page.
      Excluded from the labels file by `has_position` to avoid the
      renderer's auto-promote loop retrying an unfindable getBody every frame.
    * **Probes** — ride in their own chunk files (not the elements table) so
      they carry `has_position=False` and never run through `export_zone`.
      Their metadata is needed for the drawer.

    Returns the set of probe Object.ids (used by the labels file).
    """
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
        _build_object_data_for("chebyshev-covered bodies", cheb_objs, ctx, all_objects)

    orbitless_moons = (
        session.query(Object)
        .options(joinedload(Object.sbdb_moon))
        .filter(
            Object.orbital_source == OrbitalSource.sbdb_moon,
            Object.has_position == False,  # noqa: E712
        )
        .all()
    )
    _build_object_data_for(
        "orbit-less SBDB satellites", orbitless_moons, ctx, all_objects
    )

    probe_objs = (
        session.query(Object)
        .filter(Object.orbital_source == OrbitalSource.spice_probe)
        .all()
    )
    _build_object_data_for("probes", probe_objs, ctx, all_objects)
    return {p.id for p in probe_objs}


def _load_rendered_ids(session: Session) -> set[str]:
    """IDs of bodies that ship in some position file — gates label auto-promote.

    Sourced from the DB column rather than a runtime accumulator so the
    per-source ingest is the single writer of "is this row renderable in 3D".
    Probes carry `has_position=False` because their positions live in
    dedicated chunk files (not the elements table), but they're equally
    renderable in 3D, so OR them in by orbital_source.
    """
    return {
        oid
        for (oid,) in session.query(Object.id)
        .filter(
            or_(
                Object.has_position == True,  # noqa: E712
                Object.orbital_source == OrbitalSource.spice_probe,
            )
        )
        .all()
    }


def _load_moon_parent_names(session: Session) -> dict[str, str]:
    """Map each moon-host Object.id to its display name.

    Shipped in moon bundles (orbit.parent_name) so the frontend breadcrumb can
    name the host even when the host body isn't resident in the scene — small-
    body hosts get culled by the streaming loader once focus moves on.
    """
    host_ids = (
        session.query(Object.parent_id)
        .filter(
            Object.object_type == ObjectType.moon.value,
            Object.parent_id.is_not(None),
        )
        .distinct()
    )
    rows = (
        session.query(Object.id, Object.name)
        .filter(Object.id.in_(host_ids), Object.name.is_not(None))
        .all()
    )
    return {oid: name for oid, name in rows}


def _load_nasa_science_urls() -> dict[str, str]:
    """Load the pk→URL map, returning {} if the download file is missing."""
    path = SOURCES_METADATA_DIR / "nasa-science-urls" / "pk-to-url.json"
    if path.exists():
        urls: dict[str, str] = orjson.loads(path.read_bytes())
        logger.info("Loaded %d NASA Science URLs", len(urls))
        return urls
    logger.warning("NASA Science URL file not found: %s", path)
    return {}


# Content-class directories served under an immutable `Cache-Control` rule
# (see infrastructure/deploy/_headers). Each gets a content-hash token in
# metadata.json `versions`; the frontend appends it as `?v=` so a content change
# yields a fresh URL while unchanged classes stay cached. Roots that stay on the
# revalidating default (metadata, systems, groups, labels, credits) are absent.
VERSIONED_CLASSES = (
    "position",
    "objects",
    "nomenclature",
    "textures",
    "rings",
    "models",
    "images",
    "membership",
)


def _content_token(root: Path) -> str:
    """Stable 16-hex token over every file under `root` (path + bytes).

    Changes iff a file's relative path or contents change, so a deterministic
    re-export keeps the token (and the client's cached copy). Returns "0" when
    the directory is missing or holds no files. Nondeterministic contents only
    weaken caching (the token churns), never correctness.
    """
    if not root.is_dir():
        return "0"
    files = sorted(p for p in root.rglob("*") if p.is_file())
    if not files:
        return "0"
    digest = hashlib.sha256()
    for path in files:
        file_hash = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                file_hash.update(block)
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(file_hash.digest())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def _write_metadata_json(
    out_dir: Path,
    zone_structure: Mapping[str, Mapping[int, ZoomSnapshots]],
    chebyshev_zones: dict,
    probe_zones: dict,
    probe_coverage: dict[str, dict[str, float]],
    bundle_ns: dict,
    feature_bundle_ns: dict,
    group_bundle_ns: dict,
    skybox_metadata: dict | None,
) -> None:
    """Emit the top-level metadata.json (position manifest + bundles + skybox)."""
    position_metadata = build_position_metadata(
        zone_structure, chebyshev_zones, probe_zones, probe_coverage
    )
    metadata: dict = {
        "position": position_metadata,
        "object_bundles": bundle_ns,
        "feature_bundles": feature_bundle_ns,
        "group_bundles": group_bundle_ns,
        "versions": {cls: _content_token(out_dir / cls) for cls in VERSIONED_CLASSES},
    }
    if skybox_metadata is not None:
        metadata["skybox"] = skybox_block(skybox_metadata)
    (out_dir / "metadata.json").write_bytes(
        orjson.dumps(metadata, option=orjson.OPT_INDENT_2)
    )


def _run_chebyshev(
    session: Session,
    out_dir: Path,
    radii: dict[int, dict],
    cheb_covered_ids: set[str],
    agg: _Aggregators,
    tier_b_clean: bool,
) -> dict[str, dict]:
    """Run (or skip) the chebyshev pass behind its input signature.

    Skipping requires tier B clean: body resolution and has_localized bits
    come from DB + wikidata, which only the tier-B fingerprint tracks. When
    only the npz inputs changed, the per-body bits are reused from the meta.
    """
    sig = incremental.chebyshev_signature()
    meta = incremental.read_chebyshev_meta(out_dir)
    if tier_b_clean and meta is not None and meta.get("signature") == sig:
        manifest = meta["zone_manifest"]
        if all((out_dir / "position" / z / "0").is_dir() for z in manifest):
            logger.info(
                "Chebyshev inputs unchanged — skipped (%d zones cached)",
                len(manifest),
            )
            return manifest
    if tier_b_clean:
        has_loc = (meta or {}).get("has_localized", {})
    else:
        has_loc = {
            oid: bool(agg.all_objects.has_localized.get(oid))
            for oid in cheb_covered_ids
        }
    _wipe_chebyshev_outputs(out_dir, meta)
    manifest = write_chebyshev(session, DOWNLOAD_DIR, out_dir, radii, has_loc)
    incremental.write_chebyshev_meta(out_dir, sig, manifest, has_loc)
    return manifest


def _wipe_chebyshev_outputs(out_dir: Path, previous_meta: dict | None) -> None:
    """Remove chebyshev-owned chunk dirs before a re-encode.

    These dirs survive `remove_old_outputs` so a skipped pass keeps its
    files; a re-encoding pass starts clean so stale chunks can't linger.
    Wipes the standard cheb dirs plus whatever the previous manifest listed.
    """
    pos = out_dir / "position"
    zones = {"major/0", "major_asteroids"}
    moons_dir = pos / "moons"
    if moons_dir.exists():
        zones.update(
            f"moons/{child.name}"
            for child in moons_dir.iterdir()
            if child.is_dir() and child.name != "0"
        )
    for zone in (previous_meta or {}).get("zone_manifest", {}):
        zones.add(f"{zone}/0" if zone in ("major",) else zone)
    for zone in zones:
        path = pos / zone
        if path.exists():
            shutil.rmtree(path)


def _run_probes(
    session: Session,
    out_dir: Path,
    probe_ids: set[str],
    agg: _Aggregators,
    tier_b_clean: bool,
) -> tuple[dict[str, dict], dict[str, dict[str, float]]]:
    """Run (or skip) the probes pass behind its input signature.

    Same tier-B coupling as chebyshev: probe Object rows and has_localized
    bits are only tracked by the tier-B fingerprint, so a skip requires a
    clean tier B and unchanged kernels/events/candidates/registry.
    """
    sig = incremental.probes_signature()
    meta = incremental.read_probes_meta(out_dir)
    if (
        tier_b_clean
        and meta is not None
        and meta.get("signature") == sig
        and (out_dir / "position" / "probes").is_dir()
    ):
        logger.info(
            "Probe inputs unchanged — skipped (%d zones cached)",
            len(meta["zone_manifest"]),
        )
        return meta["zone_manifest"], meta["coverage"]
    if tier_b_clean:
        has_loc = (meta or {}).get("has_localized", {})
    else:
        has_loc = {
            oid: bool(agg.all_objects.has_localized.get(oid)) for oid in probe_ids
        }
    zone_manifest, coverage = write_probes(session, DOWNLOAD_DIR, out_dir, has_loc)
    incremental.write_probes_meta(out_dir, sig, zone_manifest, coverage, has_loc)
    return zone_manifest, coverage


def export(engine: Engine, limit_per_zone: int = _DEFAULT_ZONE_LIMIT) -> None:
    """Run the full export pipeline."""
    t0 = time.monotonic()
    out_dir = EXPORT_DIR / "v1"
    with Session(engine) as session:
        precheck_tables(session)
        nomenclature_by_body = build_nomenclature(session)
        moon_parent_names = _load_moon_parent_names(session)
        tier_b_fp = incremental.tier_b_fingerprint(session)
    tier_b_meta = incremental.read_tier_b_meta(out_dir)
    tier_b_clean = (
        tier_b_fp["ingest_stamp"] is not None
        and tier_b_meta is not None
        and tier_b_meta.get("fingerprint") == tier_b_fp
    )
    if tier_b_clean:
        logger.info(
            "Object-metadata inputs unchanged — bundle/label/feature/message "
            "writers will be skipped, unchanged zones won't be reloaded"
        )
    else:
        logger.info("Object-metadata inputs changed — full per-object rebuild")
    out_dir.mkdir(parents=True, exist_ok=True)
    remove_old_outputs(out_dir, keep_object_outputs=tier_b_clean)

    wikidata_entities = WikidataEntityCache()
    units = UnitConverter(wikidata_entities)
    orientation = load_orientation(DOWNLOAD_DIR)
    radii = load_radii(DOWNLOAD_DIR)
    gms = load_gms(DOWNLOAD_DIR)
    nut_prec = load_nut_prec(DOWNLOAD_DIR)
    nut_prec_angles = load_nut_prec_angles(DOWNLOAD_DIR)
    texture_metadata = load_texture_metadata(out_dir)
    ring_metadata = load_ring_metadata(out_dir)
    clouds_metadata = load_clouds_metadata(out_dir)
    specular_metadata = load_specular_metadata(out_dir)
    night_metadata = load_night_metadata(out_dir)
    skybox_metadata = load_skybox_metadata(out_dir)
    model_metadata = load_model_metadata(out_dir)
    probe_kernel_sources = load_probe_kernel_sources()

    ctx = ObjectDataContext(
        wikidata_entities=wikidata_entities,
        units=units,
        nasa_science_urls=_load_nasa_science_urls(),
        orientation=orientation,
        radii=radii,
        gms=gms,
        nut_prec=nut_prec,
        texture_metadata=texture_metadata,
        clouds_metadata=clouds_metadata,
        probe_kernel_sources=probe_kernel_sources,
        nomenclature_body_ids=set(nomenclature_by_body.keys()),
        parent_names=moon_parent_names,
    )

    write_systems_global(out_dir, gms, nut_prec_angles)

    # CelesTrak CSV parsing is deferred: when both earth zooms skip via their
    # zone meta, the ~120 MB of day CSVs are never read.
    _celestrak_days: dict[str, dict[int, CelesTrakElements]] | None = None

    def celestrak_loader() -> Mapping[str, dict[int, CelesTrakElements]]:
        nonlocal _celestrak_days
        if _celestrak_days is None:
            _celestrak_days = load_all_days(DOWNLOAD_DIR)
        return _celestrak_days

    agg = _Aggregators()

    with Session(engine) as session:
        # Bodies covered by chebyshev (Sun/planets/dwarves, perturber asteroids,
        # whitelisted moons) are excluded from the elements zones. Two-format
        # ride-along would just bloat the export — the frontend can derive
        # osculating elements from chebyshev positions if it needs them.
        cheb_covered_ids = chebyshev_coverage(session, DOWNLOAD_DIR)
        if cheb_covered_ids:
            logger.info(
                "Chebyshev covers %d bodies; dropping them from elements zones",
                len(cheb_covered_ids),
            )

        _drive_zone_exports(
            session,
            out_dir,
            ctx,
            celestrak_loader,
            limit_per_zone,
            cheb_covered_ids,
            agg,
            tier_b_clean,
        )

        write_system_metadata(
            session,
            out_dir,
            orientation,
            radii,
            nut_prec,
            texture_metadata,
            ring_metadata,
            clouds_metadata,
            specular_metadata,
            night_metadata,
        )
        write_credits(
            session,
            out_dir,
            texture_metadata,
            ring_metadata,
            clouds_metadata,
            night_metadata,
            skybox_metadata,
            model_metadata,
        )

        if not tier_b_clean:
            probe_ids = _build_non_zone_object_data(
                session, ctx, cheb_covered_ids, agg.all_objects
            )
        else:
            probe_ids = set()

        chebyshev_zones = _run_chebyshev(
            session, out_dir, radii, cheb_covered_ids, agg, tier_b_clean
        )
        probe_zones, probe_coverage = _run_probes(
            session, out_dir, probe_ids, agg, tier_b_clean
        )

        rendered_ids = _load_rendered_ids(session) if not tier_b_clean else set()

    if tier_b_clean:
        # Outputs on disk are already current; reuse the bucket counts the
        # last full run published so metadata.json stays consistent.
        assert tier_b_meta is not None
        bundle_ns = tier_b_meta["bundle_ns"]
        feature_bundle_ns = tier_b_meta["feature_bundle_ns"]
        group_bundle_ns = tier_b_meta["group_bundle_ns"]
        logger.info(
            "Skipped object bundles, labels, nomenclature, feature details, "
            "messages and groups (object-metadata inputs unchanged)"
        )
    else:
        # Notable moons + attitude both mutate the in-memory object bundles
        # before they're sealed. Moons need a session (the zone session above
        # is already closed), so open a short-lived one for the lookup.
        with Session(engine) as session:
            attach_notable_moons(session, agg.all_objects, wikidata_entities, radii)
            attach_featured_satellites(session, agg.all_objects, wikidata_entities)
            attach_comet_fragments(session, agg.all_objects, wikidata_entities)
        attach_probe_missions(agg.all_objects, wikidata_entities)
        # Attitude extraction runs after probe positions are written but before
        # the global object bundles are sealed — it mutates `global_data` in
        # place to inject the per-probe attitude manifest under `attitude`.
        write_attitude(out_dir, agg.all_objects.global_data)

        bundle_ns = write_object_bundles(
            out_dir, agg.all_objects.global_data, agg.all_objects.localized_data
        )
        write_nomenclature_positions(out_dir, nomenclature_by_body)
        write_nomenclature_labels(out_dir, nomenclature_by_body, wikidata_entities)
        # Feature details are built after object data so the unit converter has
        # already absorbed object-side `used_units`; nomenclature claims may add
        # more (km, m, ...) that the localization writer needs to see below.
        body_radii_km = {
            f"naif-{naif_id}": (r["a"] + r["b"] + r["c"]) / 3.0
            for naif_id, r in radii.items()
        }
        with Session(engine) as session:
            feature_details = build_feature_details(
                session, wikidata_entities, units, body_radii_km=body_radii_km
            )
        feature_bundle_ns = write_feature_detail_bundles(out_dir, feature_details)
        write_global_labels(
            out_dir, agg.all_objects, cheb_covered_ids, probe_ids, rendered_ids
        )
        write_messages(wikidata_entities, units.used_units)
        group_bundle_ns = run_groups_tier(engine, out_dir, wikidata_entities)
        incremental.write_tier_b_meta(
            out_dir, tier_b_fp, bundle_ns, feature_bundle_ns, group_bundle_ns
        )
    prune_small_bodies(out_dir, agg.zone_structure)
    _write_metadata_json(
        out_dir,
        agg.zone_structure,
        chebyshev_zones,
        probe_zones,
        probe_coverage,
        bundle_ns,
        feature_bundle_ns,
        group_bundle_ns,
        skybox_metadata,
    )

    total = sum(agg.object_counts.values())
    elapsed = time.monotonic() - t0
    logger.info("Export complete: %d objects to %s in %.1fs", total, out_dir, elapsed)
