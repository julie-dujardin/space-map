"""Download JPL's planetary-satellite discovery table to JSON.

The page (ssd.jpl.nasa.gov/sats/discovery.html) is the authoritative source for
natural-moon discovery years — it covers the obscure `S/20XX` irregulars that
Wikidata misses. Rows are grouped under per-planet header rows; we flatten them
to one record per moon for the ingest match.
"""

import json
import logging
from datetime import timedelta

import httpx
from bs4 import BeautifulSoup

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.utils.paths import SOURCES_POSITION_DIR

logger = logging.getLogger(__name__)

DISCOVERY_URL = "https://ssd.jpl.nasa.gov/sats/discovery.html"


def _parse_table(html: str) -> list[dict]:
    """Flatten the discovery table to {planet, iau_number, name, prov, year}."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.sat-discovery")
    if table is None:
        raise DownloadError("discovery table not found — page layout changed")
    rows: list[dict] = []
    planet = None
    for tr in table.select("tbody tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if "sat-discovery-planet" in (tr.get("class") or []):
            # Header cell reads e.g. "Satellites of Jupiter: 115".
            planet = cells[0].split("Satellites of", 1)[-1].split(":", 1)[0].strip()
        elif len(cells) >= 4:
            rows.append(
                {
                    "planet": planet,
                    "iau_number": cells[0] or None,
                    "name": cells[1] or None,
                    "provisional_designation": cells[2] or None,
                    "year": cells[3] or None,
                }
            )
    return rows


class JPLSatelliteDiscoveryDownloader(Downloader):
    name = PROVIDERS.JPL_SATELLITE_DISCOVERY
    # New irregulars get announced now and then; the table is one cheap page.
    max_age = timedelta(days=7)

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = SOURCES_POSITION_DIR / "jpl_satellite_discovery"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        logger.info("Downloading JPL satellite discovery table...")
        response = self.client.get(DISCOVERY_URL)
        if response.status_code in (403, 404):
            raise DownloadError(f"HTTP {response.status_code} — stopping")
        response.raise_for_status()

        rows = _parse_table(response.text)
        if not rows:
            raise DownloadError("parsed zero discovery rows")

        (self.out_dir / "moons.json").write_text(json.dumps(rows, indent=2))
        logger.info("Parsed %d moon discovery rows", len(rows))
        self._save_metadata(DISCOVERY_URL, len(rows), complete=True)
