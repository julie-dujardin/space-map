"""Download the Sixth Catalog of Orbits of Visual Binary Stars (ORB6).

ORB6 gives the visual orbits of double stars: P, a, i, Ω, T, e and ω, with
their published errors and a grade. A row is one orbit of one pair. USNO
keeps the catalogue beside the WDS, and its live copy is at Georgia State
University with the WDS files.

Writes, below sources/stars/orb6/:
- orb6orbits.txt   the orbits, fixed-width text
- orb6format.txt   the format of the orbits file
- metadata.json    the update time, the orbit and system counts and TERMS

Not taken: the ephemerides, the notes (the WDS notes file holds them), the
references, the SQL copy and the master file of all published orbits.

A row is identified by its WDS id and its discoverer code and components,
as in the WDS, and by its HIP, HD and ADS numbers.
"""

import logging
import re
from collections import defaultdict
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pyarrow as pa

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader, DownloadError
from space_map_data.download.providers.stars import wds
from space_map_data.download.providers.three_d.resumable import (
    AS_STORED,
    download_resumable,
)
from space_map_data.utils.paths import SOURCES_STARS_DIR

logger = logging.getLogger(__name__)

OUT_DIR = SOURCES_STARS_DIR / "orb6"
HOME_URL = wds.HOME_URL + "orb6.html"
ORBITS_FILE = "orb6orbits.txt"
FORMAT_FILE = "orb6format.txt"
FILES = {name: wds.HOME_URL + "orb6/" + name for name in (ORBITS_FILE, FORMAT_FILE)}

# Days per unit code of P. The format file calls `m` (minutes) and `h` "not
# yet used", but rows use them.
PERIOD_DAYS = {"m": 1 / 1440, "h": 1 / 24, "d": 1.0, "y": 365.25, "c": 36525.0}
# Arcsec per unit code of a.
AXIS_ARCSEC = {"a": 1.0, "m": 1e-3, "M": 60.0, "u": 1e-6}
# T: `c` is a year / 100, `d` JD − 2,400,000, `m` MJD, `y` a Besselian year.
# `j` is not in the format file. Its values are years.
TIME_UNITS = {"c", "d", "m", "y", "j"}
# Ω is an identified ascending node.
ASCENDING_NODE = "*"
# Ω or ω was turned by 180°.
FLIPPED = "q"
# Grades 1 (definitive) to 5 (indeterminate); 7 incomplete elements; 8 an
# interferometric orbit from visibilities; 9 an astrometric orbit.
ASTROMETRIC_GRADE = 9
INTERFEROMETRIC_GRADE = 8

DISTRIBUTION = wds.DISTRIBUTION
TERMS = {
    "license": (
        "None stated. ORB6 is one of the USNO double star catalogues beside the"
        " WDS. The WDS page asks for an acknowledgement for the WDS and its"
        " associated databases."
    ),
    "terms_url": "https://www.astro.gsu.edu/wds/wdstext.html",
    "distribution": DISTRIBUTION,
    "acknowledgement": wds.ACKNOWLEDGEMENT,
    "quotes": wds.TERMS["quotes"][:1],
}

_WDS_ID = re.compile(rb"\d{5}[+-]\d{4}")
_RELEASE = re.compile(r"last catalog update\s*:\s*([^)]+?)\s*\)", re.IGNORECASE)
_COUNTS = re.compile(r"included\s*(\d+)\s*of\s*(\d+)\s*systems", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


def parse_release(page: str) -> tuple[int, int, date]:
    """The orbit count, the system count and the update day of the page."""
    text = _TAG.sub(" ", page)
    counts = _COUNTS.search(text)
    release = _RELEASE.search(text)
    if counts is None or release is None:
        raise DownloadError("The ORB6 page gives no orbit count: the page changed")
    words = release[1].split()
    try:
        day = datetime.strptime(f"{words[1]} {words[2]} {words[-1]}", "%b %d %Y")
    except (IndexError, ValueError) as error:
        raise DownloadError(f"The ORB6 page has the date {release[1]!r}") from error
    return int(counts[1]), int(counts[2]), day.date()


def count_rows(path: Path) -> int:
    """The lines of the orbits file that hold a WDS id."""
    return sum(1 for _ in _lines(path))


class ORB6Downloader(Downloader):
    name = PROVIDERS.ORB6
    # USNO adds orbits every few weeks.
    max_age = timedelta(days=30)

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.out_dir = OUT_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        response = self.client.get(HOME_URL)
        response.raise_for_status()
        orbits, systems, day = parse_release(response.text)
        for name, url in FILES.items():
            if not download_resumable(
                self.client,
                url,
                self.out_dir / name,
                headers=AS_STORED,
                replace=True,
                check=_check(name, orbits),
            ):
                raise DownloadError(f"{url}: the fetch failed")
        logger.info("ORB6 of %s: %d orbits of %d systems", day, orbits, systems)
        self._save_metadata(
            HOME_URL,
            orbits,
            complete=True,
            version=day.isoformat(),
            systems=systems,
            files={
                name: {"url": url, "bytes": (self.out_dir / name).stat().st_size}
                for name, url in FILES.items()
            },
            terms=TERMS,
        )


def _check(name: str, expected: int) -> Callable[[Path], None]:
    def check(path: Path) -> None:
        if path.stat().st_size == 0:
            raise DownloadError(f"{name}: the file is empty")
        if name == ORBITS_FILE and (found := count_rows(path)) != expected:
            raise DownloadError(f"{name}: {found} orbits, the page gives {expected}")

    return check


# Fields of the format file: 0-based start and end. A value field has its
# unit or flag code in the byte after it.
_FIELDS = {
    "position": (0, 18),
    "wds_id": (19, 29),
    "discoverer": (30, 37),
    "components": (37, 44),
    "ads": (45, 50),
    "hd": (51, 57),
    "hip": (58, 64),
    "mag1": (66, 71),
    "mag2": (73, 78),
    "period": (80, 92),
    "period_error": (93, 104),
    "semi_major_axis": (105, 114),
    "semi_major_axis_error": (115, 124),
    "inclination": (125, 133),
    "inclination_error": (134, 142),
    "node": (143, 151),
    "node_error": (153, 161),
    "t_periastron": (162, 174),
    "t_periastron_error": (175, 186),
    "eccentricity": (187, 195),
    "eccentricity_error": (196, 204),
    "arg_periastron": (205, 213),
    "arg_periastron_error": (214, 222),
    "equinox": (223, 227),
    "last_observation": (228, 232),
    "grade": (233, 234),
    "notes": (235, 236),
    "reference": (237, 245),
    "image": (246, 264),
}
# The code after each of these fields.
_CODES = {
    "mag1": "mag1_flag",
    "mag2": "mag2_flag",
    "period": "period_unit",
    "semi_major_axis": "semi_major_axis_unit",
    "node": "node_flag",
    "t_periastron": "t_periastron_unit",
    "arg_periastron": "arg_periastron_flag",
}
_TEXT = ("wds_id", "discoverer", "components", "reference", "image")
_WHOLE = ("ads", "hd", "hip", "equinox", "last_observation", "grade")
_POSITION = re.compile(r"(\d\d)(\d\d)(\d\d\.\d*)([+-])(\d\d)(\d\d)(\d\d\.?\d*)")

ORBIT_TYPES = {
    "wds_id": pa.string(),
    "discoverer": pa.string(),
    "components": pa.string(),
    "ads": pa.int32(),
    "hd": pa.int32(),
    "hip": pa.int32(),
    "ra": pa.float64(),
    "dec": pa.float64(),
    "mag1": pa.float32(),
    "mag1_flag": pa.string(),
    "mag2": pa.float32(),
    "mag2_flag": pa.string(),
    "period": pa.float64(),
    "period_unit": pa.string(),
    "period_error": pa.float64(),
    "semi_major_axis": pa.float64(),
    "semi_major_axis_unit": pa.string(),
    "semi_major_axis_error": pa.float64(),
    "inclination": pa.float64(),
    "inclination_error": pa.float64(),
    "node": pa.float64(),
    "node_flag": pa.string(),
    "node_error": pa.float64(),
    "t_periastron": pa.float64(),
    "t_periastron_unit": pa.string(),
    "t_periastron_error": pa.float64(),
    "eccentricity": pa.float64(),
    "eccentricity_error": pa.float64(),
    "arg_periastron": pa.float64(),
    "arg_periastron_flag": pa.string(),
    "arg_periastron_error": pa.float64(),
    "equinox": pa.int16(),
    "last_observation": pa.int16(),
    "grade": pa.int8(),
    "notes": pa.bool_(),
    "reference": pa.string(),
    "image": pa.string(),
}


def read_orbits(path: Path = OUT_DIR / ORBITS_FILE) -> pa.Table:
    """Every orbit of the file, one row each, with every field.

    The values are as published, in the unit of their code column: P in
    PERIOD_DAYS, a in AXIS_ARCSEC, T in TIME_UNITS, angles in degrees, the
    errors in the unit of their value. A blank field or a lone `.` is null.
    `ra` and `dec` are the J2000 position in degrees. `discoverer` and
    `components` split the designation field at the width of the WDS
    discoverer code. Where no discoverer code is given, `discoverer` holds
    another designation, such as "YY Gem". `notes` is true when the notes
    file has a note.
    """
    columns: dict[str, list] = defaultdict(list)
    for line in _lines(path):
        text = line.decode("latin-1")
        for name, (start, end) in _FIELDS.items():
            field = text[start:end].strip()
            if name == "position":
                ra, dec = _position(field)
                columns["ra"].append(ra)
                columns["dec"].append(dec)
            elif name == "notes":
                columns[name].append(field == "n")
            elif name in _TEXT:
                columns[name].append(field or None)
            elif name in _WHOLE:
                columns[name].append(_number(int, field))
            else:
                columns[name].append(_number(float, field))
            if name in _CODES:
                columns[_CODES[name]].append(text[end : end + 1].strip() or None)
    return pa.table(
        {name: pa.array(columns[name], kind) for name, kind in ORBIT_TYPES.items()}
    )


def _lines(path: Path) -> Iterator[bytes]:
    with path.open("rb") as file:
        for line in file:
            if _WDS_ID.fullmatch(line[19:29]):
                yield line.rstrip(b"\r\n")


def _number(parse: Callable[[str], float], field: str) -> float | None:
    try:
        return parse(field)
    except ValueError:
        return None


def _position(field: str) -> tuple[float | None, float | None]:
    match = _POSITION.fullmatch(field)
    if match is None:
        return None, None
    hours, minutes, seconds, sign, degrees, arcmin, arcsec = match.groups()
    ra = 15 * (int(hours) + int(minutes) / 60 + float(seconds) / 3600)
    dec = int(degrees) + int(arcmin) / 60 + float(arcsec) / 3600
    return ra, -dec if sign == "-" else dec
