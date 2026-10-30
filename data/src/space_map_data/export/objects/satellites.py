"""Earth's featured satellites, attached to its object bundle.

Artificial satellites aren't moons, so they ride a parallel field:
``notable_satellites`` (curated pick), tracked-object count, and the
Satellites page slug for the "+N more" tile. Starlink is a constellation
group, carrying a ``group`` slug instead of an ``id``.
"""

import logging

from sqlalchemy import func
from sqlalchemy.orm import Session

from space_map_data.constants.categories import SATELLITES_SLUG
from space_map_data.constants.earth_sats.constellations import (
    CONSTELLATION_SLUG_PREFIX,
    CONSTELLATIONS,
)
from space_map_data.constants.earth_sats.featured import (
    EARTH_ID,
    FEATURED_EARTH_SATELLITES,
)
from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.images import (
    collect_group_images,
    collect_object_images,
    pick_thumbnail,
)
from space_map_data.export.names import Names, ObjectNames, entity_names
from space_map_data.export.objects.writer import ChunkObjectData
from space_map_data.models.object.main import Object, ObjectType

logger = logging.getLogger(__name__)

# Tracked objects parented to Earth that count toward the "+N more" tile. Debris
# is excluded: the tile opens the Satellites page, which doesn't list it.
_SAT_TYPES = (ObjectType.spacecraft,)
_CONSTELLATION_QID = {c.slug: c.wikidata_qid for c in CONSTELLATIONS}


def _localized(found: Names, out: dict[str, dict[str, str]], key: str) -> None:
    """Record the names (keyed by id/slug) that differ from the global one."""
    for lang, name in found.overrides().items():
        out[lang][key] = name


def attach_featured_satellites(
    session: Session,
    chunk: ChunkObjectData,
    object_names: ObjectNames,
) -> None:
    """Inject ``notable_satellites`` + ``satellite_count`` + ``satellites_group``
    into Earth's global bundle (and localized name overrides), mutating
    ``chunk`` in place."""
    global_data = chunk.global_data.get(EARTH_ID)
    if global_data is None:
        logger.warning("Earth (%s) has no object bundle; skipping satellites", EARTH_ID)
        return

    total = (
        session.query(func.count(Object.id))
        .filter(Object.parent_id == EARTH_ID, Object.object_type.in_(_SAT_TYPES))
        .scalar()
        or 0
    )

    entries: list[dict] = []
    names: dict[str, dict[str, str]] = {lang: {} for lang in LANGUAGES}
    for feat in FEATURED_EARTH_SATELLITES:
        entry: dict
        if feat.object_id is not None:
            found = object_names.find(feat.object_id)
            if found is None:
                logger.warning(
                    "Featured satellite %s not found; skipping", feat.object_id
                )
                continue
            entry = {"name": found.name, "id": feat.object_id}
            thumbnail = pick_thumbnail(collect_object_images(feat.object_id))
            if thumbnail:
                entry["thumbnail"] = thumbnail
            _localized(found, names, feat.object_id)
        else:
            slug = feat.constellation_slug
            assert slug is not None
            group_slug = f"{CONSTELLATION_SLUG_PREFIX}{slug}"
            found = entity_names(
                object_names.entities.get_referenced(_CONSTELLATION_QID.get(slug)),
                slug,
            )
            entry = {"name": found.name, "group": group_slug}
            thumbnail = pick_thumbnail(collect_group_images(group_slug))
            if thumbnail:
                entry["thumbnail"] = thumbnail
            _localized(found, names, group_slug)
        entries.append(entry)

    if not entries:
        logger.warning(
            "No featured satellites resolved for Earth; leaving bundle as-is"
        )
        return

    global_data["notable_satellites"] = entries
    global_data["satellite_count"] = total
    global_data["satellites_group"] = SATELLITES_SLUG
    for lang in LANGUAGES:
        if not names[lang]:
            continue
        localized = chunk.localized_data.get(lang, {}).get(EARTH_ID)
        if localized is not None:
            localized["notable_satellite_names"] = names[lang]
    logger.info(
        "Attached %d featured satellites to Earth (total tracked=%d)",
        len(entries),
        total,
    )
