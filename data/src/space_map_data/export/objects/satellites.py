"""Earth's featured satellites, attached to its object bundle.

Earth's artificial satellites aren't moons, so they ride a parallel field:
``notable_satellites`` (a curated MVP pick — ISS, Hubble, Starlink), plus the
total tracked-object count and the slug of the Satellites browse page the
strip's "+N more" tile links to. ISS/Hubble are object rows; Starlink is a
constellation group, so its entry carries a ``group`` slug instead of an ``id``.
"""

import logging

from sqlalchemy import func
from sqlalchemy.orm import Session

from space_map_data.constants.categories import SATELLITES_SLUG
from space_map_data.constants.earth_sats.constellations import CONSTELLATIONS
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
from space_map_data.export.objects.writer import ChunkObjectData
from space_map_data.export.wikidata import WikidataEntity, WikidataEntityCache
from space_map_data.models.object.main import Object, ObjectType

logger = logging.getLogger(__name__)

# Tracked objects parented to Earth that count toward the "+N more" tile.
_SAT_TYPES = (ObjectType.spacecraft, ObjectType.debris)
_CONSTELLATION_QID = {c.slug: c.wikidata_qid for c in CONSTELLATIONS}


def _en_name(entity: WikidataEntity | None, fallback: str) -> str:
    """English Wikidata label, else the DB/slug fallback."""
    return (entity["labels"].get("en") if entity else None) or fallback


def _localized(
    entity: WikidataEntity | None,
    en_name: str,
    out: dict[str, dict[str, str]],
    key: str,
) -> None:
    """Record per-language label overrides (keyed by id/slug) where they differ."""
    if entity is None:
        return
    for lang in LANGUAGES:
        label = entity["labels"].get(lang)
        if label and label != en_name:
            out[lang][key] = label


def attach_featured_satellites(
    session: Session,
    chunk: ChunkObjectData,
    wikidata_entities: WikidataEntityCache,
) -> None:
    """Inject ``notable_satellites`` + ``satellite_count`` + ``satellites_group``
    into Earth's global bundle (and localized name overrides).

    Mutates ``chunk`` in place (mirrors ``attach_notable_moons``).
    """
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
            row = (
                session.query(Object.wikidata_qid, Object.name)
                .filter(Object.id == feat.object_id)
                .first()
            )
            if row is None:
                logger.warning(
                    "Featured satellite %s not found; skipping", feat.object_id
                )
                continue
            qid, fallback = row
            entity = wikidata_entities.get_entity(qid)
            name = _en_name(entity, fallback)
            entry = {"name": name, "id": feat.object_id}
            thumbnail = pick_thumbnail(collect_object_images(feat.object_id))
            if thumbnail:
                entry["thumbnail"] = thumbnail
            _localized(entity, name, names, feat.object_id)
        else:
            slug = feat.constellation_slug
            assert slug is not None
            entity = wikidata_entities.get_referenced(_CONSTELLATION_QID.get(slug))
            name = _en_name(entity, slug)
            entry = {"name": name, "group": slug}
            thumbnail = pick_thumbnail(collect_group_images(slug))
            if thumbnail:
                entry["thumbnail"] = thumbnail
            _localized(entity, name, names, slug)
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
