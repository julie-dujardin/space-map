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
    multiple: bool = False


GLOBAL_CLAIMS = (
    GlobalClaim("discovery_date", "P575", "time", multiple=True),
    GlobalClaim("launch_date", "P619", "time"),
    GlobalClaim("image", "P18", "image", multiple=True),
    GlobalClaim("mass", "P2067", "quantity"),
    GlobalClaim("radius", "P2120", "quantity"),
    GlobalClaim("density", "P2054", "quantity"),
    GlobalClaim("surface_gravity", "P7015", "quantity"),
    GlobalClaim("absolute_magnitude", "P1457", "quantity"),
    GlobalClaim("apparent_magnitude", "P1215", "quantity"),
    # temperature (P2076) is handled separately — see P1480 routing below.
    GlobalClaim("min_temperature", "P7422", "quantity"),
    GlobalClaim("max_temperature", "P6591", "quantity"),
    GlobalClaim("website", "P856", "url", multiple=True),
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
    EntityRefClaim("named_after", "P138", multiple=True),
    EntityRefClaim("discovery_site", "P65", multiple=True),
    EntityRefClaim("minor_planet_group", "P196", multiple=True),
    EntityRefClaim("spectral_type", "P720", multiple=True),
    EntityRefClaim("asteroid_family", "P744"),
    EntityRefClaim("operator", "P137", multiple=True),
    EntityRefClaim("manufacturer", "P176", multiple=True),
    EntityRefClaim("launch_vehicle", "P375"),
    EntityRefClaim("launch_site", "P1427", multiple=True),
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

    _SINGLE = {
        "time": _first_time,
        "quantity": _first_quantity,
    }
    _MULTI = {
        "time": _all_times,
        "image": lambda c, p: [_commons_url(s) for s in _all_strings(c, p)],
        "url": _all_strings,
    }
    for claim in GLOBAL_CLAIMS:
        if claim.multiple:
            if v := _MULTI[claim.kind](claims, claim.pid):
                result[claim.key] = v
        else:
            if v := _SINGLE[claim.kind](claims, claim.pid):
                result[claim.key] = v

    # P2076 (temperature): route via P1480 (nature of statement) qualifier.
    # Unqualified → temperature, Q10585806 → min, Q10578722 → max.
    # Dedicated P7422/P6591 from the loop above take priority (setdefault).
    _P1480_ROUTE = {
        _QID_MINIMUM: "min_temperature",
        _QID_MAXIMUM: "max_temperature",
        _QID_AVERAGE: "temperature",
        _QID_MEAN: "temperature",
    }
    for stmt in _active_stmts(claims, "P2076"):
        dv = _stmt_value(stmt)
        if dv is None:
            continue
        parsed = _parse_quantity(dv)
        if parsed is None:
            continue
        nature = _qualifier_qid(stmt, "P1480")
        key = _P1480_ROUTE.get(nature, "temperature") if nature else "temperature"
        result.setdefault(key, parsed)

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


# Nature-of-value QIDs (used in P1480 qualifiers and elsewhere)
_QID_MINIMUM = "Q10585806"
_QID_MAXIMUM = "Q10578722"
_QID_AVERAGE = "Q202785"
_QID_MEAN = "Q2796622"

# P518 (applies to part) QID for volumetric mean radius
_QID_VOLUMETRIC_MEAN_RADIUS = "Q28809093"

# Trusted sources per property — when multiple close values exist, prefer these.
_TRUSTED_SOURCES: dict[str, list[str]] = {
    "P2067": ["Q29933828"],  # mass: prefer "service entry"
}
_TRUSTED_PROVIDERS = [
    "Q4026990",  # JPL SBDB
    "Q6952408",  # NASA Facts
]


def _qualifier_qid(stmt: dict, qual_prop: str) -> str | None:
    """Return the first QID from a qualifier property, or None."""
    for snak in stmt.get("qualifiers", {}).get(qual_prop, []):
        val = snak.get("datavalue", {}).get("value", {})
        if isinstance(val, dict) and "id" in val:
            return val["id"]
    return None


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


def _all_strings(claims: dict, prop: str) -> list[str]:
    """Extract all string values from a claim."""
    return [val for val in _claim_values(claims, prop) if isinstance(val, str) and val]


def _first_string(claims: dict, prop: str) -> str | None:
    """Extract the single string value from a claim."""
    vals = _all_strings(claims, prop)
    if len(vals) > 1:
        key = PID_TO_KEY.get(prop, prop)
        raise MultipleClaimValues(f"Multiple string values for {key}: {vals}")
    return vals[0] if vals else None


def _all_times(claims: dict, prop: str) -> list[str]:
    """Extract all time values, dropping less precise duplicates.

    Uses the Wikidata ``precision`` field (9 = year, 10 = month, 11 = day, …).
    When values at different precisions coexist, only the most precise are kept.
    """
    entries = []
    for val in _claim_values(claims, prop):
        if isinstance(val, dict) and "time" in val:
            entries.append((val.get("precision", 0), val["time"]))
    if len(entries) <= 1:
        return [t for _, t in entries]
    max_prec = max(p for p, _ in entries)
    return [t for p, t in entries if p == max_prec]


def _first_time(claims: dict, prop: str) -> str | None:
    """Extract the single time value from a claim as an ISO date string."""
    vals = _all_times(claims, prop)
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

    # Radius: prefer the volumetric mean radius (P518 = Q28809093)
    if prop == "P2120":
        mean = [
            (s, p)
            for s, p in pairs
            if _qualifier_qid(s, "P518")
            in (_QID_VOLUMETRIC_MEAN_RADIUS, _QID_AVERAGE, _QID_MEAN)
        ]
        if len(mean) == 1:
            return mean[0][1]

    # Try to disambiguate: if all values are within 10%, prefer a trusted source
    nums = [_qty_numeric(p) for _, p in pairs]
    lo, hi = min(nums), max(nums)
    if lo > 0 and (hi - lo) / hi <= 0.1:
        for qid in _TRUSTED_SOURCES.get(prop, _TRUSTED_PROVIDERS):
            sourced = [(s, p) for s, p in pairs if _is_sourced_to(s, qid)]
            if len(sourced) == 1:
                return sourced[0][1]

    key = PID_TO_KEY.get(prop, prop)
    raise MultipleClaimValues(
        f"Multiple quantity values for {key}: {[p for _, p in pairs]}"
    )


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
