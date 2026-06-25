"""Shared notable-object selection for the strip/list detail UI.

Used by small-body group bundles (notable members) and object bundles
(notable moons). A ranked list of objects becomes denormalized records
carrying name, routing id, optional diameter/discovery and a thumbnail, plus
a per-language label-override map keyed by the same routing id.
"""

from dataclasses import dataclass

from space_map_data.export.images import collect_object_images, pick_thumbnail
from space_map_data.export.wikidata import WikidataEntityCache


@dataclass
class NotableObject:
    """One statically-picked notable object (a group member or a moon)."""

    object_id: str  # full Object.id — both the routing/focus id and image-cache key
    wikidata_qid: str | None  # for localized labels at bundle-write time
    fallback_name: str  # used when no Wikidata label exists
    diameter_km: float | None
    first_obs: str | None  # discovery proxy, YYYY-MM-DD or YYYY
    mass_kg: float | None = None  # from PCK GM; major bodies only
    radii: dict | None = None  # triaxial PCK radii {a, b, c} km; major bodies only


def notable_entries(
    members: list[NotableObject],
    wikidata_entities: WikidataEntityCache,
) -> list[dict]:
    """Denormalized records for a global bundle.

    Name is the English Wikidata label when available (matching the object
    bundles' global name), else the DB fallback. Thumbnail reuses the
    search-card picker over the object's export images.
    """
    out: list[dict] = []
    for member in members:
        wd = wikidata_entities.get_entity(member.wikidata_qid)
        name = (wd["labels"].get("en") if wd else None) or member.fallback_name
        entry: dict = {"name": name, "id": member.object_id}
        if member.diameter_km is not None:
            entry["diameter_km"] = member.diameter_km
        if member.mass_kg is not None:
            entry["mass_kg"] = member.mass_kg
        if member.radii is not None:
            entry["radii"] = member.radii
        if member.first_obs:
            entry["first_obs"] = member.first_obs
        thumbnail = pick_thumbnail(collect_object_images(member.object_id))
        if thumbnail:
            entry["thumbnail"] = thumbnail
        out.append(entry)
    return out


def notable_names(
    members: list[NotableObject],
    entries: list[dict],
    lang: str,
    wikidata_entities: WikidataEntityCache,
) -> dict[str, str]:
    """Per-language label overrides keyed by object id, only where they differ."""
    out: dict[str, str] = {}
    for member, entry in zip(members, entries):
        wd = wikidata_entities.get_entity(member.wikidata_qid)
        if not wd:
            continue
        label = wd["labels"].get(lang)
        if label and label != entry["name"]:
            out[member.object_id] = label
    return out
