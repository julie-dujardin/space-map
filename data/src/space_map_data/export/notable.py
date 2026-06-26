"""Shared notable-object selection for the strip/list detail UI.

Used by small-body group bundles (notable members) and object bundles
(notable moons). A ranked list of objects becomes denormalized records
carrying name, routing id, optional diameter/discovery and a thumbnail, plus
a per-language label-override map keyed by the same routing id.
"""

from dataclasses import dataclass

from space_map_data.export.images import collect_object_images, pick_thumbnail
from space_map_data.export.objects.wikidata_claims import radius_km_from_claims
from space_map_data.export.quantities import UnitConverter
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
    radius_km: float | None = (
        None  # scalar render radius (Wikidata P2120) when no radii/diameter
    )
    albedo: float | None = None  # SBDB geometric albedo; small bodies only
    spec: str | None = (
        None  # SBDB taxonomic type (SMASS, else Tholen); small bodies only
    )


def render_size(
    naif_id: int | None,
    qid: str | None,
    radii: dict[int, dict],
    units: UnitConverter | None,
    wikidata_entities: WikidataEntityCache | None,
) -> tuple[dict | None, float | None]:
    """The body's render size for the lineup, mirroring the position pipeline.

    Returns ``(triaxial_radii, scalar_radius_km)``. PCK triaxial radii (the
    chebyshev render shape) take precedence; otherwise the Wikidata radius
    (P2120) is the elements-pipeline override used for bodies with no SBDB
    diameter (most trans-Neptunian dwarfs). SBDB diameter is carried separately.
    ``units``/``wikidata_entities`` may be ``None`` (skips the Wikidata path).
    """
    if naif_id is not None and (pck := radii.get(naif_id)) is not None:
        return pck, None
    if units is not None and wikidata_entities is not None and qid is not None:
        wd = wikidata_entities.get_entity(qid)
        if wd is not None and (r := radius_km_from_claims(wd["claims"], units, qid)):
            return None, r
    return None, None


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
        if member.radius_km is not None:
            entry["radius_km"] = member.radius_km
        if member.albedo is not None:
            entry["albedo"] = member.albedo
        if member.spec is not None:
            entry["spec"] = member.spec
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


def notable_descriptions(
    members: list[NotableObject],
    lang: str,
    wikidata_entities: WikidataEntityCache,
) -> dict[str, str]:
    """Per-language Wikidata short descriptions keyed by object id, for the
    lineup hero's hover tooltip (e.g. "moon of Jupiter")."""
    out: dict[str, str] = {}
    for member in members:
        wd = wikidata_entities.get_entity(member.wikidata_qid)
        if not wd:
            continue
        desc = wd["descriptions"].get(lang)
        if desc:
            out[member.object_id] = desc
    return out
