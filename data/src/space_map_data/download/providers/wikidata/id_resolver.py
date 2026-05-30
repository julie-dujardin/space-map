"""Resolve space-map object IDs to Wikidata QIDs via SPARQL."""

import csv
import io
import logging
import time
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tqdm import tqdm

from space_map_data.constants.earth_sats.constellations import (
    CONSTELLATIONS,
    SatelliteCategory,
)
from space_map_data.constants.providers import ID_TYPE_TO_WIKIDATA_PID, ID_TYPES
from space_map_data.models.feature import Feature
from space_map_data.models.object import Object, SBDB
from space_map_data.models.object.satcat import Satcat

# Satellite constellations to exclude
# individual constellation members don't have meaningful Wikidata entries.
# Only included massive constellations, the smaller constellations in PREFIX_TO_SLUG can have meaningful entries
CONSTELLATION_PREFIXES = [
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
] + [
    prefix
    for c in CONSTELLATIONS
    if set(c.category) & {SatelliteCategory.DEBRIS, SatelliteCategory.ROCKET}
    and c.prefix
    for prefix in ((c.prefix,) if isinstance(c.prefix, str) else c.prefix)
]

logger = logging.getLogger(__name__)

SPARQL_URL = "https://query.wikidata.org/sparql"

SPARQL_BATCH_SIZE = 1000
NAME_BATCH_SIZE = 200
AFTER_REQUEST_DELAY_SECONDS = 2  # pls don't ban me

# Each source maps to: (id_type, db_query_func_name, label)
SOURCES = (
    # Very few matches (ID_TYPES.NAIF, "_query_naif_ids", "Natural bodies (NAIF)"),  TODO only do majors/moons of majors
    (ID_TYPES.SPKID, "_query_small_body_spkids", "Small bodies (SPK-ID)"),
    # (  Too many IDs
    #     ID_TYPES.MPC_DESIGNATION,
    #     "_query_mpc_designations",
    #     "Small bodies (MPC designation)",
    # ),
    (ID_TYPES.NORAD_SATCAT, "_query_norad_ids", "Satellites (NORAD)"),
    (ID_TYPES.COSPAR, "_query_cospar_ids", "Satellites (COSPAR)"),
    # (  Too many IDs
    #     ID_TYPES.PROVISIONAL_DESIGNATION,
    #     "_query_provisional_designations",
    #     "Provisional designations",
    # ),
    (ID_TYPES.IAU_FEATURE_ID, "_query_iau_feature_ids", "IAU features"),
)


class WikidataIdResolver:
    """Resolve space-map object IDs to Wikidata QIDs.

    Results are saved incrementally as CSV files under ``ids_dir``:
    ``matches/<key>.csv`` for positive results, ``no_match/<key>.csv``
    for IDs queried with no Wikidata match.
    """

    def __init__(
        self,
        client: httpx.Client,
        session: Session,
        ids_dir: Path,
    ) -> None:
        self.client = client
        self.session = session
        self.ids_dir = ids_dir
        self._matches_dir = ids_dir / "matches"
        self._no_match_dir = ids_dir / "no_match"
        self._conflicts_dir = ids_dir / "conflicts"

    # -- Public API --

    def resolve(self, id_types: list[ID_TYPES] | None = None) -> set[str]:
        """Resolve ID sources and return all unique QIDs.

        Args:
            id_types: Which ID types to resolve. ``None`` means all
                (including name-based fallback). Include ``ID_TYPES.NAME``
                to enable the name-based search.

        IDs already present in match or no-match CSVs are skipped
        automatically, so partial runs resume where they left off.
        """
        self._matches_dir.mkdir(parents=True, exist_ok=True)
        self._no_match_dir.mkdir(parents=True, exist_ok=True)

        resolve_by_name = id_types is None or ID_TYPES.NAME in id_types

        sources = SOURCES
        if id_types is not None:
            allowed = set(id_types)
            sources = tuple(s for s in SOURCES if s[0] in allowed)

        for id_type, query_method_name, label in sources:
            pid = ID_TYPE_TO_WIKIDATA_PID[id_type]
            self._resolve_source(pid, query_method_name, label)

        # Name-based search for objects not resolved by ID
        # Skipped for now - too many queries, not useful enough (plenty of matches as is)
        # if resolve_by_name:
        #     resolved_qids = set()
        #     for csv_path in self._matches_dir.glob("*.csv"):
        #         for qids in self._read_ids_csv(csv_path.stem).values():
        #             resolved_qids.update(qids)
        #     self._resolve_by_name(resolved_qids)

        # Collect unique QIDs from the resolved sources
        all_qids: set[str] = set()
        for id_type, _, _ in sources:
            pid = ID_TYPE_TO_WIKIDATA_PID[id_type]
            for qids in self._read_ids_csv(pid).values():
                all_qids.update(qids)
        if resolve_by_name:
            for qids in self._read_ids_csv("name").values():
                all_qids.update(qids)

        # Merge in manually-resolved QIDs from conflicts/resolved_conflicts.csv,
        # filtered to entries whose object_id prefix matches the requested types.
        all_qids.update(self._read_resolved_conflict_qids(id_types))
        return all_qids

    # -- CSV helpers --

    def _ids_csv_path(self, key: str) -> Path:
        """Path to the match CSV file for a property or 'name'."""
        return self._matches_dir / f"{key}.csv"

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
        """Read all match CSV files into the full id_map structure."""
        id_map: dict[str, dict[str, list[str]]] = {}
        for csv_path in self._matches_dir.glob("*.csv"):
            key = csv_path.stem
            mapping = self._read_ids_csv(key)
            if mapping:
                id_map[key] = mapping
        return id_map

    # -- Resolved-conflict CSV --

    @staticmethod
    def _id_type_from_object_id(object_id: str) -> ID_TYPES | None:
        """Identify the ID_TYPES prefix of an object_id like ``naif--164``.

        Tolerates both the canonical ``<type>-<value>`` and a stray
        ``<type>:<value>`` form that has shown up in the manual CSV.
        """
        for id_type in ID_TYPES:
            prefix = str(id_type)
            if object_id.startswith(f"{prefix}-") or object_id.startswith(f"{prefix}:"):
                return id_type
        return None

    def _read_resolved_conflict_qids(self, id_types: list[ID_TYPES] | None) -> set[str]:
        """QIDs from resolved_conflicts.csv whose object_id prefix matches id_types."""
        csv_path = self._conflicts_dir / "resolved_conflicts.csv"
        if not csv_path.exists():
            return set()
        allowed = set(id_types) if id_types is not None else None
        qids: set[str] = set()
        skipped = 0
        for row in csv.reader(io.StringIO(csv_path.read_text())):
            if not row or len(row) < 2:
                continue
            object_id, qid = row[0].strip(), row[1].strip()
            if not object_id or not qid:
                continue
            id_type = self._id_type_from_object_id(object_id)
            if id_type is None:
                logger.warning(
                    "resolved_conflicts.csv: unrecognized id_type prefix in %r",
                    object_id,
                )
                skipped += 1
                continue
            if allowed is None or id_type in allowed:
                qids.add(qid)
        if skipped:
            logger.warning(
                "resolved_conflicts.csv: skipped %d row(s) with unknown prefix",
                skipped,
            )
        return qids

    # -- No-match CSV helpers --

    def _no_match_csv_path(self, key: str) -> Path:
        """Path to the no-match CSV for a property or 'name'."""
        return self._no_match_dir / f"{key}.csv"

    def _read_no_match_csv(self, key: str) -> set[str]:
        """Read IDs previously queried with no match."""
        csv_path = self._no_match_csv_path(key)
        if not csv_path.exists():
            return set()
        ids: set[str] = set()
        for row in csv.reader(io.StringIO(csv_path.read_text())):
            if row:
                ids.add(row[0])
        return ids

    def _append_no_match_csv(self, key: str, ids: list[str]) -> None:
        """Append IDs that had no SPARQL match, with today's date."""
        if not ids:
            return
        csv_path = self._no_match_csv_path(key)
        today = date.today().isoformat()
        buf = io.StringIO()
        writer = csv.writer(buf)
        for id_ in ids:
            writer.writerow([id_, today])
        with open(csv_path, "a") as f:
            f.write(buf.getvalue())

    # -- Resolution --

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
        # Also skip IDs previously queried with no match
        already_queried_no_match = self._read_no_match_csv(pid)
        already_known = already_resolved | already_queried_no_match
        if already_known:
            logger.info(
                "Resuming %s — %d resolved, %d no-match",
                pid,
                len(already_resolved),
                len(already_queried_no_match),
            )

        total = 0
        count = query_method(count_only=True)
        desc = f"SPARQL {pid} ({label})"

        with tqdm(total=count, desc=desc, unit="id") as pbar:
            for batch in query_method():
                total += len(batch)
                to_resolve = [id_ for id_ in batch if id_ not in already_known]
                pbar.update(len(batch))
                if not to_resolve:
                    continue

                resolved = self._sparql_resolve(pid, to_resolve)
                self._append_ids_csv(pid, resolved)
                # Record IDs that had no match
                no_match = [id_ for id_ in to_resolve if id_ not in resolved]
                self._append_no_match_csv(pid, no_match)
                already_known.update(to_resolve)

        logger.info("  %s: %d / %d resolved", pid, len(already_resolved), total)

    def _resolve_by_name(self, already_resolved_qids: set[str]) -> None:
        """Search Wikidata by object name for entities not found by ID."""
        already_resolved_names = set(self._read_ids_csv("name").keys())
        already_queried_no_match = self._read_no_match_csv("name")
        already_known = already_resolved_names | already_queried_no_match
        if already_known:
            logger.info(
                "Resuming name search — %d resolved, %d no-match",
                len(already_resolved_names),
                len(already_queried_no_match),
            )

        resolved_count = 0
        total = 0

        for batch in self._query_names():
            total += len(batch)
            to_resolve = [n for n in batch if n not in already_known]
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
                resolved_count += len(batch_mapping)
            # Record names that had no match (or only duplicate QIDs)
            no_match = [n for n in to_resolve if n not in batch_mapping]
            self._append_no_match_csv("name", no_match)
            already_known.update(to_resolve)
        logger.info(
            "  name: %d / %d resolved (excluding duplicates)", resolved_count, total
        )

    # -- DB query generators (yield batches of SPARQL_BATCH_SIZE) --

    def _query_naif_ids(self, *, count_only: bool = False) -> int | Iterator[list[str]]:
        """NAIF IDs for natural bodies → P2956."""
        stmt = select(Object.naif_id).where(Object.naif_id.is_not(None))
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
        stmt = select(SBDB.spkid).where(SBDB.spkid.is_not(None))
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
        obj_stmt = select(Object.norad_cat_id, Object.name).where(
            Object.norad_cat_id.is_not(None)
        )
        # Satcat rows not claimed by any Object via the satcat FK.
        claimed_subq = select(Object.satcat_norad_cat_id).where(
            Object.satcat_norad_cat_id.is_not(None)
        )
        satcat_stmt = select(Satcat.NORAD_CAT_ID, Satcat.OBJECT_NAME).where(
            Satcat.NORAD_CAT_ID.notin_(claimed_subq)
        )
        if count_only:
            # Approximate — includes constellations, but close enough for progress
            obj_count = (
                self.session.scalar(
                    select(func.count()).select_from(obj_stmt.subquery())
                )
                or 0
            )
            satcat_count = (
                self.session.scalar(
                    select(func.count()).select_from(satcat_stmt.subquery())
                )
                or 0
            )
            return obj_count + satcat_count

        def _generate() -> Iterator[list[str]]:
            seen: set[str] = set()
            batch: list[str] = []
            # Object-sourced NORAD IDs
            for norad_id, name in self.session.execute(obj_stmt):
                if name and any(
                    name.startswith(prefix) for prefix in CONSTELLATION_PREFIXES
                ):
                    continue
                norad_str = str(norad_id).zfill(5)
                seen.add(norad_str)
                batch.append(norad_str)
                if len(batch) >= SPARQL_BATCH_SIZE:
                    yield batch
                    batch = []
            # Satcat-only NORAD IDs (entries without Object rows)
            for norad_id, name in self.session.execute(satcat_stmt):
                norad_str = str(norad_id).zfill(5)
                if norad_str in seen:
                    continue
                if name and any(
                    name.startswith(prefix) for prefix in CONSTELLATION_PREFIXES
                ):
                    continue
                batch.append(norad_str)
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
        stmt = select(Object.mpc_designation).where(Object.mpc_designation.is_not(None))
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
        obj_stmt = select(Object.cospar_id, Object.name).where(
            Object.cospar_id.is_not(None)
        )
        claimed_subq = select(Object.satcat_norad_cat_id).where(
            Object.satcat_norad_cat_id.is_not(None)
        )
        satcat_stmt = select(Satcat.COSPAR_ID, Satcat.OBJECT_NAME).where(
            Satcat.NORAD_CAT_ID.notin_(claimed_subq),
            Satcat.COSPAR_ID.is_not(None),
        )
        if count_only:
            obj_count = (
                self.session.scalar(
                    select(func.count()).select_from(obj_stmt.subquery())
                )
                or 0
            )
            satcat_count = (
                self.session.scalar(
                    select(func.count()).select_from(satcat_stmt.subquery())
                )
                or 0
            )
            return obj_count + satcat_count

        def _generate() -> Iterator[list[str]]:
            seen: set[str] = set()
            batch: list[str] = []
            # Object-sourced COSPAR IDs
            for cospar_id, name in self.session.execute(obj_stmt):
                if name and any(
                    name.startswith(prefix) for prefix in CONSTELLATION_PREFIXES
                ):
                    continue
                cospar_str = str(cospar_id)
                seen.add(cospar_str)
                batch.append(cospar_str)
                if len(batch) >= SPARQL_BATCH_SIZE:
                    yield batch
                    batch = []
            # Satcat-only COSPAR IDs (entries without Object rows)
            for cospar_id, name in self.session.execute(satcat_stmt):
                cospar_str = str(cospar_id)
                if cospar_str in seen:
                    continue
                if name and any(
                    name.startswith(prefix) for prefix in CONSTELLATION_PREFIXES
                ):
                    continue
                batch.append(cospar_str)
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
            time.sleep(AFTER_REQUEST_DELAY_SECONDS)
            return response.json()["results"]["bindings"]

        raise RuntimeError("SPARQL rate limited after retries")
