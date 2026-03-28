"""Write per-object JSON files: objects/__global__/<id>.json and objects/<lang>/<id>.json."""

import json
import logging
from pathlib import Path

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.wikidata import WikidataEntity, resolve_name
from space_map_data.export.objects.sbdb import build_sbdb
from space_map_data.export.objects.wikidata_claims import (
    ENTITY_REF_CLAIMS,
    GLOBAL_CLAIMS,
    extract_claims,
    resolve_entity_ref,
    resolve_unit,
)
from space_map_data.export.objects.wikipedia import load_wikipedia_summaries
from space_map_data.models.object import Object

logger = logging.getLogger(__name__)

_CROSS_REF_FIELDS = (
    "wikidata_qid",
    "horizons_naif_id",
    "sbdb_spkid",
    "sbdb_mcp_designation",
    "celestrak_norad_cat_id",
    "celestrak_cospar_id",
)

_ORBIT_FIELDS = ("epoch_jd", "a", "e", "i", "om", "w", "ma", "n")

_PHYSICAL_FIELDS = ("mass_kg", "radius_km")


def _pick_attrs(obj: object, attrs: tuple[str, ...]) -> dict:
    """Extract non-None attributes from an object into a dict."""
    data: dict = {}
    for attr in attrs:
        val = getattr(obj, attr)
        if val is not None:
            data[attr] = val
    return data


def write_objects(
    objects: list[Object],
    out_dir: Path,
    wikidata_entities: dict[str, WikidataEntity],
) -> None:
    """Write per-object JSON files (global + per-language)."""
    global_dir = out_dir / "objects" / "__global__"
    global_dir.mkdir(parents=True, exist_ok=True)
    lang_dirs: dict[str, Path] = {}
    for lang in LANGUAGES:
        d = out_dir / "objects" / lang
        d.mkdir(parents=True, exist_ok=True)
        lang_dirs[lang] = d

    wiki_summaries = load_wikipedia_summaries()

    for obj in objects:
        wd = wikidata_entities.get(obj.wikidata_qid or "")
        extracted = extract_claims(wd["claims"]) if wd else {}

        # Global (non-localized)
        global_data = _build_global(obj, extracted, wikidata_entities)
        (global_dir / f"{obj.id}.json").write_text(
            json.dumps(global_data, ensure_ascii=False, separators=(",", ":"))
        )

        # Per-language (localized)
        qid = obj.wikidata_qid
        for lang in LANGUAGES:
            wiki = wiki_summaries.get(qid, {}).get(lang) if qid else None
            lang_data = _build_localized(
                obj, lang, wikidata_entities, wd, extracted, wiki
            )
            (lang_dirs[lang] / f"{obj.id}.json").write_text(
                json.dumps(lang_data, ensure_ascii=False, separators=(",", ":"))
            )

    logger.info(
        "Wrote object files for %d objects (%d languages + global)",
        len(objects),
        len(LANGUAGES),
    )


def _build_global(
    obj: Object,
    extracted: dict,
    wikidata_entities: dict[str, WikidataEntity],
) -> dict:
    """Build the language-independent JSON dict for an object."""
    data: dict = {
        "id": obj.id,
        "type": obj.object_type,
    }
    if obj.name is not None:
        data["name"] = obj.name
    if obj.provisional_designation is not None:
        data["provisional_designation"] = obj.provisional_designation

    # Cross-references
    cross_refs = _pick_attrs(obj, _CROSS_REF_FIELDS)
    if cross_refs:
        data["cross_refs"] = cross_refs

    # Orbital elements
    orbit = _pick_attrs(obj, _ORBIT_FIELDS)
    if orbit:
        orbit["scale"] = obj.scale
        if obj.parent_naif_id is not None:
            orbit["parent_naif_id"] = obj.parent_naif_id
        if obj.orbital_source is not None:
            orbit["source"] = obj.orbital_source
        data["orbit"] = orbit

    # Physical properties
    physical = _pick_attrs(obj, _PHYSICAL_FIELDS)
    if physical:
        data["physical"] = physical

    # SBDB extras
    sbdb = obj.sbdb
    if sbdb is not None:
        sbdb_data = build_sbdb(sbdb)
        if sbdb_data:
            data["sbdb"] = sbdb_data

    # Wikidata claims (non-localized)
    if extracted:
        wikidata_section: dict = {}
        for claim in GLOBAL_CLAIMS:
            if claim.key in extracted:
                val = extracted[claim.key]
                if isinstance(val, dict) and "unit" in val:
                    resolved = resolve_unit(val["unit"], wikidata_entities)
                    if resolved:
                        val = {**val, "unit": resolved}
                wikidata_section[claim.key] = val
        if wikidata_section:
            data["wikidata"] = wikidata_section

    return data


def _build_localized(
    obj: Object,
    lang: str,
    wikidata_entities: dict[str, WikidataEntity],
    wd: WikidataEntity | None,
    extracted: dict,
    wiki_summary: dict | None,
) -> dict:
    """Build the per-language JSON dict for an object."""
    data: dict = {}

    name = resolve_name(obj, lang, wikidata_entities)
    if name is not None:
        data["name"] = name

    if wd:
        desc = wd["descriptions"].get(lang) or wd["descriptions"].get("en")
        if desc:
            data["description"] = desc
        aliases = wd["aliases"].get(lang)
        if aliases:
            data["aliases"] = aliases

    if extracted:
        for claim in ENTITY_REF_CLAIMS:
            if claim.key in extracted:
                if claim.multiple:
                    ref = [
                        r
                        for qid in extracted["discoverer_qids"]
                        if (r := resolve_entity_ref(qid, lang, wikidata_entities))
                    ]
                else:
                    ref = resolve_entity_ref(
                        extracted[claim.key], lang, wikidata_entities
                    )

                if ref:
                    data[claim.key] = ref

    if wiki_summary:
        data["wikipedia"] = wiki_summary

    return data
