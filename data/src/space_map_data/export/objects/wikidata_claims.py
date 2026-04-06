"""Wikidata claim extraction and entity-reference resolution."""

import logging
from typing import Literal, NamedTuple
from urllib.parse import quote

from space_map_data.export.quantities import UnitConverter
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


class MultipleClaimValues(ValueError):
    """Raised when a single-value claim has multiple non-deprecated values."""


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
    GlobalClaim("population", "P1082", "quantity"),
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

PID_TO_KEY: dict[str, str] = {
    c.pid: c.key for c in (*GLOBAL_CLAIMS, *ENTITY_REF_CLAIMS)
}


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
    name = wd["labels"].get(lang)
    if not name:
        return None
    result: dict = {"name": name}
    title = wd["sitelinks"].get(lang)
    if title:
        result["wikipedia"] = f"https://{lang}.wikipedia.org/wiki/{quote(title)}"
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


_JPL_SBDB_QID = "Q4026990"


def _active_stmts(claims: dict, prop: str) -> list[dict]:
    """Return non-deprecated statements for *prop*, preferring ``preferred`` rank."""
    stmts = [s for s in claims.get(prop, []) if s.get("rank") != "deprecated"]
    preferred = [s for s in stmts if s.get("rank") == "preferred"]
    return preferred if preferred else stmts


def _stmt_value(stmt: dict):
    """Extract ``mainsnak.datavalue.value`` from a statement, or None."""
    return stmt.get("mainsnak", {}).get("datavalue", {}).get("value")


def _is_sourced_to(stmt: dict, qid: str) -> bool:
    """Check whether a statement cites *qid* via P248 (stated in)."""
    for ref in stmt.get("references", []):
        for snak in ref.get("snaks", {}).get("P248", []):
            val = snak.get("datavalue", {}).get("value", {})
            if isinstance(val, dict) and val.get("id") == qid:
                return True
    return False


def _claim_values(claims: dict, prop: str):
    """Yield raw ``datavalue.value`` entries for a given property.

    Skips deprecated statements.  If any statement has rank ``preferred``,
    only those are yielded.
    """
    for stmt in _active_stmts(claims, prop):
        val = _stmt_value(stmt)
        if val is not None:
            yield val


def _first_string(claims: dict, prop: str) -> str | None:
    """Extract the single string value from a claim."""
    vals = [val for val in _claim_values(claims, prop) if isinstance(val, str) and val]
    if len(vals) > 1:
        key = PID_TO_KEY.get(prop, prop)
        raise MultipleClaimValues(f"Multiple string values for {key}: {vals}")
    return vals[0] if vals else None


def _first_time(claims: dict, prop: str) -> str | None:
    """Extract the single time value from a claim as an ISO date string."""
    vals = [
        val["time"]
        for val in _claim_values(claims, prop)
        if isinstance(val, dict) and "time" in val
    ]
    if len(vals) > 1:
        key = PID_TO_KEY.get(prop, prop)
        raise MultipleClaimValues(f"Multiple time values for {key}: {vals}")
    return vals[0] if vals else None


def _parse_quantity(dv: dict) -> dict | float | None:
    """Parse a raw quantity datavalue into a float or {value, unit} dict."""
    if not isinstance(dv, dict) or "amount" not in dv:
        return None
    try:
        value = float(dv["amount"])
    except (ValueError, TypeError):
        return None
    unit = dv.get("unit", "1")
    if unit == "1":
        return value
    unit_qid = unit.rsplit("/", 1)[-1] if "/" in unit else unit
    return {"value": value, "unit": unit_qid}


def _qty_numeric(q: dict | float) -> float:
    """Extract the numeric value from a parsed quantity."""
    return q if isinstance(q, (int, float)) else q["value"]


def _first_quantity(claims: dict, prop: str) -> dict | float | None:
    """Extract the single quantity value from a claim.

    Returns plain float for dimensionless quantities, or {"value": float, "unit": "Q..."}.
    When multiple values remain and all are within 10% of each other, the one
    sourced to JPL SBDB (Q4026990) is preferred.
    """
    stmts = _active_stmts(claims, prop)
    pairs: list[tuple[dict, dict | float]] = []
    for stmt in stmts:
        dv = _stmt_value(stmt)
        if dv is None:
            continue
        parsed = _parse_quantity(dv)
        if parsed is not None:
            pairs.append((stmt, parsed))

    if len(pairs) <= 1:
        return pairs[0][1] if pairs else None

    # Try to disambiguate: if all values are within 10%, prefer JPL SBDB source
    nums = [_qty_numeric(p) for _, p in pairs]
    lo, hi = min(nums), max(nums)
    if lo > 0 and (hi - lo) / hi <= 0.1:
        sbdb = [(s, p) for s, p in pairs if _is_sourced_to(s, _JPL_SBDB_QID)]
        if len(sbdb) == 1:
            return sbdb[0][1]

    key = PID_TO_KEY.get(prop, prop)
    raise MultipleClaimValues(f"Multiple quantity values for {key}: {[p for _, p in pairs]}")


def _first_entity_qid(claims: dict, prop: str) -> str | None:
    """Extract the single entity QID from a claim."""
    vals = [
        val["id"]
        for val in _claim_values(claims, prop)
        if isinstance(val, dict) and "id" in val
    ]
    if len(vals) > 1:
        key = PID_TO_KEY.get(prop, prop)
        raise MultipleClaimValues(f"Multiple entity values for {key}: {vals}")
    return vals[0] if vals else None


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


def radius_km_from_claims(claims: dict, units: UnitConverter) -> float | None:
    """Extract the mean radius in km from raw Wikidata claims (P2120), or None."""
    qty = _first_quantity(claims, "P2120")
    if qty is None:
        return None
    if isinstance(qty, (int, float)):
        # Dimensionless — assume km (rare but possible)
        return float(qty)
    unit_qid = qty.get("unit")
    if not unit_qid:
        return None
    metres = units.convert_to_base(
        float(qty["value"]), unit_qid, expected_type="length"
    )
    if metres is None:
        logger.warning("radius_km_from_claims: unknown unit QID %s, skipping", unit_qid)
        return None
    return metres / 1000.0
