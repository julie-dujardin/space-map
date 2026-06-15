"""Wikidata claim extraction and entity-reference resolution."""

import logging
from dataclasses import dataclass
from typing import Literal, NamedTuple
from urllib.parse import quote, urlparse

from space_map_data.constants.countries import COUNTRY_BY_QID, COUNTRY_SLUG_PREFIX
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.wikidata import (
    WikidataEntity,
    WikidataEntityCache,
    active_statements,
)

logger = logging.getLogger(__name__)


@dataclass
class EntityRef:
    """A resolved Wikidata reference, optionally pointing at a map focus target.

    ``primary_*`` + ``secondary_*`` form an extensible path-like locator:
    body alone → just primary (e.g. ``primary=(naif, 499)``); feature on a
    body → primary names the body, secondary refines (e.g.
    ``secondary=(feature, 12345)``). When ``primary_id`` is set the
    ``wikipedia`` field is omitted on serialization — the frontend opens
    the target's drawer instead.
    """

    name: str
    short_name: str | None = None
    wikipedia: str | None = None
    primary_id: str | None = None
    primary_type: str | None = None
    secondary_id: str | None = None
    secondary_type: str | None = None

    def to_dict(self) -> dict:
        out: dict = {"name": self.name}
        if self.short_name:
            out["short_name"] = self.short_name
        if self.primary_id is not None:
            out["primary_id"] = self.primary_id
            out["primary_type"] = self.primary_type
            if self.secondary_id is not None:
                out["secondary_id"] = self.secondary_id
                out["secondary_type"] = self.secondary_type
        elif self.wikipedia:
            out["wikipedia"] = self.wikipedia
        return out


@dataclass(frozen=True)
class FocusTarget:
    """A resolved map focus target with the display name to show in the ref."""

    primary_type: str
    primary_id: str
    secondary_type: str | None
    secondary_id: str | None
    name: str


class FocusResolver:
    """Resolve referenced QIDs to map focus targets (body or feature).

    ``located_on_physical_feature`` is same-body by construction in IAU
    nomenclature; ``location`` is most often the parent body but may
    occasionally name a sub-feature. The resolver tries feature (same
    body) first, then any body, to honor the "most precise wins" rule.

    The display name comes from canonical project data (IAU feature name
    or Object.name) — not the referenced Wikidata entity — so resolution
    works even when the parent's Wikidata payload only lives in
    ``nomenclature/`` (not ``referenced/``), which is the common case.
    """

    def __init__(
        self,
        body_by_qid: dict[str, tuple[str, str | None]],
        feature_by_qid_per_body: dict[str, dict[str, tuple[int, str]]],
    ) -> None:
        self._body_by_qid = body_by_qid
        self._feature_by_qid_per_body = feature_by_qid_per_body

    def resolve(self, qid: str, current_body_id: str) -> FocusTarget | None:
        per_body = self._feature_by_qid_per_body.get(current_body_id)
        if per_body and qid in per_body:
            feature_id, feature_name = per_body[qid]
            primary_type, primary_id = _split_object_id(current_body_id)
            return FocusTarget(
                primary_type=primary_type,
                primary_id=primary_id,
                secondary_type="feature",
                secondary_id=str(feature_id),
                name=feature_name,
            )
        target = self._body_by_qid.get(qid)
        if target:
            object_id, body_name = target
            if body_name is None:
                # Body row has no usable name to display — skip.
                return None
            primary_type, primary_id = _split_object_id(object_id)
            return FocusTarget(
                primary_type=primary_type,
                primary_id=primary_id,
                secondary_type=None,
                secondary_id=None,
                name=body_name,
            )
        return None


def _split_object_id(object_id: str) -> tuple[str, str]:
    """Split an ``<id_type>-<value>`` Object.id into its parts.

    Handles negative NAIF values like ``naif--164`` (the ``str.partition``
    split keeps everything after the first ``-`` intact).
    """
    prefix, sep, value = object_id.partition("-")
    if not sep:
        raise ValueError(f"Object id {object_id!r} missing id-type prefix")
    return prefix, value


def make_feature_entityref(body_id: str, feature_id: int, name: str) -> EntityRef:
    """EntityRef pointing at a feature on ``body_id``."""
    prefix, value = _split_object_id(body_id)
    return EntityRef(
        name=name,
        primary_type=prefix,
        primary_id=value,
        secondary_type="feature",
        secondary_id=str(feature_id),
    )


def make_body_entityref(object_id: str, name: str) -> EntityRef:
    """EntityRef pointing at a body (no secondary)."""
    prefix, value = _split_object_id(object_id)
    return EntityRef(name=name, primary_type=prefix, primary_id=value)


_INSTANCE_OF_IGNORED = {
    "Q3901935",  # superior planet (orbits further from the Sun)
    "Q844911",  # inferior planet (orbits closer to the Sun)
    "Q2517610",  # list article
    "Q6999",  # astronomical object (too generic)
    "Q2221906",  # geographic location (too generic)
}


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
    GlobalClaim("inception", "P571", "time"),
    GlobalClaim("dissolved", "P576", "time"),
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
    EntityRefClaim("operators", "P137", multiple=True),
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
    claims: dict,
    claim: GlobalClaim,
    qid: str,
    wikidata_entities: WikidataEntityCache | None,
) -> list | dict | float | str | None:
    """Dispatch a single GlobalClaim to the appropriate extractor."""
    kind, pid, multiple, needs_unit = (
        claim.kind,
        claim.pid,
        claim.multiple,
        claim.needs_unit,
    )
    if kind == "time":
        if pid == "P619":
            return _launch_date(claims, wikidata_entities)
        if multiple:
            return _all_times(claims, pid, wikidata_entities)
        return _single_time(claims, pid, qid, wikidata_entities)
    if kind == "quantity":
        return _single_quantity(claims, pid, needs_unit=needs_unit, qid=qid)
    if kind == "image":
        return _all_strings(claims, pid)
    if kind == "url":
        return _all_strings(claims, pid)
    return None


def extract_claims(
    claims: dict,
    qid: str,
    wikidata_entities: WikidataEntityCache | None = None,
    *,
    global_claims: tuple[GlobalClaim, ...] = GLOBAL_CLAIMS,
    entity_ref_claims: tuple[EntityRefClaim, ...] = ENTITY_REF_CLAIMS,
    route_temperature: bool = True,
) -> dict:
    """Extract target properties from raw Wikidata claims.

    Returns a flat dict with parsed values (not the raw claim structure).
    Pass alternative ``global_claims``/``entity_ref_claims`` tuples to drive
    extraction for a different entity class (e.g. IAU nomenclature features).
    ``route_temperature`` controls the object-specific P2076 nature-of-value
    routing — features have no temperature claims to disambiguate.
    """
    result: dict = {}

    for claim in global_claims:
        v = _extract_global(claims, claim, qid, wikidata_entities)
        if v:
            result[claim.key] = v

    if route_temperature:
        # P2076 (temperature): group by P1480/P5102 qualifier, then
        # disambiguate each group. P7422/P6591 from the loop above take
        # priority via setdefault.
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

    for claim in entity_ref_claims:
        if claim.multiple:
            qids = [
                q
                for q in _all_entity_qids(claims, claim.pid)
                if not claim.exclude_set or q not in claim.exclude_set
            ]
            if qids:
                result[claim.key] = qids
        else:
            if ref_qid := _single_entity_qid(claims, claim.pid, qid):
                result[claim.key] = ref_qid

    return result


def drop_covered_qids(extracted: dict, covered: set[str], obj_id: str) -> None:
    """Strip QIDs already shown via an authoritative field from Wikidata claims.

    Cross-refs by QID so a derived ref (e.g. a SATCAT constellation linked to a
    group page) isn't duplicated by the matching Wikidata claim (e.g. P361
    part_of). Mutates ``extracted``; claims we don't otherwise cover are kept.
    """
    if not covered:
        return
    for claim in ENTITY_REF_CLAIMS:
        val = extracted.get(claim.key)
        if val is None:
            continue
        if claim.multiple:
            kept = [q for q in val if q not in covered]
            if len(kept) != len(val):
                logger.info(
                    "Dropped covered QIDs from %s %s: %s",
                    obj_id,
                    claim.key,
                    [q for q in val if q in covered],
                )
                if kept:
                    extracted[claim.key] = kept
                else:
                    del extracted[claim.key]
        elif val in covered:
            logger.info("Dropped covered QID from %s %s: %s", obj_id, claim.key, val)
            del extracted[claim.key]


def resolve_entity_ref(
    qid: str,
    lang: str,
    wikidata_entities: WikidataEntityCache,
    *,
    focus_resolver: FocusResolver | None = None,
    focus_body_id: str | None = None,
) -> EntityRef | None:
    """Resolve a QID to an ``EntityRef`` using downloaded entity data.

    When a ``focus_resolver`` is provided and the QID maps to a known map
    target, the ref carries primary/secondary focus fields and the wiki
    link is dropped — the frontend opens the target's drawer instead, and
    that drawer already exposes the wiki link. Callers gate by claim key
    (e.g. only ``located_on_*`` and ``location`` should be focus-resolved,
    not ``named_after``). Focus targets get their display name from
    canonical project data, so they don't require ``referenced/`` payload.
    """
    focus = None
    if focus_resolver is not None and focus_body_id is not None:
        focus = focus_resolver.resolve(qid, focus_body_id)
    if focus is not None:
        return EntityRef(
            name=focus.name,
            primary_type=focus.primary_type,
            primary_id=focus.primary_id,
            secondary_type=focus.secondary_type,
            secondary_id=focus.secondary_id,
        )

    wd = wikidata_entities.get_referenced(qid)
    if not wd:
        return None
    name = wd["labels"].get(lang)
    if not name:
        return None
    ref = EntityRef(name=name)
    short = _shortest_ref_name(name, lang, wd)
    if short:
        ref.short_name = short
    title = wd["sitelinks"].get(lang)
    if title:
        ref.wikipedia = f"https://{lang}.wikipedia.org/wiki/{quote(title)}"

    return ref


def attach_country_group_link(ref: EntityRef, qid: str) -> None:
    """If ``qid`` is a known country, point the ref at its /g/country-<slug> page."""
    country = COUNTRY_BY_QID.get(qid)
    if country is None:
        return
    ref.primary_type = "group"
    ref.primary_id = f"{COUNTRY_SLUG_PREFIX}{country.slug}"


def _shortest_ref_name(label: str, lang: str, wd: WikidataEntity) -> str | None:
    """Return the shortest available short name for a referenced entity, or None.

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

    return None


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
    "P2044": [  # Elevation: prefer the highest-point measurement, then average
        "Q3393392",  # highest point
        _QID_AVERAGE,
        _QID_MEAN,
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
# Time properties where the earliest value wins when multiple remain at the
# same precision — e.g. an organisation's inception date often spans a
# predecessor founding and a later restructuring; we want the longer history.
_PICK_EARLIEST_TIME: set[str] = {"P571"}  # inception


def _qualifier_qid(stmt: dict, qual_prop: str) -> str | None:
    """Return the first QID from a qualifier property, or None."""
    for snak in stmt.get("qualifiers", {}).get(qual_prop, []):
        val = snak.get("datavalue", {}).get("value", {})
        if isinstance(val, dict) and "id" in val:
            return val["id"]
    return None


def _series_ordinal(stmt: dict) -> int | None:
    """Return the P1545 series ordinal of a statement, or None."""
    for snak in stmt.get("qualifiers", {}).get("P1545", []):
        val = snak.get("datavalue", {}).get("value")
        if isinstance(val, str) and val.lstrip("-").isdigit():
            return int(val)
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
            if not isinstance(url, str):
                continue
            host = (urlparse(url).hostname or "").lower()
            if host == "nasa.gov" or host.endswith(".nasa.gov"):
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


def _stmt_time(stmt: dict) -> tuple[int, str] | None:
    """Return (precision, time-string) from a statement's mainsnak, or None."""
    val = _stmt_value(stmt)
    if isinstance(val, dict) and "time" in val:
        return val.get("precision", 0), val["time"]
    return None


def _refined_time(
    stmt: dict, wikidata_entities: WikidataEntityCache | None
) -> tuple[int, str] | None:
    """Resolve a statement's P4241 (refine date) qualifier to a more precise time.

    P4241 points to an event entity that may carry a more precise timestamp on
    P585 (point in time) or P619 (date of spacecraft launch). Returns
    (precision, time) of the more precise time, or None.
    """
    if wikidata_entities is None:
        return None
    refine_qid = _qualifier_qid(stmt, "P4241")
    if not refine_qid:
        return None
    event = wikidata_entities.get_referenced(refine_qid)
    if not event:
        return None
    base = _stmt_time(stmt)
    base_precision = base[0] if base else 0
    for prop in ("P585", "P619"):
        for event_stmt in active_statements(event["claims"], prop):
            t = _stmt_time(event_stmt)
            if t and t[0] > base_precision:
                return t
    return None


def _stmt_times(
    claims: dict, prop: str, wikidata_entities: WikidataEntityCache | None
) -> list[tuple[int, str]]:
    """Extract (precision, time) pairs for a property, applying P4241 refinement."""
    entries: list[tuple[int, str]] = []
    for stmt in active_statements(claims, prop):
        refined = _refined_time(stmt, wikidata_entities)
        t = refined or _stmt_time(stmt)
        if t is not None:
            entries.append(t)
    return entries


def _all_times(
    claims: dict, prop: str, wikidata_entities: WikidataEntityCache | None = None
) -> list[str]:
    """Extract all time values, dropping less precise duplicates.

    Uses the Wikidata ``precision`` field (9 = year, 10 = month, 11 = day, …).
    When values at different precisions coexist, only the most precise are kept.
    Applies P4241 (refine date) qualifier resolution when a cache is provided.
    """
    entries = _stmt_times(claims, prop, wikidata_entities)
    if len(entries) <= 1:
        return [t for _, t in entries]
    max_prec = max(p for p, _ in entries)
    return [t for p, t in entries if p == max_prec]


def _single_time(
    claims: dict,
    prop: str,
    qid: str,
    wikidata_entities: WikidataEntityCache | None = None,
) -> str | None:
    """Extract the single time value from a claim as an ISO date string.

    Times sort lexicographically (ISO format with leading sign + zero-padded
    year), so ``min(vals)`` gives the earliest moment.
    """
    vals = list(dict.fromkeys(_all_times(claims, prop, wikidata_entities)))
    if len(vals) > 1:
        if prop in _PICK_EARLIEST_TIME:
            return min(vals)
        key = PID_TO_KEY.get(prop, prop)
        logger.critical(
            "Multiple time values for %s on %s: %s — picking first", key, qid, vals
        )
    return vals[0] if vals else None


def _launch_date(
    claims: dict, wikidata_entities: WikidataEntityCache | None
) -> str | None:
    """Extract the launch date (P619), picking the earliest when multiple.

    Each statement's P4241 (refine date) qualifier is resolved before picking,
    so the chosen value uses the more precise time when available.
    """
    entries = _stmt_times(claims, "P619", wikidata_entities)
    if not entries:
        return None
    return min(entries, key=lambda t: t[1])[1]


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

    # Prefer by qualifier value (checked across the common disambiguation
    # qualifiers Wikidata uses for "what kind of measurement is this").
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
                _qualifier_qid(s, "P31"),  # instance of (value's kind)
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

    # Distinguished only by series ordinal (P1545): pick the lowest ordinal.
    ordinals = [(_series_ordinal(s), p) for s, p in pairs]
    if any(o is not None for o, _ in ordinals):
        return min(ordinals, key=lambda t: (t[0] is None, t[0]))[1]

    key = PID_TO_KEY.get(prop, prop)
    logger.critical(
        "Multiple quantity values for %s on %s: %s — picking first",
        key,
        qid,
        [p for _, p in pairs],
    )
    return pairs[0][1]


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


def _single_entity_qid(claims: dict, prop: str, qid: str) -> str | None:
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
        logger.critical(
            "Multiple entity values for %s on %s: %s — picking first", key, qid, vals
        )
    return vals[0] if vals else None


def _all_entity_qids(claims: dict, prop: str) -> list[str]:
    """Extract all entity QIDs from a claim."""
    return [
        val["id"]
        for val in _claim_values(claims, prop)
        if isinstance(val, dict) and "id" in val
    ]


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
