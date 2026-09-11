"""Download the live Earth cloud-cover texture from clouds.matteason.co.uk.

The upstream service derives near-real-time cloud cover from EUMETSAT data
and refreshes every 3h. Each run saves the current image. It then fills
missed slots from a GitHub mirror that publishes one release per refresh.
The mirror keeps the full-size PNG for recent weeks only. Older weeks become
2K and video archives, which we skip.

License: project is CC0; EUMETSAT data requires the attribution string
recorded in ``metadata.json`` for the texture-attribution pipeline.

On-disk layout::

    sources/textures/clouds/earth/yyyy/mm/dd/HH.png
    sources/textures/clouds/earth/metadata.json
"""

import logging
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.utils.paths import SOURCES_TEXTURES_DIR

logger = logging.getLogger(__name__)

RESOLUTION = "8192x4096"
SOURCE_URL = f"https://clouds.matteason.co.uk/images/{RESOLUTION}/clouds-alpha.png"
MIRROR_RELEASES_URL = (
    "https://api.github.com/repos/"
    "joshuabinswanger/matteason_live-cloud-maps_downloader/releases?per_page=100"
)
MIRROR_TAG_FORMAT = "maps-%Y%m%d_%H%M"
MIRROR_ASSET_PREFIX = "clouds_alpha_"
ATTRIBUTION = "Contains modified EUMETSAT data"
SLOT_HOURS = 3
IMAGE_TIMEOUT_S = 120.0


class EarthCloudsDownloader(Downloader):
    """Download the live Earth cloud-cover texture and backfill missed slots."""

    name = PROVIDERS.EARTH_CLOUDS

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = SOURCES_TEXTURES_DIR / "clouds" / "earth"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def _slot_path(self, when: datetime) -> Path:
        # Bucket by the upstream's UTC-aligned 3h slot so a startup-immediate
        # run for a slot we already fetched is a no-op.
        hour = (when.hour // SLOT_HOURS) * SLOT_HOURS
        return (
            self.out_dir
            / f"{when.year:04d}"
            / f"{when.month:02d}"
            / f"{when.day:02d}"
            / f"{hour:02d}.png"
        )

    def is_complete(self, limit: int | None) -> bool:
        return self._slot_path(datetime.now(timezone.utc)).exists()

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        self._fetch(SOURCE_URL, self._slot_path(datetime.now(timezone.utc)))
        self._save_metadata(
            SOURCE_URL,
            1,
            complete=False,
            attribution=ATTRIBUTION,
        )
        self._backfill()

    def _fetch(self, url: str, target: Path) -> None:
        try:
            response = self.client.get(url, timeout=IMAGE_TIMEOUT_S)
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise DownloadError(f"Failed to fetch {url}: {e}") from e

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        logger.info(
            "Saved %s bytes -> %s",
            f"{len(response.content):,}",
            target.relative_to(self.out_dir),
        )

    def _backfill(self) -> None:
        missing = [
            (target, url)
            for target, url in self._mirror_assets()
            if not target.exists()
        ]
        logger.info("Backfilling %d missed slots from the mirror", len(missing))
        failed = 0
        for target, url in missing:
            try:
                self._fetch(url, target)
            except DownloadError as e:
                logger.error("%s", e)
                failed += 1
        if failed:
            raise DownloadError(f"{failed} of {len(missing)} backfill slots failed")

    def _mirror_assets(self) -> Iterator[tuple[Path, str]]:
        """Yield ``(slot path, asset URL)`` for each full-size mirror release."""
        url: str | None = MIRROR_RELEASES_URL
        while url:
            try:
                response = self.client.get(
                    url, headers={"Accept": "application/vnd.github+json"}
                )
                response.raise_for_status()
            except httpx.HTTPError as e:
                raise DownloadError(f"Failed to list mirror releases: {e}") from e

            for release in response.json():
                tag = release["tag_name"]
                try:
                    when = datetime.strptime(tag, MIRROR_TAG_FORMAT)
                except ValueError:
                    logger.debug("Skipping mirror release %s: not a single slot", tag)
                    continue
                asset = next(
                    (
                        a
                        for a in release["assets"]
                        if a["name"].startswith(MIRROR_ASSET_PREFIX)
                        and a["name"].endswith(".png")
                    ),
                    None,
                )
                if asset is None:
                    logger.warning("Skipping mirror release %s: no alpha PNG", tag)
                    continue
                yield self._slot_path(when), asset["browser_download_url"]
            url = response.links.get("next", {}).get("url")
