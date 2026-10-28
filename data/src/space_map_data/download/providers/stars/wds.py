"""Download the Washington Double Star Catalog (WDS).

The WDS lists the measured pairs of double and multiple stars. A row is one
pair: its WDS id, its discoverer code and its components (AB, AC, Aa,Ab,
AB,C). The star systems take from it the pairs, the component letters, the
Gaia DR3 source of each component, and the codes that say whether a pair is
physical. USNO keeps the catalogue. Its live copy is at Georgia State
University, because the USNO hosts do not serve it.

Writes, below sources/stars/wds/:
- wdsweb_summ2.txt      the pairs, the main catalogue
- wds_components.summ   one row for each component of a pair, with a position
                        from the primary's position and the last measure
- wds_comp_dr3.txt      the same rows with the Gaia DR3 source of each
                        component
- bf.txt                the Bayer, Flamsteed, proper and variable-star names
- wdsnewnotes_main.txt  the notes
- wdsweb_format.txt     the format of the main catalogue
- metadata.json         the date of the catalogue, its pair count and TERMS

Not taken, because the tree does not use them: the main catalogue with the
constellation (the same rows and one column more), the references and
discoverer codes, the synonyms of the notes, the supplement (WDSS), the
Hipparcos, Tycho and Struve cross-references, the SQL dump, and the orbit
catalogue (ORB6).

The files are fixed-width by bytes. A few notes hold UTF-8, so the readers
cut a field from the bytes and then decode it.
"""

import logging
import re
from collections import defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pyarrow as pa

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader, DownloadError
from space_map_data.download.providers.three_d.resumable import (
    AS_STORED,
    download_resumable,
)
from space_map_data.utils.files import SYNC_BYTES
from space_map_data.utils.paths import SOURCES_STARS_DIR

logger = logging.getLogger(__name__)

OUT_DIR = SOURCES_STARS_DIR / "wds"
HOME_URL = "https://www.astro.gsu.edu/wds/"
PAIRS_FILE = "wdsweb_summ2.txt"
COMPONENTS_FILE = "wds_components.summ"
GAIA_FILE = "wds_comp_dr3.txt"
NAMES_FILE = "bf.txt"
NOTES_FILE = "wdsnewnotes_main.txt"
FORMAT_FILE = "wdsweb_format.txt"
# Each file, and its path below HOME_URL.
FILES = {
    PAIRS_FILE: "Webtextfiles/wdsweb_summ2.txt",
    COMPONENTS_FILE: "Webtextfiles/wds_components.summ",
    GAIA_FILE: "misc/wds_comp_dr3.txt",
    NAMES_FILE: "misc/bf.txt",
    NOTES_FILE: "Webtextfiles/wdsnewnotes_main.txt",
    FORMAT_FILE: "Webtextfiles/wdsweb_format.txt",
}

# The note codes of a pair, in its `notes`. The format file defines them.
PHYSICAL_CODES = frozenset("TVZ")
OPTICAL_CODES = frozenset("SUY")
# A "dubious double": a typo in the position, a plate flaw, or a pair that was
# not seen again.
DUBIOUS_CODE = "X"
# The proper motions of the pair are in arcseconds per 100 years, not 1000.
CENTURY_MOTION_CODE = "P"
# The main catalogue writes this for a separation that does not fit its field.
# The components file has the true value.
SEPARATION_OVERFLOW = 999.9

ACKNOWLEDGEMENT = (
    "This research has made use of the Washington Double Star Catalog"
    " maintained at the U.S. Naval Observatory."
)
# The tier that the terms allow; the extrasolar export takes the strictest.
DISTRIBUTION = "non-commercial"
TERMS = {
    "license": (
        "None stated. GSU asks for an acknowledgement and a notice of the papers"
        " that use the catalogue. The VizieR copy (B/wds) has no License line."
    ),
    "terms_url": "https://www.astro.gsu.edu/wds/wdstext.html",
    "distribution": DISTRIBUTION,
    "acknowledgement": ACKNOWLEDGEMENT,
    "quotes": [
        {
            "url": "https://www.astro.gsu.edu/wds/wdstext.html",
            "text": (
                "If the WDS and associated databases were helpful for your"
                " research work, the following acknowledgement would be"
                " appreciated: ``This research has made use of the Washington"
                " Double Star Catalog maintained at the U.S. Naval"
                " Observatory.'' A notification of references to relevant"
                " papers is appreciated."
            ),
        },
        {
            "url": "https://www.astro.gsu.edu/wds/faq.html",
            "about": "the full measures database",
            "text": (
                "Finally, an earlier version of the full database was once taken"
                " without permission, then repackaged and presented as a new"
                " catalog with no attribution. Given the enormous number of man"
                " years spent in the USNO Library and at the computer in"
                " maintaining this database, this will not be allowed to happen"
                " again."
            ),
        },
    ],
}

_ID = re.compile(rb"\d{5}[+-]\d{4}")
_RELEASE = re.compile(
    r"(\d+)\s+systems based on\s+(\d+)\s+means as of\s+([^.<]+?)\s*\."
)
_POSITION = re.compile(
    rb"(\d\d)(\d\d)(\d\d(?:\.\d*)?)\s*([+-])(\d\d)(\d\d)(\d\d(?:\.\d*)?)"
)
_GAIA_ID = re.compile(rb"DR3\s+(\d+)")


@dataclass(frozen=True)
class Release:
    """What the home page says of the files."""

    # The page calls the pairs "systems".
    pairs: int
    means: int
    as_of: str
    day: date


def parse_release(page: str) -> Release:
    """The pair count and the date that the home page gives."""
    match = _RELEASE.search(page)
    if match is None:
        raise DownloadError("The WDS home page gives no pair count: the page changed")
    as_of = " ".join(match[3].split())
    words = as_of.split()
    try:
        day = datetime.strptime(f"{words[1]} {words[2]} {words[-1]}", "%b %d %Y")
    except (IndexError, ValueError) as error:
        raise DownloadError(f"The WDS home page has the date {as_of!r}") from error
    return Release(int(match[1]), int(match[2]), as_of, day.date())


def count_rows(path: Path) -> int:
    """The lines of a WDS file that start with a WDS id."""
    with path.open("rb") as file:
        return sum(1 for line in file if _ID.match(line))


class WDSDownloader(Downloader):
    name = PROVIDERS.WDS
    # GSU puts out new files every few weeks.
    max_age = timedelta(days=30)

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.out_dir = OUT_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        response = self.client.get(HOME_URL)
        response.raise_for_status()
        release = parse_release(response.text)
        rows: dict[str, int] = {}
        for name, remote in FILES.items():
            expected = release.pairs if name == PAIRS_FILE else None
            if not download_resumable(
                self.client,
                HOME_URL + remote,
                self.out_dir / name,
                headers=AS_STORED,
                replace=True,
                check=_rows_check(name, expected, rows),
                sync_bytes=SYNC_BYTES,
            ):
                raise DownloadError(f"{HOME_URL}{remote}: the fetch failed")
        logger.info(
            "WDS of %s: %d pairs, %d component rows with a Gaia DR3 column",
            release.day,
            rows[PAIRS_FILE],
            rows[GAIA_FILE],
        )
        self._save_metadata(
            HOME_URL,
            release.pairs,
            complete=True,
            version=release.day.isoformat(),
            as_of=release.as_of,
            means=release.means,
            files={
                name: {
                    "url": HOME_URL + remote,
                    "bytes": (self.out_dir / name).stat().st_size,
                    "rows": rows[name],
                }
                for name, remote in FILES.items()
            },
            terms=TERMS,
        )


def _rows_check(
    name: str, expected: int | None, rows: dict[str, int]
) -> Callable[[Path], None]:
    """Count the rows of a fetched file. The format file has none."""

    def check(path: Path) -> None:
        found = count_rows(path)
        if name != FORMAT_FILE and found == 0:
            raise DownloadError(f"{name}: no rows")
        if expected is not None and found != expected:
            raise DownloadError(
                f"{name}: {found} pairs, the home page gives {expected}"
            )
        if name == FORMAT_FILE and path.stat().st_size == 0:
            raise DownloadError(f"{name}: the file is empty")
        rows[name] = found

    return check


def read_pairs(path: Path = OUT_DIR / PAIRS_FILE) -> pa.Table:
    """The pairs of the main catalogue, one row each.

    - `components`: null for the only pair of a system, which is A and B.
    - `first_date`, `last_date`: years; `pa_first`, `pa_last`: degrees, not
      precessed. Null where the catalogue writes -1.
    - `sep_first`, `sep_last`: arcseconds. SEPARATION_OVERFLOW means that much
      or more.
    - `mag1`, `mag2`: the band is V unless `notes` holds K, R or B.
    - `pm1_*`, `pm2_*`: proper motion of the primary and the secondary in
      mas/yr, the RA one times cos(dec). CENTURY_MOTION_CODE is applied.
    - `notes`: the codes of PHYSICAL_CODES, OPTICAL_CODES, DUBIOUS_CODE and
      the others of the format file.
    - `ra`, `dec`: degrees, J2000, of the primary of the pair. Null where the
      catalogue has only the arcminute position of the WDS id.
    """
    columns: dict[str, list] = defaultdict(list)
    for line in _lines(path):
        notes = _text(line[107:111])
        _common(columns, line, notes)
        columns["components"].append(_text(line[17:22]))
        columns["pa_first"].append(_whole(line[38:41]))
        columns["pa_last"].append(_whole(line[42:45]))
        columns["sep_first"].append(_float(line[46:51]))
        columns["sep_last"].append(_float(line[52:57]))
    return _table(columns, PAIR_TYPES)


def read_components(path: Path = OUT_DIR / GAIA_FILE) -> pa.Table:
    """The components of the pairs, one row each, from either components file.

    The rows repeat the values of their pair. `pa` and `sep` are the last
    measure, in degrees and arcseconds, with no overflow. `ra` and `dec` are
    the component's own position (degrees, J2000). `primary` is true for the
    primary of the pair. `source_id` is the Gaia DR3 source, from
    wds_comp_dr3.txt only. Both components of a close pair can have the same
    source, and one component can be in two rows.
    """
    columns: dict[str, list] = defaultdict(list)
    for line in _lines(path):
        _common(columns, line, _text(line[107:111]))
        columns["component"].append(_text(line[17:22]))
        columns["pa"].append(_angle(line[38:44]))
        columns["sep"].append(_float(line[45:53]))
        columns["primary"].append(line[131:134] == b"**p")
        gaia = _GAIA_ID.search(line, 134)
        columns["source_id"].append(int(gaia[1]) if gaia else None)
    return _table(columns, COMPONENT_TYPES)


def read_names(path: Path = OUT_DIR / NAMES_FILE) -> pa.Table:
    """The Bayer, Flamsteed, proper and variable-star names of bf.txt.

    `component` is null when the names are those of the system.
    """
    columns: dict[str, list] = defaultdict(list)
    for line in _lines(path):
        columns["wds_id"].append(line[:10].decode("ascii"))
        columns["discoverer"].append(_text(line[11:18]))
        columns["component"].append(_text(line[18:22]))
        names = (_text(line[at : at + 22]) for at in (22, 44, 66))
        last = _text(line[88:])
        columns["names"].append(
            [name for name in (*names, last) if name not in (None, ".")]
        )
    return _table(columns, NAME_TYPES)


def read_notes(path: Path = OUT_DIR / NOTES_FILE) -> pa.Table:
    """The notes, one row per note: a WDS id and the pair or star it names.

    `key` is a discoverer code or a designation. `references` are the codes
    of wdsnewref.txt, which is not taken.
    """
    notes: list[dict] = []
    wds_id = None
    with path.open("rb") as file:
        for raw in file:
            line = raw.rstrip(b"\r\n")
            if _ID.match(line):
                wds_id = line[:10].decode("ascii")
            if wds_id is None or not line.strip():
                continue
            key = _text(line[11:22])
            if key is not None:
                notes.append({"wds_id": wds_id, "key": key, "text": [], "refs": []})
            elif not notes:
                continue
            note = notes[-1]
            text = _text(line[23:95])
            reference = _text(line[95:])
            if text is not None:
                note["text"].append(text)
            if reference not in (None, ".", *note["refs"]):
                note["refs"].append(reference)
    return pa.table(
        {
            "wds_id": pa.array([n["wds_id"] for n in notes], pa.string()),
            "key": pa.array([n["key"] for n in notes], pa.string()),
            "text": pa.array([" ".join(n["text"]) for n in notes], pa.string()),
            "references": pa.array([n["refs"] for n in notes], pa.list_(pa.string())),
        }
    )


_COMMON_TYPES = {
    "wds_id": pa.string(),
    "discoverer": pa.string(),
    "first_date": pa.int16(),
    "last_date": pa.int16(),
    "observations": pa.int32(),
    "mag1": pa.float64(),
    "mag2": pa.float64(),
    "spectral_type": pa.string(),
    "pm1_ra": pa.int32(),
    "pm1_dec": pa.int32(),
    "pm2_ra": pa.int32(),
    "pm2_dec": pa.int32(),
    "dm": pa.string(),
    "notes": pa.string(),
    "ra": pa.float64(),
    "dec": pa.float64(),
}
PAIR_TYPES = {
    **_COMMON_TYPES,
    "components": pa.string(),
    "pa_first": pa.int16(),
    "pa_last": pa.int16(),
    "sep_first": pa.float64(),
    "sep_last": pa.float64(),
}
COMPONENT_TYPES = {
    **_COMMON_TYPES,
    "component": pa.string(),
    "pa": pa.float64(),
    "sep": pa.float64(),
    "primary": pa.bool_(),
    "source_id": pa.int64(),
}
NAME_TYPES = {
    "wds_id": pa.string(),
    "discoverer": pa.string(),
    "component": pa.string(),
    "names": pa.list_(pa.string()),
}


def _lines(path: Path) -> Iterator[bytes]:
    with path.open("rb") as file:
        for line in file:
            if _ID.match(line):
                yield line.rstrip(b"\r\n")


def _common(columns: dict[str, list], line: bytes, notes: str | None) -> None:
    """The fields at the same place in the pairs and the components files."""
    scale = 10 if notes is not None and CENTURY_MOTION_CODE in notes else 1
    columns["wds_id"].append(line[:10].decode("ascii"))
    columns["discoverer"].append(_text(line[10:17]))
    columns["first_date"].append(_whole(line[23:27]))
    columns["last_date"].append(_whole(line[28:32]))
    columns["observations"].append(_int(line[33:37]))
    columns["mag1"].append(_float(line[58:63]))
    columns["mag2"].append(_float(line[64:69]))
    columns["spectral_type"].append(_text(line[70:79]))
    for name, at in (("pm1_ra", 80), ("pm1_dec", 84), ("pm2_ra", 89), ("pm2_dec", 93)):
        motion = _int(line[at : at + 4])
        columns[name].append(None if motion is None else motion * scale)
    columns["dm"].append(_text(line[98:106]))
    columns["notes"].append(notes)
    ra, dec = _position(line[112:130])
    columns["ra"].append(ra)
    columns["dec"].append(dec)


def _table(columns: dict[str, list], types: dict[str, pa.DataType]) -> pa.Table:
    return pa.table(
        {name: pa.array(columns[name], kind) for name, kind in types.items()}
    )


def _text(field: bytes) -> str | None:
    return field.decode("utf-8", errors="replace").strip() or None


def _int(field: bytes) -> int | None:
    try:
        return int(field)
    except ValueError:
        return None


def _float(field: bytes) -> float | None:
    try:
        return float(field)
    except ValueError:
        return None


def _whole(field: bytes) -> int | None:
    """A count, a year or an angle. The catalogue writes -1 for none."""
    value = _int(field)
    return None if value is None or value < 0 else value


def _angle(field: bytes) -> float | None:
    angle = _float(field)
    return None if angle is None or angle < 0 else angle


def _position(field: bytes) -> tuple[float | None, float | None]:
    match = _POSITION.fullmatch(field.strip())
    if match is None:
        return None, None
    hours, minutes, seconds, sign, degrees, arcmin, arcsec = match.groups()
    ra = 15 * (int(hours) + int(minutes) / 60 + float(seconds) / 3600)
    dec = int(degrees) + int(arcmin) / 60 + float(arcsec) / 3600
    return ra, -dec if sign == b"-" else dec
