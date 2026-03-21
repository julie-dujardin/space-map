"""Download Wikidata entities for objects in the space-map database."""

import csv
import io
import json
import logging
import time
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import func, select
from tqdm import tqdm

from space_map_data.constants.providers import (
    ID_TYPE_TO_WIKIDATA_PID,
    ID_TYPES,
    PROVIDERS,
)
from space_map_data.download.downloader import Downloader
from space_map_data.utils.db import get_session
from space_map_data.models.feature import Feature
from space_map_data.models.object import Object, SBDB

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

# Each source maps to: (id_type, db_query_func_name, label)
SOURCES = (
    (ID_TYPES.NAIF, "_query_naif_ids", "Natural bodies (NAIF)"),
    (ID_TYPES.SPKID, "_query_small_body_spkids", "Small bodies (SPK-ID)"),
    (
        ID_TYPES.MPC_DESIGNATION,
        "_query_mpc_designations",
        "Small bodies (MPC designation)",
    ),
    (ID_TYPES.NORAD_SATCAT, "_query_norad_ids", "Satellites (NORAD)"),
    (ID_TYPES.COSPAR, "_query_cospar_ids", "Satellites (COSPAR)"),
    (
        ID_TYPES.PROVISIONAL_DESIGNATION,
        "_query_provisional_designations",
        "Provisional designations",
    ),
    (ID_TYPES.IAU_FEATURE_ID, "_query_iau_feature_ids", "IAU features"),
)

NAME_BATCH_SIZE = 200


class WikidataDownloader(Downloader):
    name = PROVIDERS.WIKIDATA

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        self.session = get_session()
        id_map = self._load_or_resolve_id_map()

        # Collect all unique QIDs and fetch entities into entities/ subdir
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

        # Second pass: fetch entities referenced by claims (discoverers, named-after)
        referenced_qids = self._collect_referenced_qids(entities_dir)
        if referenced_qids:
            logger.info(
                "Fetching %d referenced entities (discoverers, named-after)",
                len(referenced_qids),
            )
            self._fetch_entities(sorted(referenced_qids), entities_dir, limit=limit)

        self._save_metadata(
            API_URL, len(all_qids), complete=limit is None or len(all_qids) <= limit
        )

    def _load_or_resolve_id_map(self) -> dict[str, dict[str, list[str]]]:
        """Load cached ID CSVs, resolve any missing sources, and return full map."""
        self._ids_dir = self.out_dir / "ids"
        self._ids_dir.mkdir(exist_ok=True)

        self._resolve_all()

        return self._load_all_ids()

    # -- CSV helpers --

    def _ids_csv_path(self, key: str) -> Path:
        """Path to the CSV file for a property or 'name'."""
        return self._ids_dir / f"{key}.csv"

    def _read_ids_csv(self, key: str) -> dict[str, list[str]]:
        """Read a property CSV back into a {search_term: [qids]} mapping."""
        csv_path = self._ids_csv_path(key)
        if not csv_path.exists():
            return {}
        mapping: dict[str, list[str]] = {}
        for row in csv.reader(io.StringIO(csv_path.read_text())):
            if not row:
                continue
            search_term = row[0]
            qids = row[1].split() if len(row) > 1 and row[1] else []
            mapping[search_term] = qids
        return mapping

    def _append_ids_csv(self, key: str, mapping: dict[str, list[str]]) -> None:
        """Append resolved rows to a property CSV."""
        if not mapping:
            return
        csv_path = self._ids_csv_path(key)
        buf = io.StringIO()
        writer = csv.writer(buf)
        for search_term, qids in mapping.items():
            writer.writerow([search_term, " ".join(qids)])
        with open(csv_path, "a") as f:
            f.write(buf.getvalue())

    def _load_all_ids(self) -> dict[str, dict[str, list[str]]]:
        """Read all CSV files from ids/ into the full id_map structure."""
        id_map: dict[str, dict[str, list[str]]] = {}
        for csv_path in self._ids_dir.glob("*.csv"):
            key = csv_path.stem
            mapping = self._read_ids_csv(key)
            if mapping:
                id_map[key] = mapping
        return id_map

    # -- Resolution --

    def _resolve_all(self) -> None:
        """Resolve missing ID groups against Wikidata, saving per-batch.

        Always runs each source — _resolve_source skips already-resolved terms,
        so partial CSVs from interrupted runs are resumed automatically.
        """
        for id_type, query_method_name, label in SOURCES:
            pid = ID_TYPE_TO_WIKIDATA_PID[id_type]
            self._resolve_source(pid, query_method_name, label)

        # Name-based search for objects not resolved by ID
        resolved_qids = set()
        for csv_path in self._ids_dir.glob("*.csv"):
            for qids in self._read_ids_csv(csv_path.stem).values():
                resolved_qids.update(qids)
        self._resolve_by_name(resolved_qids)

    def _resolve_source(
        self,
        pid: str,
        query_method_name: str,
        label: str,
    ) -> None:
        """Resolve a single source, appending to CSV after each batch."""
        query_method = getattr(self, query_method_name)

        # Load already-resolved search terms for resumability
        already_resolved = set(self._read_ids_csv(pid).keys())
        if already_resolved:
            logger.info(
                "Resuming %s — %d terms already resolved", pid, len(already_resolved)
            )

        total = 0
        count = query_method(count_only=True)
        desc = f"SPARQL {pid} ({label})"

        with tqdm(total=count, desc=desc, unit="id") as pbar:
            for batch in query_method():
                total += len(batch)
                to_resolve = [id_ for id_ in batch if id_ not in already_resolved]
                pbar.update(len(batch))
                if not to_resolve:
                    continue

                resolved = self._sparql_resolve(pid, to_resolve)
                self._append_ids_csv(pid, resolved)
                already_resolved.update(resolved.keys())

        logger.info("  %s: %d / %d resolved", pid, len(already_resolved), total)

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

    def _query_mpc_designations(
        self, *, count_only: bool = False
    ) -> int | Iterator[list[str]]:
        """MPC designations for small bodies → P5736."""
        stmt = select(Object.sbdb_mcp_designation).where(
            Object.sbdb_mcp_designation.is_not(None)
        )
        if count_only:
            return (
                self.session.scalar(select(func.count()).select_from(stmt.subquery()))
                or 0
            )
        return self._batched_scalars(stmt, str)

    def _query_cospar_ids(
        self, *, count_only: bool = False
    ) -> int | Iterator[list[str]]:
        """COSPAR IDs for non-constellation satellites → P247."""
        stmt = select(Object.celestrak_cospar_id, Object.name).where(
            Object.celestrak_cospar_id.is_not(None)
        )
        if count_only:
            return (
                self.session.scalar(select(func.count()).select_from(stmt.subquery()))
                or 0
            )

        def _generate() -> Iterator[list[str]]:
            batch: list[str] = []
            for cospar_id, name in self.session.execute(stmt):
                if name and any(
                    name.startswith(prefix) for prefix in CONSTELLATION_PREFIXES
                ):
                    continue
                batch.append(str(cospar_id))
                if len(batch) >= SPARQL_BATCH_SIZE:
                    yield batch
                    batch = []
            if batch:
                yield batch

        return _generate()

    def _query_provisional_designations(
        self, *, count_only: bool = False
    ) -> int | Iterator[list[str]]:
        """Provisional designations → P490."""
        stmt = select(Object.provisional_designation).where(
            Object.provisional_designation.is_not(None)
        )
        if count_only:
            return (
                self.session.scalar(select(func.count()).select_from(stmt.subquery()))
                or 0
            )
        return self._batched_scalars(stmt, str)

    def _query_iau_feature_ids(
        self, *, count_only: bool = False
    ) -> int | Iterator[list[str]]:
        """IAU planetary feature IDs → P2824."""
        stmt = select(Feature.feature_id).where(Feature.feature_id.is_not(None))
        if count_only:
            return (
                self.session.scalar(select(func.count()).select_from(stmt.subquery()))
                or 0
            )
        return self._batched_scalars(stmt, str)

    def _query_names(self) -> Iterator[list[str]]:
        """Object names for label-based Wikidata search."""
        stmt = select(Object.name).where(
            Object.name.is_not(None),
            Object.name != "",
        )

        def _generate() -> Iterator[list[str]]:
            batch: list[str] = []
            for name in self.session.scalars(stmt):
                assert name is not None
                if any(name.startswith(prefix) for prefix in CONSTELLATION_PREFIXES):
                    continue
                batch.append(name)
                if len(batch) >= NAME_BATCH_SIZE:
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

    def _sparql_resolve(self, prop: str, ids: list[str]) -> dict[str, list[str]]:
        """SPARQL query to resolve a batch of IDs to QIDs.

        Returns a dict mapping each ID to a list of QIDs (one ID may match
        multiple Wikidata entities).
        """
        values = " ".join(f'"{v}"' for v in ids)
        query = (
            f"SELECT ?item ?id WHERE {{\n"
            f"  VALUES ?id {{ {values} }}\n"
            f"  ?item wdt:{prop} ?id .\n"
            f"}}"
        )
        results = self._sparql_query(query)
        mapping: dict[str, list[str]] = {}
        for row in results:
            qid = row["item"]["value"].rsplit("/", 1)[-1]
            key = row["id"]["value"]
            mapping.setdefault(key, []).append(qid)
        for key, qids in mapping.items():
            if len(qids) > 1:
                logger.warning(
                    "  %s %s → multiple entities: %s", prop, key, ", ".join(qids)
                )
        return mapping

    def _resolve_by_name(self, already_resolved_qids: set[str]) -> dict[str, list[str]]:
        """Search Wikidata by object name for entities not found by ID."""
        already_resolved_names = set(self._read_ids_csv("name").keys())
        if already_resolved_names:
            logger.info(
                "Resuming name search — %d names already resolved",
                len(already_resolved_names),
            )

        mapping: dict[str, list[str]] = {}
        total = 0

        for batch in self._query_names():
            total += len(batch)
            to_resolve = [n for n in batch if n not in already_resolved_names]
            if not to_resolve:
                continue
            resolved = self._sparql_resolve_by_name(to_resolve)
            batch_mapping: dict[str, list[str]] = {}
            for name, qids in resolved.items():
                new_qids = [q for q in qids if q not in already_resolved_qids]
                if new_qids:
                    batch_mapping[name] = new_qids
            if batch_mapping:
                self._append_ids_csv("name", batch_mapping)
                mapping.update(batch_mapping)
                already_resolved_names.update(batch_mapping.keys())
        logger.info(
            "  name: %d / %d resolved (excluding duplicates)", len(mapping), total
        )
        return mapping

    def _sparql_resolve_by_name(self, names: list[str]) -> dict[str, list[str]]:
        """SPARQL query to resolve names to QIDs via label matching.

        Filters to entities that have at least one known astronomical property.
        """
        values = " ".join(f'"{n}"@en' for n in names)
        pid_filters = " UNION ".join(
            f"{{ ?item wdt:{pid} [] }}" for pid in ID_TYPE_TO_WIKIDATA_PID.values()
        )
        query = (
            f"SELECT ?item ?name WHERE {{\n"
            f"  VALUES ?name {{ {values} }}\n"
            f"  ?item rdfs:label ?name .\n"
            f"  {{ {pid_filters} }}\n"
            f"}}"
        )
        results = self._sparql_query(query)
        mapping: dict[str, list[str]] = {}
        for row in results:
            qid = row["item"]["value"].rsplit("/", 1)[-1]
            key = row["name"]["value"]
            mapping.setdefault(key, []).append(qid)
        for key, qids in mapping.items():
            if len(qids) > 1:
                logger.warning(
                    "  name '%s' → multiple entities: %s", key, ", ".join(qids)
                )
        return mapping

    def _sparql_query(self, query: str) -> list[dict]:
        """Execute a SPARQL query with rate limiting and retry on 429."""
        max_retries = 10
        for attempt in range(max_retries + 1):
            response = self.client.post(
                SPARQL_URL,
                data={"query": query},
                headers={"Accept": "application/sparql-results+json"},
                timeout=120.0,
            )
            if response.status_code == 429:
                retry_after_header = response.headers.get("retry-after")
                if retry_after_header:
                    retry_after = int(retry_after_header)
                else:
                    retry_after = 2 ** (attempt + 1)
                logger.warning("SPARQL 429 — retrying in %ds", retry_after)
                time.sleep(retry_after)
                continue
            response.raise_for_status()
            time.sleep(AFTER_RQUEST_DELAY_SECONDS)
            return response.json()["results"]["bindings"]

        raise RuntimeError("SPARQL rate limited after retries")

    # -- Referenced entities --

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

    def _collect_referenced_qids(self, entities_dir: Path) -> set[str]:
        """Scan downloaded entities for QID references in claims we care about."""
        referenced: set[str] = set()
        for entity_file in entities_dir.glob("Q*.json"):
            try:
                entity = json.loads(entity_file.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            claims = entity.get("claims", {})
            for prop in self._REFERENCED_PROPERTIES:
                for stmt in claims.get(prop, []):
                    dv = stmt.get("mainsnak", {}).get("datavalue", {}).get("value", {})
                    if isinstance(dv, dict) and "id" in dv:
                        referenced.add(dv["id"])
        # Subtract those already on disk
        on_disk = {f.stem for f in entities_dir.glob("Q*.json")}
        return referenced - on_disk

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
