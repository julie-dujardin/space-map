"""Download the Wikidata items that carry a SIMBAD identifier.

Property `P3083` holds one SIMBAD identifier, for example `M 31`. It matches
`ident.id` in SIMBAD, so it links a Wikidata item to a SIMBAD object.

The Wikidata query service cannot return this many rows. The list comes from
QLever, a mirror of Wikidata at the University of Freiburg.

Writes, below sources/catalogues/wikidata-simbad-ids/:
- simbad-ids.tsv.gz   item URI and SIMBAD identifier, as QLever returns them
- metadata.json

Licence: CC0. https://www.wikidata.org/wiki/Wikidata:Licensing
"""

import logging
from datetime import timedelta
from pathlib import Path

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.download.providers.catalogues.fetch import post_lines_gz
from space_map_data.utils.paths import SOURCES_CATALOGUES_DIR

logger = logging.getLogger(__name__)

QLEVER_URL = "https://qlever.dev/api/wikidata"
OUT_DIR = SOURCES_CATALOGUES_DIR / "wikidata-simbad-ids"
IDS_FILE = "simbad-ids.tsv.gz"

_PREFIX = "PREFIX wdt: <http://www.wikidata.org/prop/direct/> "
_PATTERN = "WHERE { ?item wdt:P3083 ?simbad }"
IDS_QUERY = _PREFIX + "SELECT ?item ?simbad " + _PATTERN
COUNT_QUERY = _PREFIX + "SELECT (COUNT(*) AS ?n) " + _PATTERN
_TSV = {"Accept": "text/tab-separated-values"}


class WikidataSimbadIdsDownloader(Downloader):
    name = PROVIDERS.WIKIDATA_SIMBAD_IDS
    # Wikidata gains identifiers all the time.
    max_age = timedelta(days=30)

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.out_dir = OUT_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        counted = self._count()

        def check(part: Path, lines: int) -> None:
            if lines - 1 != counted:
                raise DownloadError(
                    f"QLever returned {lines - 1} identifiers and counts {counted}"
                )

        post_lines_gz(
            self.client,
            QLEVER_URL,
            self.out_dir / IDS_FILE,
            data={"query": IDS_QUERY, "action": "tsv_export"},
            headers=_TSV,
            check=check,
        )
        logger.info("%s: %d identifiers", IDS_FILE, counted)
        self._save_metadata(QLEVER_URL, counted, complete=True)

    def _count(self) -> int:
        response = self.client.post(
            QLEVER_URL, data={"query": COUNT_QUERY}, headers=_TSV, timeout=120.0
        )
        response.raise_for_status()
        return int(response.text.split()[1])
