"""Download Wikidata entities for objects in the space-map database."""

import json
import logging
import time
from collections.abc import Collection
from pathlib import Path

from tqdm import tqdm

from space_map_data.constants.providers import ID_TYPES, PROVIDERS
from space_map_data.download.downloader import Downloader
from space_map_data.download.providers.wikidata.id_resolver import WikidataIdResolver
from space_map_data.download.providers.wikidata.qids import ORBIT_CLASS_QIDS
from space_map_data.export.objects.wikidata_claims import ENTITY_REF_CLAIMS, PID_TO_KEY
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)

API_URL = "https://www.wikidata.org/w/api.php"

ENTITY_BATCH_SIZE = 50
AFTER_REQUEST_DELAY_SECONDS = 2  # pls don't ban me


class WikidataDownloader(Downloader):
    name = PROVIDERS.WIKIDATA

    _OBJECT_ID_TYPES = [
        ID_TYPES.NAIF,
        ID_TYPES.SPKID,
        ID_TYPES.MPC_DESIGNATION,
        ID_TYPES.NORAD_SATCAT,
        ID_TYPES.COSPAR,
        ID_TYPES.PROVISIONAL_DESIGNATION,
        ID_TYPES.NAME,
    ]

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        session = get_session()
        ids_dir = self.out_dir / "ids"

        resolver = WikidataIdResolver(self.client, session, ids_dir, self.metadata_file)

        # Resolve and fetch objects (all sources except IAU features)
        object_qids = resolver.resolve(self._OBJECT_ID_TYPES)
        objects_dir = self.out_dir / "objects"
        objects_dir.mkdir(exist_ok=True)
        self._fetch_entities(
            object_qids, objects_dir, limit=limit, fetch_desc="objects"
        )

        # Resolve and fetch IAU nomenclature features separately
        nomenclature_qids = resolver.resolve([ID_TYPES.IAU_FEATURE_ID])
        nomenclature_dir = self.out_dir / "nomenclature"
        nomenclature_dir.mkdir(exist_ok=True)
        self._fetch_entities(
            nomenclature_qids, nomenclature_dir, limit=limit, fetch_desc="nomenclature"
        )

        # Fetch orbit class entities into their own directory
        orbit_class_qids = {qid for qid in ORBIT_CLASS_QIDS.values() if qid is not None}
        orbit_classes_dir = self.out_dir / "orbit_classes"
        orbit_classes_dir.mkdir(exist_ok=True)
        self._fetch_entities(
            orbit_class_qids, orbit_classes_dir, limit=None, fetch_desc="orbit classes"
        )

        # Second pass: fetch referenced entities and units
        referenced_dir = self.out_dir / "referenced"
        referenced_dir.mkdir(exist_ok=True)
        units_dir = self.out_dir / "units"
        units_dir.mkdir(exist_ok=True)
        primary_dirs = [objects_dir, nomenclature_dir]
        all_dirs = [*primary_dirs, referenced_dir, units_dir]
        referenced_qids, unit_qids = self._collect_secondary_qids(
            primary_dirs, all_dirs
        )
        if referenced_qids:
            logger.info(
                "Fetching %d referenced entities (discoverers, named-after)",
                len(referenced_qids),
            )
            self._fetch_entities(
                referenced_qids,
                referenced_dir,
                limit=None,
                fetch_desc="referenced",
            )
        if unit_qids:
            logger.info("Fetching %d unit entities", len(unit_qids))
            self._fetch_entities(unit_qids, units_dir, limit=None, fetch_desc="units")

        # Fetch property entities (P-IDs) for label localization
        properties_dir = self.out_dir / "properties"
        properties_dir.mkdir(exist_ok=True)
        property_pids = PID_TO_KEY.keys() - {
            f.stem for f in properties_dir.glob("P*.json")
        }
        if property_pids:
            logger.info("Fetching %d property entities", len(property_pids))
            self._fetch_entities(
                property_pids, properties_dir, limit=None, fetch_desc="properties"
            )

        all_count = len(object_qids) + len(nomenclature_qids)
        self._save_metadata(
            API_URL,
            all_count,
            complete=limit is None or all_count <= limit,
            ids_complete=resolver.ids_complete(),
        )

    # -- Referenced entities --

    @staticmethod
    def _on_disk(dirs: list[Path]) -> set[str]:
        """Return QIDs already saved in any of the given directories."""
        return {f.stem for d in dirs for f in d.glob("Q*.json")}

    def _collect_secondary_qids(
        self, primary_dirs: list[Path], all_dirs: list[Path]
    ) -> tuple[set[str], set[str]]:
        """Scan downloaded entities and return (referenced_qids, unit_qids)."""
        referenced: set[str] = set()
        units: set[str] = set()
        for entity_file in (f for d in primary_dirs for f in d.glob("Q*.json")):
            try:
                entity = json.loads(entity_file.read_text())
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to read %s: %s", entity_file, exc)
                continue
            claims = entity.get("claims", {})
            for prop in (c.pid for c in ENTITY_REF_CLAIMS):
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
        # Unit QIDs should not be skipped just because they exist in referenced/.
        # A QID in referenced/ is not usable as a unit (localization only scans
        # units/), so we exclude only primary dirs + units/ when deduplicating.
        units_on_disk = self._on_disk(primary_dirs) | self._on_disk(
            [d for d in all_dirs if d.name == "units"]
        )
        return referenced - on_disk, units - units_on_disk

    # -- Entity fetching --

    def _fetch_entities(
        self,
        qids: Collection[str],
        entities_dir: Path,
        *,
        limit: int | None,
        fetch_desc: str = "wbgetentities",
    ) -> None:
        """Fetch full entity data via wbgetentities, saving one JSON per entity."""
        to_fetch = [qid for qid in qids if not (entities_dir / f"{qid}.json").exists()]
        if limit is not None:
            to_fetch = to_fetch[:limit]

        if not to_fetch:
            logger.info("All %s already downloaded", fetch_desc)
            return

        logger.info(
            "Fetching %s %s (%s already on disk)",
            f"{len(to_fetch):,}",
            fetch_desc,
            f"{len(qids) - len(to_fetch):,}",
        )

        batches = [
            to_fetch[i : i + ENTITY_BATCH_SIZE]
            for i in range(0, len(to_fetch), ENTITY_BATCH_SIZE)
        ]
        for batch in tqdm(batches, desc=fetch_desc, unit="batch"):
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
