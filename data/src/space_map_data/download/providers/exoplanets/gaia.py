"""Download the Gaia DR3 tables that bear on exoplanets.

Reads the Gaia ids that the NASA archive and SIMBAD give. Writes:
- dr2_neighbourhood.csv       the DR3 sources near each Gaia DR2 id. A DR2 id
                              is not a DR3 id.
- nss_two_body_orbit.csv      the orbit solutions of the known stars, and
                              every solution of Gaia's planet search
- vari_planetary_transit.csv  Gaia's transit candidates
- gaia_source.csv             the `gaia_source` rows of the known DR3 ids, and
                              of the DR3 neighbours of the DR2 ids, that are
                              not positionable. The bulk download holds the
                              others.
- fidelity.csv                the astrometric fidelity of those rows
- astrophysical_parameters.csv  the GSP-Phot radii, FLAME and GSP-Spec
                              values of those rows, as the bulk Gaia ingest
                              reads them
- flame_spec.csv              FLAME's run on GSP-Spec for those rows
- xgboost.csv                 the XP metallicities of those rows (Andrae, Rix
                              & Chandra 2023), with the vetted red-giant and
                              OBA golden sample flags of the bulk download

Licence: CC BY-NC 3.0 IGO, credit ESA/Gaia/DPAC.
https://www.cosmos.esa.int/web/gaia-users/license
The XP metallicities: CC BY 4.0, cite Andrae, Rix & Chandra 2023, ApJS 267, 8.
"""

import csv
import logging
import re
from collections.abc import Iterable
from pathlib import Path

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.exoplanets import nasa_archive, simbad
from space_map_data.download.providers.exoplanets.inputs import InputReader
from space_map_data.download.providers.exoplanets.tap import (
    Rows,
    tap_join,
    tap_rows,
    write_csv,
)
from space_map_data.download.providers.stars import (
    gaia_fidelity,
    gaia_source,
    gaia_xp_metallicity,
)
from space_map_data.download.providers.stars.gaia_flame_spec import (
    FLAME_SPEC_COLUMNS,
)
from space_map_data.extrasolar.sources.gaia import ASTROPHYSICAL_COLUMNS
from space_map_data.utils.paths import SOURCES_EXOPLANETS_DIR

logger = logging.getLogger(__name__)

TAP_URL = "https://gea.esac.esa.int/tap-server/tap/sync"
OUT_DIR = SOURCES_EXOPLANETS_DIR / "gaia"
ID_CHUNK = 1000

_GAIA_ID_RE = re.compile(r"Gaia DR([23]) (\d+)")

_DR2_NEIGHBOURHOOD = (
    "select n.* from TAP_UPLOAD.sent as s"
    " join gaiadr3.dr2_neighbourhood as n on n.dr2_source_id = s.id"
)
_HOST_ORBITS = (
    "select o.* from TAP_UPLOAD.sent as s"
    " join gaiadr3.nss_two_body_orbit as o on o.source_id = s.id"
)
_PLANET_SEARCH_ORBITS = (
    "select * from gaiadr3.nss_two_body_orbit"
    " where nss_solution_type like 'OrbitalTargetedSearch%'"
)
_TRANSITS = "select * from gaiadr3.vari_planetary_transit"
_UNPOSITIONABLE = (
    f"select {', '.join(f'g.{column}' for column in gaia_source.COLUMNS)}"
    " from TAP_UPLOAD.sent as s join gaiadr3.gaia_source as g on g.source_id = s.id"
    " where g.parallax_over_error is null"
    f" or g.parallax_over_error <= {gaia_source.MIN_PARALLAX_OVER_ERROR}"
)
_FIDELITY = (
    f"select {', '.join(f'f.{column}' for column in gaia_fidelity.COLUMNS)}"
    " from TAP_UPLOAD.sent as s"
    " join external.gaiaedr3_spurious as f on f.source_id = s.id"
)
_ASTROPHYSICAL = (
    f"select a.source_id, {', '.join(f'a.{c}' for c in ASTROPHYSICAL_COLUMNS)}"
    " from TAP_UPLOAD.sent as s"
    " join gaiadr3.astrophysical_parameters as a on a.source_id = s.id"
)
_FLAME_SPEC = (
    f"select a.source_id, {', '.join(f'a.{c}' for c in FLAME_SPEC_COLUMNS)}"
    " from TAP_UPLOAD.sent as s"
    " join gaiadr3.astrophysical_parameters_supp as a on a.source_id = s.id"
)
# The archive has no CASE, so the two flags come as the ids of the joined rows.
_XGBOOST = (
    f"select {', '.join(f'x.{c}' for c in gaia_xp_metallicity.TABLE_COLUMNS)},"
    " v.source_id as vetted_id, o.source_id as oba_id"
    " from TAP_UPLOAD.sent as s"
    " join external.xgboost_table1 as x on x.source_id = s.id"
    " left outer join external.xgboost_table2 as v on v.source_id = x.source_id"
    " left outer join gaiadr3.gold_sample_oba_stars as o"
    " on o.source_id = x.source_id"
)
XGBOOST_HEADER = [
    *gaia_xp_metallicity.TABLE_COLUMNS,
    gaia_xp_metallicity.VETTED,
    gaia_xp_metallicity.OBA,
]
SOURCE_FILE = "gaia_source.csv"
FIDELITY_FILE = "fidelity.csv"
ASTROPHYSICAL_FILE = "astrophysical_parameters.csv"
FLAME_SPEC_FILE = "flame_spec.csv"
XGBOOST_FILE = "xgboost.csv"
FILES = (SOURCE_FILE, FIDELITY_FILE, ASTROPHYSICAL_FILE, FLAME_SPEC_FILE, XGBOOST_FILE)


def _header(path: Path) -> list[str]:
    with path.open(newline="") as f:
        return next(csv.reader(f), [])


def xgboost_rows(header: list[str], rows: list[list[str]]) -> list[list[str]]:
    """The rows with the two membership flags, as the bulk chunks hold them."""
    vetted, oba = header.index("vetted_id"), header.index("oba_id")
    width = len(gaia_xp_metallicity.TABLE_COLUMNS)
    return [
        [*row[:width], str(bool(row[vetted])).lower(), str(bool(row[oba])).lower()]
        for row in rows
    ]


def gaia_ids(texts: Iterable[str]) -> tuple[list[int], list[int]]:
    """Find the Gaia DR2 ids and the Gaia DR3 ids printed in `texts`."""
    found: dict[str, set[int]] = {"2": set(), "3": set()}
    for text in texts:
        for release, source_id in _GAIA_ID_RE.findall(text):
            found[release].add(int(source_id))
    return sorted(found["2"]), sorted(found["3"])


class ExoplanetGaiaDownloader(InputReader):
    name = PROVIDERS.EXOPLANET_GAIA
    # Files that print ids as `Gaia DR3 <id>` and `Gaia DR2 <id>`.
    inputs = (
        nasa_archive.OUT_DIR / "stellarhosts.csv",
        nasa_archive.OUT_DIR / "k2pandc.csv",
        simbad.OUT_DIR / simbad.IDS_FILE,
    )
    # Gaia DR3 does not change. The provider runs again when an input does.
    max_age = None

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = OUT_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def is_complete(self, limit: int | None) -> bool:
        # A file or an astrophysical column added since the last run forces a
        # refetch: the ingest reads every column.
        return (
            super().is_complete(limit)
            and all((self.out_dir / name).exists() for name in FILES)
            and _header(self.out_dir / ASTROPHYSICAL_FILE)
            == ["source_id", *ASTROPHYSICAL_COLUMNS]
        )

    def _by_id(self, query: str, ids: list[int]) -> Rows:
        return tap_join(self.client, TAP_URL, query, "id", "long", ids, ID_CHUNK)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        self.require_inputs()
        dr2_ids, dr3_ids = gaia_ids(path.read_text() for path in self.inputs)
        logger.info(
            "Fetching Gaia tables for %d DR2 ids and %d DR3 ids...",
            len(dr2_ids),
            len(dr3_ids),
        )
        neighbour_header, neighbours = self._by_id(_DR2_NEIGHBOURHOOD, dr2_ids)
        if not neighbours:
            raise DownloadError(f"Gaia has no neighbour for {len(dr2_ids)} DR2 ids")
        _, host_orbits = self._by_id(_HOST_ORBITS, dr3_ids)
        orbit_header, search_orbits = tap_rows(
            self.client, TAP_URL, _PLANET_SEARCH_ORBITS
        )
        # A planet-search solution of a known star is in both results.
        orbits = dict.fromkeys(map(tuple, [*host_orbits, *search_orbits]))
        transit_header, transits = tap_rows(self.client, TAP_URL, _TRANSITS)
        neighbour_ids = [
            int(row[neighbour_header.index("dr3_source_id")]) for row in neighbours
        ]
        source_header, sources = self._by_id(
            _UNPOSITIONABLE, sorted(set(dr3_ids) | set(neighbour_ids))
        )
        source_ids = sorted({int(row[0]) for row in sources})
        fidelity_header, fidelity = (
            self._by_id(_FIDELITY, source_ids)
            if source_ids
            else (list(gaia_fidelity.COLUMNS), [])
        )
        astrophysical_header, astrophysical = (
            self._by_id(_ASTROPHYSICAL, source_ids)
            if source_ids
            else (["source_id", *ASTROPHYSICAL_COLUMNS], [])
        )
        flame_spec_header, flame_spec = (
            self._by_id(_FLAME_SPEC, source_ids)
            if source_ids
            else (["source_id", *FLAME_SPEC_COLUMNS], [])
        )
        xgboost = xgboost_rows(*self._by_id(_XGBOOST, source_ids)) if source_ids else []
        logger.info(
            "  %d DR2 neighbours, %d orbits (%d from the planet search), %d transits,"
            " %d unpositionable sources (%d with a fidelity, %d with astrophysical"
            " parameters, %d with FLAME on GSP-Spec, %d with an XP metallicity)",
            len(neighbours),
            len(orbits),
            len(search_orbits),
            len(transits),
            len(sources),
            len(fidelity),
            len(astrophysical),
            len(flame_spec),
            len(xgboost),
        )

        # Every query has passed, so the files are one generation.
        write_csv(self.out_dir / "dr2_neighbourhood.csv", neighbour_header, neighbours)
        write_csv(self.out_dir / "nss_two_body_orbit.csv", orbit_header, orbits)
        write_csv(self.out_dir / "vari_planetary_transit.csv", transit_header, transits)
        write_csv(self.out_dir / SOURCE_FILE, source_header, sources)
        write_csv(self.out_dir / FIDELITY_FILE, fidelity_header, fidelity)
        write_csv(
            self.out_dir / ASTROPHYSICAL_FILE, astrophysical_header, astrophysical
        )
        write_csv(self.out_dir / FLAME_SPEC_FILE, flame_spec_header, flame_spec)
        write_csv(self.out_dir / XGBOOST_FILE, XGBOOST_HEADER, xgboost)
        self._save_metadata(
            TAP_URL,
            len(neighbours),
            complete=True,
            dr2_ids=len(dr2_ids),
            dr3_ids=len(dr3_ids),
            orbits=len(orbits),
            transits=len(transits),
            unpositionable_sources=len(sources),
            fidelity_rows=len(fidelity),
            astrophysical_rows=len(astrophysical),
            flame_spec_rows=len(flame_spec),
            xgboost_rows=len(xgboost),
        )
