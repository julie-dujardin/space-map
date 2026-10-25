"""Download the IAU NameExoWorlds names of exoplanets and their host stars.

The IAU ran three NameExoWorlds editions. Each gave public names to planets
and to their host stars:
- 2015: the IAU press release iau1514. iau.org no longer serves it, so the
  provider reads its Wayback Machine copy. That copy has the corrected
  spelling "Lipperhey".
- 2019 and 2022: the full tables (XLSX) on the NameExoWorlds site.

Writes, below sources/exoplanets/nameexoworlds/:
- iau1514.html, 2019.xlsx, 2022.xlsx   the files as served
- names.json                           one entry per name: edition, row of
                                       its table, kind (star or planet),
                                       designation, name
- metadata.json
"""

import html
import io
import json
import logging
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import asdict, dataclass

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader, DownloadError
from space_map_data.utils.paths import SOURCES_EXOPLANETS_DIR

logger = logging.getLogger(__name__)

OUT_DIR = SOURCES_EXOPLANETS_DIR / "nameexoworlds"
NAMES_FILE = "names.json"
STAR, PLANET = "star", "planet"

PRESS_RELEASE_2015 = (
    "http://web.archive.org/web/20200110050438/"
    "https://www.iau.org/news/pressreleases/detail/iau1514/"
)
TABLES = {
    2019: "https://nameexoworlds.iau.org/_files/ugd/"
    "6358ac_f8290c984e9a47b1bba9e6c31d9ff48c.xlsx",
    2022: "https://nameexoworlds.iau.org/_files/ugd/"
    "042af1_47a8bbf2e40340c0a716694b62ef3d72.xlsx",
}
# Columns of the XLSX tables, for the star and for the planet.
COLUMNS = {
    STAR: ("Star catalog ID", "Name Star"),
    PLANET: ("Exoplanet catalog ID", "Name Exoplanet"),
}
# Names per edition and kind as announced. A smaller count is a broken file.
EXPECTED = {
    (2015, STAR): 14,
    (2015, PLANET): 31,
    (2019, STAR): 112,
    (2019, PLANET): 112,
    (2022, STAR): 20,
    (2022, PLANET): 20,
}

_SHEET_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_CELL_REF = re.compile(r"([A-Z]+)\d+")


@dataclass(frozen=True)
class ExoWorldName:
    edition: int
    # The names of one row belong to one system.
    row: int
    kind: str
    designation: str
    name: str


def clean(text: str) -> str:
    """A name or designation without footnote marks and extra spaces."""
    return " ".join(text.replace("*", " ").split())


def xlsx_rows(content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    """The titles of the first sheet of an XLSX file, and its rows by title."""
    with zipfile.ZipFile(io.BytesIO(content)) as book:
        shared = []
        if "xl/sharedStrings.xml" in book.namelist():
            for item in ET.fromstring(book.read("xl/sharedStrings.xml")):
                shared.append("".join(t.text or "" for t in item.iter(f"{_SHEET_NS}t")))
        sheet = ET.fromstring(book.read("xl/worksheets/sheet1.xml"))
    rows: list[dict[str, str]] = []
    for row in sheet.iter(f"{_SHEET_NS}row"):
        cells: dict[str, str] = {}
        for cell in row.iter(f"{_SHEET_NS}c"):
            kind, value = cell.get("t"), cell.find(f"{_SHEET_NS}v")
            if kind == "s" and value is not None and value.text is not None:
                text = shared[int(value.text)]
            elif kind == "inlineStr":
                text = "".join(t.text or "" for t in cell.iter(f"{_SHEET_NS}t"))
            else:
                text = value.text if value is not None and value.text else ""
            column = _CELL_REF.fullmatch(cell.get("r", ""))
            if column is not None:
                cells[column[1]] = text
        rows.append(cells)
    if not rows:
        raise DownloadError("the XLSX sheet is empty")
    header = {column: title.strip() for column, title in rows[0].items() if title}
    return list(header.values()), [
        {header[c]: v for c, v in cells.items() if c in header} for cells in rows[1:]
    ]


def table_names(edition: int, content: bytes) -> list[ExoWorldName]:
    """The star and planet names of a 2019 or 2022 table."""
    header, rows = xlsx_rows(content)
    missing = [c for pair in COLUMNS.values() for c in pair if c not in header]
    if missing:
        raise DownloadError(f"{edition} table has no columns {missing}")
    found = []
    for at, row in enumerate(rows):
        for kind, (designation, name) in COLUMNS.items():
            if clean(row.get(designation, "")) and clean(row.get(name, "")):
                found.append(
                    ExoWorldName(
                        edition, at, kind, clean(row[designation]), clean(row[name])
                    )
                )
    return found


def _cell_lines(cell: str) -> list[str]:
    text = re.sub(r"<br\s*/?>", "\n", cell)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    return [line.strip() for line in text.split("\n") if line.strip()]


def press_release_names(page: str) -> list[ExoWorldName]:
    """The names of the 2015 press release table.

    Each row is one system: the kinds, designations and names are cells of
    lines in the same order.
    """
    tables = re.findall(r"<table.*?</table>", page, flags=re.DOTALL)
    if len(tables) != 1:
        raise DownloadError(f"iau1514 has {len(tables)} tables, not 1")
    found = []
    for at, row in enumerate(re.findall(r"<tr.*?</tr>", tables[0], flags=re.DOTALL)):
        cells = [
            _cell_lines(c) for c in re.findall(r"<td.*?</td>", row, flags=re.DOTALL)
        ]
        if len(cells) < 3 or not cells[0]:
            continue
        kinds, designations, names = cells[:3]
        if not len(kinds) == len(designations) == len(names):
            raise DownloadError(f"iau1514 row does not line up: {designations}")
        for kind, designation, name in zip(kinds, designations, names):
            if kind.lower() not in (STAR, PLANET):
                raise DownloadError(f"iau1514 row has the kind {kind!r}")
            found.append(
                ExoWorldName(2015, at, kind.lower(), clean(designation), clean(name))
            )
    return found


def check_counts(names: list[ExoWorldName]) -> None:
    for (edition, kind), expected in EXPECTED.items():
        count = sum(1 for n in names if n.edition == edition and n.kind == kind)
        if count < expected:
            raise DownloadError(
                f"{count} {kind} names of {edition}, the IAU announced {expected}"
            )


class NameExoWorldsDownloader(Downloader):
    name = PROVIDERS.NAME_EXO_WORLDS
    # The editions are closed. A new edition needs its file added here.
    max_age = None

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.out_dir = OUT_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def _get(self, url: str) -> bytes:
        response = self.client.get(url, follow_redirects=True, timeout=120.0)
        response.raise_for_status()
        return response.content

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        files = {"iau1514.html": self._get(PRESS_RELEASE_2015)}
        names = press_release_names(files["iau1514.html"].decode("utf-8", "replace"))
        for edition, url in TABLES.items():
            files[f"{edition}.xlsx"] = self._get(url)
            names += table_names(edition, files[f"{edition}.xlsx"])
        check_counts(names)

        for filename, content in files.items():
            (self.out_dir / filename).write_bytes(content)
        (self.out_dir / NAMES_FILE).write_text(
            json.dumps([asdict(n) for n in names], indent=2, ensure_ascii=False) + "\n"
        )
        logger.info("%d NameExoWorlds names", len(names))
        self._save_metadata(TABLES[2022], len(names), complete=True)
