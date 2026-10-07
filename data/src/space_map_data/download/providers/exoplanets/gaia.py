"""Download the Gaia DR3 tables that bear on exoplanets.

Reads the Gaia ids that the NASA archive and SIMBAD give. Writes:
- dr2_neighbourhood.csv       the DR3 sources near each Gaia DR2 id. A DR2 id
                              is not a DR3 id.
- nss_two_body_orbit.csv      the orbit solutions of the known stars, and
                              every solution of Gaia's planet search
- vari_planetary_transit.csv  Gaia's transit candidates

This provider does not fetch `gaia_source` rows.

Licence: CC BY-NC 3.0 IGO, credit ESA/Gaia/DPAC.
https://www.cosmos.esa.int/web/gaia-users/license
"""

import logging
import re
from collections.abc import Iterable

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
        logger.info(
            "  %d DR2 neighbours, %d orbits (%d from the planet search), %d transits",
            len(neighbours),
            len(orbits),
            len(search_orbits),
            len(transits),
        )

        # Every query has passed, so the three files are one generation.
        write_csv(self.out_dir / "dr2_neighbourhood.csv", neighbour_header, neighbours)
        write_csv(self.out_dir / "nss_two_body_orbit.csv", orbit_header, orbits)
        write_csv(self.out_dir / "vari_planetary_transit.csv", transit_header, transits)
        self._save_metadata(
            TAP_URL,
            len(neighbours),
            complete=True,
            dr2_ids=len(dr2_ids),
            dr3_ids=len(dr3_ids),
            orbits=len(orbits),
            transits=len(transits),
        )
