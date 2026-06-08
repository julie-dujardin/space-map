"""Merge generated localization entries into frontend/messages/{lang}.json."""

import orjson
import logging

from space_map_data.constants.earth_sats.launch_sites import LAUNCH_SITE_BY_SLUG
from space_map_data.constants.earth_sats.manufacturers import MANUFACTURER_BY_SLUG
from space_map_data.constants.earth_sats.operators import OPERATOR_BY_SLUG
from space_map_data.constants.feature_types import FEATURE_TYPES
from space_map_data.constants.providers import LANGUAGES
from space_map_data.constants.wikidata_qids import FEATURE_TYPE_QIDS
from space_map_data.export.groups.registry import (
    LAUNCH_SITE_SLUG_PREFIX,
    MANUFACTURER_SLUG_PREFIX,
    OPERATOR_SLUG_PREFIX,
    GROUPS,
    GroupType,
)
from space_map_data.export.objects.wikidata_claims import PID_TO_KEY, resolve_unit
from space_map_data.export.wikidata import (
    WikidataEntity,
    WikidataEntityCache,
    active_statements,
)
from space_map_data.utils.paths import PROJECT_ROOT, SOURCES_METADATA_DIR

logger = logging.getLogger(__name__)

MESSAGES_DIR = PROJECT_ROOT / "frontend" / "messages"
BASE_LOCALE = "en"

# All prefixes managed by this module — keys with these prefixes are removed
# before writing fresh ones, so hand-written keys are never touched.
GENERATED_PREFIXES = (
    "unit_name_",
    "unit_symbol_",
    "property_name_",
    "feature_type_label_",
    "feature_type_description_",
    "group_name_",
)

_UNIT_SYMBOL_PID = "P5061"

# Units whose labels must always be exported regardless of whether they appear
# in used_units (they bypass the normal UnitConverter path).
_ALWAYS_INCLUDE_UNITS: set[str] = {
    "degree_fahrenheit",
    "astronomical_unit",  # system scale orbital elements
    "hour",  # sbdb rot_per - rotation period
    "year",  # sbdb per_y - orbital period
    "jupiter_radius",  # exoplanet radii
    "kilometre_per_second",  # orbital speed readout
}

# Units with no Wikidata entity — reuse the same label/symbol across all languages.
_UNIT_FALLBACK_LABELS: dict[str, tuple[str, str]] = {
    "magnitude": ("magnitude", "magnitude"),
}


def _unit_qids() -> set[str]:
    """Return QIDs present in the units/ download directory."""
    units_dir = SOURCES_METADATA_DIR / "wikidata" / "units"
    if not units_dir.exists():
        return set()
    return {f.stem for f in units_dir.glob("Q*.json")}


def _extract_symbol(entity: WikidataEntity, lang: str) -> str | None:
    """Extract the unit symbol (P5061), preferring *lang* then ``mul`` (multilingual) then English."""
    stmts = active_statements(entity["claims"], _UNIT_SYMBOL_PID)
    for target in (lang, "mul", "en"):
        for stmt in stmts:
            dv = stmt.get("mainsnak", {}).get("datavalue", {}).get("value", {})
            if isinstance(dv, dict) and dv.get("language") == target:
                return dv.get("text")
    return None


def _collect_unit_labels(
    wikidata_entities: WikidataEntityCache,
    used_units: set[str],
) -> dict[str, dict[str, str]]:
    """Return {lang: {key: value}} for unit name and symbol entries.

    Only includes units whose normalized key appears in *used_units*.
    """
    qids = _unit_qids()
    if not qids:
        return {}

    # Build {normalized_english_key: (qid, entity)} mapping
    units: dict[str, tuple[str, WikidataEntity]] = {}
    for qid in sorted(qids):
        entity = wikidata_entities.get_referenced(qid)
        if not entity:
            continue
        key = resolve_unit(qid, wikidata_entities)
        if key and (key in used_units or key in _ALWAYS_INCLUDE_UNITS):
            units[key] = (qid, entity)

    if not units:
        return {}

    result: dict[str, dict[str, str]] = {}
    for lang in LANGUAGES:
        labels: dict[str, str] = {}
        for key, (_qid, entity) in units.items():
            label = entity["labels"].get(lang) or entity["labels"].get("en")
            if label:
                labels[f"unit_name_{key}"] = label

            symbol = _extract_symbol(entity, lang)
            if symbol:
                labels[f"unit_symbol_{key}"] = symbol
            elif label:
                labels[f"unit_symbol_{key}"] = label

        for key, (name, symbol) in _UNIT_FALLBACK_LABELS.items():
            labels[f"unit_name_{key}"] = name
            labels[f"unit_symbol_{key}"] = symbol

        result[lang] = labels

    return result


def _collect_property_labels(
    wikidata_entities: WikidataEntityCache,
) -> dict[str, dict[str, str]]:
    """Return {lang: {key: value}} for property name entries."""
    properties = wikidata_entities.property_items()
    if not properties:
        return {}

    result: dict[str, dict[str, str]] = {}
    for lang in LANGUAGES:
        labels: dict[str, str] = {}
        for pid, entity in sorted(properties.items()):
            key = PID_TO_KEY.get(pid)
            if not key:
                continue
            label = entity["labels"].get(lang) or entity["labels"].get("en")
            if label:
                labels[f"property_name_{key}"] = label
        result[lang] = labels

    return result


def _collect_feature_type_labels(
    wikidata_entities: WikidataEntityCache,
) -> dict[str, dict[str, str]]:
    """Return {lang: {key: value}} for IAU feature type labels and descriptions.

    Only emits entries for locales that actually have a Wikidata
    label/description — missing translations are left out so Paraglide's
    compile-time baseLocale fallback fills them in. Codes without a Wikidata
    QID (CL/LF/LO/ST) and any field gap in baseLocale itself are backfilled
    from ``FEATURE_TYPES`` so the baseLocale JSON always has every key.
    """
    result: dict[str, dict[str, str]] = {lang: {} for lang in LANGUAGES}
    base = result[BASE_LOCALE]

    for code, qid in FEATURE_TYPE_QIDS.items():
        label_key = f"feature_type_label_{code}"
        desc_key = f"feature_type_description_{code}"
        entity = wikidata_entities.get_feature_type(qid) if qid else None

        if entity:
            for lang in LANGUAGES:
                if label := entity["labels"].get(lang):
                    result[lang][label_key] = label[:1].upper() + label[1:]
                if desc := entity["descriptions"].get(lang):
                    result[lang][desc_key] = desc[:1].upper() + desc[1:]

        # Fall back to the in-repo IAU constants for the baseLocale where
        # Wikidata didn't provide a value (or had no entity at all).
        fallback = FEATURE_TYPES[code]
        base.setdefault(label_key, fallback.singular)
        base.setdefault(desc_key, fallback.description)

    return result


def _collect_group_name_labels(
    wikidata_entities: WikidataEntityCache,
) -> dict[str, dict[str, str]]:
    """Return {lang: {group_name_<slug>: label}}, deduped by QID.

    A company that is both operator and manufacturer ships under one slug
    only — its sibling shares the same display name. Country and orbit-class
    groups are skipped: countries resolve from the ISO code via
    ``Intl.DisplayNames``, and orbit classes reuse the autogenerated
    ``orbit_class_<NAME>`` keys already shipped for the body-detail view.
    """
    result: dict[str, dict[str, str]] = {lang: {} for lang in LANGUAGES}
    base = result[BASE_LOCALE]
    seen_qids: set[str] = set()

    for group in GROUPS:
        if group.type in (GroupType.COUNTRY, GroupType.ORBIT_CLASS):
            continue
        if group.wikidata_qid and group.wikidata_qid in seen_qids:
            continue
        key = f"group_name_{group.slug}"
        if group.wikidata_qid:
            seen_qids.add(group.wikidata_qid)
            entity = wikidata_entities.get_referenced(group.wikidata_qid)
            if entity:
                for lang in LANGUAGES:
                    if label := entity["labels"].get(lang):
                        result[lang][key] = label
        base.setdefault(key, _group_fallback_name(group))

    return result


def _group_fallback_name(group) -> str:
    if group.type is GroupType.OPERATOR:
        op = OPERATOR_BY_SLUG.get(group.slug.removeprefix(OPERATOR_SLUG_PREFIX))
        if op is not None:
            return op.name
    elif group.type is GroupType.LAUNCH_SITE:
        site = LAUNCH_SITE_BY_SLUG.get(group.slug.removeprefix(LAUNCH_SITE_SLUG_PREFIX))
        if site is not None:
            return site.name
    elif group.type is GroupType.MANUFACTURER:
        mfr = MANUFACTURER_BY_SLUG.get(
            group.slug.removeprefix(MANUFACTURER_SLUG_PREFIX)
        )
        if mfr is not None:
            return mfr.name
    return group.slug


def write_messages(
    wikidata_entities: WikidataEntityCache,
    used_units: set[str],
) -> None:
    """Collect unit + property labels and merge them into frontend message files."""
    unit_labels = _collect_unit_labels(wikidata_entities, used_units)
    property_labels = _collect_property_labels(wikidata_entities)
    feature_type_labels = _collect_feature_type_labels(wikidata_entities)
    group_name_labels = _collect_group_name_labels(wikidata_entities)

    for lang in LANGUAGES:
        msg_file = MESSAGES_DIR / f"{lang}.json"
        if msg_file.exists():
            existing = orjson.loads(msg_file.read_bytes())
        else:
            existing = {}

        # Strip old generated keys
        manual = {
            k: v
            for k, v in existing.items()
            if not any(k.startswith(p) for p in GENERATED_PREFIXES)
        }

        # Merge fresh generated keys
        generated = {
            **unit_labels.get(lang, {}),
            **property_labels.get(lang, {}),
            **feature_type_labels.get(lang, {}),
            **group_name_labels.get(lang, {}),
        }
        merged = {**manual, **dict(sorted(generated.items()))}

        msg_file.write_bytes(orjson.dumps(merged, option=orjson.OPT_INDENT_2))
        logger.info(
            "Wrote %d generated keys to %s (%d total)",
            len(generated),
            msg_file.name,
            len(merged),
        )


def write_group_messages(wikidata_entities: WikidataEntityCache) -> None:
    """Refresh only ``group_name_*`` keys; leave other generated keys intact."""
    group_name_labels = _collect_group_name_labels(wikidata_entities)

    for lang in LANGUAGES:
        msg_file = MESSAGES_DIR / f"{lang}.json"
        existing = orjson.loads(msg_file.read_bytes()) if msg_file.exists() else {}
        preserved = {
            k: v for k, v in existing.items() if not k.startswith("group_name_")
        }
        fresh = group_name_labels.get(lang, {})
        merged = {**preserved, **dict(sorted(fresh.items()))}
        msg_file.write_bytes(orjson.dumps(merged, option=orjson.OPT_INDENT_2))
        logger.info(
            "Refreshed %d group_name_* keys in %s (%d total)",
            len(fresh),
            msg_file.name,
            len(merged),
        )
