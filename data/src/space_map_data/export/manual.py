"""Merge hand-authored manual objects into the regular object bundles.

The manual overlay (utils/manual_overlay.py) defines objects that have no DB row
or position chunk. We fold them straight into ``global_data``/``localized_data``
so they hash-bucket into the normal ``v1/objects`` bundles — from there detail,
the placeholder/scene path, and the search index treat them like any other
object. Their ``extra-<n>`` id prefix is what routes them to ``/u/<n>``.
"""

import logging

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.objects.wikidata_claims import (
    INSTANCE_OF_IGNORED,
    resolve_entity_ref,
)
from space_map_data.export.objects.wikipedia import load_wikipedia_summaries_for_qid
from space_map_data.export.objects.writer import ChunkObjectData
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.utils.manual_overlay import (
    manual_object_instance_of,
    manual_object_labels,
    read_manual_objects,
)

logger = logging.getLogger(__name__)


def _global(entry: dict, name: str) -> dict:
    """Language-independent bundle entry (mirrors export/objects/writer._build_global)."""
    e = entry.get("elements") or {}
    data: dict = {"id": entry["id"], "type": "spacecraft", "name": name}
    if entry.get("model_slug"):
        data["model_name"] = entry["model_slug"]
    if entry.get("wikidata_qid"):
        data["cross_refs"] = {"wikidata_qid": entry["wikidata_qid"]}
    if entry.get("radius_km"):
        data["sbdb"] = {"diameter": entry["radius_km"] * 2}
    # No `source`: these elements are hand-authored, not from an ephemeris
    # archive, so the frontend shows no data-source credit.
    data["orbit"] = {
        "epoch_jd": e.get("epoch"),
        "a": e.get("a"),
        "e": e.get("e"),
        "i": e.get("i"),
        "om": e.get("om"),
        "w": e.get("w"),
        "ma": e.get("ma"),
        "n": e.get("n"),
        "scale": "system",
        "parent_id": entry.get("parent_id"),
    }
    return data


def inject_manual_objects(
    data: ChunkObjectData, wikidata_entities: WikidataEntityCache
) -> None:
    """Fold manual-overlay objects into the object-bundle accumulators."""
    entries = read_manual_objects()
    if not entries:
        return
    for entry in entries:
        obj_id = entry["id"]
        qid = entry.get("wikidata_qid")
        labels = manual_object_labels(qid) if qid else {}
        summaries = load_wikipedia_summaries_for_qid(qid) if qid else {}
        instance_qids = (
            [q for q in manual_object_instance_of(qid) if q not in INSTANCE_OF_IGNORED]
            if qid
            else []
        )
        name = labels.get("en") or entry.get("name") or obj_id
        data.global_data[obj_id] = _global(entry, name)
        any_localized = False
        for lang in LANGUAGES:
            block: dict = {}
            if lang in labels:
                block["name"] = labels[lang]
            summary = summaries.get(lang)
            if summary:
                # `description` backs the search field; `wikipedia` the drawer.
                if summary.description or summary.extract:
                    block["description"] = summary.description or summary.extract
                block["wikipedia"] = summary.to_dict()
            # Wikidata P31 drives the displayed type (the header prefers it over
            # the placeholder "spacecraft" global type).
            refs = [
                ref.to_dict()
                for ref_qid in instance_qids
                if (ref := resolve_entity_ref(ref_qid, lang, wikidata_entities))
            ]
            if refs:
                block["instance_of"] = refs
            if block:
                data.localized_data[lang][obj_id] = block
                any_localized = True
        data.has_localized[obj_id] = any_localized
    logger.info("Injected %d manual objects into object bundles", len(entries))
