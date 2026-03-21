"""Write localization/units/<lang>.json files with localized unit labels and symbols."""

import json
import logging
from pathlib import Path

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.objects.wikidata_claims import resolve_unit
from space_map_data.export.wikidata import WikidataEntity
from space_map_data.utils.paths import DOWNLOAD_DIR

logger = logging.getLogger(__name__)

_UNIT_SYMBOL_PID = "P5061"


def _unit_qids() -> set[str]:
    """Return QIDs present in the units/ download directory."""
    units_dir = DOWNLOAD_DIR / "wikidata" / "units"
    if not units_dir.exists():
        return set()
    return {f.stem for f in units_dir.glob("Q*.json")}


def _extract_symbol(entity: WikidataEntity, lang: str) -> str | None:
    """Extract the unit symbol (P5061) for a given language, falling back to English."""
    for stmt in entity["claims"].get(_UNIT_SYMBOL_PID, []):
        dv = stmt.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if isinstance(dv, dict) and dv.get("language") == lang:
            return dv.get("text")
    # Fallback to English
    if lang != "en":
        for stmt in entity["claims"].get(_UNIT_SYMBOL_PID, []):
            dv = stmt.get("mainsnak", {}).get("datavalue", {}).get("value", {})
            if isinstance(dv, dict) and dv.get("language") == "en":
                return dv.get("text")
    return None


def write_unit_labels(
    out_dir: Path,
    wikidata_entities: dict[str, WikidataEntity],
) -> None:
    """Write per-language unit label JSON files.

    Each file is a flat {key: string} map with keys like:
      - unit_kilogram → localized label
      - unit_symbol_kilogram → localized symbol (e.g. "kg")
    """
    qids = _unit_qids()
    if not qids:
        logger.info("No unit entities found, skipping unit labels")
        return

    # Build {normalized_english_key: (qid, entity)} mapping
    units: dict[str, tuple[str, WikidataEntity]] = {}
    for qid in sorted(qids):
        entity = wikidata_entities.get(qid)
        if not entity:
            continue
        key = resolve_unit(qid, wikidata_entities)
        if key:
            units[key] = (qid, entity)

    if not units:
        logger.info("No unit labels resolved, skipping")
        return

    labels_dir = out_dir / "localization" / "units"
    labels_dir.mkdir(parents=True, exist_ok=True)

    for lang in LANGUAGES:
        labels: dict[str, str] = {}
        for key, (_qid, entity) in units.items():
            # Label: target lang → English fallback
            label = entity["labels"].get(lang) or entity["labels"].get("en")
            if label:
                labels[f"unit_{key}"] = label

            # Symbol: target lang → English fallback → English label fallback
            symbol = _extract_symbol(entity, lang)
            if symbol:
                labels[f"unit_symbol_{key}"] = symbol
            elif label:
                labels[f"unit_symbol_{key}"] = entity["labels"].get("en", label)

        out_file = labels_dir / f"{lang}.json"
        out_file.write_text(json.dumps(labels, ensure_ascii=False, indent=2))
        logger.info("Wrote %d unit entries to %s", len(labels), out_file.name)
