"""Download the exoplanet.eu catalogue (Extrasolar Planets Encyclopaedia).

The CSV export is the site's filter form, posted with every status box
ticked. A plain GET returns the confirmed planets only.

The catalogue accepts companions up to 60 Jupiter masses and objects without
a host star, so it lists more objects than the NASA archive.

Licence: CC BY 4.0. https://exoplanet.eu/
"""

import csv
import io
import logging
import re
from collections import Counter
from datetime import timedelta

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.utils.paths import SOURCES_EXOPLANETS_DIR

logger = logging.getLogger(__name__)

CATALOG_URL = "https://exoplanet.eu/catalog/"
CSV_URL = f"{CATALOG_URL}csv/"
OUT_DIR = SOURCES_EXOPLANETS_DIR / "exoplanet-eu"
CATALOG_FILE = "catalog.csv"
# The columns that the pipeline reads.
COLUMNS = (
    "name",
    "alternate_names",
    "star_name",
    "star_alternate_names",
    "planet_status",
)

_TOKEN_RE = re.compile(r'name="csrfmiddlewaretoken" value="([^"]+)"')
_STATUS_RE = re.compile(r'name="(status_\d+)"')


def export_form(html: str) -> dict[str, str]:
    """Build the export form from the catalogue page, every status ticked."""
    token = _TOKEN_RE.search(html)
    statuses = sorted(set(_STATUS_RE.findall(html)))
    if token is None or not statuses:
        raise DownloadError("exoplanet.eu catalogue page has no filter form")
    return {
        "csrfmiddlewaretoken": token.group(1),
        # The site ignores the status boxes when the filter expression is absent.
        "query_f": "",
        **dict.fromkeys(statuses, "on"),
    }


def status_counts(body: str) -> Counter[str]:
    """Count the rows of each `planet_status`. Fail on a missing column."""
    reader = csv.DictReader(io.StringIO(body))
    missing = [column for column in COLUMNS if column not in (reader.fieldnames or [])]
    if missing:
        raise DownloadError(
            f"exoplanet.eu export has no column {', '.join(missing)}: {body[:80]!r}"
        )
    return Counter(row["planet_status"] for row in reader)


class ExoplanetEUDownloader(Downloader):
    name = PROVIDERS.EXOPLANET_EU
    # The catalogue changes most days. A week matches the NASA archive.
    max_age = timedelta(days=7)

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = OUT_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        logger.info("Downloading exoplanet.eu catalogue...")
        page = self.client.get(CATALOG_URL)
        page.raise_for_status()
        # Django rejects the POST without the page cookie and a same-site Referer.
        response = self.client.post(
            CSV_URL,
            data=export_form(page.text),
            headers={"Referer": CATALOG_URL},
            timeout=300.0,
        )
        response.raise_for_status()

        counts = status_counts(response.text)
        if len(counts) < 2:
            raise DownloadError(
                f"exoplanet.eu export holds one status only: {dict(counts)}"
            )
        (self.out_dir / CATALOG_FILE).write_text(response.text)
        logger.info("  %s: %s", CATALOG_FILE, dict(counts))
        self._save_metadata(
            CSV_URL, counts.total(), complete=True, status_counts=dict(counts)
        )
