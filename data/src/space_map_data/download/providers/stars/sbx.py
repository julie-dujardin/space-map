"""Download SBX, the eXtended Catalogue of Spectroscopic Binary Orbits.

SBX continues SB9 (Pourbaix et al. 2004), which it replaced on 2025-06-24.
A row of `orbits` is one spectroscopic orbit: P, T, e, ω, K1, K2 and the
systemic velocity, with errors. A system can have several orbits, numbered
by `on`. ULB keeps the catalogue and serves it through its TAP service.

Writes, below sources/stars/sbx/:
- systems.csv         one row per system: position, parallax, proper motion,
                      magnitudes and spectral types
- orbits.csv          the orbits
- alias.csv           the other designations of each system
- configurations.csv  the systems that are parts of one multiple star
- duplicates.csv      the SB9 entries that duplicate another system
- metadata.json       the rows of each table and TERMS

Not taken: the 224,148 radial velocities.

A row is identified by its SBX system number `sn`. `alias` gives the HIP,
HD, Gaia DR3, WDS, HR and other ids of each system.
"""

import logging
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pv

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader, DownloadError
from space_map_data.download.providers.three_d.resumable import download_resumable
from space_map_data.utils.paths import SOURCES_STARS_DIR

logger = logging.getLogger(__name__)

OUT_DIR = SOURCES_STARS_DIR / "sbx"
HOME_URL = "https://astro.ulb.ac.be/sbx/"
TAP_URL = HOME_URL + "tap/sync"
SYSTEMS, ORBITS, ALIAS, CONFIGURATIONS, DUPLICATES = (
    "systems",
    "orbits",
    "alias",
    "configurations",
    "duplicates",
)
TABLES = (SYSTEMS, ORBITS, ALIAS, CONFIGURATIONS, DUPLICATES)

CITATION = (
    "Merle, T., Jorissen, A., Alexandre, S., et al. 2026, MNRAS, 547, 2,"
    " The SB9 catalogue: status, comparison with non-single stars from Gaia"
    " DR3 and evolution to SBX"
)
DISTRIBUTION = "open"
TERMS = {
    "license": "CC BY 4.0, the License line of the VizieR copy (B/sbx).",
    "terms_url": "https://cdsarc.cds.unistra.fr/ftp/B/sbx/ReadMe",
    "distribution": DISTRIBUTION,
    "citation": CITATION,
    "note": (
        "The systems table repeats Gaia DR3 positions, parallaxes and proper"
        " motions, which are CC BY-NC 3.0 IGO. The orbits are SBX's own."
    ),
    "quotes": [
        {
            "url": "https://vizier.cfa.harvard.edu/ftp/cats/B/sbx/ReadMe",
            "text": "License: CC-BY-4.0",
        },
        {
            "url": HOME_URL,
            "text": (
                "If SB9 or SBX helped you in your published work, we would"
                " appreciate it if you could cite one of the following"
                " references"
            ),
        },
    ],
}

_STRING, _FLOAT, _INT = pa.string(), pa.float64(), pa.int64()
COUNTS = ("num_RV1", "num_RV2")
# The column types of the TAP schema.
TYPES: dict[str, dict[str, pa.DataType]] = {
    SYSTEMS: {
        **dict.fromkeys(
            (
                "band1",
                "band2",
                "component",
                "coordinates_1900_legacy",
                "coordinates_2000_legacy",
                "mag1_source",
                "mag2_source",
                "parallax_source",
                "pm_source",
                "position_source",
                "st1",
                "st1_bibcode",
                "st2",
                "st2_bibcode",
            ),
            _STRING,
        ),
        **dict.fromkeys(
            (
                "dec",
                "dec_error",
                "mag1",
                "mag2",
                "parallax",
                "parallax_error",
                "pmdec",
                "pmdec_error",
                "pm_epoch",
                "pmra",
                "pmra_error",
                "position_epoch",
                "ra",
                "ra_error",
            ),
            _FLOAT,
        ),
        "sn": _INT,
    },
    ORBITS: {
        **dict.fromkeys(
            (
                "accessibility_legacy",
                "bibcode",
                "contributor",
                "epoch_reference",
                "grade_legacy",
                "note",
            ),
            _STRING,
        ),
        **dict.fromkeys(
            (
                "apparent_systemic_velocity_1",
                "apparent_systemic_velocity_2",
                "apparent_systemic_velocity_error_1",
                "apparent_systemic_velocity_error_2",
                "eccentricity",
                "eccentricity_error",
                "grade",
                "K1",
                "K1_error",
                "K2",
                "K2_error",
                "periastron_argument",
                "periastron_argument_error",
                "periastron_time",
                "periastron_time_error",
                "periastron_time_flag",
                "period",
                "period_error",
                "rms_RV1",
                "rms_RV2",
                "systemic_velocity",
                "systemic_velocity_error",
            ),
            _FLOAT,
        ),
        **dict.fromkeys(("on", "sn"), _INT),
        # The service writes these counts with a decimal point.
        **dict.fromkeys(COUNTS, _FLOAT),
    },
    ALIAS: {"catalog": _STRING, "identifier": _STRING, "sn": _INT, "version": _STRING},
    CONFIGURATIONS: {
        **dict.fromkeys(("child1", "child2", "parent", "sn"), _INT),
        **dict.fromkeys(
            ("family", "in_high_order", "in_quadruple", "in_triple"), _STRING
        ),
    },
    DUPLICATES: {"sn": _INT, "sn_duplicate": _INT},
}


class SBXDownloader(Downloader):
    name = PROVIDERS.SBX
    # The catalogue takes new orbits as they are published.
    max_age = timedelta(days=30)

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.out_dir = OUT_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        rows = {name: self._count(name) for name in TABLES}
        for name in TABLES:
            if not download_resumable(
                self.client,
                TAP_URL,
                self.out_dir / f"{name}.csv",
                method="POST",
                data=_query(f"SELECT * FROM {name}"),
                replace=True,
                check=_rows_check(name, rows[name]),
            ):
                raise DownloadError(f"{TAP_URL}: the fetch of {name} failed")
        logger.info("SBX: %s", rows)
        self._save_metadata(
            HOME_URL, rows[ORBITS], complete=True, rows=rows, terms=TERMS
        )

    def _count(self, name: str) -> int:
        response = self.client.post(
            TAP_URL, data=_query(f"SELECT COUNT(*) FROM {name}"), timeout=300.0
        )
        response.raise_for_status()
        lines = response.text.split()
        try:
            return int(lines[1])
        except (IndexError, ValueError) as error:
            raise DownloadError(f"SBX count of {name}: {response.text!r}") from error


def _query(adql: str) -> dict[str, str]:
    return {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": adql}


def _rows_check(name: str, expected: int) -> Callable[[Path], None]:
    def check(path: Path) -> None:
        found = read_table(name, path.parent, path).num_rows
        if found != expected:
            raise DownloadError(f"{name}: {found} rows, the service counts {expected}")

    return check


def read_table(
    name: str, directory: Path = OUT_DIR, path: Path | None = None
) -> pa.Table:
    """One table, with the column names and types of the TAP schema.

    Text is trimmed, and an empty text is null. Values keep the units of the
    schema: angles in deg, times and periods in d, velocities in km/s. In
    `orbits`, `epoch_reference` says whether T0 is a JD, an MJD or an RJD
    (JD − 2,400,000), and a T0 of a JD can be shortened by 2,400,000. A
    non-zero `periastron_time_flag` marks a T0 of another event, such as an
    eclipse (SB9 ReadMe, note 2). K1 is that of component 1. The schema
    does not say whose ω it is; a spectroscopic orbit gives the primary's.
    """
    table = pv.read_csv(
        path or directory / f"{name}.csv",
        parse_options=pv.ParseOptions(newlines_in_values=True),
        convert_options=pv.ConvertOptions(
            column_types=TYPES[name], strings_can_be_null=True
        ),
    )
    for at, field in enumerate(table.schema):
        if field.name in COUNTS:
            table = table.set_column(at, field.name, table[field.name].cast(_INT))
        elif pa.types.is_string(field.type):
            text = pc.utf8_trim_whitespace(table[field.name])
            text = pc.if_else(pc.equal(text, ""), None, text)
            table = table.set_column(at, field.name, text)
    return table
