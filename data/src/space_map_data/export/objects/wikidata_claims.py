"""Wikidata claim extraction and entity-reference resolution."""

import logging
import re
from typing import Literal, NamedTuple
from urllib.parse import quote

from space_map_data.export.elements import WikidataEntity

logger = logging.getLogger(__name__)


class GlobalClaim(NamedTuple):
    key: str
    pid: str
    kind: Literal["time", "quantity", "image", "url"]


GLOBAL_CLAIMS = (
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


ENTITY_REF_CLAIMS = (
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


def extract_claims(claims: dict) -> dict:
    """Extract target properties from raw Wikidata claims.

    Returns a flat dict with parsed values (not the raw claim structure).
    """
    result: dict = {}

    _EXTRACTORS = {
        "time": _first_time,
        "quantity": _first_quantity,
        "image": lambda c, p: _commons_url(s) if (s := _first_string(c, p)) else None,
        "url": _first_string,
    }
    for claim in GLOBAL_CLAIMS:
        if v := _EXTRACTORS[claim.kind](claims, claim.pid):
            result[claim.key] = v

    # Multi-value entity refs
    for key, prop in (("discoverer_qids", "P61"),):
        qids = _all_entity_qids(claims, prop)
        if qids:
            result[key] = qids

    # Single-value entity refs
    for claim in ENTITY_REF_CLAIMS:
        if qid := _first_entity_qid(claims, claim.pid):
            result[claim.key] = qid

    return result


def resolve_entity_ref(
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
    title = wd["sitelinks"].get(lang)
    if title:
        result["wikipedia"] = f"https://{lang}.wikipedia.org/wiki/{quote(title)}"
    elif en_title := wd["sitelinks"].get("en"):
        result["wikipedia"] = f"https://en.wikipedia.org/wiki/{quote(en_title)}"
    return result


def resolve_unit(
    unit_qid: str,
    wikidata_entities: dict[str, WikidataEntity],
) -> str | None:
    """Resolve a unit QID to a normalized English label, or None if not found."""
    unit_wd = wikidata_entities.get(unit_qid)
    if unit_wd:
        label = unit_wd["labels"].get("en")
        if label:
            return label.lower().replace(" ", "_")
    logger.warning("could not resolve unit %s", unit_qid)
    return None


# -- Claim value extractors --


def _first_string(claims: dict, prop: str) -> str | None:
    """Extract the first string value from a claim."""
    for stmt in claims.get(prop, []):
        val = stmt.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(val, str) and val:
            return val
    return None


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
