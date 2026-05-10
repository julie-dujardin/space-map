"""Write the global per-language label files used for pre-interaction labels.

One ``/v1/labels/{lang}.gz`` is emitted per supported language, listing only
*promoted* bodies — those rendered as individual meshes with labels on first
paint (planets, dwarf planets, moons, stars, barycenters, Lagrange points,
plus the curated extras in :mod:`space_map_data.constants.promoted`).

Format: gzipped UTF-8, one ``{id}\\x1f{name}\\x1f{flags}`` line per object.
``flags`` is a single-character set; currently the only flag is ``m`` for
*minor* (rendered as a collapsed halo by default, expands on hover) — set
for moons whose label fell back to the provisional designation. The frontend
fetches one file at app start (or on locale change) and uses its keys as the
authoritative promoted set.

Replaces the old per-chunk ``{part}.loc.{lang}.gz`` layout, which scaled with
chunks × languages × time-snapshots and was wasted bytes on the (vast
majority) of objects that never get a pre-interaction label.
"""

import gzip
import logging
from pathlib import Path

from space_map_data.constants.promoted import PROMOTED_EXTRA_IDS, PROMOTED_TYPES
from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.objects.writer import ChunkObjectData
from space_map_data.models.object import ObjectType

logger = logging.getLogger(__name__)

_US = "\x1f"  # ASCII Unit Separator — delimiter between fields


def _is_promoted(obj_id: str, global_data: dict, cheb_covered_ids: set[str]) -> bool:
    return (
        global_data.get("type") in PROMOTED_TYPES
        or obj_id in PROMOTED_EXTRA_IDS
        or obj_id in cheb_covered_ids
    )


def _resolve_label(loc: dict | None, glob: dict) -> tuple[str, str]:
    """Return ``(name, flags)`` for one (object, lang) pair.

    Name precedence: localized Wikidata label → DB ``name`` → provisional
    designation → empty string. Flags is ``"m"`` when the chosen name is a
    moon's provisional designation (no real name in either Wikidata or the
    DB), otherwise empty — the frontend renders flagged labels as collapsed
    halos that expand on hover, so e.g. Saturn's ``naif-65289``/``S2020 S48``
    doesn't crowd the inner Saturn system at first paint.
    """
    loc_name = loc.get("name") if loc else None
    db_name = glob.get("name")
    designation = glob.get("provisional_designation")
    name = loc_name or db_name or designation or ""
    is_minor_moon = (
        glob.get("type") == ObjectType.moon
        and not loc_name
        and (not db_name or db_name == designation)
        and bool(designation)
    )
    return name, "m" if is_minor_moon else ""


def write_global_labels(
    out_dir: Path,
    all_objects: ChunkObjectData,
    cheb_covered_ids: set[str],
) -> None:
    """Write ``/v1/labels/{lang}.gz`` for every supported language.

    Bodies with chebyshev coverage are auto-promoted regardless of type:
    they're rendered as individual meshes by virtue of their precise
    ephemerides, so they always belong in the labels set (catches the DE441
    perturber asteroids that aren't in :data:`PROMOTED_EXTRA_IDS`).
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
        if _is_promoted(obj_id, glob, cheb_covered_ids)
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
            name, flags = _resolve_label(loc, glob)
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
