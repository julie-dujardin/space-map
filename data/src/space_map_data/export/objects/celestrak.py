"""SATCAT metadata export helpers (exported under the "celestrak" JSON key)."""

from space_map_data.constants.earth_sats.constellations import (
    CONSTELLATION_BY_SLUG,
    CONSTELLATION_SLUG_PREFIX,
    STATION_CONSTELLATION_SLUGS,
)
from space_map_data.constants.earth_sats.launch_vehicles import (
    LAUNCH_VEHICLE_BY_CONSTELLATION,
    LAUNCH_VEHICLE_SLUG_PREFIX,
)
from space_map_data.constants.earth_sats.launch_sites import (
    LAUNCH_SITE_BY_CODE,
    LAUNCH_SITE_SLUG_PREFIX,
)
from space_map_data.constants.earth_sats.manufacturers import MANUFACTURER_BY_QID
from space_map_data.constants.earth_sats.operators import (
    OPERATOR_BY_QID,
    ActiveDate,
)
from space_map_data.constants.earth_sats.organizations import (
    ORGANIZATION_SLUG_PREFIX,
)
from space_map_data.constants.earth_sats.satellite_models import (
    BUS_BY_SLUG,
    BUS_SLUG_PREFIX,
)
from space_map_data.export.objects.wikidata_claims import EntityRef, resolve_entity_ref
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.models.object import Satcat


_GLOBAL_FIELDS = (
    "object_type",
    "ops_status",
    "data_status",
    "launch_date",
    "decay_date",
    "period",
    "apogee",
    "perigee",
    "rcs",
    "orbit_center",
    "orbit_center_docked_to",
    "launch_site_code",
    "owner",
    "constellation_slug",
    "bus_slug",
)


# GCAT's hardware figures, in the unit ladder the Wikidata claims already use
# so a page never quotes one mass in tonnes and the next in kilograms.
_SIZE_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("mass_kg", "mass", "mass"),
    ("dry_mass_kg", "mass", "dry_mass"),
    ("span_m", "length", "span"),
    ("length_m", "length", "length"),
    ("diameter_m", "length", "diameter"),
)


def build_satcat_global(sat: Satcat, units: UnitConverter) -> dict:
    """Non-localized SATCAT fields, omitting None/empty entries."""
    data: dict = {}
    for attr in _GLOBAL_FIELDS:
        val = getattr(sat, attr)
        if val is not None:
            data[attr] = val
    for attr, qty_type, key in _SIZE_FIELDS:
        val = getattr(sat, attr)
        if val is None:
            continue
        converted = units.best_unit(val, qty_type)
        if converted is not None:
            data[key] = converted
    # Only sent when true: an absent flag reads as "stated", which is the common
    # case and the one the client should not annotate.
    if sat.mass_estimated and "mass" in data:
        data["mass_estimated"] = True
    if sat.span_estimated and "span" in data:
        data["span_estimated"] = True
    if sat.categories:
        data["categories"] = sat.categories
    if sat.country_codes:
        data["country_codes"] = sat.country_codes
    return data


def build_satcat_localized(
    sat: Satcat,
    lang: str,
    wikidata_entities: WikidataEntityCache,
) -> dict:
    """Localized SATCAT refs (constellation, launch_site, operators)."""
    data: dict = {}

    if sat.constellation_slug is not None:
        ref = _constellation_group_ref(sat.constellation_slug, lang, wikidata_entities)
        if ref is not None:
            data["constellation"] = ref.to_dict()

    if sat.bus_slug is not None:
        ref = _bus_group_ref(sat.bus_slug, lang, wikidata_entities)
        if ref is not None:
            data["bus"] = ref.to_dict()

    if sat.launch_site_code is not None:
        site = LAUNCH_SITE_BY_CODE.get(sat.launch_site_code)
        if site is not None:
            site_group_slug = f"{LAUNCH_SITE_SLUG_PREFIX}{site.slug}"
            name = site.name
            if site.wikidata_qid is not None:
                ref = resolve_entity_ref(site.wikidata_qid, lang, wikidata_entities)
                if ref is not None and ref.name:
                    name = ref.name
            data["launch_site"] = [
                {
                    "name": name,
                    "primary_type": "group",
                    "primary_id": site_group_slug,
                }
            ]

    if sat.operator_qids:
        refs = resolve_operator_refs(sat.operator_qids, lang, wikidata_entities)
        if refs:
            data["operators"] = refs

    if sat.manufacturer_qids:
        mfr_refs = resolve_manufacturer_refs(
            sat.manufacturer_qids, lang, wikidata_entities
        )
        if mfr_refs:
            # Overrides the Wikidata P176 path (which has no /g/mfr-* link).
            data["manufacturer"] = mfr_refs

    return data


def _constellation_group_ref(
    slug: str,
    lang: str,
    wikidata_entities: WikidataEntityCache,
) -> EntityRef | None:
    """EntityRef for a constellation, pointing at /g/<slug> instead of Wikipedia.

    Falls back to the slug when no QID is registered, matching the group
    page's own fallback. ROCKET constellations resolve to their lv-
    launch-vehicle page instead (a spent stage's "constellation" is its vehicle).
    """
    if slug in STATION_CONSTELLATION_SLUGS:
        return None
    lv = LAUNCH_VEHICLE_BY_CONSTELLATION.get(slug)
    if lv is not None:
        group_slug = f"{LAUNCH_VEHICLE_SLUG_PREFIX}{lv.slug}"
        qid = lv.qid
        fallback = lv.name or slug
    else:
        spec = CONSTELLATION_BY_SLUG.get(slug)
        if spec is None:
            return None
        group_slug = f"{CONSTELLATION_SLUG_PREFIX}{slug}"
        qid = spec.wikidata_qid
        fallback = slug
    if qid is not None:
        ref = resolve_entity_ref(qid, lang, wikidata_entities)
        if ref is not None:
            ref.primary_type = "group"
            ref.primary_id = group_slug
            return ref
    return EntityRef(name=fallback, primary_type="group", primary_id=group_slug)


def _bus_group_ref(
    slug: str,
    lang: str,
    wikidata_entities: WikidataEntityCache,
) -> EntityRef | None:
    """EntityRef for a satellite bus, pointing at /g/bus-<slug>.

    Falls back to the curated name, matching the bus group page's own
    fallback — a third of these buses have no Wikidata label to resolve.
    """
    spec = BUS_BY_SLUG.get(slug)
    if spec is None:
        return None
    group_slug = f"{BUS_SLUG_PREFIX}{slug}"
    if spec.wikidata_qid is not None:
        ref = resolve_entity_ref(spec.wikidata_qid, lang, wikidata_entities)
        if ref is not None:
            ref.primary_type = "group"
            ref.primary_id = group_slug
            return ref
    name = spec.also_known_as[0] if spec.also_known_as else slug
    return EntityRef(name=name, primary_type="group", primary_id=group_slug)


def merge_operator_qids(extracted: dict, sat: Satcat | None) -> None:
    """Merge SATCAT operator_qids into ``extracted["operators"]``, dedup preserving order.

    Mutates in place so the generic ENTITY_REF_CLAIMS resolver sees the unified
    list and resolves each QID only once.
    """
    if sat is None or not sat.operator_qids:
        return
    existing = extracted.get("operators", [])
    merged = list(dict.fromkeys([*existing, *sat.operator_qids]))
    extracted["operators"] = merged


def covered_authoritative_qids(sat: Satcat | None) -> set[str]:
    """QIDs already shown via a SATCAT-derived, group-linked ref.

    Wikidata claims pointing at one of these (e.g. P361 part_of) are dropped
    at export to avoid a double-render.
    """
    if sat is None:
        return set()
    qids: set[str] = set()
    if sat.constellation_slug and (
        spec := CONSTELLATION_BY_SLUG.get(sat.constellation_slug)
    ):
        if spec.wikidata_qid is not None:
            qids.add(spec.wikidata_qid)
    if sat.bus_slug and (spec := BUS_BY_SLUG.get(sat.bus_slug)):
        if spec.wikidata_qid is not None:
            qids.add(spec.wikidata_qid)
    if sat.launch_site_code and (site := LAUNCH_SITE_BY_CODE.get(sat.launch_site_code)):
        if site.wikidata_qid is not None:
            qids.add(site.wikidata_qid)
    qids.update(sat.operator_qids or [])
    qids.update(sat.manufacturer_qids or [])
    return qids


def _serialize_active_date(ad: ActiveDate) -> int | str:
    """int stays int (year), date becomes ISO string."""
    return ad if isinstance(ad, int) else ad.isoformat()


def resolve_operator_refs(
    qids: list[str],
    lang: str,
    wikidata_entities: WikidataEntityCache,
) -> list[dict]:
    """Resolve operator QIDs to entity refs, linked to /g/org-<slug>.

    ``active_from``/``active_until`` ride along when set, so the satellite
    detail page can show the operator's tenure window.
    """
    refs = []
    for qid in qids:
        ref = resolve_entity_ref(qid, lang, wikidata_entities)
        spec = OPERATOR_BY_QID.get(qid)
        # We need the OperatorSpec to make the group link — without it we can't
        # name the destination so just drop the ref entirely.
        if spec is None:
            continue
        name = ref.name if ref is not None and ref.name else spec.name
        ref_dict: dict = {
            "name": name,
            "primary_type": "group",
            "primary_id": f"{ORGANIZATION_SLUG_PREFIX}{spec.slug}",
        }
        if spec.active_from is not None:
            ref_dict["active_from"] = _serialize_active_date(spec.active_from)
        if spec.active_until is not None:
            ref_dict["active_until"] = _serialize_active_date(spec.active_until)
        refs.append(ref_dict)
    return refs


def resolve_manufacturer_refs(
    qids: list[str],
    lang: str,
    wikidata_entities: WikidataEntityCache,
) -> list[dict]:
    """Resolve manufacturer QIDs to entity refs, linked to /g/org-<slug>."""
    refs = []
    for qid in qids:
        spec = MANUFACTURER_BY_QID.get(qid)
        if spec is None:
            continue
        ref = resolve_entity_ref(qid, lang, wikidata_entities)
        name = ref.name if ref is not None and ref.name else spec.name
        refs.append(
            {
                "name": name,
                "primary_type": "group",
                "primary_id": f"{ORGANIZATION_SLUG_PREFIX}{spec.slug}",
            }
        )
    return refs
