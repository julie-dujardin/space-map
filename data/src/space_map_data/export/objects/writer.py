"""Write per-object JSON files: objects/__global__/<id>.json.gz and objects/<lang>/<id>.json.gz."""

import gzip
import orjson
import logging
from pathlib import Path

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.wikidata import (
    WikidataEntity,
    WikidataEntityCache,
    active_statements,
)
from space_map_data.export.objects.wikipedia import (
    WikipediaSummary,
    load_wikipedia_summaries_for_qid,
    load_wikipedia_image_filenames,
)
from space_map_data.export.images import collect_object_images
from space_map_data.export.objects.celestrak import (
    build_satcat_global,
    build_satcat_localized,
    merge_operator_qids,
)
from space_map_data.export.objects.sbdb import build_sbdb
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.objects.wikidata_claims import (
    ENTITY_REF_CLAIMS,
    GLOBAL_CLAIMS,
    extract_claims,
    resolve_entity_ref,
    resolve_unit,
)
from space_map_data.models.object import Object
from space_map_data.models.object.sbdb import OrbitClass

logger = logging.getLogger(__name__)

_QID_CURRENCY = "Q8142"


def _iso_currency_code(
    unit_qid: str, wikidata_entities: WikidataEntityCache
) -> str | None:
    """Return the ISO 4217 code if *unit_qid* is a currency, else None."""
    entity = wikidata_entities.get_referenced(unit_qid)
    if not entity:
        return None
    p31_qids = {
        stmt.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
        for stmt in active_statements(entity["claims"], "P31")
    }
    if _QID_CURRENCY not in p31_qids:
        return None
    for stmt in active_statements(entity["claims"], "P498"):
        dv = stmt.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(dv, str):
            return dv
    return None


_CROSS_REF_FIELDS = (
    "wikidata_qid",
    "horizons_naif_id",
    "sbdb_spkid",
    "sbdb_mcp_designation",
    "celestrak_norad_cat_id",
    "celestrak_cospar_id",
)

_ORBIT_FIELDS = ("epoch_jd", "a", "e", "i", "om", "w", "ma", "n")


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
    wikidata_entities: WikidataEntityCache,
    chunk_entities: dict[str, WikidataEntity | None],
    units: UnitConverter,
    nasa_science_urls: dict[str, str],
    orientation: dict[int, dict],
    radii: dict[int, dict],
) -> dict[str, dict[str, int]]:
    """Write per-object JSON files (global + per-language).

    Returns {obj_id: {lang: flag}} where flag is:
      0 = no file written
      1 = localized file written for this lang
      2 = no localized file, but English file exists (frontend should fetch en/)
    """
    global_dir = out_dir / "objects" / "__global__"
    global_dir.mkdir(parents=True, exist_ok=True)
    lang_dirs: dict[str, Path] = {}
    for lang in LANGUAGES:
        d = out_dir / "objects" / lang
        d.mkdir(parents=True, exist_ok=True)
        lang_dirs[lang] = d

    all_flags: dict[str, dict[str, int]] = {}

    for obj in objects:
        qid = obj.wikidata_qid or (
            obj.satcat.wikidata_qid
            if obj.celestrak_norad_cat_id is not None and obj.satcat
            else None
        )
        wd = chunk_entities.get(qid) if qid else None
        try:
            extracted = extract_claims(wd["claims"], qid=qid) if qid and wd else {}
        except Exception as exc:
            logger.error("Error extracting claims for %s (%s): %s", obj.id, qid, exc)
            extracted = {}

        sat = obj.satcat if obj.celestrak_norad_cat_id is not None else None
        merge_operator_qids(extracted, sat)

        # Collect image filenames from all Wikipedia languages
        wiki_image_filenames = load_wikipedia_image_filenames(qid) if qid else []

        # Global (non-localized, always written)
        global_data = _build_global(
            obj,
            extracted,
            wikidata_entities,
            units,
            nasa_science_urls,
            orientation,
            radii,
            wiki_image_filenames,
        )
        (global_dir / f"{obj.id}.json.gz").write_bytes(
            gzip.compress(orjson.dumps(global_data))
        )
        wiki_summaries = load_wikipedia_summaries_for_qid(qid) if qid else {}

        en_available = None
        obj_flags: dict[str, int] = {}

        for lang in LANGUAGES:
            wiki_summary = wiki_summaries.get(lang)
            lang_data = _build_localized(
                obj, lang, wikidata_entities, wd, extracted, wiki_summary
            )
            if lang_data:
                (lang_dirs[lang] / f"{obj.id}.json.gz").write_bytes(
                    gzip.compress(orjson.dumps(lang_data))
                )
                obj_flags[lang] = 1
                if lang == "en":
                    en_available = True
            else:
                obj_flags[lang] = 2 if en_available else 0

        all_flags[obj.id] = obj_flags

    logger.info(
        "Wrote object files for %d objects (%d languages + global)",
        len(objects),
        len(LANGUAGES),
    )
    return all_flags


_IMAGE_KEYS = {"image", "logo_image"}


def _build_global(
    obj: Object,
    extracted: dict,
    wikidata_entities: WikidataEntityCache,
    units: UnitConverter,
    nasa_science_urls: dict[str, str],
    orientation: dict[int, dict],
    radii: dict[int, dict],
    wiki_image_filenames: list[str] | None = None,
) -> dict:
    """Build the language-independent JSON dict for an object."""
    data: dict = {
        "id": obj.id,
        "type": obj.object_type,
    }
    if obj.map_texture_available:
        data["map_texture_available"] = True
    if obj.name is not None:
        data["name"] = obj.name
    if obj.sbdb_mcp_designation is not None:
        data["sbdb_primary_designation"] = obj.sbdb_mcp_designation
    if obj.provisional_designation is not None:
        data["provisional_designation"] = obj.provisional_designation

    # Cross-references
    cross_refs = _pick_attrs(obj, _CROSS_REF_FIELDS)
    if cross_refs:
        data["cross_refs"] = cross_refs

    nasa_url = nasa_science_urls.get(obj.id)
    if nasa_url:
        data["nasa_science_url"] = nasa_url

    # Orbital elements — parabolic comets use q/tp instead of a/ma/n
    sbdb = obj.sbdb if obj.sbdb_spkid is not None else None
    if sbdb is not None and sbdb.class_ == OrbitClass.PAR:
        orbit = _pick_attrs(obj, ("epoch_jd", "e", "i", "om", "w"))
        if sbdb.q is not None:
            orbit["q"] = sbdb.q
        if sbdb.tp is not None:
            orbit["tp"] = sbdb.tp
    else:
        orbit = _pick_attrs(obj, _ORBIT_FIELDS)
    if orbit:
        orbit["scale"] = obj.scale
        if obj.parent_naif_id is not None:
            orbit["parent_naif_id"] = obj.parent_naif_id
        if obj.orbital_source is not None:
            orbit["source"] = obj.orbital_source
        data["orbit"] = orbit

    # Orientation data (from SPICE PCK)
    if obj.horizons_naif_id is not None and obj.horizons_naif_id in orientation:
        data["orientation"] = orientation[obj.horizons_naif_id]

    # Triaxial radii (km, along body-fixed X, Y, Z) from SPICE PCK
    if obj.horizons_naif_id is not None and obj.horizons_naif_id in radii:
        data["radii"] = radii[obj.horizons_naif_id]

    # SBDB extras
    if sbdb is not None:
        sbdb_data = build_sbdb(sbdb, units)
        if sbdb_data:
            data["sbdb"] = sbdb_data

    # CelesTrak enrichment
    if obj.celestrak_norad_cat_id is not None and obj.satcat is not None:
        celestrak_data = build_satcat_global(obj.satcat)
        if celestrak_data:
            data["celestrak"] = celestrak_data

    # Images (collected from Wikidata P18/P154 + Wikipedia pageimages)
    images = collect_object_images(extracted, wiki_image_filenames or [])
    if images:
        data["images"] = images

    # Wikidata claims (non-localized, excluding image fields handled above)
    if extracted:
        wikidata_section: dict = {}
        # Keys from GLOBAL_CLAIMS + "temperature" (routed from P2076, not a GlobalClaim)
        wikidata_keys = [c.key for c in GLOBAL_CLAIMS] + ["temperature"]
        # SPICE PCK radii supersede the Wikidata radius — skip it when present.
        if "radii" in data:
            wikidata_keys = [k for k in wikidata_keys if k != "radius"]
        for key in wikidata_keys:
            if key in _IMAGE_KEYS:
                continue
            if key in extracted:
                val = extracted[key]
                if isinstance(val, dict) and "unit" in val:
                    iso = _iso_currency_code(val["unit"], wikidata_entities)
                    if iso:
                        val = {"value": val["value"], "currency": iso}
                    else:
                        converted = units.convert(float(val["value"]), val["unit"])
                        if converted is not None:
                            val = converted
                        else:
                            resolved = resolve_unit(val["unit"], wikidata_entities)
                            if resolved:
                                units.used_units.add(resolved)
                                val = {**val, "unit": resolved}
                wikidata_section[key] = val
        if wikidata_section:
            data["wikidata"] = wikidata_section

    return data


def _build_localized(
    obj: Object,
    lang: str,
    wikidata_entities: WikidataEntityCache,
    wd: WikidataEntity | None,
    extracted: dict,
    wiki_summary: WikipediaSummary | None,
) -> dict:
    """Build the per-language JSON dict for an object."""
    data: dict = {}

    if wd and lang in wd["labels"]:
        data["name"] = wd["labels"][lang]

    if wd:
        desc = wd["descriptions"].get(lang)
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
                        for qid in extracted[claim.key]
                        if (r := resolve_entity_ref(qid, lang, wikidata_entities))
                    ]
                else:
                    ref = resolve_entity_ref(
                        extracted[claim.key], lang, wikidata_entities
                    )

                if ref:
                    data[claim.key] = ref

    if obj.celestrak_norad_cat_id is not None and obj.satcat is not None:
        # SATCAT-derived refs overwrite Wikidata-derived ones (e.g. launch_site)
        # since SATCAT is the authoritative source for satellite metadata.
        data.update(build_satcat_localized(obj.satcat, lang, wikidata_entities))

    if wiki_summary:
        data["wikipedia"] = wiki_summary.to_dict()

    return data
