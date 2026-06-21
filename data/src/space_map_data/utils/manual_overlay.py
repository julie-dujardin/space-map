"""Hand-authored overlays under ``sources/metadata/manual/``.

Same idea as the model ``manual/`` dir and Commons ``manual-extra.json``: data
the automated providers can't discover, merged at search/export time.

- ``aliases.json`` — ``{object_id: {lang: [alias, ...]}}``, extra search names.
- ``objects.json`` — objects with no DB row / position chunk, folded into the
  regular object bundles at export (export/manual.py):
  ``{id, wikidata_qid, parent_id, elements, radius_km, model_slug}``. Use an
  ``extra-<n>`` id so it routes to ``/u/<n>``. Each ``wikidata_qid`` is fetched
  into the manual Wikidata subdir so the Wikipedia downloader gives it a
  description.
"""

import logging

import orjson

from space_map_data.constants.providers import LANGUAGES
from space_map_data.utils.paths import SOURCES_MANUAL_DIR, SOURCES_METADATA_DIR

logger = logging.getLogger(__name__)

ALIASES_PATH = SOURCES_MANUAL_DIR / "aliases.json"
OBJECTS_PATH = SOURCES_MANUAL_DIR / "objects.json"

# Wikidata entities for manual objects live in their own subdir so the object
# ingest (which scans wikidata/objects) ignores them, while the Wikipedia
# downloader scans this dir too (see WikipediaDownloader._ENTITY_SUBDIRS).
MANUAL_WIKIDATA_DIR = SOURCES_METADATA_DIR / "wikidata" / "manual"


def read_manual_aliases() -> dict[str, dict[str, list[str]]]:
    """Return ``{object_id: {lang: [alias, ...]}}``; ``{}`` if absent/corrupt."""
    if not ALIASES_PATH.exists():
        return {}
    try:
        data = orjson.loads(ALIASES_PATH.read_bytes())
    except orjson.JSONDecodeError:
        logger.warning("Corrupt %s; ignoring", ALIASES_PATH)
        return {}
    out: dict[str, dict[str, list[str]]] = {}
    for obj_id, by_lang in data.items():
        if not isinstance(by_lang, dict):
            logger.warning("Skipping manual alias entry for %s: not a mapping", obj_id)
            continue
        cleaned = {
            lang: [str(a) for a in terms]
            for lang, terms in by_lang.items()
            if isinstance(terms, list) and terms
        }
        if cleaned:
            out[obj_id] = cleaned
    return out


def read_manual_objects() -> list[dict]:
    """Return the hand-authored object list; ``[]`` if absent/corrupt.

    Entries missing an ``id`` are dropped (logged) — every downstream consumer
    keys on it.
    """
    if not OBJECTS_PATH.exists():
        return []
    try:
        data = orjson.loads(OBJECTS_PATH.read_bytes())
    except orjson.JSONDecodeError:
        logger.warning("Corrupt %s; ignoring", OBJECTS_PATH)
        return []
    if not isinstance(data, list):
        logger.warning("%s is not a list; ignoring", OBJECTS_PATH)
        return []
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict) or not entry.get("id"):
            logger.warning("Skipping manual object with no id: %r", entry)
            continue
        out.append(entry)
    return out


def manual_object_labels(qid: str) -> dict[str, str]:
    """Per-language Wikidata labels for a manual object's QID, or ``{}``."""
    path = MANUAL_WIKIDATA_DIR / f"{qid}.json"
    if not path.exists():
        return {}
    entity = orjson.loads(path.read_bytes())
    labels = entity.get("labels", {})
    return {lang: labels[lang]["value"] for lang in LANGUAGES if lang in labels}
