"""Download Wikidata entities for objects in the space-map database."""

import json
import logging
import time
from collections.abc import Collection
from pathlib import Path

import httpx
from tqdm import tqdm

from space_map_data.constants.earth_sats import all_wikidata_qids as earth_sats_qids
from space_map_data.constants.earth_sats.orbit_class import EarthOrbitClass
from space_map_data.constants.nomenclature.feature_types import FEATURE_TYPES
from space_map_data.constants.nomenclature.quadrangles import quadrangle_qids
from space_map_data.constants.providers import ID_TYPES, PROVIDERS
from space_map_data.constants.small_bodies import ORBIT_CLASS_QIDS
from space_map_data.download.downloader import Downloader
from space_map_data.download.providers.wikidata.id_resolver import WikidataIdResolver
from space_map_data.export.nomenclature.wikidata_claims import (
    FEATURE_ENTITY_REF_CLAIMS,
    FEATURE_PID_TO_KEY,
)
from space_map_data.export.objects.wikidata_claims import (
    ENTITY_REF_CLAIMS,
    GLOBAL_CLAIMS,
    PID_TO_KEY,
)
from space_map_data.probes.probe_id import load_qids as load_probe_qids
from space_map_data.utils.db import get_session
from space_map_data.utils.paths import SOURCES_METADATA_DIR

logger = logging.getLogger(__name__)

API_URL = "https://www.wikidata.org/w/api.php"

ENTITY_BATCH_SIZE = 50
AFTER_REQUEST_DELAY_SECONDS = 2  # pls don't ban me


class WikidataDownloader(Downloader):
    name = PROVIDERS.WIKIDATA

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = SOURCES_METADATA_DIR / "wikidata"
        self.out_dir.mkdir(parents=True, exist_ok=True)

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

        resolver = WikidataIdResolver(self.client, session, ids_dir)

        # Resolve and fetch objects (all sources except IAU features)
        object_qids = resolver.resolve(self._OBJECT_ID_TYPES)
        # Probe QIDs are hand-curated in spice/probe_ids.json (no external
        # ID property gets us there via SPARQL), so seed them directly.
        object_qids |= load_probe_qids()
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

        # Fetch IAU feature-type entities (one per 2-letter IAU code that has a
        # Wikidata counterpart). Used at export time to emit localized
        # label/description messages for the frontend nomenclature popover.
        feature_type_qids = {
            ft.qid for ft in FEATURE_TYPES.values() if ft.qid is not None
        }
        feature_types_dir = self.out_dir / "feature_types"
        feature_types_dir.mkdir(exist_ok=True)
        self._fetch_entities(
            feature_type_qids,
            feature_types_dir,
            limit=None,
            fetch_desc="feature types",
        )

        # Fetch QIDs declared in earth-sat constant catalogs (operators,
        # constellations, launch sites). They aren't necessarily reachable via
        # entity claims on satellites, so seed them directly.
        referenced_dir = self.out_dir / "referenced"
        referenced_dir.mkdir(exist_ok=True)
        self._fetch_entities(
            earth_sats_qids(),
            referenced_dir,
            limit=None,
            fetch_desc="earth-sat catalogs",
        )
        # Orbit-class group QIDs (small-body + earth-sat zones). Group bundles
        # and the Wikipedia downloader resolve group QIDs from referenced/.
        orbit_class_qids = {
            qid
            for qid in (
                *ORBIT_CLASS_QIDS.values(),
                *(c.qid for c in EarthOrbitClass),
            )
            if qid is not None
        }
        self._fetch_entities(
            orbit_class_qids, referenced_dir, limit=None, fetch_desc="orbit classes"
        )
        # IAU planetary quadrangles (Mercury/Mars/Venus). Not reachable via
        # feature claims — features carry quad_code/quad_name from the IAU
        # XML, not a P706/P276 link to the quadrangle's Wikidata entity.
        self._fetch_entities(
            quadrangle_qids(),
            referenced_dir,
            limit=None,
            fetch_desc="quadrangles",
        )

        # Second pass: fetch referenced entities and units. Each primary tier
        # specifies its own follow set — nomenclature features add P276/P706
        # on top of the shared object refs without bloating the object scan.
        units_dir = self.out_dir / "units"
        units_dir.mkdir(exist_ok=True)
        shared_follow = tuple(c.pid for c in ENTITY_REF_CLAIMS)
        # Dedup since FEATURE_ENTITY_REF_CLAIMS overlaps with the shared set
        # (P31, P138) — extracting twice would just hit the same statements.
        feature_follow = tuple(
            dict.fromkeys(
                shared_follow + tuple(c.pid for c in FEATURE_ENTITY_REF_CLAIMS)
            )
        )
        primary_scans = [
            (objects_dir, shared_follow),
            (nomenclature_dir, feature_follow),
        ]
        all_dirs = [objects_dir, nomenclature_dir, referenced_dir, units_dir]
        referenced_qids, unit_qids = self._collect_secondary_qids(
            primary_scans, all_dirs
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
        all_pids = PID_TO_KEY.keys() | FEATURE_PID_TO_KEY.keys()
        property_pids = all_pids - {f.stem for f in properties_dir.glob("P*.json")}
        if property_pids:
            logger.info("Fetching %d property entities", len(property_pids))
            self._fetch_entities(
                property_pids, properties_dir, limit=None, fetch_desc="properties"
            )

        all_count = len(object_qids) + len(nomenclature_qids)
        self._save_metadata(
            API_URL,
            all_count,
            complete=False,
        )

    # -- Referenced entities --

    @staticmethod
    def _on_disk(dirs: list[Path]) -> set[str]:
        """Return QIDs already saved in any of the given directories."""
        return {f.stem for d in dirs for f in d.glob("Q*.json")}

    def _collect_secondary_qids(
        self,
        primary_scans: list[tuple[Path, tuple[str, ...]]],
        all_dirs: list[Path],
    ) -> tuple[set[str], set[str]]:
        """Scan downloaded entities and return (referenced_qids, unit_qids).

        Each primary scan is ``(dir, follow_pids)`` so different entity classes
        can follow different reference properties (e.g. nomenclature adds
        ``P276``/``P706``).
        """
        referenced: set[str] = set()
        units: set[str] = set()
        time_pids = tuple(c.pid for c in GLOBAL_CLAIMS if c.kind == "time")
        for primary_dir, follow_pids in primary_scans:
            for entity_file in primary_dir.glob("Q*.json"):
                try:
                    entity = json.loads(entity_file.read_text())
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning("Failed to read %s: %s", entity_file, exc)
                    continue
                claims = entity.get("claims", {})
                for prop in follow_pids:
                    for stmt in claims.get(prop, []):
                        dv = (
                            stmt.get("mainsnak", {})
                            .get("datavalue", {})
                            .get("value", {})
                        )
                        if isinstance(dv, dict) and "id" in dv:
                            referenced.add(dv["id"])
                # P4241 (refine date) qualifier targets an event entity whose own
                # time claim provides a more precise timestamp. It can appear on
                # any time property (e.g. P619 launch_date, P575 discovery_date).
                for prop in time_pids:
                    for stmt in claims.get(prop, []):
                        for snak in stmt.get("qualifiers", {}).get("P4241", []):
                            dv = snak.get("datavalue", {}).get("value", {})
                            if isinstance(dv, dict) and "id" in dv:
                                referenced.add(dv["id"])
                for prop_stmts in claims.values():
                    for stmt in prop_stmts:
                        dv = (
                            stmt.get("mainsnak", {})
                            .get("datavalue", {})
                            .get("value", {})
                        )
                        if isinstance(dv, dict) and "unit" in dv:
                            unit = dv["unit"]
                            if (
                                isinstance(unit, str)
                                and "wikidata.org/entity/Q" in unit
                            ):
                                units.add(unit.rsplit("/", 1)[-1])
        primary_dirs = [d for d, _ in primary_scans]
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
