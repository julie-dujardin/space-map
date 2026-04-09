"""Merge generated localization entries into frontend/messages/{lang}.json."""

import orjson
import logging

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.objects.wikidata_claims import PID_TO_KEY, resolve_unit
from space_map_data.export.wikidata import (
    WikidataEntity,
    WikidataEntityCache,
    active_statements,
)
from space_map_data.utils.paths import DOWNLOAD_DIR, PROJECT_ROOT

logger = logging.getLogger(__name__)

MESSAGES_DIR = PROJECT_ROOT / "frontend" / "messages"

# All prefixes managed by this module — keys with these prefixes are removed
# before writing fresh ones, so hand-written keys are never touched.
_GENERATED_PREFIXES = ("unit_name_", "unit_symbol_", "property_name_")

_UNIT_SYMBOL_PID = "P5061"

# Units whose labels must always be exported regardless of whether they appear
# in used_units (they bypass the normal UnitConverter path).
_ALWAYS_INCLUDE_UNITS: set[str] = {
    "degree_fahrenheit",
    "astronomical_unit",  # system scale orbital elements
    "hour",  # sbdb rot_per - rotation period
    "year",  # sbdb per_y - orbital period
}


def _unit_qids() -> set[str]:
    """Return QIDs present in the units/ download directory."""
    units_dir = DOWNLOAD_DIR / "wikidata" / "units"
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


def write_messages(
    wikidata_entities: WikidataEntityCache,
    used_units: set[str],
) -> None:
    """Collect unit + property labels and merge them into frontend message files."""
    unit_labels = _collect_unit_labels(wikidata_entities, used_units)
    property_labels = _collect_property_labels(wikidata_entities)

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
            if not any(k.startswith(p) for p in _GENERATED_PREFIXES)
        }

        # Merge fresh generated keys
        generated = {
            **unit_labels.get(lang, {}),
            **property_labels.get(lang, {}),
        }
        merged = {**manual, **dict(sorted(generated.items()))}

        msg_file.write_bytes(orjson.dumps(merged, option=orjson.OPT_INDENT_2))
        logger.info(
            "Wrote %d generated keys to %s (%d total)",
            len(generated),
            msg_file.name,
            len(merged),
        )
