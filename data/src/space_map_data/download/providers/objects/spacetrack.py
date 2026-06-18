"""Download the current GP/TLE catalogue from Space-Track.

Space-Track's ``gp`` class is the live equivalent of CelesTrak's active GP
list — the latest element set for every on-orbit object, in CCSDS OMM CSV with
the same keywords. We fetch it once a day and write ``gp-active.csv`` under a
day-tiered tree mirroring the CelesTrak layout, so the export overlay and the
ingest catalogue consume it unchanged. Credentials come from the environment
(``SPACETRACK_IDENTITY`` / ``SPACETRACK_PASSWORD``); the API rejects anonymous
access and throttles aggressively, so we keep this to a single query per run.
"""

import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.utils.paths import SOURCES_POSITION_DIR

logger = logging.getLogger(__name__)

LOGIN_URL = "https://www.space-track.org/ajaxauth/login"
# Latest element set for every non-decayed object updated in the last 30 days —
# the active on-orbit catalogue, matching CelesTrak's GROUP=active but complete.
GP_QUERY = (
    "https://www.space-track.org/basicspacedata/query/class/gp"
    "/decay_date/null-val/epoch/%3Enow-30/orderby/NORAD_CAT_ID%20asc/format/csv"
)


class SpaceTrackDownloader(Downloader):
    name = PROVIDERS.SPACETRACK

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = SOURCES_POSITION_DIR / "spacetrack" / "current"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def _day_dir(self, day: date) -> Path:
        return self.out_dir / f"{day.year:04d}" / f"{day.month:02d}" / f"{day.day:02d}"

    def is_complete(self, limit: int | None) -> bool:
        # The GP catalogue is refetched every UTC day; skip only if today is done.
        if not self.metadata_file.exists():
            return False
        meta = json.loads(self.metadata_file.read_text())
        today = datetime.now(timezone.utc).date().isoformat()
        return meta.get("day") == today

    def _login(self) -> None:
        identity = os.environ.get("SPACETRACK_IDENTITY")
        password = os.environ.get("SPACETRACK_PASSWORD")
        if not identity or not password:
            raise DownloadError(
                "SPACETRACK_IDENTITY/SPACETRACK_PASSWORD not set — cannot "
                "authenticate to Space-Track"
            )
        logger.info("Authenticating to Space-Track as %s...", identity)
        resp = self.client.post(
            LOGIN_URL, data={"identity": identity, "password": password}
        )
        resp.raise_for_status()
        # Success returns an empty-string body (``""``); a failure returns a
        # non-empty ``{"Login":"Failed"}``-style payload.
        if resp.text.strip().strip('"'):
            raise DownloadError(f"Space-Track login failed: {resp.text[:120]!r}")

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        self._login()

        today = datetime.now(timezone.utc).date()
        day_dir = self._day_dir(today)
        day_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Downloading Space-Track GP catalogue...")
        resp = self.client.get(GP_QUERY)
        resp.raise_for_status()
        body = resp.text
        # The OMM CSV header leads with metadata columns; NORAD_CAT_ID is always
        # in it. Anything else (login HTML, JSON error) means the query failed.
        if "NORAD_CAT_ID" not in body[:2000]:
            raise DownloadError(f"Unexpected GP response: {body[:120]!r}")

        out_file = day_dir / "gp-active.csv"
        out_file.write_text(body)
        record_count = body.count("\n") - 1
        logger.info(
            "Saved %s GP records -> %s",
            f"{record_count:,}",
            out_file.relative_to(self.out_dir),
        )

        self._save_metadata(
            GP_QUERY, record_count, complete=True, day=today.isoformat()
        )
