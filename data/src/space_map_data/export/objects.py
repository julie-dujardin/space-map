"""Write per-object JSON files: objects/__global__/<id>.json and objects/<lang>/<id>.json."""

import json
import logging
import re
from pathlib import Path
from typing import Literal, NamedTuple
from urllib.parse import quote

from space_map_data.download.providers.wikipedia import LANGUAGES
from space_map_data.export.labels import WikidataEntity, resolve_name
from space_map_data.models.object import SBDB, Object
from space_map_data.utils.paths import DOWNLOAD_DIR

logger = logging.getLogger(__name__)


class GlobalClaim(NamedTuple):
    key: str
    pid: str
    kind: Literal["time", "quantity", "image", "url"]


_GLOBAL_CLAIMS = (
    GlobalClaim("discovery_date", "P575", "time"),
    GlobalClaim("launch_date", "P619", "time"),
    GlobalClaim("image", "P18", "image"),
    GlobalClaim("mass", "P2067", "quantity"),
    GlobalClaim("radius", "P2120", "quantity"),
    GlobalClaim("density", "P2054", "quantity"),
    GlobalClaim("surface_gravity", "P7015", "quantity"),
    GlobalClaim("absolute_magnitude", "P1457", "quantity"),
    GlobalClaim("apparent_magnitude", "P1215", "quantity"),
    GlobalClaim("temperature", "P2076", "quantity"),
    GlobalClaim("min_temperature", "P7422", "quantity"),
    GlobalClaim("max_temperature", "P6591", "quantity"),
    GlobalClaim("website", "P856", "url"),
)


class EntityRefClaim(NamedTuple):
    key: str
    output: str
    pid: str


_ENTITY_REF_CLAIMS = (
    EntityRefClaim("named_after_qid", "named_after", "P138"),
    EntityRefClaim("discovery_site_qid", "discovery_site", "P65"),
    EntityRefClaim("minor_planet_group_qid", "minor_planet_group", "P196"),
    EntityRefClaim("spectral_type_qid", "spectral_type", "P720"),
    EntityRefClaim("asteroid_family_qid", "asteroid_family", "P744"),
    EntityRefClaim("operator_qid", "operator", "P137"),
    EntityRefClaim("manufacturer_qid", "manufacturer", "P176"),
    EntityRefClaim("launch_vehicle_qid", "launch_vehicle", "P375"),
    EntityRefClaim("launch_site_qid", "launch_site", "P1427"),
)

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

    wiki_summaries = _load_wikipedia_summaries()

    for obj in objects:
        wd = wikidata_entities.get(obj.wikidata_qid or "")
        extracted = _extract_claims(wd["claims"]) if wd else {}

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


def _extract_claims(claims: dict) -> dict:
    """Extract target properties from raw Wikidata claims.

    Returns a flat dict with parsed values (not the raw claim structure).
    """
    result: dict = {}

    # --- Non-localized (global) ---

    for claim in _GLOBAL_CLAIMS:
        if claim.kind == "time":
            if v := _first_time(claims, claim.pid):
                result[claim.key] = v
        elif claim.kind == "quantity":
            if v := _first_quantity(claims, claim.pid):
                result[claim.key] = v
        elif claim.kind == "image":
            for stmt in claims.get(claim.pid, []):
                filename = stmt.get("mainsnak", {}).get("datavalue", {}).get("value")
                if isinstance(filename, str) and filename:
                    result[claim.key] = _commons_url(filename)
                    break
        elif claim.kind == "url":
            for stmt in claims.get(claim.pid, []):
                url = stmt.get("mainsnak", {}).get("datavalue", {}).get("value")
                if isinstance(url, str) and url:
                    result[claim.key] = url
                    break

    # --- Entity references (localized, resolved at build time) ---

    # Multi-value entity refs
    for key, prop in (("discoverer_qids", "P61"),):
        qids = _all_entity_qids(claims, prop)
        if qids:
            result[key] = qids

    # Single-value entity refs
    for claim in _ENTITY_REF_CLAIMS:
        if qid := _first_entity_qid(claims, claim.pid):
            result[claim.key] = qid

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
        for claim in _GLOBAL_CLAIMS:
            if claim.key in extracted:
                val = extracted[claim.key]
                if isinstance(val, dict) and "unit" in val:
                    unit_wd = wikidata_entities.get(val["unit"])
                    if unit_wd:
                        label = unit_wd["labels"].get("en")
                        if label:
                            val = {**val, "unit": label.lower().replace(" ", "_")}
                wikidata_section[claim.key] = val
        if wikidata_section:
            data["wikidata"] = wikidata_section

    return data


_SBDB_FIELDS = (
    "neo",
    "pha",
    "class_",
    "sats",
    "diameter",
    "extent",
    "albedo",
    "rot_per",
    "GM",
    "H",
    "G",
    "spec_B",
    "spec_T",
    "BV",
    "UB",
    "IR",
    "moid",
    "moid_jup",
    "t_jup",
    "per_y",
    "q",
    "ad",
    "prefix",
    "M1",
    "M2",
    "K1",
    "K2",
    "PC",
)


def _build_sbdb(sbdb: SBDB) -> dict:
    """Build the SBDB extras dict, omitting None values."""
    data: dict = {}
    for attr in _SBDB_FIELDS:
        val = getattr(sbdb, attr)
        if val is not None:
            data[attr.rstrip("_")] = val
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
        for claim in _ENTITY_REF_CLAIMS:
            if claim.key in extracted:
                ref = _resolve_entity_ref(extracted[claim.key], lang, wikidata_entities)
                if ref:
                    data[claim.output] = ref

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
