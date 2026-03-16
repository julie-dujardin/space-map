"""Download Wikidata entities for objects in the space-map database."""

import json
import logging
import time
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import func, select
from tqdm import tqdm

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader
from space_map_data.utils.db import get_session
from space_map_data.models.body import Object, SBDB

logger = logging.getLogger(__name__)

SPARQL_URL = "https://query.wikidata.org/sparql"
API_URL = "https://www.wikidata.org/w/api.php"

SPARQL_BATCH_SIZE = 1000
ENTITY_BATCH_SIZE = 50
AFTER_RQUEST_DELAY_SECONDS = 2  # pls don't ban me

# Satellite constellations to exclude
# individual constellation members don't have meaningful Wikidata entries.
CONSTELLATION_PREFIXES = (
    "STARLINK",
    "ONEWEB",
    "IRIDIUM",
    "KUIPER",
    "QIANFAN",
    "HULIANWANG DIGUI",
    "GLOBALSTAR",
    "ORBCOMM",
    "FLOCK",
    "SPACEBEE",
    "SITRO-AIS",
    "GEESAT",
    "GONETS-M",
    "TIANQI",
    "CONNECTA IOT",
    "TIANMU-1",
)

# Each source maps to: (wikidata_property, db_query_func_name, label)
SOURCES = (
    ("P2956", "_query_naif_ids", "Natural bodies"),
    ("P716", "_query_small_body_spkids", "Named small bodies"),
    ("P377", "_query_norad_ids", "Satellites"),
)


class WikidataDownloader(Downloader):
    name = PROVIDERS.WIKIDATA

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        self.session = get_session()
        id_map = self._load_or_resolve_id_map()

        # Collect all unique QIDs and fetch entities into entities/ subdir
        all_qids = sorted({qid for group in id_map.values() for qid in group.values()})
        entities_dir = self.out_dir / "entities"
        entities_dir.mkdir(exist_ok=True)
        self._fetch_entities(all_qids, entities_dir, limit=limit)

        self._save_metadata(
            API_URL, len(all_qids), complete=limit is None or len(all_qids) <= limit
        )

    def _load_or_resolve_id_map(self) -> dict[str, dict[str, str]]:
        """Load cached id_map.json if it exists, otherwise resolve and save."""
        map_file = self.out_dir / "id_map.json"
        if map_file.exists():
            logger.info("Loading cached ID mapping from id_map.json")
            return json.loads(map_file.read_text())

        id_map = self._resolve_all()

        map_file.write_text(json.dumps(id_map, indent=2))
        logger.info("ID mapping saved -> id_map.json")
        return id_map

    def _resolve_all(self) -> dict[str, dict[str, str]]:
        """Resolve all ID groups against Wikidata, querying DB in batches."""
        id_map: dict[str, dict[str, str]] = {}

        for prop, query_method_name, label in SOURCES:
            query_method = getattr(self, query_method_name)
            mapping: dict[str, str] = {}
            total = 0

            count = query_method(count_only=True)

            desc = f"SPARQL {prop} ({label})"
            with tqdm(total=count, desc=desc, unit="id") as pbar:
                for batch in query_method():
                    total += len(batch)
                    resolved = self._sparql_resolve(prop, batch)
                    mapping.update(resolved)
                    pbar.update(len(batch))

            id_map[prop] = mapping
            logger.info("  %s: %d / %d resolved", prop, len(mapping), total)

        return id_map

    # -- DB query generators (yield batches of SPARQL_BATCH_SIZE) --

    def _query_naif_ids(self, *, count_only: bool = False) -> int | Iterator[list[str]]:
        """NAIF IDs for natural bodies → P2956."""
        stmt = select(Object.horizons_naif_id).where(
            Object.horizons_naif_id.is_not(None)
        )
        if count_only:
            return (
                self.session.scalar(select(func.count()).select_from(stmt.subquery()))
                or 0
            )
        return self._batched_scalars(stmt, str)

    def _query_small_body_spkids(
        self, *, count_only: bool = False
    ) -> int | Iterator[list[str]]:
        """SPK-IDs for named small bodies → P716."""
        stmt = select(SBDB.spkid).where(
            SBDB.name.is_not(None), SBDB.name != "", SBDB.spkid.is_not(None)
        )
        if count_only:
            return (
                self.session.scalar(select(func.count()).select_from(stmt.subquery()))
                or 0
            )
        return self._batched_scalars(stmt, str)

    def _query_norad_ids(
        self, *, count_only: bool = False
    ) -> int | Iterator[list[str]]:
        """NORAD catalog numbers for non-constellation satellites → P377."""
        stmt = select(Object.celestrak_norad_cat_id, Object.name).where(
            Object.celestrak_norad_cat_id.is_not(None)
        )
        if count_only:
            # Approximate — includes constellations, but close enough for progress
            return (
                self.session.scalar(select(func.count()).select_from(stmt.subquery()))
                or 0
            )

        def _generate() -> Iterator[list[str]]:
            batch: list[str] = []
            for norad_id, name in self.session.execute(stmt):
                if name and any(
                    name.startswith(prefix) for prefix in CONSTELLATION_PREFIXES
                ):
                    continue
                batch.append(str(norad_id))
                if len(batch) >= SPARQL_BATCH_SIZE:
                    yield batch
                    batch = []
            if batch:
                yield batch

        return _generate()

    def _batched_scalars(self, stmt, convert=None) -> Iterator[list[str]]:
        """Yield batches of scalar results from a query."""
        batch: list[str] = []
        for value in self.session.scalars(stmt):
            batch.append(convert(value) if convert else value)
            if len(batch) >= SPARQL_BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch

    # -- SPARQL --

    def _sparql_resolve(self, prop: str, ids: list[str]) -> dict[str, str]:
        """SPARQL query to resolve a batch of IDs to QIDs."""
        values = " ".join(f'"{v}"' for v in ids)
        query = (
            f"SELECT ?item ?id WHERE {{\n"
            f"  VALUES ?id {{ {values} }}\n"
            f"  ?item wdt:{prop} ?id .\n"
            f"}}"
        )
        results = self._sparql_query(query)
        mapping: dict[str, str] = {}
        for row in results:
            qid = row["item"]["value"].rsplit("/", 1)[-1]
            mapping[row["id"]["value"]] = qid
        return mapping

    def _sparql_query(self, query: str) -> list[dict]:
        """Execute a SPARQL query with rate limiting and retry on 429."""
        max_retries = 3
        for attempt in range(max_retries + 1):
            response = self.client.post(
                SPARQL_URL,
                data={"query": query},
                headers={"Accept": "application/sparql-results+json"},
                timeout=120.0,
            )
            if response.status_code == 429:
                wait = 2 ** (attempt + 1)
                logger.warning("SPARQL 429 — retrying in %ds", wait)
                time.sleep(wait)
                continue
            response.raise_for_status()
            time.sleep(AFTER_RQUEST_DELAY_SECONDS)
            return response.json()["results"]["bindings"]

        raise RuntimeError("SPARQL rate limited after retries")

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

            time.sleep(AFTER_RQUEST_DELAY_SECONDS)
