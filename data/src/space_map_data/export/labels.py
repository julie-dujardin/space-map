"""Write the global per-language label files used for pre-interaction labels.

One ``/v1/labels/{lang}.gz`` is emitted per supported language, listing only
*promoted* bodies — those rendered as individual meshes with labels on first
paint (planets, dwarf planets, moons, stars, barycenters, Lagrange points,
curated extras, and every high-accuracy probe).

Format: gzipped UTF-8, one ``{id}\\x1f{name}\\x1f{flags}`` line per object.
The only flag is ``m`` for *minor* (collapsed halo, expands on hover), set
for moons with no real name and for probes outside the curated flagship
list. The frontend fetches one file at app start and uses its keys as the
authoritative promoted set.
"""

import gzip
import logging
from pathlib import Path

from space_map_data.constants.promoted import PROMOTED_EXTRA_IDS, PROMOTED_TYPES
from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.objects.writer import ChunkObjectData
from space_map_data.models.object import ObjectType
from space_map_data.utils.designations import format_provisional_designation

logger = logging.getLogger(__name__)

_US = "\x1f"  # ASCII Unit Separator — delimiter between fields


def _is_promoted(
    obj_id: str,
    global_data: dict,
    cheb_covered_ids: set[str],
    probe_ids: set[str],
    rendered_ids: set[str],
) -> bool:
    """A body is promoted if it'd be rendered as an individual mesh on first
    paint. Type/curated/cheb/probe membership is the *intent* check;
    ``rendered_ids`` is the *capability* check — a body absent from every
    position file can't render in 3D, and promoting it anyway would make the
    renderer retry an unfindable ``getBody`` every frame.
    """
    if obj_id not in rendered_ids and obj_id not in cheb_covered_ids:
        return False
    return (
        global_data.get("type") in PROMOTED_TYPES
        or obj_id in PROMOTED_EXTRA_IDS
        or obj_id in cheb_covered_ids
        or obj_id in probe_ids
    )


def _resolve_label(
    obj_id: str, loc: dict | None, glob: dict, probe_ids: set[str]
) -> tuple[str, str]:
    """Return ``(name, flags)`` for one (object, lang) pair.

    Name precedence: localized Wikidata label → DB ``name`` → provisional
    designation → empty string. Flags is ``"m"`` (collapsed halo) when the
    name is a moon's provisional designation, or the object is a non-
    flagship probe — keeps unnamed moons and minor probes from crowding
    the map at first paint.
    """
    loc_name = loc.get("name") if loc else None
    db_name = glob.get("name")
    raw_designation = glob.get("provisional_designation")
    designation = format_provisional_designation(raw_designation)
    # A DB name that is just the designation reads better in the IAU spelling.
    if db_name and db_name == raw_designation:
        db_name = designation
    name = loc_name or db_name or designation or ""
    is_minor_moon = (
        glob.get("type") == ObjectType.moon
        and not loc_name
        and (not db_name or db_name == designation)
        and bool(designation)
    )
    is_minor_probe = obj_id in probe_ids and obj_id not in PROMOTED_EXTRA_IDS
    return name, "m" if (is_minor_moon or is_minor_probe) else ""


def write_global_labels(
    out_dir: Path,
    all_objects: ChunkObjectData,
    cheb_covered_ids: set[str],
    probe_ids: set[str],
    rendered_ids: set[str],
) -> None:
    """Write ``/v1/labels/{lang}.gz`` for every supported language.

    Bodies with chebyshev coverage are auto-promoted regardless of type,
    since precise ephemerides mean they render as individual meshes anyway
    (catches DE441 perturber asteroids outside :data:`PROMOTED_EXTRA_IDS`).
    Every probe in ``probe_ids`` is likewise promoted, carrying the ``m``
    flag unless it's a curated flagship.

    ``rendered_ids`` excludes bodies present only in object bundles (e.g.
    orbit-less SBDB satellites) — promoting those would make the frontend
    retry an unfindable ``getBody`` every frame.
    """
    missing_extras = sorted(PROMOTED_EXTRA_IDS - all_objects.global_data.keys())
    if missing_extras:
        logger.warning(
            "PROMOTED_EXTRA_IDS not found in exported objects (typo or filtered out upstream): %s",
            missing_extras,
        )

    promoted_ids = sorted(
        obj_id
        for obj_id, glob in all_objects.global_data.items()
        if _is_promoted(obj_id, glob, cheb_covered_ids, probe_ids, rendered_ids)
    )

    labels_dir = out_dir / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)

    for lang in LANGUAGES:
        lang_data = all_objects.localized_data.get(lang, {})
        lines = []
        named = 0
        minor = 0
        for obj_id in promoted_ids:
            loc = lang_data.get(obj_id)
            glob = all_objects.global_data.get(obj_id, {})
            name, flags = _resolve_label(obj_id, loc, glob, probe_ids)
            if name:
                named += 1
            if flags:
                minor += 1
            lines.append(f"{obj_id}{_US}{name}{_US}{flags}")
        out_file = labels_dir / f"{lang}.gz"
        out_file.write_bytes(gzip.compress("\n".join(lines).encode()))
        logger.info(
            "Wrote %d/%d labels (%d minor) to %s",
            named,
            len(promoted_ids),
            minor,
            out_file,
        )
