"""Download Tokovinin's Multiple Star Catalogue (MSC).

The MSC gives the hierarchy of physical multiple stars of three or more
components: the pairs that make each system, and the letters of their
components. It is the first source of the star systems for structure.
Tokovinin publishes each version as one tarball on his page, and the
provider takes the newest that the page links.

Writes, below sources/stars/msc/:
- newmsc-<date>.tar.gz  the tarball, as published
- Readme                its description, with the format of each table
- comp.tsv              the components: position, parallax, proper motion,
                        magnitudes, HIP and HD numbers
- sys.tsv               the pairs: primary, secondary and parent, which code
                        the hierarchy, with period, separation and masses
- orb.tsv               the orbits
- notes.tsv             the notes
- metadata.json         the version, the rows of each table and TERMS

The tables are fixed-width with a `|` between two fields. `read_table` splits
them at the `|` and names the fields as the Readme does.
"""

import io
import logging
import re
import tarfile
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin

import httpx
import pyarrow as pa

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.cds import Field, byte_by_byte
from space_map_data.download.downloader import Downloader, DownloadError
from space_map_data.download.providers.three_d.resumable import (
    AS_STORED,
    download_resumable,
)
from space_map_data.utils.paths import SOURCES_STARS_DIR

logger = logging.getLogger(__name__)

OUT_DIR = SOURCES_STARS_DIR / "msc"
# The https chain of the host is broken.
PAGE_URL = "http://www.ctio.noirlab.edu/~atokovin/stars/"
README_FILE = "Readme"
COMP_FILE, SYS_FILE, ORB_FILE, NOTES_FILE = (
    "comp.tsv",
    "sys.tsv",
    "orb.tsv",
    "notes.tsv",
)
TABLES = (COMP_FILE, SYS_FILE, ORB_FILE, NOTES_FILE)

# The parents in sys.tsv that are not a component label.
ROOT_PARENT = "*"
TRAPEZIUM_PARENT = "t"
# A pair that is optical or spurious. It is not in the hierarchy.
REFUTED_PARENT = "X"

TERMS = {
    "license": (
        "None stated. Tokovinin's page and the Readme state no terms. The MSC"
        " is the catalogue of Tokovinin 2018, ApJS 235, 6, and the AAS holds"
        " the copyright of the ApJS articles of that time that are not gold"
        " open access. Whether this one is was not checked."
    ),
    "terms_url": "https://journals.aas.org/article-charges-and-copyright/",
    "distribution": "non-commercial",
    "quotes": [
        {
            "url": "https://journals.aas.org/article-charges-and-copyright/",
            "text": (
                "The AAS holds the copyright for all non-gold-OA articles"
                " published in … the Astrophysical Journal Supplement Series"
                " prior to 11 Oct 2021."
            ),
        },
        {
            "url": "https://journals.aas.org/article-charges-and-copyright/",
            "text": ("all gold OA articles … are published under a CC-BY 4.0 license"),
        },
    ],
}

_TARBALL = re.compile(r"""href\s*=\s*["']?(newmsc-(\d{8})\.tar\.gz)""", re.IGNORECASE)


def newest_tarball(page: str) -> tuple[str, date]:
    """The newest tarball that the page links, and its date."""
    found: dict[str, date] = {}
    for match in _TARBALL.finditer(page):
        try:
            found[match[1]] = datetime.strptime(match[2], "%Y%m%d").date()
        except ValueError:
            continue
    if not found:
        raise DownloadError("The MSC page links no newmsc-<date>.tar.gz")
    name = max(found, key=found.__getitem__)
    return name, found[name]


class MSCDownloader(Downloader):
    name = PROVIDERS.MSC
    # A new version comes out once or twice a year.
    max_age = timedelta(days=30)

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.out_dir = OUT_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        response = self.client.get(PAGE_URL)
        response.raise_for_status()
        name, version = newest_tarball(response.text)
        url = urljoin(PAGE_URL, name)
        tarball = self.out_dir / name
        if not download_resumable(
            self.client,
            url,
            tarball,
            headers=AS_STORED,
            replace=True,
            check=_check_tarball,
        ):
            raise DownloadError(f"{url}: the fetch failed")
        rows = extract(tarball, self.out_dir)
        for old in self.out_dir.glob("newmsc-*.tar.gz"):
            if old.name != name:
                logger.info("Deleting %s, a version older than %s", old.name, name)
                old.unlink()
        logger.info("MSC of %s: %s", version, rows)
        self._save_metadata(
            url,
            rows[COMP_FILE],
            complete=True,
            version=version.isoformat(),
            tarball=name,
            rows=rows,
            terms=TERMS,
        )


def extract(tarball: Path, out_dir: Path) -> dict[str, int]:
    """Write the Readme and the tables of the tarball. Returns their rows."""
    members = _members(tarball.read_bytes())
    readme = members[README_FILE].decode("latin-1")
    rows = {name: len(_split(members[name], readme, name)) for name in TABLES}
    for name, content in members.items():
        part = out_dir / (name + ".part")
        part.write_bytes(content)
        part.replace(out_dir / name)
    return rows


def read_table(name: str, directory: Path = OUT_DIR) -> pa.Table:
    """One table, with the labels of the Readme as column names.

    A is a string, I is int64, F is float64. A blank field is null, and so is
    a number that does not parse (one grade is `*`). A zero stays: the Readme
    says that an unknown number is zero, but some zeros are true values, such
    as an eccentricity.
    """
    readme = (directory / README_FILE).read_text(encoding="latin-1")
    fields = byte_by_byte(readme, name)
    rows = _split((directory / name).read_bytes(), readme, name)
    return pa.table(
        {
            field.label: _column([row[at] for row in rows], field)
            for at, field in enumerate(fields)
        }
    )


def _check_tarball(path: Path) -> None:
    _members(path.read_bytes())


def _members(content: bytes) -> dict[str, bytes]:
    """The Readme and the tables in a tarball, by name."""
    try:
        with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
            files = {
                PurePosixPath(member.name).name: member
                for member in archive.getmembers()
                if member.isfile()
            }
            missing = sorted({README_FILE, *TABLES} - set(files))
            if missing:
                raise DownloadError(f"the tarball has no {', '.join(missing)}")
            members = {}
            for name in (README_FILE, *TABLES):
                data = archive.extractfile(files[name])
                if data is None:
                    raise DownloadError(f"the tarball cannot give {name}")
                members[name] = data.read()
            return members
    except (tarfile.TarError, EOFError, OSError) as error:
        raise DownloadError(f"cannot read the tarball: {error}") from error


def _split(content: bytes, readme: str, name: str) -> list[list[str]]:
    """The fields of each line of a table. A line with a wrong count fails."""
    fields = byte_by_byte(readme, name)
    count = len(fields)
    if len({field.label for field in fields}) != count:
        raise DownloadError(f"{name}: the Readme repeats a label")
    rows = []
    for number, line in enumerate(content.decode("latin-1").splitlines(), 1):
        if not line.strip():
            continue
        fields = line.split("|")
        if len(fields) != count:
            raise DownloadError(
                f"{name}, line {number}: {len(fields)} fields, the Readme gives {count}"
            )
        rows.append([value.strip() for value in fields])
    return rows


def _column(values: list[str], field: Field) -> pa.Array:
    if field.kind == "A":
        return pa.array([value or None for value in values], pa.string())
    if field.kind == "I":
        return pa.array([_number(int, value) for value in values], pa.int64())
    return pa.array([_number(float, value) for value in values], pa.float64())


def _number(parse: Callable[[str], float], value: str) -> float | None:
    try:
        return parse(value)
    except ValueError:
        return None
