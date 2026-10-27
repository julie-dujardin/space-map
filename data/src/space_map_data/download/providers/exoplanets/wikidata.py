"""Download the Wikidata items of exoplanets that have a Wikipedia article.

An item is in the list when it carries a NASA Exoplanet Archive id (`P5667`,
the archive's planet name) or an exoplanet.eu id (`P5653`, the slug of its
page), and has an article in at least one of the site's languages. The list
gives each item all its values of both, and its count of articles. Host stars
carry archive ids too: they reach no planet. A list or disambiguation item is
not in the list: some carry a planet's ids after a merge, and their article
is the list.

The list comes from QLever, as the list of star items does.

Writes, below sources/exoplanets/wikidata/:
- items.tsv.gz    one row per item, as QLever returns it (SPARQL TSV)
- metadata.json

Licence: CC0. https://www.wikidata.org/wiki/Wikidata:Licensing
"""

import gzip
import logging
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import httpx

from space_map_data.constants.providers import LANGUAGES, PROVIDERS
from space_map_data.download.downloader import Downloader
from space_map_data.download.providers.catalogues.fetch import (
    QLEVER_URL,
    download_item_list,
)
from space_map_data.download.providers.stars.wikidata_stars import (
    SEPARATOR,
    parse_term,
)
from space_map_data.utils.paths import SOURCES_EXOPLANETS_DIR

logger = logging.getLogger(__name__)

OUT_DIR = SOURCES_EXOPLANETS_DIR / "wikidata"
ITEMS_FILE = OUT_DIR / "items.tsv.gz"

# Wikimedia list article, Wikimedia disambiguation page.
NOT_PLANET_QIDS = ("Q13406463", "Q4167410")

_PREFIXES = """\
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX schema: <http://schema.org/>
"""
_WIKIS = " ".join(f"<https://{lang}.wikipedia.org/>" for lang in LANGUAGES)
_NOT_PLANETS = " ".join(f"wd:{qid}" for qid in NOT_PLANET_QIDS)

# The items with an article, and their count of articles.
_ARTICLES = f"""\
SELECT ?item (COUNT(DISTINCT ?wiki) AS ?n) WHERE {{
  {{ ?item wdt:P5667 [] . }} UNION {{ ?item wdt:P5653 [] . }}
  ?article schema:about ?item ; schema:isPartOf ?wiki .
  VALUES ?wiki {{ {_WIKIS} }}
  MINUS {{ ?item wdt:P31 ?other . VALUES ?other {{ {_NOT_PLANETS} }} }}
}} GROUP BY ?item"""
ITEMS_QUERY = f"""{_PREFIXES}\
SELECT ?item
  (GROUP_CONCAT(DISTINCT ?archive_id; SEPARATOR="{SEPARATOR}") AS ?archive)
  (GROUP_CONCAT(DISTINCT ?eu_id; SEPARATOR="{SEPARATOR}") AS ?eu)
  (SAMPLE(?n) AS ?articles)
WHERE {{
  {{ {_ARTICLES} }}
  OPTIONAL {{ ?item wdt:P5667 ?archive_id . }}
  OPTIONAL {{ ?item wdt:P5653 ?eu_id . }}
}} GROUP BY ?item"""
COUNT_QUERY = f"{_PREFIXES}SELECT (COUNT(*) AS ?items) WHERE {{ {{ {_ARTICLES} }} }}"
COLUMNS = ("?item", "?archive", "?eu", "?articles")
# Items are added more often than removed. A count under this share of the
# previous one shows a failed query.
MIN_SHARE_OF_PREVIOUS = 0.95


@dataclass(frozen=True)
class ExoplanetItem:
    qid: str
    # NASA archive planet names.
    archive: tuple[str, ...]
    # exoplanet.eu page slugs.
    eu: tuple[str, ...]
    # Articles in the site's languages.
    articles: int


def _values(text: str | None) -> tuple[str, ...]:
    if not text:
        return ()
    return tuple(dict.fromkeys(v.strip() for v in text.split(SEPARATOR) if v.strip()))


def read_items(path: Path = ITEMS_FILE) -> list[ExoplanetItem]:
    """The items of the list. Raises ValueError for a file that does not parse."""
    with gzip.open(path, "rt", encoding="utf-8", newline="\n") as file:
        lines = file.read().split("\n")
    if tuple(lines[0].split("\t")) != COLUMNS:
        raise ValueError(f"{path}: columns {lines[0]!r}")
    items = []
    for line in lines[1:]:
        if not line:
            continue
        item, archive, eu, articles = map(parse_term, line.split("\t"))
        if item is None or articles is None:
            raise ValueError(f"{path}: row without an item or a count: {line!r}")
        items.append(ExoplanetItem(item, _values(archive), _values(eu), int(articles)))
    return items


def exoplanet_qids(path: Path = ITEMS_FILE) -> set[str]:
    """The QIDs of the list; empty before its first download."""
    if not path.exists():
        return set()
    return {item.qid for item in read_items(path)}


class WikidataExoplanetsDownloader(Downloader):
    name = PROVIDERS.WIKIDATA_EXOPLANETS
    # Articles and ids are added all the time.
    max_age = timedelta(days=30)

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.out_dir = OUT_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        counted = download_item_list(
            self.client,
            ITEMS_FILE,
            COUNT_QUERY,
            ITEMS_QUERY,
            int(self._previous_count() * MIN_SHARE_OF_PREVIOUS),
            read_items,
        )
        self._save_metadata(QLEVER_URL, counted, complete=True)
