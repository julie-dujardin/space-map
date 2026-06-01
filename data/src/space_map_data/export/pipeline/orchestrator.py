"""Export orchestrator: query DB, drive zone exports, write global outputs."""

import logging
import time
from collections import defaultdict
from collections.abc import Iterator, Mapping
from concurrent.futures import (
    FIRST_COMPLETED,
    Future,
    ThreadPoolExecutor,
    as_completed,
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
from space_map_data.export.labels import write_global_labels
from space_map_data.export.localization import write_messages
from space_map_data.export.nomenclature.writer import (
    build_nomenclature,
    write_nomenclature_files,
)
from space_map_data.export.objects.writer import (
    ChunkObjectData,
    write_object_bundles,
)
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
    ZoneExportResult,
    build_zone_object_data,
    export_zone,
)
from space_map_data.export.position import write_chebyshev
from space_map_data.export.position.chebyshev.coverage import chebyshev_coverage
from space_map_data.export.position.elements.celestrak_source import (
    CelesTrakElements,
    load_all_days,
)
from space_map_data.export.position.probes import write_probes
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
)
from space_map_data.models.object.sbdb import CometPrefix
from space_map_data.utils.paths import DOWNLOAD_DIR, EXPORT_DIR

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
# largest-combo size. 8 keeps the big MBA-unnamed combo (~3 GB) + smaller
# ones in flight under ~20 GB.
_MAX_ZONE_IN_FLIGHT = 8


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


def _iter_sbdb_zone_snapshots(
    session: Session,
    cheb_covered_ids: set[str],
) -> Iterator[tuple[str, int, ZoneSnapshots]]:
    """Yield (zone, zoom, snapshots) per (SBDB class, named) combo with rows.

    Generator pauses after each yield so the caller can submit the snapshots
    to the executor before we move on. Resuming runs ``session.expunge_all()``
    to release the identity map's ref to the loaded objects — workers keep
    them alive via their own refs, so no lazy load can fire. That's the
    memory bound for big combos (MBA-unnamed alone is ~3 GB of ORM rows).
    """
    named_col = case((SBDB.name.is_not(None), 1), else_=0).label("named")
    combos = (
        session.query(SBDB.class_, named_col).group_by(SBDB.class_, named_col).all()
    )
    for cls, named in combos:
        zoom = 0 if named else 1
        name_filter = SBDB.name.is_not(None) if named else SBDB.name.is_(None)
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
        objects = q.order_by(Object.random_int).all()
        if not objects:
            continue
        # All SBDB classes ship under one parent dir so the prune pass and
        # incremental wipe rules can target them as a group.
        zone = f"small_bodies/{cls.name}"
        yield zone, zoom, single_snapshot(objects)
        del objects
        session.expunge_all()


def _run_earth_zones(
    session: Session,
    out_dir: Path,
    ctx: ObjectDataContext,
    celestrak_days: Mapping[str, dict[int, CelesTrakElements]],
    agg: _Aggregators,
) -> None:
    """Run Earth-zone exports inline (synchronous).

    Per-day overlays mutate the same Object instances in-place, so multiple
    days can't be shipped to threads simultaneously without cloning.
    Main-thread work still overlaps with the executor pool processing other
    zones.
    """
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
            earth_snapshots(base_objects, celestrak_days),
            out_dir,
            ctx,
        )
        _record("earth", zoom_label, result, agg)


def _drive_zone_exports(
    session: Session,
    out_dir: Path,
    ctx: ObjectDataContext,
    celestrak_days: Mapping[str, dict[int, CelesTrakElements]],
    limit_per_zone: int,
    cheb_covered_ids: set[str],
    agg: _Aggregators,
) -> dict[Future, tuple[str, int]]:
    """Submit threaded zone exports + run Earth zones inline.

    Returns the pending futures (executor has joined, but the results are
    still wrapped). Caller drains them via :func:`_record` after writing the
    intermediate outputs that don't depend on per-object data.
    """
    futures: dict[Future, tuple[str, int]] = {}
    with ThreadPoolExecutor(max_workers=_MAX_ZONE_IN_FLIGHT) as executor:
        in_flight: set[Future] = set()

        def gate() -> None:
            """Block until at least one slot frees up.

            Without this the loop would queue every combo's loaded ORM
            objects in the executor's work queue, defeating max_workers as a
            memory bound. The expunge after each SBDB submit only frees
            memory once *all* refs to those objects drop — including the
            queued future's — so we have to keep the queue short too.
            """
            while len(in_flight) >= _MAX_ZONE_IN_FLIGHT:
                done, _pending = wait(in_flight, return_when=FIRST_COMPLETED)
                in_flight.difference_update(done)

        def submit_zone(zone: str, zoom: int, snapshots: ZoneSnapshots) -> None:
            gate()
            f = executor.submit(export_zone, zone, zoom, snapshots, out_dir, ctx)
            futures[f] = (zone, zoom)
            in_flight.add(f)

        for zone, zoom, snapshots in _iter_non_sbdb_zone_snapshots(
            session, cheb_covered_ids, limit_per_zone
        ):
            submit_zone(zone, zoom, snapshots)
        for zone, zoom, snapshots in _iter_sbdb_zone_snapshots(
            session, cheb_covered_ids
        ):
            submit_zone(zone, zoom, snapshots)
        _run_earth_zones(session, out_dir, ctx, celestrak_days, agg)
        # executor joins here — session still open so ORM objects remain valid
    return futures


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


def _load_nasa_science_urls() -> dict[str, str]:
    """Load the pk→URL map, returning {} if the download file is missing."""
    path = DOWNLOAD_DIR / "nasa-science-urls" / "pk-to-url.json"
    if path.exists():
        urls: dict[str, str] = orjson.loads(path.read_bytes())
        logger.info("Loaded %d NASA Science URLs", len(urls))
        return urls
    logger.warning("NASA Science URL file not found: %s", path)
    return {}


def _write_metadata_json(
    out_dir: Path,
    zone_structure: Mapping[str, Mapping[int, ZoomSnapshots]],
    chebyshev_zones: dict,
    probe_zones: dict,
    bundle_ns: dict,
    skybox_metadata: dict | None,
) -> None:
    """Emit the top-level metadata.json (position manifest + bundles + skybox)."""
    position_metadata = build_position_metadata(
        zone_structure, chebyshev_zones, probe_zones
    )
    metadata: dict = {"position": position_metadata, "object_bundles": bundle_ns}
    if skybox_metadata is not None:
        metadata["skybox"] = skybox_block(skybox_metadata)
    (out_dir / "metadata.json").write_bytes(
        orjson.dumps(metadata, option=orjson.OPT_INDENT_2)
    )


def export(engine: Engine, limit_per_zone: int = _DEFAULT_ZONE_LIMIT) -> None:
    """Run the full export pipeline."""
    t0 = time.monotonic()
    with Session(engine) as session:
        precheck_tables(session)
        nomenclature_payload = build_nomenclature(session)
    out_dir = EXPORT_DIR / "v1"
    out_dir.mkdir(parents=True, exist_ok=True)
    remove_old_outputs(out_dir)

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
        nomenclature_body_ids=set(nomenclature_payload.keys()),
    )

    write_systems_global(out_dir, gms, nut_prec_angles)
    celestrak_days = load_all_days(DOWNLOAD_DIR)

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

        futures = _drive_zone_exports(
            session,
            out_dir,
            ctx,
            celestrak_days,
            limit_per_zone,
            cheb_covered_ids,
            agg,
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

        # Aggregate has_localized from elements futures before writing chebyshev
        # — the cheb body header carries one bit per body, gated on the same
        # union map the elements files use.
        for f in as_completed(futures):
            zone, zoom = futures[f]
            _record(zone, zoom, f.result(), agg)

        probe_ids = _build_non_zone_object_data(
            session, ctx, cheb_covered_ids, agg.all_objects
        )

        chebyshev_zones = write_chebyshev(
            session, DOWNLOAD_DIR, out_dir, radii, agg.all_objects.has_localized
        )
        probe_zones = write_probes(
            session, DOWNLOAD_DIR, out_dir, agg.all_objects.has_localized
        )

        rendered_ids = _load_rendered_ids(session)

    bundle_ns = write_object_bundles(
        out_dir, agg.all_objects.global_data, agg.all_objects.localized_data
    )
    write_nomenclature_files(out_dir, nomenclature_payload)
    write_global_labels(
        out_dir, agg.all_objects, cheb_covered_ids, probe_ids, rendered_ids
    )
    write_messages(wikidata_entities, units.used_units)
    prune_small_bodies(out_dir, agg.zone_structure)
    _write_metadata_json(
        out_dir,
        agg.zone_structure,
        chebyshev_zones,
        probe_zones,
        bundle_ns,
        skybox_metadata,
    )

    total = sum(agg.object_counts.values())
    elapsed = time.monotonic() - t0
    logger.info("Export complete: %d objects to %s in %.1fs", total, out_dir, elapsed)
