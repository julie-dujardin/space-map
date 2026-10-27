"""Download the Wikidata items of stars that have a Wikipedia article.

An item is in the list when it carries a Gaia DR3 id (`P13228`), a Hipparcos
or an HD number (`P528` with the catalogue in qualifier `P972`), and has an
article in at least one of the site's languages. The list gives each item its
ids, its English and multilingual labels, and its count of articles.

An item whose types (`P31/P279*`) reach a galaxy, a nebula, a cluster or
another object that is not a star is not in the list, unless its types also
reach a star or a star system. Wikidata puts binary and double stars below
asterism, and gives some nebulae the type of their central star.

The list comes from QLever, a mirror of Wikidata at the University of
Freiburg. The Wikidata query service cannot scan this many items.

Writes, below sources/stars/wikidata/:
- items.tsv.gz    one row per item, as QLever returns it (SPARQL TSV)
- metadata.json

Licence: CC0. https://www.wikidata.org/wiki/Wikidata:Licensing
"""

import gzip
import logging
import re
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
from space_map_data.utils.paths import SOURCES_STARS_DIR

logger = logging.getLogger(__name__)

OUT_DIR = SOURCES_STARS_DIR / "wikidata"
ITEMS_FILE = OUT_DIR / "items.tsv.gz"

HIPPARCOS_QID = "Q537199"
HENRY_DRAPER_QID = "Q111130"
SEPARATOR = "|"
# Galaxy, nebula, planetary nebula, reflection nebula, star cluster, quasar,
# active galactic nucleus, H II region, interstellar medium, galaxy cluster,
# asterism.
NOT_STAR_QIDS = (
    "Q318",
    "Q42372",
    "Q13632",
    "Q203958",
    "Q168845",
    "Q83373",
    "Q46587",
    "Q11282",
    "Q41872",
    "Q204107",
    "Q9262",
)
# Star, binary star, double star, multiple star, star system, brown dwarf.
STAR_QIDS = ("Q523", "Q50053", "Q13890", "Q878367", "Q595871", "Q101600")

_PREFIXES = """\
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX ps: <http://www.wikidata.org/prop/statement/>
PREFIX pq: <http://www.wikidata.org/prop/qualifier/>
PREFIX wikibase: <http://wikiba.se/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX schema: <http://schema.org/>
"""
_WIKIS = " ".join(f"<https://{lang}.wikipedia.org/>" for lang in LANGUAGES)
_NOT_STARS = " ".join(f"wd:{qid}" for qid in NOT_STAR_QIDS)
_STARS = " ".join(f"wd:{qid}" for qid in STAR_QIDS)


def _not_deprecated(statement: str) -> str:
    # Wikidata marks a wrong value deprecated. The Gaia id's `wdt:` leaves
    # those out already.
    return f"FILTER NOT EXISTS {{ {statement} wikibase:rank wikibase:DeprecatedRank }}"


# The items with an article, and their count of articles.
_ARTICLES = f"""\
SELECT ?item (COUNT(DISTINCT ?wiki) AS ?n) WHERE {{
  {{ ?item wdt:P13228 [] . }}
  UNION {{ ?item p:P528 ?s . ?s pq:P972 wd:{HIPPARCOS_QID} . {_not_deprecated("?s")} }}
  UNION {{ ?item p:P528 ?s . ?s pq:P972 wd:{HENRY_DRAPER_QID} . {_not_deprecated("?s")} }}
  ?article schema:about ?item ; schema:isPartOf ?wiki .
  VALUES ?wiki {{ {_WIKIS} }}
  MINUS {{
    ?item wdt:P31/wdt:P279* ?other .
    VALUES ?other {{ {_NOT_STARS} }}
    MINUS {{ ?item wdt:P31/wdt:P279* ?star . VALUES ?star {{ {_STARS} }} }}
  }}
}} GROUP BY ?item"""
ITEMS_QUERY = f"""{_PREFIXES}\
SELECT ?item
  (GROUP_CONCAT(DISTINCT ?gaia_id; SEPARATOR="{SEPARATOR}") AS ?gaia_dr3)
  (GROUP_CONCAT(DISTINCT ?hip_id; SEPARATOR="{SEPARATOR}") AS ?hip)
  (GROUP_CONCAT(DISTINCT ?hd_id; SEPARATOR="{SEPARATOR}") AS ?hd)
  (SAMPLE(?en) AS ?label_en) (SAMPLE(?mul) AS ?label_mul) (SAMPLE(?n) AS ?articles)
WHERE {{
  {{ {_ARTICLES} }}
  OPTIONAL {{ ?item wdt:P13228 ?gaia_id . }}
  OPTIONAL {{
    ?item p:P528 ?s1 . ?s1 ps:P528 ?hip_id ; pq:P972 wd:{HIPPARCOS_QID} .
    {_not_deprecated("?s1")}
  }}
  OPTIONAL {{
    ?item p:P528 ?s2 . ?s2 ps:P528 ?hd_id ; pq:P972 wd:{HENRY_DRAPER_QID} .
    {_not_deprecated("?s2")}
  }}
  OPTIONAL {{ ?item rdfs:label ?en . FILTER(LANG(?en) = "en") }}
  OPTIONAL {{ ?item rdfs:label ?mul . FILTER(LANG(?mul) = "mul") }}
}} GROUP BY ?item"""
COUNT_QUERY = f"{_PREFIXES}SELECT (COUNT(*) AS ?items) WHERE {{ {_ARTICLES} }}"
COLUMNS = ("?item", "?gaia_dr3", "?hip", "?hd", "?label_en", "?label_mul", "?articles")
# Items are added more often than removed. A count under this share of the
# previous one shows a failed query.
MIN_SHARE_OF_PREVIOUS = 0.95
# A Gaia DR3 source_id holds the level-12 HEALPix pixel of its source above
# bit 35.
GAIA_PIXEL_LEVEL = 12
GAIA_PIXEL_SHIFT = 35
_GAIA_PIXELS = 12 * 4**GAIA_PIXEL_LEVEL

_ESCAPES = {
    "t": "\t",
    "n": "\n",
    "r": "\r",
    "b": "\b",
    "f": "\f",
    '"': '"',
    "'": "'",
    "\\": "\\",
}
# HD gives one number to a system. Its component A is the star of that number.
_HD_PRIMARY = re.compile(r"^(\d+) ?A$")


@dataclass(frozen=True)
class StarItem:
    qid: str
    gaia_dr3: tuple[str, ...]
    # Hipparcos and HD numbers without their prefix.
    hip: tuple[str, ...]
    hd: tuple[str, ...]
    label_en: str | None
    label_mul: str | None
    # Articles in the site's languages.
    articles: int


def parse_term(text: str) -> str | None:
    """The value of one SPARQL TSV term: an IRI's last segment, a literal's
    text without its quotes, language tag or datatype. None when empty.

    Raises ValueError for a literal that does not parse.
    """
    if not text:
        return None
    if text.startswith("<"):
        return text[1:-1].rsplit("/", 1)[-1]
    if not text.startswith('"'):
        return text
    out, i = [], 1
    while i < len(text) and text[i] != '"':
        if text[i] == "\\":
            escaped = _ESCAPES.get(text[i + 1 : i + 2])
            if escaped is None:
                raise ValueError(f"unknown escape in the term {text!r}")
            out.append(escaped)
            i += 2
        else:
            out.append(text[i])
            i += 1
    if i >= len(text):
        raise ValueError(f"unterminated term {text!r}")
    return "".join(out)


def _numbers(
    text: str | None, prefix: str, primary: re.Pattern[str] | None = None
) -> tuple[str, ...]:
    """The ids that are numbers, each once. An id that `primary` matches
    gives the number in its first group."""
    if not text:
        return ()
    out: dict[str, None] = {}
    for value in text.split(SEPARATOR):
        number = value.strip().removeprefix(prefix).strip()
        if primary is not None and (match := primary.match(number)):
            number = match[1]
        if number.isdigit():
            out[number] = None
        else:
            logger.debug("Skipped the catalogue id %r", value)
    return tuple(out)


def _gaia_ids(text: str | None, qid: str) -> tuple[str, ...]:
    """The Gaia DR3 source_ids whose pixel is on the sky."""
    ids = _numbers(text, "")
    bad = [id_ for id_ in ids if int(id_) >> GAIA_PIXEL_SHIFT >= _GAIA_PIXELS]
    if bad:
        logger.warning("%s: skipped the Gaia DR3 ids out of range %s", qid, bad)
    return tuple(id_ for id_ in ids if id_ not in bad)


def read_items(path: Path = ITEMS_FILE) -> list[StarItem]:
    """The items of the list. Raises ValueError for a file that does not parse."""
    with gzip.open(path, "rt", encoding="utf-8", newline="\n") as file:
        lines = file.read().split("\n")
    if tuple(lines[0].split("\t")) != COLUMNS:
        raise ValueError(f"{path}: columns {lines[0]!r}")
    items = []
    for line in lines[1:]:
        if not line:
            continue
        item, gaia, hip, hd, en, mul, articles = map(parse_term, line.split("\t"))
        if item is None or articles is None:
            raise ValueError(f"{path}: row without an item or a count: {line!r}")
        items.append(
            StarItem(
                qid=item,
                gaia_dr3=_gaia_ids(gaia, item),
                hip=_numbers(hip, "HIP"),
                hd=_numbers(hd, "HD", _HD_PRIMARY),
                label_en=en,
                label_mul=mul,
                articles=int(articles),
            )
        )
    return items


def star_qids(path: Path = ITEMS_FILE) -> set[str]:
    """The QIDs of the list; empty before its first download."""
    if not path.exists():
        return set()
    return {item.qid for item in read_items(path)}


class WikidataStarsDownloader(Downloader):
    name = PROVIDERS.WIKIDATA_STARS
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
