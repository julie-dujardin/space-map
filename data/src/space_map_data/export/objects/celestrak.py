"""CelesTrak enrichment export helpers."""

from space_map_data.constants.earth_sats.constellations import CONSTELLATION_BY_SLUG
from space_map_data.constants.earth_sats.launch_sites import LAUNCH_SITE_BY_CODE
from space_map_data.export.objects.wikidata_claims import resolve_entity_ref
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.models.object import CelesTrak


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
    "orbit_type",
    "launch_site_code",
    "owner",
    "constellation_slug",
)


def build_celestrak_global(ct: CelesTrak) -> dict:
    """Non-localized CelesTrak fields, omitting None/empty entries."""
    data: dict = {}
    for attr in _GLOBAL_FIELDS:
        val = getattr(ct, attr)
        if val is not None:
            data[attr] = val
    if ct.categories:
        data["categories"] = ct.categories
    if ct.country_codes:
        data["country_codes"] = ct.country_codes
    return data


def build_celestrak_localized(
    ct: CelesTrak,
    lang: str,
    wikidata_entities: WikidataEntityCache,
) -> dict:
    """Localized CelesTrak refs (constellation, launch_site, operators)."""
    data: dict = {}

    if ct.constellation_slug is not None:
        spec = CONSTELLATION_BY_SLUG.get(ct.constellation_slug)
        if spec is not None and spec.wikidata_qid is not None:
            ref = resolve_entity_ref(spec.wikidata_qid, lang, wikidata_entities)
            if ref:
                data["constellation"] = ref

    if ct.launch_site_code is not None:
        site = LAUNCH_SITE_BY_CODE.get(ct.launch_site_code)
        if site is not None and site.wikidata_qid is not None:
            ref = resolve_entity_ref(site.wikidata_qid, lang, wikidata_entities)
            if ref:
                data["launch_site"] = ref

    return data


def merge_operator_qids(extracted: dict, ct: CelesTrak | None) -> None:
    """Merge CelesTrak operator_qids into ``extracted["operators"]``, dedup preserving order.

    Mutates ``extracted`` in place so the generic ENTITY_REF_CLAIMS resolver
    picks up the unified list and resolves each QID only once.
    """
    if ct is None or not ct.operator_qids:
        return
    existing = extracted.get("operators", [])
    merged = list(dict.fromkeys([*existing, *ct.operator_qids]))
    extracted["operators"] = merged
