"""Download Wikidata entities for objects in the space-map database."""

import json
import logging
import time
from pathlib import Path

from tqdm import tqdm

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader
from space_map_data.download.providers.wikidata.id_resolver import WikidataIdResolver
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)

API_URL = "https://www.wikidata.org/w/api.php"

ENTITY_BATCH_SIZE = 50
AFTER_REQUEST_DELAY_SECONDS = 2  # pls don't ban me

# Properties whose values are entity references we want to download
_REFERENCED_PROPERTIES = (
    "P61",  # discoverer
    "P138",  # named after
    "P65",  # site of discovery
    "P196",  # minor planet group
    "P720",  # spectral type
    "P744",  # asteroid family
    "P137",  # operator (spacecraft)
    "P176",  # manufacturer (spacecraft)
    "P375",  # launch vehicle (spacecraft)
    "P1427",  # launch site (spacecraft)
)


class WikidataDownloader(Downloader):
    name = PROVIDERS.WIKIDATA

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        session = get_session()
        ids_dir = self.out_dir / "ids"

        resolver = WikidataIdResolver(self.client, session, ids_dir, self.metadata_file)
        id_map = resolver.resolve_all()

        # Collect all unique QIDs and fetch root entities
        all_qids = sorted(
            {
                qid
                for group in id_map.values()
                for qids in group.values()
                for qid in qids
            }
        )
        entities_dir = self.out_dir / "entities"
        entities_dir.mkdir(exist_ok=True)
        self._fetch_entities(all_qids, entities_dir, limit=limit)

        # Second pass: fetch referenced entities and units
        referenced_dir = self.out_dir / "referenced"
        referenced_dir.mkdir(exist_ok=True)
        units_dir = self.out_dir / "units"
        units_dir.mkdir(exist_ok=True)
        all_dirs = [entities_dir, referenced_dir, units_dir]
        referenced_qids, unit_qids = self._collect_secondary_qids(
            entities_dir, all_dirs
        )
        if referenced_qids:
            logger.info(
                "Fetching %d referenced entities (discoverers, named-after)",
                len(referenced_qids),
            )
            self._fetch_entities(sorted(referenced_qids), referenced_dir, limit=None)
        if unit_qids:
            logger.info("Fetching %d unit entities", len(unit_qids))
            self._fetch_entities(sorted(unit_qids), units_dir, limit=None)

        self._save_metadata(
            API_URL,
            len(all_qids),
            complete=limit is None or len(all_qids) <= limit,
            ids_complete=resolver.ids_complete(),
        )

    # -- Referenced entities --

    @staticmethod
    def _on_disk(dirs: list[Path]) -> set[str]:
        """Return QIDs already saved in any of the given directories."""
        return {f.stem for d in dirs for f in d.glob("Q*.json")}

    def _collect_secondary_qids(
        self, entities_dir: Path, all_dirs: list[Path]
    ) -> tuple[set[str], set[str]]:
        """Scan downloaded entities and return (referenced_qids, unit_qids)."""
        referenced: set[str] = set()
        units: set[str] = set()
        for entity_file in entities_dir.glob("Q*.json"):
            try:
                entity = json.loads(entity_file.read_text())
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to read %s: %s", entity_file, exc)
                continue
            claims = entity.get("claims", {})
            for prop in _REFERENCED_PROPERTIES:
                for stmt in claims.get(prop, []):
                    dv = stmt.get("mainsnak", {}).get("datavalue", {}).get("value", {})
                    if isinstance(dv, dict) and "id" in dv:
                        referenced.add(dv["id"])
            for prop_stmts in claims.values():
                for stmt in prop_stmts:
                    dv = stmt.get("mainsnak", {}).get("datavalue", {}).get("value", {})
                    if isinstance(dv, dict) and "unit" in dv:
                        unit = dv["unit"]
                        if isinstance(unit, str) and "wikidata.org/entity/Q" in unit:
                            units.add(unit.rsplit("/", 1)[-1])
        on_disk = self._on_disk(all_dirs)
        return referenced - on_disk, units - on_disk

    # -- Entity fetching --

    def _fetch_entities(
        self, qids: list[str], entities_dir: Path, *, limit: int | None
    ) -> None:
        """Fetch full entity data via wbgetentities, saving one JSON per entity."""
        to_fetch = [qid for qid in qids if not (entities_dir / f"{qid}.json").exists()]
        if limit is not None:
            to_fetch = to_fetch[:limit]

        if not to_fetch:
            logger.info("All entities already downloaded")
            return

        logger.info(
            "Fetching %s entities (%s already on disk)",
            f"{len(to_fetch):,}",
            f"{len(qids) - len(to_fetch):,}",
        )

        batches = [
            to_fetch[i : i + ENTITY_BATCH_SIZE]
            for i in range(0, len(to_fetch), ENTITY_BATCH_SIZE)
        ]
        for batch in tqdm(batches, desc="wbgetentities", unit="batch"):
            response = self.client.get(
                API_URL,
                params={
                    "action": "wbgetentities",
                    "ids": "|".join(batch),
                    "format": "json",
                },
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()

            entities = data.get("entities", {})
            for qid, entity in entities.items():
                if "missing" in entity:
                    logger.warning("Entity %s not found", qid)
                    continue
                out_file = entities_dir / f"{qid}.json"
                out_file.write_text(json.dumps(entity, ensure_ascii=False, indent=2))

            time.sleep(AFTER_REQUEST_DELAY_SECONDS)
