"""Export orchestrator: query DB, write chunked output files."""

import logging
import math
import orjson
import shutil
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from space_map_data.models.object.sbdb import CometPrefix
from sqlalchemy import case, or_
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, joinedload

from space_map_data.export.chebyshev import write_chebyshev
from space_map_data.export.credits import write_credits
from space_map_data.export.elements import CHUNK_SIZE, write_chunk
from space_map_data.export.elements.format import VERSION
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
from space_map_data.export.wikidata import WikidataEntityCache
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


def _build_metadata(
    zone_structure: dict[str, dict[int, int]],
    object_counts: dict[tuple[str, int], int],
    total_bytes: dict[tuple[str, int], int],
) -> dict:
    zones = {}
    for zone, zoom_parts in sorted(zone_structure.items()):
        zooms = {}
        for zoom, part_count in sorted(zoom_parts.items()):
            count = object_counts.get((zone, zoom), 0)
            nbytes = total_bytes.get((zone, zoom), 0)
            zooms[str(zoom)] = {
                "parts": part_count,
                "object_count": count,
                "avg_part_bytes": nbytes // part_count if part_count else 0,
            }
        zones[zone] = {"zooms": zooms}
    return {
        "version": VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "zones": zones,
    }


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


def _write_parts(
    objects: list[Object],
    out_dir: Path,
    zone: str,
    zoom: int,
    wikidata_entities: WikidataEntityCache,
    units: UnitConverter,
    nasa_science_urls: dict[str, str],
    orientation: dict[int, dict],
    radii: dict[int, dict],
    nut_prec: dict[int, dict[str, list[float]]],
    texture_metadata: dict[str, dict],
) -> tuple[int, int, ChunkObjectData]:
    """Split objects into CHUNK_SIZE parts, write elements/labels/ids per chunk.

    Returns `(num_parts, elements_bytes, aggregated_object_data)`. The object
    data is accumulated across parts but NOT written here — the caller merges
    data from all (zone, zoom) tasks and writes hash-bucketed bundles at the
    end.
    """
    aggregated = ChunkObjectData()

    num_parts = max(1, math.ceil(len(objects) / CHUNK_SIZE))
    total_bytes = 0
    for part_idx in range(num_parts):
        chunk = objects[part_idx * CHUNK_SIZE : (part_idx + 1) * CHUNK_SIZE]
        chunk_entities = {
            qid: wikidata_entities.get_entity(qid)
            for obj in chunk
            if (
                qid := obj.wikidata_qid
                or (
                    obj.satcat.wikidata_qid
                    if obj.norad_cat_id is not None and obj.satcat
                    else None
                )
            )
        }
        chunk_data = build_chunk_object_data(
            chunk,
            wikidata_entities,
            chunk_entities,
            units,
            nasa_science_urls,
            orientation=orientation,
            radii=radii,
            nut_prec=nut_prec,
            texture_metadata=texture_metadata,
        )
        aggregated.global_data.update(chunk_data.global_data)
        for lang, by_id in chunk_data.localized_data.items():
            aggregated.localized_data[lang].update(by_id)
        aggregated.flags.update(chunk_data.flags)
        total_bytes += write_chunk(
            chunk,
            out_dir,
            zone,
            zoom,
            part_idx,
            chunk_entities,
            chunk_data.flags,
            units,
            _chunk_source(chunk, zone, part_idx),
        )

    return num_parts, total_bytes, aggregated


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

    zone_structure: defaultdict[str, dict[int, int]] = defaultdict(dict)
    object_counts: defaultdict[tuple[str, int], int] = defaultdict(int)
    total_bytes_map: defaultdict[tuple[str, int], int] = defaultdict(int)

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
                    "earth",
                    0,
                    _earth_base.filter(~_is_constellation),
                ),
                (
                    "earth",
                    1,
                    _earth_base.filter(_is_constellation),
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
                f = executor.submit(
                    _write_parts,
                    objects,
                    out_dir,
                    zone,
                    zoom,
                    wikidata_entities,
                    units,
                    nasa_science_urls,
                    orientation,
                    radii,
                    nut_prec,
                    texture_metadata,
                )
                futures[f] = (zone, zoom, len(objects))

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
                    _write_parts,
                    objects,
                    out_dir,
                    zone,
                    zoom,
                    wikidata_entities,
                    units,
                    nasa_science_urls,
                    orientation,
                    radii,
                    nut_prec,
                    texture_metadata,
                )
                futures[f] = (zone, zoom, len(objects))
            # executor joins here — session still open so ORM objects remain valid

        write_system_metadata(
            session, out_dir, orientation, radii, nut_prec, texture_metadata
        )
        write_credits(session, out_dir, texture_metadata)
        chebyshev_manifest = write_chebyshev(session, DOWNLOAD_DIR, out_dir, radii)

    all_objects = ChunkObjectData()
    for f in as_completed(futures):
        zone, zoom, count = futures[f]
        num_parts, nbytes, zone_data = f.result()
        object_counts[(zone, zoom)] += count
        total_bytes_map[(zone, zoom)] += nbytes
        zone_structure[zone][zoom] = num_parts
        logger.info("  %s zoom=%d: %d objects, %d parts", zone, zoom, count, num_parts)
        all_objects.global_data.update(zone_data.global_data)
        for lang, by_id in zone_data.localized_data.items():
            all_objects.localized_data[lang].update(by_id)
        all_objects.flags.update(zone_data.flags)

    bundle_ns = write_object_bundles(
        out_dir, all_objects.global_data, all_objects.localized_data
    )

    # --- Other outputs ---
    write_messages(wikidata_entities, units.used_units)

    metadata = _build_metadata(zone_structure, object_counts, total_bytes_map)
    metadata["object_bundles"] = bundle_ns
    if chebyshev_manifest:
        metadata["chebyshev"] = chebyshev_manifest
    (out_dir / "metadata.json").write_bytes(
        orjson.dumps(metadata, option=orjson.OPT_INDENT_2)
    )

    total = sum(object_counts.values())
    elapsed = time.monotonic() - t0
    logger.info("Export complete: %d objects to %s in %.1fs", total, out_dir, elapsed)
