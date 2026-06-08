"""SATCAT metadata export helpers (exported under the "celestrak" JSON key)."""

from space_map_data.constants.earth_sats.constellations import CONSTELLATION_BY_SLUG
from space_map_data.constants.earth_sats.launch_sites import (
    LAUNCH_SITE_BY_CODE,
    LAUNCH_SITE_SLUG_PREFIX,
)
from space_map_data.constants.earth_sats.manufacturers import (
    MANUFACTURER_BY_QID,
    MANUFACTURER_SLUG_PREFIX,
)
from space_map_data.constants.earth_sats.operators import (
    OPERATOR_BY_QID,
    OPERATOR_SLUG_PREFIX,
    ActiveDate,
)
from space_map_data.export.objects.wikidata_claims import EntityRef, resolve_entity_ref
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
)


def build_satcat_global(sat: Satcat) -> dict:
    """Non-localized SATCAT fields, omitting None/empty entries."""
    data: dict = {}
    for attr in _GLOBAL_FIELDS:
        val = getattr(sat, attr)
        if val is not None:
            data[attr] = val
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
            # Same key as ``EntityRefClaim("manufacturer", "P176")`` so SATCAT
            # refs override the Wikidata-resolved ones (which lack /g/mfr-* links).
            data["manufacturer"] = mfr_refs

    return data


def _constellation_group_ref(
    slug: str,
    lang: str,
    wikidata_entities: WikidataEntityCache,
) -> EntityRef | None:
    """EntityRef for a constellation, pointing at /g/<slug> instead of Wikipedia.

    Display name comes from Wikidata when a QID is registered; otherwise the
    slug stands in. The group page renders the same fallback, so the chip and
    the destination stay consistent.
    """
    spec = CONSTELLATION_BY_SLUG.get(slug)
    if spec is None:
        return None
    if spec.wikidata_qid is not None:
        ref = resolve_entity_ref(spec.wikidata_qid, lang, wikidata_entities)
        if ref is not None:
            ref.primary_type = "group"
            ref.primary_id = slug
            return ref
    return EntityRef(name=slug, primary_type="group", primary_id=slug)


def merge_operator_qids(extracted: dict, sat: Satcat | None) -> None:
    """Merge SATCAT operator_qids into ``extracted["operators"]``, dedup preserving order.

    Mutates ``extracted`` in place so the generic ENTITY_REF_CLAIMS resolver
    picks up the unified list and resolves each QID only once.
    """
    if sat is None or not sat.operator_qids:
        return
    existing = extracted.get("operators", [])
    merged = list(dict.fromkeys([*existing, *sat.operator_qids]))
    extracted["operators"] = merged


def _serialize_active_date(ad: ActiveDate) -> int | str:
    """int stays int (year), date becomes ISO string."""
    return ad if isinstance(ad, int) else ad.isoformat()


def resolve_operator_refs(
    qids: list[str],
    lang: str,
    wikidata_entities: WikidataEntityCache,
) -> list[dict]:
    """Resolve operator QIDs to entity refs, linked to /g/op-<slug>.

    Falls back to the Wikidata label for the visible name. ``active_from`` /
    ``active_until`` (when set on the OperatorSpec) ride along so the satellite
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
            "primary_id": f"{OPERATOR_SLUG_PREFIX}{spec.slug}",
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
    """Resolve manufacturer QIDs to entity refs, linked to /g/mfr-<slug>."""
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
                "primary_id": f"{MANUFACTURER_SLUG_PREFIX}{spec.slug}",
            }
        )
    return refs
