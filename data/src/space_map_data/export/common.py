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

from space_map_data.export.elements import CHUNK_SIZE, write_chunk
from space_map_data.export.elements.format import VERSION
from space_map_data.export.objects import write_objects
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.localization import write_messages
from space_map_data.export.systems import (
    load_orientation,
    load_radii,
    write_system_metadata,
)
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.download.providers.wikidata.id_resolver import (
    CONSTELLATION_PREFIXES,
)
from space_map_data.models.object import Object, ObjectType, SBDB
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
    for d in ("elements", "objects"):
        p = out_dir / d
        if p.exists():
            shutil.rmtree(p)
    # System metadata is regenerated each export (individual textures are not)
    for d in ("textures/systems", "systems"):
        p = out_dir / d
        if p.exists():
            shutil.rmtree(p)


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
) -> tuple[int, int]:
    """Split objects into CHUNK_SIZE parts and write. Returns (num_parts, total_bytes)."""
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
                    if obj.celestrak_norad_cat_id is not None and obj.satcat
                    else None
                )
            )
        }
        # write_objects must come first — its return value feeds write_chunk
        object_flags = write_objects(
            chunk,
            out_dir,
            wikidata_entities,
            chunk_entities,
            units,
            nasa_science_urls,
            orientation=orientation,
            radii=radii,
        )
        total_bytes += write_chunk(
            chunk,
            out_dir,
            zone,
            zoom,
            part_idx,
            chunk_entities,
            object_flags,
            units,
        )
    return num_parts, total_bytes


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

    zone_structure: defaultdict[str, dict[int, int]] = defaultdict(dict)
    object_counts: defaultdict[tuple[str, int], int] = defaultdict(int)
    total_bytes_map: defaultdict[tuple[str, int], int] = defaultdict(int)

    futures: dict = {}

    with Session(engine) as session:
        with ThreadPoolExecutor() as executor:
            # Non-SBDB zones: (zone, zoom, query)
            _earth_base = (
                session.query(Object)
                .options(joinedload(Object.satcat))
                .filter(
                    Object.sbdb_spkid.is_(None),
                    Object.object_type.in_(_SAT_TYPE_VALUES),
                    Object.parent_naif_id == _EARTH_NAIF_ID,
                )
            )
            _is_constellation = or_(
                *(Object.name.startswith(p) for p in CONSTELLATION_PREFIXES)
            )
            non_sbdb = [
                (
                    "major",
                    0,
                    session.query(Object)
                    .options(joinedload(Object.sbdb))
                    .filter(Object.object_type.in_(_SUN_MAJOR_TYPE_VALUES)),
                ),
                (
                    "moons",
                    0,
                    session.query(Object).filter(
                        Object.sbdb_spkid.is_(None),
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
                        Object.sbdb_spkid.is_(None),
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
                )
                futures[f] = (zone, zoom, len(objects))
            # executor joins here — session still open so ORM objects remain valid

        write_system_metadata(session, out_dir, orientation, radii)

    for f in as_completed(futures):
        zone, zoom, count = futures[f]
        num_parts, nbytes = f.result()
        object_counts[(zone, zoom)] += count
        total_bytes_map[(zone, zoom)] += nbytes
        zone_structure[zone][zoom] = num_parts
        logger.info("  %s zoom=%d: %d objects, %d parts", zone, zoom, count, num_parts)

    # --- Other outputs ---
    write_messages(wikidata_entities, units.used_units)

    metadata = _build_metadata(zone_structure, object_counts, total_bytes_map)
    (out_dir / "metadata.json").write_bytes(
        orjson.dumps(metadata, option=orjson.OPT_INDENT_2)
    )

    total = sum(object_counts.values())
    elapsed = time.monotonic() - t0
    logger.info("Export complete: %d objects to %s in %.1fs", total, out_dir, elapsed)
