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

from tqdm import tqdm

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader

logger = logging.getLogger(__name__)

QUERY_URL = "https://ssd-api.jpl.nasa.gov/sbdb_query.api"
OBJECT_URL = "https://ssd-api.jpl.nasa.gov/sbdb.api"
PER_REQUEST_DELAY_SECONDS = 1


class SBDBSatellitesDownloader(Downloader):
    name = PROVIDERS.SBDB_SATELLITES

    def _list_parents(self) -> list[str]:
        """Return SPK-IDs of all small bodies that have known satellites."""
        response = self.client.get(
            QUERY_URL,
            params={"fields": "spkid", "sb-sat": "true"},
        )
        response.raise_for_status()
        payload = response.json()
        spkids = [str(row[0]) for row in payload.get("data") or []]
        logger.info("SBDB lists %d small bodies with known satellites", len(spkids))
        return spkids

    def _fetch_object(self, spkid: str) -> dict:
        response = self.client.get(
            OBJECT_URL,
            params={"spk": spkid, "sat": "1", "full-prec": "true"},
        )
        response.raise_for_status()
        return response.json()

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        spkids = self._list_parents()

        to_fetch = [s for s in spkids if not (self.out_dir / f"{s}.json").exists()]
        already = len(spkids) - len(to_fetch)
        if already:
            logger.info("%d satellite payloads already on disk, skipping", already)

        if limit is not None and len(to_fetch) > limit:
            logger.info(
                "Limiting fetch to %d of %d remaining parents", limit, len(to_fetch)
            )
            to_fetch = to_fetch[:limit]

        for spkid in tqdm(
            to_fetch, desc="SBDB satellites", unit="obj", dynamic_ncols=True
        ):
            try:
                payload = self._fetch_object(spkid)
            except Exception as exc:
                logger.warning(
                    "Failed to fetch satellites for spkid %s: %s", spkid, exc
                )
                continue

            if not payload.get("sat"):
                logger.warning(
                    "spkid %s reported sb-sat=true but response had no sat array",
                    spkid,
                )
                continue

            (self.out_dir / f"{spkid}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2)
            )
            time.sleep(PER_REQUEST_DELAY_SECONDS)

        on_disk = sum(1 for _ in self.out_dir.glob("*.json"))
        self._save_metadata(
            OBJECT_URL,
            on_disk,
            complete=on_disk == len(spkids),
        )
