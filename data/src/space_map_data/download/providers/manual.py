"""Fetch Wikidata entities for hand-authored manual objects.

Reads ``sources/metadata/manual/objects.json`` and pulls the Wikidata entity for
each entry's ``wikidata_qid`` into the manual Wikidata subdir. The Wikipedia
downloader scans that subdir too, so manual objects get descriptions through the
normal Wikipedia pipeline; the search index and export read labels + summaries
from there. P31 (instance of) targets are pulled into the shared ``referenced/``
dir so export can resolve them to localized type labels. See
utils/manual_overlay.py.
"""

import json
import logging
import time
from pathlib import Path

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader
from space_map_data.download.providers.wikidata.downloader import API_URL
from space_map_data.utils.manual_overlay import (
    MANUAL_WIKIDATA_DIR,
    manual_object_instance_of,
    read_manual_objects,
)
from space_map_data.utils.paths import SOURCES_MANUAL_DIR

logger = logging.getLogger(__name__)

# Referenced entities (P31 targets etc.) share the main wikidata cache dir so
# WikidataEntityCache.get_referenced finds them.
REFERENCED_DIR = MANUAL_WIKIDATA_DIR.parent / "referenced"


class ManualDownloader(Downloader):
    name = PROVIDERS.MANUAL

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        # metadata.json lives next to the hand-authored overlay files.
        self.out_dir = SOURCES_MANUAL_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        qids = sorted(
            {
                entry["wikidata_qid"]
                for entry in read_manual_objects()
                if entry.get("wikidata_qid")
            }
        )
        if not qids:
            logger.info("No manual objects with a wikidata_qid; nothing to fetch")
            self._save_metadata(API_URL, 0, complete=False)
            return

        MANUAL_WIKIDATA_DIR.mkdir(parents=True, exist_ok=True)
        to_fetch = [
            qid for qid in qids if not (MANUAL_WIKIDATA_DIR / f"{qid}.json").exists()
        ]
        for qid in to_fetch:
            self._fetch_entity(qid, MANUAL_WIKIDATA_DIR)
            time.sleep(1)

        # P31 targets feed the displayed type — resolve their labels via the
        # shared referenced/ cache (claims are on disk now for every qid).
        ref_qids = sorted({q for qid in qids for q in manual_object_instance_of(qid)})
        REFERENCED_DIR.mkdir(parents=True, exist_ok=True)
        ref_to_fetch = [
            q for q in ref_qids if not (REFERENCED_DIR / f"{q}.json").exists()
        ]
        for qid in ref_to_fetch:
            self._fetch_entity(qid, REFERENCED_DIR)
            time.sleep(1)

        logger.info(
            "Manual objects: %d wikidata entities, %d referenced types "
            "(%d + %d already on disk)",
            len(to_fetch),
            len(ref_to_fetch),
            len(qids) - len(to_fetch),
            len(ref_qids) - len(ref_to_fetch),
        )
        self._save_metadata(API_URL, len(qids), complete=False)

    def _fetch_entity(self, qid: str, out_dir: Path) -> None:
        """Fetch one Wikidata entity (labels + sitelinks + claims) via wbgetentities."""
        response = self.client.get(
            API_URL,
            params={"action": "wbgetentities", "ids": qid, "format": "json"},
            timeout=60.0,
        )
        response.raise_for_status()
        entity = response.json().get("entities", {}).get(qid)
        if entity is None or "missing" in entity:
            logger.warning("Manual object entity %s not found", qid)
            return
        (out_dir / f"{qid}.json").write_text(
            json.dumps(entity, ensure_ascii=False, indent=2)
        )
