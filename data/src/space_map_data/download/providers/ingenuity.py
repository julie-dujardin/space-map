"""Download the flights of the Ingenuity helicopter.

NASA's location map of Perseverance publishes two layers for the helicopter:
each airfield, and the ground track of each flight. Both give times as the
rover's spacecraft clock, so the clock kernel of Mars 2020 comes with them.
`probes/ingenuity_traverse.py` builds the traverse from these files.

On-disk layout::

    sources/position/ingenuity/m20_heli_waypoints.json
    sources/position/ingenuity/m20_heli_flight_path.json
    sources/position/ingenuity/m2020_168_sclkscet_refit_v19.tsc
"""

import json
import logging

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.constants.traverses.references import TRAVERSE_SOURCES
from space_map_data.download.downloader import Downloader, DownloadError
from space_map_data.utils.paths import SOURCES_POSITION_DIR

logger = logging.getLogger(__name__)

INGENUITY_DIR = SOURCES_POSITION_DIR / "ingenuity"

_LAYERS_URL = "https://mars.nasa.gov/mmgis-maps/M20/Layers/json"
_SCLK_URL = "https://naif.jpl.nasa.gov/pub/naif/pds/pds4/mars2020/mars2020_spice/spice_kernels/sclk"

WAYPOINTS_FILE = "m20_heli_waypoints.json"
FLIGHT_PATH_FILE = "m20_heli_flight_path.json"
# The last flight was in 2024. Every refit since then covers it.
SCLK_FILE = "m2020_168_sclkscet_refit_v19.tsc"

FILES = {
    WAYPOINTS_FILE: f"{_LAYERS_URL}/{WAYPOINTS_FILE}",
    FLIGHT_PATH_FILE: f"{_LAYERS_URL}/{FLIGHT_PATH_FILE}",
    SCLK_FILE: f"{_SCLK_URL}/{SCLK_FILE}",
}


def _check(name: str, body: bytes) -> int:
    """The record count of one file. Raises when the file is not what it
    should be."""
    if name == SCLK_FILE:
        if not body.startswith(b"KPL/SCLK"):
            raise DownloadError(f"{name}: not an SCLK kernel")
        return 1
    try:
        features = json.loads(body)["features"]
    except (ValueError, KeyError, TypeError) as e:
        raise DownloadError(f"{name}: not a feature collection") from e
    if not features:
        raise DownloadError(f"{name}: no features")
    return len(features)


class IngenuityDownloader(Downloader):
    """The airfields and ground tracks of Ingenuity, and the rover's clock."""

    name = PROVIDERS.INGENUITY

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.out_dir = INGENUITY_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def is_complete(self, limit: int | None) -> bool:
        return super().is_complete(limit) and all(
            (self.out_dir / name).exists() for name in FILES
        )

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        counts = {}
        for name, url in FILES.items():
            logger.info("Fetching %s", url)
            try:
                resp = self.client.get(url, timeout=120.0)
                resp.raise_for_status()
            except httpx.HTTPError as e:
                raise DownloadError(f"Failed to fetch {url}: {e}") from e
            counts[name] = _check(name, resp.content)
            (self.out_dir / name).write_bytes(resp.content)
            logger.info("Saved %s (%d records)", name, counts[name])
        self._save_metadata(
            url=TRAVERSE_SOURCES["m20_heli"].url,
            record_count=counts[FLIGHT_PATH_FILE],
            complete=True,
            airfields=counts[WAYPOINTS_FILE],
        )
