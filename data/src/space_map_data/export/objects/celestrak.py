"""SATCAT metadata export helpers (exported under the "celestrak" JSON key)."""

from space_map_data.constants.earth_sats.constellations import CONSTELLATION_BY_SLUG
from space_map_data.constants.earth_sats.launch_sites import LAUNCH_SITE_BY_CODE
from space_map_data.export.objects.wikidata_claims import resolve_entity_ref
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
        spec = CONSTELLATION_BY_SLUG.get(sat.constellation_slug)
        if spec is not None and spec.wikidata_qid is not None:
            ref = resolve_entity_ref(spec.wikidata_qid, lang, wikidata_entities)
            if ref:
                data["constellation"] = ref

    if sat.launch_site_code is not None:
        site = LAUNCH_SITE_BY_CODE.get(sat.launch_site_code)
        if site is not None and site.wikidata_qid is not None:
            ref = resolve_entity_ref(site.wikidata_qid, lang, wikidata_entities)
            if ref:
                data["launch_site"] = [ref]

    return data


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
