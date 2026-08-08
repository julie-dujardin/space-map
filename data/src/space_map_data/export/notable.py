"""Shared notable-object selection for the strip/list detail UI.

Used by small-body group bundles (notable members) and object bundles
(notable moons). A ranked list of objects becomes denormalized records
carrying name, routing id, optional diameter/discovery and a thumbnail, plus
a per-language label-override map keyed by the same routing id.
"""

from dataclasses import dataclass
from typing import NamedTuple

from sqlalchemy.orm import Session

from space_map_data.constants.orientation import ORIENTATION_SOURCE_PCK
from space_map_data.export.images import (
    collect_feature_images,
    collect_group_images,
    collect_object_images,
    pick_thumbnail,
)
from space_map_data.export.systems import displacement_block
from space_map_data.export.objects.wikidata_claims import radius_km_from_claims
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.models.object.main import Object


@dataclass
class NotableObject:
    """One statically-picked notable member: an object, a moon, a group, or a
    surface feature.

    A group member (e.g. a constellation listed in its orbit zone) sets
    ``group_slug`` and routes to ``/g/<slug>`` instead of focusing an object —
    ``object_id`` is empty for it. A feature member (on a ``ft-`` page) sets
    ``feature_id`` and keeps its host body in ``object_id``, routing to
    ``/b/<body>/f/<feature_id>``. ``wikidata_qid`` still drives localized labels.
    """

    object_id: str  # full Object.id — both the routing/focus id and image-cache key
    wikidata_qid: str | None  # for localized labels at bundle-write time
    fallback_name: str  # used when no Wikidata label exists
    diameter_km: float | None
    first_obs: str | None  # discovery proxy, YYYY-MM-DD or YYYY
    group_slug: str | None = None  # set → a group member, routes to /g/<slug>
    feature_id: int | None = None  # set → a surface feature on `object_id`
    sitelinks_count: int | None = None  # Wikidata prominence, for cross-member ranking
    mass_kg: float | None = None  # from PCK GM; major bodies only
    radii: dict | None = None  # triaxial PCK radii {a, b, c} km; major bodies only
    radius_km: float | None = (
        None  # scalar render radius (Wikidata P2120) when no radii/diameter
    )
    pole: dict | None = None  # IAU J2000 pole {ra, dec} deg, for the lineup's true tilt
    albedo: float | None = None  # SBDB geometric albedo; small bodies only
    spec: str | None = (
        None  # SBDB taxonomic type (SMASS, else Tholen); small bodies only
    )
    color: str | None = None  # physically-derived #rrggbb surface tint; small bodies
    # Mass of the body's *rings*, not the body: the Ring Systems page charts its
    # members against each other. Same shape as the object bundle's `ring_stats.mass`.
    ring_mass: dict | None = None
    # The one figure each Structure & Activity page ranks its members by, in the
    # same shape the body's own panel carries it. Set only on that page's members:
    # every collection here is bodies-with-a-property, and the property is the chart.
    ocean: dict | None = None  # cat-oceans; `interior.ocean_block`
    atmosphere_pressure: dict | None = (
        None  # cat-atmospheres; `atmosphere.pressure_block`
    )
    # What the member's own tile draws instead of a photograph: the body cut
    # open, or its air seen edge-on. Trimmed to what a 60 px drawing uses —
    # `interior.cutaway_layers` and `atmosphere.limb_profile`.
    cutaway: list[dict] | None = None
    limb: dict | None = None


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


def pole_from_orientation(
    orientation: dict[int, dict], naif_id: int | None
) -> dict | None:
    """The body's IAU J2000 pole {ra, dec} (deg), if known.

    Gives the lineup hero its true axial tilt. The orientation table is a merge
    of three sets (see ``load_orientation``), so the pole carries the ``source``
    of whichever published it — a small-body lineup tilts its members on DAMIT
    poles and must not credit them to the PCK.
    """
    if naif_id is None or naif_id not in orientation:
        return None
    o = orientation[naif_id]
    pole = {"ra": o["pole_ra_0"], "dec": o["pole_dec_0"]}
    if o.get("source") and o["source"] != ORIENTATION_SOURCE_PCK:
        pole["source"] = o["source"]
    return pole


class RenderGeometry(NamedTuple):
    """A body's lineup render geometry: triaxial radii, scalar-radius fallback, pole."""

    radii: dict | None
    radius_km: float | None
    pole: dict | None


def render_geometry(
    naif_id: int | None,
    qid: str | None,
    radii: dict[int, dict],
    units: UnitConverter | None = None,
    wikidata_entities: WikidataEntityCache | None = None,
    orientation: dict[int, dict] | None = None,
) -> RenderGeometry:
    """The lineup render geometry for a body — size + tilt — as one bundle.

    The single source every member builder uses, so a body sizes *and* tilts
    identically wherever it appears (e.g. Pluto on the dwarf-planet page and in
    its trans-Neptunian orbit-class zone). ``units``/``wikidata_entities`` enable
    the Wikidata-radius fallback; ``orientation`` enables the pole — omit either
    to skip that source.
    """
    triaxial, radius_km = render_size(naif_id, qid, radii, units, wikidata_entities)
    return RenderGeometry(
        triaxial, radius_km, pole_from_orientation(orientation or {}, naif_id)
    )


def _member_entity(member: NotableObject, wikidata_entities: WikidataEntityCache):
    """The member's Wikidata entity. Group members (constellations) are only
    referenced from claims, not downloaded as own entities; feature entities
    live in their own nomenclature store."""
    if member.group_slug is not None:
        return wikidata_entities.get_referenced(member.wikidata_qid)
    if member.feature_id is not None:
        return wikidata_entities.get_feature_entity(member.wikidata_qid)
    return wikidata_entities.get_entity(member.wikidata_qid)


def _member_key(member: NotableObject) -> str:
    """The routing id the frontend keys label/description overrides by
    (``member.group ?? feature key ?? member.id``)."""
    if member.group_slug is not None:
        return member.group_slug
    if member.feature_id is not None:
        return feature_member_key(member.object_id, member.feature_id)
    return member.object_id


def feature_member_key(object_id: str, feature_id: int) -> str:
    """Routing key for a feature member; mirrored by the frontend member list."""
    return f"{object_id}:{feature_id}"


def textured_object_ids(session: Session) -> set[str]:
    """Ids of objects with an exported surface texture, for the lineup's
    ``texture`` flag — spares the frontend a speculative (often-404) fetch."""
    return {
        row[0] for row in session.query(Object.id).filter(Object.map_texture_available)
    }


# An object can have bundles from several provenances (e.g. Eros: mission +
# DAMIT); in-situ beats radar beats convex lightcurve.
_PROVENANCE_RANK = {"missions": 0, "radar": 1, "lightcurve": 2}


def shape_model_slugs(model_metadata: dict[str, dict]) -> dict[str, str]:
    """Best shape-model bundle slug per object id.

    Spacecraft bundles share ``model_metadata`` but must not leak into body
    lineups, so gate on ``kind == "shape_model"``. Equal-provenance ties break
    to the newest DAMIT model, matching the ingest's preferred-model policy.
    """
    best: dict[str, tuple] = {}
    for slug, meta in model_metadata.items():
        if meta.get("kind") != "shape_model" or not meta.get("object_id"):
            continue
        rank = (
            _PROVENANCE_RANK.get(meta.get("provenance", ""), 3),
            -(meta.get("damit_model_id") or 0),
        )
        cur = best.get(meta["object_id"])
        if cur is None or rank < cur[0]:
            best[meta["object_id"]] = (rank, slug)
    return {oid: slug for oid, (_, slug) in best.items()}


def notable_entries(
    members: list[NotableObject],
    wikidata_entities: WikidataEntityCache,
    displacement_metadata: dict[str, dict] | None = None,
    model_slugs: dict[str, str] | None = None,
    textured_ids: set[str] | None = None,
) -> list[dict]:
    """Denormalized records for a global bundle.

    Name is the English Wikidata label when available (matching the object
    bundles' global name), else the DB fallback. Thumbnail reuses the
    search-card picker over the object's export images. ``displacement_metadata``
    (when supplied) lets a member carry its DEM block so the lineup renders the
    same relief as the main map. ``model_slugs`` ({object_id: slug}, shape-model
    only) lets a member load its shape mesh instead of a sphere. ``textured_ids``
    (when supplied) stamps ``texture`` true/false on every object entry —
    explicit false (not omission) so the frontend can tell "no texture" from a
    pre-flag bundle it should still probe.
    """
    out: list[dict] = []
    for member in members:
        wd = _member_entity(member, wikidata_entities)
        name = (wd["labels"].get("en") if wd else None) or member.fallback_name
        # Group members route to /g/<slug>; object members focus their mesh.
        if member.group_slug is not None:
            entry: dict = {"name": name, "group": member.group_slug}
            thumbnail = pick_thumbnail(collect_group_images(member.group_slug))
            if thumbnail:
                entry["thumbnail"] = thumbnail
            out.append(entry)
            continue
        # Feature members carry their host body in `id` and route to its
        # feature URL; none of the render fields below apply to them.
        if member.feature_id is not None:
            entry = {
                "name": name,
                "id": member.object_id,
                "feature_id": member.feature_id,
            }
            if member.diameter_km is not None:
                entry["diameter_km"] = member.diameter_km
            if member.first_obs:
                entry["first_obs"] = member.first_obs
            thumbnail = pick_thumbnail(collect_feature_images(member.feature_id))
            if thumbnail:
                entry["thumbnail"] = thumbnail
            out.append(entry)
            continue
        entry = {"name": name, "id": member.object_id}
        if member.diameter_km is not None:
            entry["diameter_km"] = member.diameter_km
        if member.mass_kg is not None:
            entry["mass_kg"] = member.mass_kg
        if member.radii is not None:
            entry["radii"] = member.radii
        if member.radius_km is not None:
            entry["radius_km"] = member.radius_km
        if member.pole is not None:
            entry["pole"] = member.pole
        if member.albedo is not None:
            entry["albedo"] = member.albedo
        if member.spec is not None:
            entry["spec"] = member.spec
        if member.color is not None:
            entry["color"] = member.color
        if member.ring_mass is not None:
            entry["ring_mass"] = member.ring_mass
        if member.ocean is not None:
            entry["ocean"] = member.ocean
        if member.atmosphere_pressure is not None:
            entry["atmosphere_pressure"] = member.atmosphere_pressure
        if member.cutaway is not None:
            entry["cutaway"] = member.cutaway
        if member.limb is not None:
            entry["limb"] = member.limb
        if member.first_obs:
            entry["first_obs"] = member.first_obs
        if displacement_metadata and (
            disp := displacement_metadata.get(member.object_id)
        ):
            entry["displacement"] = displacement_block(disp)
        if model_slugs and (slug := model_slugs.get(member.object_id)):
            entry["model"] = slug
        if textured_ids is not None:
            entry["texture"] = member.object_id in textured_ids
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
        wd = _member_entity(member, wikidata_entities)
        if not wd:
            continue
        label = wd["labels"].get(lang)
        if label and label != entry["name"]:
            out[_member_key(member)] = label
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
        wd = _member_entity(member, wikidata_entities)
        if not wd:
            continue
        desc = wd["descriptions"].get(lang)
        if desc:
            out[_member_key(member)] = desc
    return out
