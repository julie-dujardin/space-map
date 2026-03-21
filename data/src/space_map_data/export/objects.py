"""Write per-object JSON files: objects/__global__/<id>.json and objects/<lang>/<id>.json."""

import json
import logging
import re
from pathlib import Path
from urllib.parse import quote

from space_map_data.download.providers.wikipedia import LANGUAGES
from space_map_data.export.labels import WikidataEntity, resolve_name
from space_map_data.models.object import SBDB, Object
from space_map_data.utils.paths import DOWNLOAD_DIR

logger = logging.getLogger(__name__)


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

    wiki_summaries = _load_wikipedia_summaries()

    for obj in objects:
        wd = wikidata_entities.get(obj.wikidata_qid or "")
        extracted = _extract_claims(wd["claims"]) if wd else {}

        # Global (non-localized)
        global_data = _build_global(obj, wd, extracted, wikidata_entities)
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


def _extract_claims(claims: dict) -> dict:
    """Extract target properties from raw Wikidata claims.

    Returns a flat dict with parsed values (not the raw claim structure).
    """
    result: dict = {}

    # --- Non-localized (global) ---

    # Time properties
    for key, prop in (("discovery_date", "P575"), ("launch_date", "P619")):
        if v := _first_time(claims, prop):
            result[key] = v

    # Quantity properties
    for key, prop in (
        ("mass", "P2067"),
        ("radius", "P2120"),
        ("density", "P2054"),
        ("surface_gravity", "P7015"),
        ("absolute_magnitude", "P1457"),
        ("apparent_magnitude", "P1215"),
        ("temperature", "P2076"),
        ("min_temperature", "P7422"),
        ("max_temperature", "P6591"),
    ):
        if v := _first_quantity(claims, prop):
            result[key] = v

    # Image (Commons filename → URL)
    for stmt in claims.get("P18", []):
        filename = stmt.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(filename, str) and filename:
            result["image"] = _commons_url(filename)
            break

    # Website URL
    for stmt in claims.get("P856", []):
        url = stmt.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(url, str) and url:
            result["website"] = url
            break

    # --- Entity references (localized, resolved at build time) ---

    # Multi-value entity refs
    for key, prop in (("discoverer_qids", "P61"),):
        qids = _all_entity_qids(claims, prop)
        if qids:
            result[key] = qids

    # Single-value entity refs
    for key, prop in (
        ("named_after_qid", "P138"),
        ("discovery_site_qid", "P65"),
        ("minor_planet_group_qid", "P196"),
        ("spectral_type_qid", "P720"),
        ("asteroid_family_qid", "P744"),
        ("operator_qid", "P137"),
        ("manufacturer_qid", "P176"),
        ("launch_vehicle_qid", "P375"),
        ("launch_site_qid", "P1427"),
    ):
        if qid := _first_entity_qid(claims, prop):
            result[key] = qid

    return result


def _first_time(claims: dict, prop: str) -> str | None:
    """Extract the first time value from a claim as an ISO date string."""
    for stmt in claims.get(prop, []):
        tv = stmt.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if isinstance(tv, dict) and "time" in tv:
            return _parse_wikidata_time(tv["time"])
    return None


def _first_quantity(claims: dict, prop: str) -> dict | float | None:
    """Extract the first quantity value from a claim.

    Returns plain float for dimensionless quantities, or {"value": float, "unit": "Q..."}.
    """
    for stmt in claims.get(prop, []):
        dv = stmt.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if not isinstance(dv, dict) or "amount" not in dv:
            continue
        try:
            value = float(dv["amount"])
        except (ValueError, TypeError):
            continue
        unit = dv.get("unit", "1")
        if unit == "1":
            return value
        # Extract QID from unit URL like "http://www.wikidata.org/entity/Q11570"
        unit_qid = unit.rsplit("/", 1)[-1] if "/" in unit else unit
        return {"value": value, "unit": unit_qid}
    return None


def _first_entity_qid(claims: dict, prop: str) -> str | None:
    """Extract the first entity QID from a claim."""
    for stmt in claims.get(prop, []):
        dv = stmt.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if isinstance(dv, dict) and "id" in dv:
            return dv["id"]
    return None


def _all_entity_qids(claims: dict, prop: str) -> list[str]:
    """Extract all entity QIDs from a claim."""
    qids = []
    for stmt in claims.get(prop, []):
        dv = stmt.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if isinstance(dv, dict) and "id" in dv:
            qids.append(dv["id"])
    return qids


def _parse_wikidata_time(time_str: str) -> str | None:
    """Parse Wikidata time format '+1769-08-08T00:00:00Z' → '1769-08-08'."""
    m = re.match(r"[+-]?(\d{4,})-(\d{2})-(\d{2})", time_str)
    if not m:
        return None
    year, month, day = m.group(1), m.group(2), m.group(3)
    if month == "00" or day == "00":
        return year if month == "00" else f"{year}-{month}"
    return f"{year}-{month}-{day}"


def _commons_url(filename: str) -> str:
    """Convert a Wikimedia Commons filename to a thumbnail URL."""
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(filename)}?width=300"


def _resolve_entity_ref(
    qid: str,
    lang: str,
    wikidata_entities: dict[str, WikidataEntity],
) -> dict | None:
    """Resolve a QID to {name, wikipedia?} using downloaded entity data."""
    wd = wikidata_entities.get(qid)
    if not wd:
        return None
    name = wd["labels"].get(lang) or wd["labels"].get("en")
    if not name:
        return None
    result: dict = {"name": name}
    # Wikipedia URL from sitelinks
    title = wd["sitelinks"].get(lang)
    if title:
        result["wikipedia"] = f"https://{lang}.wikipedia.org/wiki/{quote(title)}"
    elif en_title := wd["sitelinks"].get("en"):
        result["wikipedia"] = f"https://en.wikipedia.org/wiki/{quote(en_title)}"
    return result


def _build_global(
    obj: Object,
    wd: WikidataEntity | None,
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
    cross_refs: dict = {}
    if wd:
        # wikidata_qid is implicitly known since wd exists, but include for convenience
        pass
    if obj.wikidata_qid is not None:
        cross_refs["wikidata_qid"] = obj.wikidata_qid
    if obj.horizons_naif_id is not None:
        cross_refs["horizons_naif_id"] = obj.horizons_naif_id
    if obj.sbdb_spkid is not None:
        cross_refs["sbdb_spkid"] = obj.sbdb_spkid
    if obj.sbdb_mcp_designation is not None:
        cross_refs["sbdb_mcp_designation"] = obj.sbdb_mcp_designation
    if obj.celestrak_norad_cat_id is not None:
        cross_refs["celestrak_norad_cat_id"] = obj.celestrak_norad_cat_id
    if obj.celestrak_cospar_id is not None:
        cross_refs["celestrak_cospar_id"] = obj.celestrak_cospar_id
    if cross_refs:
        data["cross_refs"] = cross_refs

    # Orbital elements
    orbit: dict = {}
    if obj.epoch_jd is not None:
        orbit["epoch_jd"] = obj.epoch_jd
    if obj.a is not None:
        orbit["a"] = obj.a
    if obj.e is not None:
        orbit["e"] = obj.e
    if obj.i is not None:
        orbit["i"] = obj.i
    if obj.om is not None:
        orbit["om"] = obj.om
    if obj.w is not None:
        orbit["w"] = obj.w
    if obj.ma is not None:
        orbit["ma"] = obj.ma
    if obj.n is not None:
        orbit["n"] = obj.n
    if orbit:
        orbit["scale"] = obj.scale
        if obj.parent_naif_id is not None:
            orbit["parent_naif_id"] = obj.parent_naif_id
        if obj.orbital_source is not None:
            orbit["source"] = obj.orbital_source
        data["orbit"] = orbit

    # Physical properties
    physical: dict = {}
    if obj.mass_kg is not None:
        physical["mass_kg"] = obj.mass_kg
    if obj.radius_km is not None:
        physical["radius_km"] = obj.radius_km
    if obj.discovery_date is not None:
        physical["discovery_date"] = str(obj.discovery_date)
    if physical:
        data["physical"] = physical

    # SBDB extras
    sbdb = obj.sbdb
    if sbdb is not None:
        sbdb_data = _build_sbdb(sbdb)
        if sbdb_data:
            data["sbdb"] = sbdb_data

    # Wikidata claims (non-localized)
    if extracted:
        wikidata_section: dict = {}
        _GLOBAL_CLAIM_KEYS = (
            "discovery_date",
            "launch_date",
            "image",
            "mass",
            "radius",
            "density",
            "surface_gravity",
            "absolute_magnitude",
            "apparent_magnitude",
            "temperature",
            "min_temperature",
            "max_temperature",
            "website",
        )
        for key in _GLOBAL_CLAIM_KEYS:
            if key in extracted:
                val = extracted[key]
                if isinstance(val, dict) and "unit" in val:
                    unit_wd = wikidata_entities.get(val["unit"])
                    if unit_wd:
                        label = unit_wd["labels"].get("en")
                        if label:
                            val = {**val, "unit": label.lower().replace(" ", "_")}
                wikidata_section[key] = val
        if wikidata_section:
            data["wikidata"] = wikidata_section

    return data


def _build_sbdb(sbdb: SBDB) -> dict:
    """Build the SBDB extras dict, omitting None values."""
    data: dict = {}

    # Classification
    if sbdb.neo is not None:
        data["neo"] = sbdb.neo
    if sbdb.pha is not None:
        data["pha"] = sbdb.pha
    if sbdb.class_ is not None:
        data["class"] = sbdb.class_
    if sbdb.sats is not None:
        data["sats"] = sbdb.sats

    # Physical
    if sbdb.diameter is not None:
        data["diameter"] = sbdb.diameter
    if sbdb.extent is not None:
        data["extent"] = sbdb.extent
    if sbdb.albedo is not None:
        data["albedo"] = sbdb.albedo
    if sbdb.rot_per is not None:
        data["rot_per"] = sbdb.rot_per
    if sbdb.GM is not None:
        data["GM"] = sbdb.GM

    # Magnitude
    if sbdb.H is not None:
        data["H"] = sbdb.H
    if sbdb.G is not None:
        data["G"] = sbdb.G

    # Spectral
    if sbdb.spec_B is not None:
        data["spec_B"] = sbdb.spec_B
    if sbdb.spec_T is not None:
        data["spec_T"] = sbdb.spec_T

    # Colors
    if sbdb.BV is not None:
        data["BV"] = sbdb.BV
    if sbdb.UB is not None:
        data["UB"] = sbdb.UB
    if sbdb.IR is not None:
        data["IR"] = sbdb.IR

    # Orbit-derived
    if sbdb.moid is not None:
        data["moid"] = sbdb.moid
    if sbdb.moid_jup is not None:
        data["moid_jup"] = sbdb.moid_jup
    if sbdb.t_jup is not None:
        data["t_jup"] = sbdb.t_jup
    if sbdb.per_y is not None:
        data["per_y"] = sbdb.per_y
    if sbdb.q is not None:
        data["q"] = sbdb.q
    if sbdb.ad is not None:
        data["ad"] = sbdb.ad

    # Comet-specific
    if sbdb.prefix is not None:
        data["prefix"] = sbdb.prefix
    if sbdb.M1 is not None:
        data["M1"] = sbdb.M1
    if sbdb.M2 is not None:
        data["M2"] = sbdb.M2
    if sbdb.K1 is not None:
        data["K1"] = sbdb.K1
    if sbdb.K2 is not None:
        data["K2"] = sbdb.K2
    if sbdb.PC is not None:
        data["PC"] = sbdb.PC

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
        # Multi-value: discoverers
        if "discoverer_qids" in extracted:
            discoverers = [
                ref
                for qid in extracted["discoverer_qids"]
                if (ref := _resolve_entity_ref(qid, lang, wikidata_entities))
            ]
            if discoverers:
                data["discoverers"] = discoverers

        # Single-value entity refs
        _ENTITY_REF_KEYS = (
            ("named_after_qid", "named_after"),
            ("discovery_site_qid", "discovery_site"),
            ("minor_planet_group_qid", "minor_planet_group"),
            ("spectral_type_qid", "spectral_type"),
            ("asteroid_family_qid", "asteroid_family"),
            ("operator_qid", "operator"),
            ("manufacturer_qid", "manufacturer"),
            ("launch_vehicle_qid", "launch_vehicle"),
            ("launch_site_qid", "launch_site"),
        )
        for claim_key, output_key in _ENTITY_REF_KEYS:
            if claim_key in extracted:
                ref = _resolve_entity_ref(extracted[claim_key], lang, wikidata_entities)
                if ref:
                    data[output_key] = ref

    if wiki_summary:
        data["wikipedia"] = wiki_summary

    return data


def _load_wikipedia_summaries() -> dict[str, dict[str, dict]]:
    """Load Wikipedia summaries into {qid: {lang: summary_dict}}."""
    wiki_dir = DOWNLOAD_DIR / "wikipedia"
    if not wiki_dir.exists():
        logger.info("No Wikipedia summaries found")
        return {}

    result: dict[str, dict[str, dict]] = {}
    for lang in LANGUAGES:
        lang_dir = wiki_dir / lang
        if not lang_dir.exists():
            continue
        for f in lang_dir.glob("Q*.json"):
            qid = f.stem
            try:
                page = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            summary = _extract_wikipedia(page)
            if summary:
                result.setdefault(qid, {})[lang] = summary

    total = sum(len(langs) for langs in result.values())
    logger.info("Loaded %d Wikipedia summaries for %d entities", total, len(result))
    return result


def _extract_wikipedia(page: dict) -> dict | None:
    """Extract display-relevant fields from a Wikipedia API response."""
    if page.get("missing"):
        return None
    data: dict = {}
    if extract := page.get("extract"):
        data["extract"] = extract
    if desc := page.get("description"):
        data["description"] = desc
    if thumb := page.get("thumbnail", {}).get("source"):
        data["thumbnail"] = thumb
    if original := page.get("original", {}).get("source"):
        data["image"] = original
    if url := page.get("fullurl"):
        data["url"] = url
    return data or None
