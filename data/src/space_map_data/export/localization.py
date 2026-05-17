"""Merge generated localization entries into frontend/messages/{lang}.json."""

import orjson
import logging

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.deepl import (
    MessageValue,
    load_translations as load_deepl_translations,
    lookup_translation,
)
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
GENERATED_PREFIXES = ("unit_name_", "unit_symbol_", "property_name_")

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


def _strip_generated(data: dict[str, MessageValue]) -> dict[str, MessageValue]:
    return {
        k: v
        for k, v in data.items()
        if not any(k.startswith(p) for p in GENERATED_PREFIXES)
    }


def write_messages(
    wikidata_entities: WikidataEntityCache,
    used_units: set[str],
) -> None:
    """Collect unit + property labels and merge them into frontend message files.

    For non-English languages, manual (non-generated) entries are replaced with
    DeepL translations pulled from ``DOWNLOAD_DIR/deepl/{lang}.json`` (produced
    by the download phase). Plural-variant en.json entries are expanded into
    the target locale's CLDR plural categories. Strings missing from the cache
    fall back to the existing translation, then to the English source.
    """
    unit_labels = _collect_unit_labels(wikidata_entities, used_units)
    property_labels = _collect_property_labels(wikidata_entities)

    en_file = MESSAGES_DIR / "en.json"
    en_manual: dict[str, MessageValue] = (
        _strip_generated(orjson.loads(en_file.read_bytes())) if en_file.exists() else {}
    )

    for lang in LANGUAGES:
        msg_file = MESSAGES_DIR / f"{lang}.json"
        existing: dict[str, MessageValue] = (
            orjson.loads(msg_file.read_bytes()) if msg_file.exists() else {}
        )

        if lang == "en":
            manual: dict[str, MessageValue] = _strip_generated(existing)
        else:
            existing_manual = _strip_generated(existing)
            translations = load_deepl_translations(lang)
            manual = {}
            untranslated: list[str] = []
            for key, en_value in en_manual.items():
                if not en_value:
                    manual[key] = en_value
                    continue
                translated = lookup_translation(translations, key, en_value, lang)
                if translated is None:
                    untranslated.append(key)
                    manual[key] = existing_manual.get(key, en_value)
                else:
                    manual[key] = translated
            if untranslated:
                logger.warning(
                    "DeepL cache missing %d translation(s) for %s; "
                    "keeping prior values where present (first few: %s) — "
                    "run `space-map-download deepl` to refresh",
                    len(untranslated),
                    lang,
                    untranslated[:5],
                )

        generated = {
            **unit_labels.get(lang, {}),
            **property_labels.get(lang, {}),
        }
        merged: dict[str, MessageValue] = {
            **manual,
            **dict(sorted(generated.items())),
        }

        msg_file.write_bytes(orjson.dumps(merged, option=orjson.OPT_INDENT_2))
        logger.info(
            "Wrote %d manual + %d generated keys to %s (%d total)",
            len(manual),
            len(generated),
            msg_file.name,
            len(merged),
        )
