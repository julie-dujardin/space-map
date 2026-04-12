"""Wikidata claim extraction and entity-reference resolution."""

import logging
from typing import Literal, NamedTuple
from urllib.parse import quote

from space_map_data.export.quantities import UnitConverter
from space_map_data.export.wikidata import (
    WikidataEntity,
    WikidataEntityCache,
    active_statements,
)

logger = logging.getLogger(__name__)


_INSTANCE_OF_IGNORED = {
    "Q3901935",  # superior planet (orbits further from the Sun)
    "Q844911",  # inferior planet (orbits closer to the Sun)
    "Q2517610",  # list article
    "Q6999",  # astronomical object (too generic)
    "Q2221906",  # geographic location (too generic)
}


class MultipleClaimValues(ValueError):
    """Raised when a single-value claim has multiple non-deprecated values."""


class GlobalClaim(NamedTuple):
    key: str
    pid: str
    kind: Literal["time", "quantity", "image", "url"]
    multiple: bool = False
    needs_unit: bool = True


GLOBAL_CLAIMS = (
    GlobalClaim("discovery_date", "P575", "time", multiple=True),
    GlobalClaim("launch_date", "P619", "time"),
    GlobalClaim("image", "P18", "image", multiple=True),
    GlobalClaim("mass", "P2067", "quantity"),
    GlobalClaim("radius", "P2120", "quantity"),
    GlobalClaim("density", "P2054", "quantity"),
    GlobalClaim("surface_gravity", "P7015", "quantity"),
    GlobalClaim("absolute_magnitude", "P1457", "quantity", needs_unit=False),
    GlobalClaim("apparent_magnitude", "P1215", "quantity", needs_unit=False),
    # temperature (P2076) is handled separately — see P1480 routing below.
    GlobalClaim("min_temperature", "P7422", "quantity"),
    GlobalClaim("max_temperature", "P6591", "quantity"),
    GlobalClaim("website", "P856", "url", multiple=True),
    GlobalClaim("blog", "P1581", "url", multiple=True),
    GlobalClaim("logo_image", "P154", "image", multiple=True),
    GlobalClaim("population", "P1082", "quantity", needs_unit=False),
    GlobalClaim("capital_cost", "P2130", "quantity"),
    GlobalClaim("length", "P2043", "quantity"),
    GlobalClaim("width", "P2049", "quantity"),
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
    EntityRefClaim("developer", "P178", multiple=True),
    EntityRefClaim("funder", "P8324", multiple=True),
    EntityRefClaim("country_of_origin", "P495", multiple=True),
    EntityRefClaim("launch_contractor", "P1079", multiple=True),
    EntityRefClaim("part_of", "P361", multiple=True),  # Nasa programs
)

PID_TO_KEY: dict[str, str] = {
    c.pid: c.key for c in (*GLOBAL_CLAIMS, *ENTITY_REF_CLAIMS)
} | {
    "P2076": "temperature",  # routed via P1480, not a regular GlobalClaim
}


def _extract_global(
    claims: dict, claim: GlobalClaim, qid: str
) -> list | dict | float | str | None:
    """Dispatch a single GlobalClaim to the appropriate extractor."""
    kind, pid, multiple, needs_unit = (
        claim.kind,
        claim.pid,
        claim.multiple,
        claim.needs_unit,
    )
    if kind == "time":
        return _all_times(claims, pid) if multiple else _single_time(claims, pid)
    if kind == "quantity":
        return _single_quantity(claims, pid, needs_unit=needs_unit, qid=qid)
    if kind == "image":
        return [_commons_url(s) for s in _all_strings(claims, pid)]
    if kind == "url":
        return _all_strings(claims, pid)
    return None


def extract_claims(claims: dict, qid: str) -> dict:
    """Extract target properties from raw Wikidata claims.

    Returns a flat dict with parsed values (not the raw claim structure).
    """
    result: dict = {}

    for claim in GLOBAL_CLAIMS:
        v = _extract_global(claims, claim, qid)
        if v:
            result[claim.key] = v

    # P2076 (temperature): group by P1480/P5102 qualifier, then disambiguate each group.
    # P7422/P6591 from the loop above take priority via setdefault.
    _NATURE_ROUTE = {
        _QID_MINIMUM: "min_temperature",
        _QID_MAXIMUM: "max_temperature",
        _QID_AVERAGE: "temperature",
        _QID_MEAN: "temperature",
    }
    grouped: dict[str, list[dict]] = {}
    for stmt in active_statements(claims, "P2076"):
        nature = (
            _qualifier_qid(stmt, "P1480")
            or _qualifier_qid(stmt, "P5102")
            or _qualifier_qid(stmt, "P518")
        )
        key = _NATURE_ROUTE.get(nature, "temperature") if nature else "temperature"
        grouped.setdefault(key, []).append(stmt)
    for key, stmts in grouped.items():
        v = _resolve_quantity(_qty_pairs(stmts), "P2076", qid=qid)
        if v:
            result.setdefault(key, v)

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
            if ref_qid := _single_entity_qid(claims, claim.pid):
                result[claim.key] = ref_qid

    return result


_REF_NAME_SHORTEN_THRESHOLD = 15
_REF_NAME_WARN_THRESHOLD = 20


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
    if len(name) > _REF_NAME_SHORTEN_THRESHOLD:
        name = _shortest_ref_name(name, lang, wd, qid)
    result: dict = {"name": name}
    title = wd["sitelinks"].get(lang)
    if title:
        result["wikipedia"] = f"https://{lang}.wikipedia.org/wiki/{quote(title)}"
    return result


def _shortest_ref_name(label: str, lang: str, wd: WikidataEntity, qid: str) -> str:
    """Return the shortest available name for a referenced entity.

    Checks P1813 (short name) claims and aliases for the given language,
    and returns the shortest candidate that is shorter than the label.
    """
    candidates: list[str] = []

    # P1813 — official short name
    for stmt in active_statements(wd["claims"], "P1813"):
        val = _stmt_value(stmt)
        if isinstance(val, dict) and val.get("language") == lang and val.get("text"):
            candidates.append(val["text"])

    # Aliases for this language
    candidates.extend(wd["aliases"].get(lang, []))

    shorter = [c for c in candidates if len(c) < len(label)]
    if shorter:
        return min(shorter, key=len)  # type: ignore  # ty what the fuck

    # TODO: export both long & short forms, let the frontend handle it
    # if len(label) > _REF_NAME_WARN_THRESHOLD:
    #     logger.warning("No short form for referenced entity %s (%s)", qid, label)
    return label


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

# qualifier: preferred values per property, tried in order.
_PREFERRED_CRITERIA: dict[str, list[str]] = {
    "P2067": [  # Arbitrarily prefer the mass closer to service entry, instead of dry mass
        "Q29933828",  # service entry
        "Q2333272",  # launch mass
        "Q854248",  # takeoff
        "Q65088056",  # Gross mass
    ],
}
_TRUSTED_PROVIDERS = [
    "Q4026990",  # JPL SBDB
    "Q6952408",  # NASA Facts
]

# Disambiguation overrides for specific (QID, property) pairs with multiple values.
_PICK_FIRST: set[tuple[str, str]] = {
    ("Q18325885", "P1215"),  # 486958 Arrokoth apparent magnitude
    ("Q16081", "P2120"),  # Proteus radius (209 vs 210 km)
}
_AVERAGE: set[tuple[str, str]] = {
    ("Q135193382", "P2120"),  # 3I/ATLAS radius (min/max)
    ("Q319", "P1215"),  # Jupiter apparent magnitude (min/max)
}
_DISCARD: set[tuple[str, str]] = {
    ("Q147561", "P7015"),  # 2101 Adonis surface gravity (uncorrelated values)
}
# Properties where the largest value wins when multiple remain after filtering.
_PICK_MAX: set[str] = {"P2043", "P2049"}  # length, width


def _qualifier_qid(stmt: dict, qual_prop: str) -> str | None:
    """Return the first QID from a qualifier property, or None."""
    for snak in stmt.get("qualifiers", {}).get(qual_prop, []):
        val = snak.get("datavalue", {}).get("value", {})
        if isinstance(val, dict) and "id" in val:
            return val["id"]
    return None


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


def _has_any_reference(stmt: dict) -> bool:
    """Check whether a statement has any non-empty reference block."""
    for ref in stmt.get("references", []):
        if ref.get("snaks"):
            return True
    return False


def _has_nasa_ref_url(stmt: dict) -> bool:
    """Check whether a statement has a P854 (reference URL) on a nasa.gov domain."""
    for ref in stmt.get("references", []):
        for snak in ref.get("snaks", {}).get("P854", []):
            url = snak.get("datavalue", {}).get("value", "")
            if isinstance(url, str) and ".nasa.gov" in url:
                return True
    return False


def _claim_values(claims: dict, prop: str):
    """Yield raw ``datavalue.value`` entries for a given property.

    Skips deprecated statements.  If any statement has rank ``preferred``,
    only those are yielded.
    """
    for stmt in active_statements(claims, prop):
        val = _stmt_value(stmt)
        if val is not None:
            yield val


def _all_strings(claims: dict, prop: str) -> list[str]:
    """Extract all string values from a claim."""
    return [val for val in _claim_values(claims, prop) if isinstance(val, str) and val]


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


def _single_time(claims: dict, prop: str) -> str | None:
    """Extract the single time value from a claim as an ISO date string."""
    vals = list(dict.fromkeys(_all_times(claims, prop)))
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


def _qty_pairs(
    stmts: list[dict], *, needs_unit: bool = True
) -> list[tuple[dict, dict | float]]:
    """Parse statements into (statement, parsed-value) pairs, filtering by unit requirement."""
    pairs: list[tuple[dict, dict | float]] = []
    for stmt in stmts:
        dv = _stmt_value(stmt)
        if dv is None:
            continue
        parsed = _parse_quantity(dv)
        if parsed is None:
            continue
        if needs_unit and isinstance(parsed, (int, float)):
            continue
        pairs.append((stmt, parsed))
    return pairs


def _resolve_quantity(
    pairs: list[tuple[dict, dict | float]],
    prop: str,
    *,
    qid: str,
) -> dict | float | None:
    """Disambiguate a list of (statement, parsed-value) pairs into a single value.

    Applies deduplication, qualifier-based preference, trusted-source preference,
    and per-entity overrides (_PICK_FIRST, _AVERAGE, _DISCARD).
    """
    if len(pairs) <= 1:
        return pairs[0][1] if pairs else None

    # Deduplicate identical values
    unique = list({repr(p): (s, p) for s, p in pairs}.values())
    if len(unique) == 1:
        return unique[0][1]

    # Radius: prefer the mean/average value (P518 qualifier)
    if prop == "P2120":
        mean = [
            (s, p)
            for s, p in pairs
            if _qualifier_qid(s, "P518") in (_QID_AVERAGE, _QID_MEAN)
        ]
        if len(mean) == 1:
            return mean[0][1]

    # Prefer by qualifier value (checked across P1013, P518, P3831)
    for crit_qid in _PREFERRED_CRITERIA.get(prop, []):
        matched = [
            (s, p)
            for s, p in pairs
            if crit_qid
            in (
                _qualifier_qid(s, "P1013"),  # criterion used
                _qualifier_qid(s, "P518"),  # applies to part
                _qualifier_qid(s, "P3831"),  # object of statement has role
                _qualifier_qid(s, "P1552"),  # has characteristic
            )
        ]
        if len(matched) == 1:
            return matched[0][1]

    # Prefer a trusted source (P248) or nasa.gov reference URL (P854)
    for src_qid in _TRUSTED_PROVIDERS:
        sourced = [(s, p) for s, p in pairs if _is_sourced_to(s, src_qid)]
        if len(sourced) == 1:
            return sourced[0][1]
    nasa = [(s, p) for s, p in pairs if _has_nasa_ref_url(s)]
    if len(nasa) == 1:
        return nasa[0][1]
    sourced = [(s, p) for s, p in pairs if _has_any_reference(s)]
    if len(sourced) == 1:
        return sourced[0][1]

    if (qid, prop) in _PICK_FIRST:
        return pairs[0][1]
    if (qid, prop) in _AVERAGE:
        vals = [p["value"] if isinstance(p, dict) else p for _, p in pairs]
        mean = sum(vals) / len(vals)
        template = pairs[0][1]
        if isinstance(template, dict):
            return {**template, "value": mean}
        return mean
    if (qid, prop) in _DISCARD:
        return None
    if prop in _PICK_MAX:
        vals = [(p["value"] if isinstance(p, dict) else p, p) for _, p in pairs]
        return max(vals, key=lambda t: t[0])[1]

    key = PID_TO_KEY.get(prop, prop)
    raise MultipleClaimValues(
        f"Multiple quantity values for {key}: {[p for _, p in pairs]}"
    )


def _single_quantity(
    claims: dict,
    prop: str,
    *,
    needs_unit: bool,
    qid: str,
) -> dict | float | None:
    """Extract the single quantity value from a claim.

    Returns plain float for dimensionless quantities, or {"value": float, "unit": "Q..."}.
    Entries lacking units are ignored when *needs_unit* is True.
    """
    pairs = _qty_pairs(active_statements(claims, prop), needs_unit=needs_unit)
    return _resolve_quantity(pairs, prop, qid=qid)


def _single_entity_qid(claims: dict, prop: str) -> str | None:
    """Extract the single entity QID from a claim."""
    vals = list(
        dict.fromkeys(
            val["id"]
            for val in _claim_values(claims, prop)
            if isinstance(val, dict) and "id" in val
        )
    )
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


def radius_km_from_claims(claims: dict, units: UnitConverter, qid: str) -> float | None:
    """Extract the mean radius in km from raw Wikidata claims (P2120), or None."""
    qty = _single_quantity(claims, "P2120", needs_unit=True, qid=qid)
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
