"""Download JPL's planetary-satellite physical parameters table to JSON.

The page (ssd.jpl.nasa.gov/sats/phys_par/) gives the GM of each satellite with
its 1σ and the ephemeris that fitted it (JUP365, PLU060, …). It is the only GM
source here that states an uncertainty, so it tells a measured GM from an
upper limit or a value that the fit could not constrain.
"""

import json
import logging
import re
from datetime import timedelta

import httpx
from bs4 import BeautifulSoup, Tag

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader, DownloadError
from space_map_data.utils.paths import SOURCES_POSITION_DIR

logger = logging.getLogger(__name__)

PHYSICAL_URL = "https://ssd.jpl.nasa.gov/sats/phys_par/"

# The columns before the radius and density groups: planet, satellite, code,
# then the GM value, sigma and ephemeris.
_GM_CELLS = 6


def _number(cell: str) -> float | None:
    """A printed value, None for an empty cell or "n/a"."""
    try:
        return float(cell)
    except ValueError:
        return None


def _printed(cell: str) -> str | None:
    """A printed value as its text, None for an empty cell or "n/a"."""
    return cell if _number(cell) is not None else None


def _own_text(td: Tag) -> str:
    """The text of a cell without the cells nested in it.

    The page leaves its cells unclosed, so each cell holds the next ones.
    """
    parts = [
        child if isinstance(child, str) else child.get_text()
        for child in td.children
        if not (isinstance(child, Tag) and child.name == "td")
    ]
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def parse_table(html: str) -> list[dict]:
    """One record per satellite: its NAIF id and its GM as the table prints it.

    ``gm_km3_s2`` is the printed text ("4.30"), whose digits say to what
    precision the fit is known. An upper limit ("<0.0002") keeps its bound and
    sets ``gm_upper_limit``. A GM of 0 is kept as the table prints it.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table#sat_phys_par")
    if table is None:
        raise DownloadError("physical parameters table not found — layout changed")
    rows: list[dict] = []
    for tr in table.select("tbody tr"):
        cells = [_own_text(td) for td in tr.find_all("td")]
        if len(cells) < _GM_CELLS:
            logger.warning("Skipping a short row of the JPL table: %s", cells)
            continue
        planet, name, code, gm, sigma, ephemeris = cells[:_GM_CELLS]
        upper_limit = gm.startswith("<")
        rows.append(
            {
                "planet": planet,
                "name": name,
                "naif_id": int(code),
                "gm_km3_s2": _printed(gm.lstrip("<")),
                "gm_sigma_km3_s2": _number(sigma),
                "gm_upper_limit": upper_limit,
                "ephemeris": ephemeris or None,
            }
        )
    return rows


class JPLSatellitePhysicalDownloader(Downloader):
    name = PROVIDERS.JPL_SATELLITE_PHYSICAL
    # JPL updates the table when a satellite ephemeris is refitted.
    max_age = timedelta(days=30)

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = SOURCES_POSITION_DIR / "jpl_satellite_physical"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        logger.info("Downloading JPL satellite physical parameters...")
        response = self.client.get(PHYSICAL_URL)
        if response.status_code in (403, 404):
            raise DownloadError(f"HTTP {response.status_code} — stopping")
        response.raise_for_status()

        rows = parse_table(response.text)
        if not rows:
            raise DownloadError("parsed zero satellite rows")

        (self.out_dir / "satellites.json").write_text(json.dumps(rows, indent=2))
        logger.info("Parsed %d satellite rows", len(rows))
        self._save_metadata(PHYSICAL_URL, len(rows), complete=True)
