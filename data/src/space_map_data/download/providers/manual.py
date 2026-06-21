"""Fetch Wikidata entities for hand-authored manual objects.

Reads ``sources/metadata/manual/objects.json`` and pulls the Wikidata entity for
each entry's ``wikidata_qid`` into the manual Wikidata subdir. The Wikipedia
downloader scans that subdir too, so manual objects get descriptions through the
normal Wikipedia pipeline; the search index and export read labels + summaries
from there. See utils/manual_overlay.py.
"""

import json
import logging
import time

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader
from space_map_data.download.providers.wikidata.downloader import API_URL
from space_map_data.utils.manual_overlay import MANUAL_WIKIDATA_DIR, read_manual_objects
from space_map_data.utils.paths import SOURCES_MANUAL_DIR

logger = logging.getLogger(__name__)


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
            self._fetch_entity(qid)
            time.sleep(1)

        logger.info(
            "Manual objects: %d wikidata entities (%d already on disk)",
            len(to_fetch),
            len(qids) - len(to_fetch),
        )
        self._save_metadata(API_URL, len(qids), complete=False)

    def _fetch_entity(self, qid: str) -> None:
        """Fetch one Wikidata entity (labels + sitelinks) via wbgetentities."""
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
        (MANUAL_WIKIDATA_DIR / f"{qid}.json").write_text(
            json.dumps(entity, ensure_ascii=False, indent=2)
        )
