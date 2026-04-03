"""Wikidata claim extraction and entity-reference resolution."""

import logging
from typing import Literal, NamedTuple
from urllib.parse import quote

from space_map_data.export.wikidata import WikidataEntityCache

logger = logging.getLogger(__name__)


_INSTANCE_OF_IGNORED = {
    # superior/inferior planet: wether the planet orbits closer or further away from the sun
    "Q3901935",
    "Q844911",
    # list articles
    "Q2517610",
    # no shit
    "Q6999",  # "astronomical object"
    "Q2221906",  # "geographic location"
}


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
    pid: str
    multiple: bool = False
    exclude_set: set[str] | None = None


ENTITY_REF_CLAIMS = (
    EntityRefClaim(
        "instance_of", "P31", multiple=True, exclude_set=_INSTANCE_OF_IGNORED
    ),
    EntityRefClaim("named_after", "P138"),
    EntityRefClaim("discovery_site", "P65"),
    EntityRefClaim("minor_planet_group", "P196"),
    EntityRefClaim("spectral_type", "P720"),
    EntityRefClaim("asteroid_family", "P744"),
    EntityRefClaim("operator", "P137"),
    EntityRefClaim("manufacturer", "P176"),
    EntityRefClaim("launch_vehicle", "P375"),
    EntityRefClaim("launch_site", "P1427"),
    EntityRefClaim("discoverers", "P61", multiple=True),
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

    for claim in ENTITY_REF_CLAIMS:
        if claim.multiple:
            qids = [
                q
                for q in _all_entity_qids(claims, claim.pid)
                if not claim.exclude_set or q not in claim.exclude_set
            ]
            if qids:
                result[claim.key] = qids
        else:
            if qid := _first_entity_qid(claims, claim.pid):
                result[claim.key] = qid

    return result


def resolve_entity_ref(
    qid: str,
    lang: str,
    wikidata_entities: WikidataEntityCache,
) -> dict | None:
    """Resolve a QID to {name, wikipedia?} using downloaded entity data."""
    wd = wikidata_entities.get_referenced(qid)
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
    wikidata_entities: WikidataEntityCache,
) -> str | None:
    """Resolve a unit QID to a normalized English label, or None if not found."""
    unit_wd = wikidata_entities.get_referenced(unit_qid)
    if unit_wd:
        label = unit_wd["labels"].get("en")
        if label:
            return label.lower().replace(" ", "_")
    logger.warning("could not resolve unit %s", unit_qid)
    return None


# -- Claim value extractors --


def _claim_values(claims: dict, prop: str):
    """Yield raw ``datavalue.value`` entries for a given property, skipping deprecated statements."""
    for stmt in claims.get(prop, []):
        if stmt.get("rank") == "deprecated":
            continue
        val = stmt.get("mainsnak", {}).get("datavalue", {}).get("value")
        if val is not None:
            yield val


def _first_string(claims: dict, prop: str) -> str | None:
    """Extract the first string value from a claim."""
    for val in _claim_values(claims, prop):
        if isinstance(val, str) and val:
            return val
    return None


def _first_time(claims: dict, prop: str) -> str | None:
    """Extract the first time value from a claim as an ISO date string."""
    for val in _claim_values(claims, prop):
        if isinstance(val, dict) and "time" in val:
            return val["time"]
    return None


def _first_quantity(claims: dict, prop: str) -> dict | float | None:
    """Extract the first quantity value from a claim.

    Returns plain float for dimensionless quantities, or {"value": float, "unit": "Q..."}.
    """
    for dv in _claim_values(claims, prop):
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
    for val in _claim_values(claims, prop):
        if isinstance(val, dict) and "id" in val:
            return val["id"]
    return None


def _all_entity_qids(claims: dict, prop: str) -> list[str]:
    """Extract all entity QIDs from a claim."""
    return [
        val["id"]
        for val in _claim_values(claims, prop)
        if isinstance(val, dict) and "id" in val
    ]


def _commons_url(filename: str) -> str:
    """Convert a Wikimedia Commons filename to a thumbnail URL."""
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(filename)}?width=300"
