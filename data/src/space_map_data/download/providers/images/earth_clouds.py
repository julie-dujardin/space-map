"""Download the live Earth cloud-cover texture from clouds.matteason.co.uk.

The upstream service derives near-real-time cloud cover from EUMETSAT data
and refreshes every 3h; the scheduler enforces our cadence. We grab the
highest-resolution PNG (with native alpha) and write it under a date-
partitioned path so historical snapshots are retained.

License: project is CC0; EUMETSAT data requires the attribution string
recorded in ``metadata.json`` for the texture-attribution pipeline.

On-disk layout::

    sources/textures/clouds/earth/yyyy/mm/dd/HH.png
    sources/textures/clouds/earth/metadata.json
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.utils.paths import SOURCES_TEXTURES_DIR

logger = logging.getLogger(__name__)

RESOLUTION = "8192x4096"
SOURCE_URL = f"https://clouds.matteason.co.uk/images/{RESOLUTION}/clouds-alpha.png"
ATTRIBUTION = "Contains modified EUMETSAT data"
SLOT_HOURS = 3


class EarthCloudsDownloader(Downloader):
    """Download the live Earth cloud-cover texture."""

    name = PROVIDERS.EARTH_CLOUDS

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = SOURCES_TEXTURES_DIR / "clouds" / "earth"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def _slot_path(self, now: datetime) -> Path:
        # Bucket by the upstream's UTC-aligned 3h slot so a startup-immediate
        # run for a slot we already fetched is a no-op.
        hour = (now.hour // SLOT_HOURS) * SLOT_HOURS
        return (
            self.out_dir
            / f"{now.year:04d}"
            / f"{now.month:02d}"
            / f"{now.day:02d}"
            / f"{hour:02d}.png"
        )

    def is_complete(self, limit: int | None) -> bool:
        return self._slot_path(datetime.now(timezone.utc)).exists()

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        target = self._slot_path(datetime.now(timezone.utc))
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            response = self.client.get(SOURCE_URL, timeout=120.0)
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise DownloadError(f"Failed to fetch {SOURCE_URL}: {e}") from e

        target.write_bytes(response.content)
        logger.info(
            "Saved %s (%s bytes) -> %s",
            target.name,
            f"{len(response.content):,}",
            target.relative_to(self.out_dir),
        )

        self._save_metadata(
            SOURCE_URL,
            1,
            complete=False,
            attribution=ATTRIBUTION,
        )
