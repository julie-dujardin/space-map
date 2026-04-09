"""Map NASA Science URLs from display names to object PKs.

Reads  name-to-url.json  (hand-curated, keyed by display name)
Writes pk-to-url.json    (keyed by Object.id, usable by the export pipeline)
"""

import json
import logging
import re

from space_map_data.models.object.main import Object, ObjectType
from space_map_data.utils.db import get_session
from space_map_data.utils.paths import DOWNLOAD_DIR

logger = logging.getLogger(__name__)

NASA_SCIENCE_DIR = DOWNLOAD_DIR / "nasa-science-urls"
INPUT_FILE = NASA_SCIENCE_DIR / "name-to-url.json"
OUTPUT_FILE = NASA_SCIENCE_DIR / "pk-to-url.json"

# JSON category → ObjectType values to restrict matches
CATEGORY_TYPES: dict[str, list[ObjectType]] = {
    "sun": [ObjectType.star],
    "planets": [ObjectType.planet],
    "dwarf_planets": [ObjectType.dwarf_planet],
    "moons": [ObjectType.moon],
    "small_bodies": [
        ObjectType.asteroid,
        ObjectType.asteroid_inner,
        ObjectType.asteroid_main_belt,
        ObjectType.asteroid_trojan,
        ObjectType.asteroid_centaur,
        ObjectType.asteroid_tno,
        ObjectType.comet,
    ],
}


def _strip_compound(name: str) -> str | None:
    """'Didymos and Dimorphos' → 'Didymos', '243 Ida and Dactyl' → '243 Ida'."""
    if " and " in name:
        return name.split(" and ")[0]
    return None


def _strip_comet_parenthetical(name: str) -> str | None:
    """'103P/Hartley (Hartley 2)' → '103P/Hartley'."""
    m = re.match(r"^(\d+\w?/[^\s(]+)", name)
    return m.group(1) if m else None


def _resolve_name(
    session, name: str, types: list[ObjectType]
) -> tuple[str, str] | None:
    """Try to find a unique object matching *name* within *types*.

    Returns (object_id, matched_db_name) or None.
    """
    type_strs = [t.value for t in types]

    # 1. Exact match on Object.name
    rows = (
        session.query(Object.id, Object.name)
        .filter(Object.name == name, Object.object_type.in_(type_strs))
        .all()
    )
    if len(rows) == 1:
        return rows[0]

    # 2. Compound names — try first part ("Didymos and Dimorphos" → "Didymos")
    first_part = _strip_compound(name)
    if first_part:
        rows = (
            session.query(Object.id, Object.name)
            .filter(Object.name.endswith(first_part), Object.object_type.in_(type_strs))
            .all()
        )
        if len(rows) == 1:
            return rows[0]

    # 3. Suffix match — "Apophis" → "99942 Apophis"
    rows = (
        session.query(Object.id, Object.name)
        .filter(Object.name.endswith(f" {name}"), Object.object_type.in_(type_strs))
        .all()
    )
    if len(rows) == 1:
        return rows[0]

    # 4. Comet designation prefix — "103P/Hartley (Hartley 2)" → match "103P/Hartley 2"
    prefix = _strip_comet_parenthetical(name)
    if prefix:
        rows = (
            session.query(Object.id, Object.name)
            .filter(Object.name.startswith(prefix), Object.object_type.in_(type_strs))
            .all()
        )
        if len(rows) == 1:
            return rows[0]

    # 5. Parenthetical content match — "Shoemaker-Levy 9" → "(Shoemaker-Levy 9)"
    rows = (
        session.query(Object.id, Object.name)
        .filter(
            Object.name.contains(f"({name})"),
            Object.object_type.in_(type_strs),
        )
        .all()
    )
    if len(rows) == 1:
        return rows[0]

    # 6. Interstellar objects — strip leading chars: "1I/'Oumuamua" → "'Oumuamua"
    m = re.match(r"^\d+I/(.+)", name)
    if m:
        suffix = m.group(1)
        rows = (
            session.query(Object.id, Object.name)
            .filter(
                Object.name.contains(suffix),
                Object.object_type.in_(type_strs),
            )
            .all()
        )
        if len(rows) == 1:
            return rows[0]

    return None


def build_pk_to_url() -> None:
    """Read name-to-url.json and write pk-to-url.json with Object.id keys."""
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Input file not found: {INPUT_FILE}")

    name_to_url: dict[str, dict[str, str]] = json.loads(INPUT_FILE.read_text())
    session = get_session()

    pk_to_url: dict[str, str] = {}
    unmatched: list[str] = []

    for category, entries in name_to_url.items():
        types = CATEGORY_TYPES.get(category)
        if types is None:
            logger.warning("Unknown category %r — skipping", category)
            continue

        for display_name, url in entries.items():
            result = _resolve_name(session, display_name, types)
            if result:
                obj_id, db_name = result
                pk_to_url[obj_id] = url
                logger.debug("  %s → %s (%s)", display_name, obj_id, db_name)
            else:
                unmatched.append(display_name)
                logger.warning("No match for %r in %s", display_name, category)

    OUTPUT_FILE.write_text(json.dumps(pk_to_url, indent=2, ensure_ascii=False) + "\n")
    logger.info(
        "Wrote %d URLs to %s (%d unmatched)",
        len(pk_to_url),
        OUTPUT_FILE.name,
        len(unmatched),
    )
