"""Download the IAU Catalog of Star Names.

The IAU Working Group on Star Names publishes the adopted names as a table on
its own site. The table gives each name with its designation, its Hipparcos
number, and the date of adoption. The text file that older tools read stopped
in 2022.

Writes, below sources/stars/iau/:
- names.html      the page as served
- names.json      the rows of the table, keyed by its column titles
- metadata.json
"""

import json
import logging
from datetime import timedelta

import httpx
from bs4 import BeautifulSoup

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.utils.paths import SOURCES_STARS_DIR

logger = logging.getLogger(__name__)

PAGE_URL = "https://exopla.net/star-names/modern-iau-star-names/"
OUT_DIR = SOURCES_STARS_DIR / "iau"

NAME_COLUMN = "proper names"
REQUIRED_COLUMNS = frozenset({NAME_COLUMN, "Designation", "HIP"})
# The list had 452 names in 2022.
MIN_NAMES = 450
# The list grows. A withdrawn name is possible, a large loss is a broken page.
MIN_SHARE_OF_PREVIOUS = 0.95


def parse_names(html: str) -> list[dict[str, str]]:
    """The rows of the star-name table, keyed by its column titles."""
    for table in BeautifulSoup(html, "html.parser").find_all("table"):
        head, body = table.find("thead"), table.find("tbody")
        if head is None or body is None:
            continue
        titles = [
            cell.get_text(" ", strip=True) for cell in head.find_all(["th", "td"])
        ]
        if not REQUIRED_COLUMNS <= set(titles):
            continue
        names = []
        # Only the body: the foot holds the titles again, with filter fields.
        for row in body.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
            if len(cells) != len(titles):
                logger.warning("Skipped a row with %d cells: %r", len(cells), cells[:3])
                continue
            names.append(dict(zip(titles, cells)))
        return names
    raise DownloadError(f"No table with the columns {sorted(REQUIRED_COLUMNS)}")


class IAUStarNamesDownloader(Downloader):
    name = PROVIDERS.IAU_STAR_NAMES
    # The working group adopts names in batches, a few times a year.
    max_age = timedelta(days=30)

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.out_dir = OUT_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        response = self.client.get(PAGE_URL)
        response.raise_for_status()
        names = parse_names(response.text)
        unnamed = sum(1 for row in names if not row[NAME_COLUMN])
        floor = max(MIN_NAMES, int(self._previous_count() * MIN_SHARE_OF_PREVIOUS))
        if len(names) < floor or unnamed:
            raise DownloadError(
                f"{len(names)} rows where at least {floor} are expected, "
                f"{unnamed} without a name: the page changed"
            )
        (self.out_dir / "names.html").write_bytes(response.content)
        (self.out_dir / "names.json").write_text(
            json.dumps(names, indent=2, ensure_ascii=False) + "\n"
        )
        logger.info("%d star names", len(names))
        self._save_metadata(PAGE_URL, len(names), complete=True)

    def _previous_count(self) -> int:
        if not self.metadata_file.exists():
            return 0
        return json.loads(self.metadata_file.read_text())["record_count"]
