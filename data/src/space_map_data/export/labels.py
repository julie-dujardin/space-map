"""Write the global per-language label files used for pre-interaction labels.

One ``/v1/labels/{lang}.gz`` is emitted per supported language, listing only
*promoted* bodies — those rendered as individual meshes with labels on first
paint (planets, dwarf planets, moons, stars, barycenters, Lagrange points,
plus the curated extras in :mod:`space_map_data.constants.promoted`).

Format: gzipped UTF-8, one ``{id}\\x1f{name}`` line per object. The frontend
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

logger = logging.getLogger(__name__)

_US = "\x1f"  # ASCII Unit Separator — delimiter between id and name


def _is_promoted(obj_id: str, global_data: dict) -> bool:
    return global_data.get("type") in PROMOTED_TYPES or obj_id in PROMOTED_EXTRA_IDS


def write_global_labels(out_dir: Path, all_objects: ChunkObjectData) -> None:
    """Write ``/v1/labels/{lang}.gz`` for every supported language.

    Name fallback per (object, lang): localized Wikidata label (already with
    its own lang→en fallback inside ``_build_localized``) → object's global
    ``name`` (``obj.name`` from the DB). When neither exists the line ships
    just ``{id}{US}`` and the frontend falls back to the id.
    """
    promoted_ids = sorted(
        obj_id
        for obj_id, glob in all_objects.global_data.items()
        if _is_promoted(obj_id, glob)
    )

    labels_dir = out_dir / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)

    for lang in LANGUAGES:
        lang_data = all_objects.localized_data.get(lang, {})
        lines = []
        named = 0
        for obj_id in promoted_ids:
            loc = lang_data.get(obj_id)
            glob = all_objects.global_data.get(obj_id, {})
            name = (loc and loc.get("name")) or glob.get("name") or ""
            if name:
                named += 1
            lines.append(f"{obj_id}{_US}{name}")
        out_file = labels_dir / f"{lang}.gz"
        out_file.write_bytes(gzip.compress("\n".join(lines).encode()))
        logger.info("Wrote %d/%d labels to %s", named, len(promoted_ids), out_file)
