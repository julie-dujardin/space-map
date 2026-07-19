"""Download satellite data for asteroids/comets with known moons.

The bulk SBDB Query API exposes a ``sats`` count per asteroid but not the
satellite payload (orbits, names, references). This downloader:

1. Queries SBDB Query for parents with at least one satellite (``sb-sat=true``).
2. Per parent, calls the per-object SBDB API with ``sat=1`` and saves the
   raw JSON as ``{spkid}.json``.
"""

import json
import logging
import time
from datetime import timedelta
from pathlib import Path

import httpx
from tqdm import tqdm

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader
from space_map_data.utils.paths import SOURCES_POSITION_DIR

logger = logging.getLogger(__name__)

QUERY_URL = "https://ssd-api.jpl.nasa.gov/sbdb_query.api"
OBJECT_URL = "https://ssd-api.jpl.nasa.gov/sbdb.api"
PER_REQUEST_DELAY_SECONDS = 1


class SBDBMoonsDownloader(Downloader):
    name = PROVIDERS.SBDB_MOONS
    # New satellite discoveries and refined orbits land irregularly.
    max_age = timedelta(days=7)

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = SOURCES_POSITION_DIR / "sbdb" / "moons"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def _list_parents(self) -> list[tuple[str, str | None]]:
        """Return ``(SPK-ID, designation)`` for all small bodies with satellites.

        The designation is carried so duplicate fetches can be suppressed: SBDB
        SPK-IDs drift for unnumbered bodies, so the same object reappears under a
        new SPK-ID that the filename existence check would miss.
        """
        response = self.client.get(
            QUERY_URL,
            params={"fields": "spkid,pdes", "sb-sat": "true"},
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data") or []
        logger.info("SBDB lists %d small bodies with known satellites", len(rows))
        return [(str(row[0]), row[1]) for row in rows]

    def _payload_index(self) -> dict[str, Path]:
        """Map designation (``object.des``) → saved payload path.

        SBDB SPK-IDs drift for unnumbered bodies, so a parent may already be
        on disk under a different SPK-ID than the query now reports.
        """
        index: dict[str, Path] = {}
        for path in self.out_dir.glob("*.json"):
            if path.name == "metadata.json":
                continue
            try:
                obj = json.loads(path.read_text()).get("object") or {}
            except (json.JSONDecodeError, OSError):
                logger.warning("Unreadable satellite payload %s, ignoring", path.name)
                continue
            des = obj.get("des")
            if des:
                index[des] = path
        return index

    def _fetch_object(self, spkid: str) -> dict:
        response = self.client.get(
            OBJECT_URL,
            params={"spk": spkid, "sat": "1", "full-prec": "true"},
        )
        response.raise_for_status()
        return response.json()

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        parents = self._list_parents()
        index = self._payload_index()

        # (spkid to fetch, existing payload path — possibly under a drifted
        # SPK-ID — to replace on success)
        to_fetch: list[tuple[str, Path | None]] = []
        fresh = 0
        for spkid, des in parents:
            direct = self.out_dir / f"{spkid}.json"
            existing = direct if direct.exists() else None
            if existing is None and des is not None:
                existing = index.get(des)
            if existing is not None and self._is_fresh(existing):
                fresh += 1
                continue
            to_fetch.append((spkid, existing))
        if fresh:
            logger.info("%d satellite payloads still fresh, skipping", fresh)

        if limit is not None and len(to_fetch) > limit:
            logger.info(
                "Limiting fetch to %d of %d stale/missing parents",
                limit,
                len(to_fetch),
            )
            to_fetch = to_fetch[:limit]

        for spkid, old_path in tqdm(
            to_fetch, desc="SBDB satellites", unit="obj", dynamic_ncols=True
        ):
            try:
                payload = self._fetch_object(spkid)
            except Exception as exc:
                logger.warning(
                    "Failed to fetch satellites for spkid %s: %s%s",
                    spkid,
                    exc,
                    " (keeping stale payload)" if old_path is not None else "",
                )
                continue

            if not payload.get("sat"):
                logger.warning(
                    "spkid %s reported sb-sat=true but response had no sat array",
                    spkid,
                )
                continue

            out_path = self.out_dir / f"{spkid}.json"
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
            if old_path is not None and old_path != out_path:
                # Ingest reads every payload, so the drifted-ID copy of the
                # same body must not survive alongside the fresh one.
                logger.info("Removing %s: SPK-ID drifted to %s", old_path.name, spkid)
                old_path.unlink()
            time.sleep(PER_REQUEST_DELAY_SECONDS)

        # Complete when every parent has a payload (fresh or not), directly or
        # via an aliased SPK-ID that shares its designation.
        final_index = self._payload_index()
        remaining = [
            spkid
            for spkid, des in parents
            if not (self.out_dir / f"{spkid}.json").exists()
            and not (des is not None and des in final_index)
        ]
        parent_ids = {spkid for spkid, _ in parents}
        parent_des = {des for _, des in parents if des is not None}
        orphans = [
            path.name
            for des, path in final_index.items()
            if des not in parent_des and path.stem not in parent_ids
        ]
        if orphans:
            logger.warning(
                "%d payloads no longer match any sb-sat parent (kept): %s",
                len(orphans),
                ", ".join(sorted(orphans)),
            )
        on_disk = sum(
            1 for p in self.out_dir.glob("*.json") if p.name != "metadata.json"
        )
        self._save_metadata(
            OBJECT_URL,
            on_disk,
            complete=not remaining,
        )
