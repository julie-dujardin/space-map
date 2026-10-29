"""The Gaia DR3 sources near the Gaia DR2 ids of SPICY.

SPICY gives the Gaia DR2 counterpart of a candidate young stellar object. A
DR2 id is not a DR3 id, so the extrasolar ingest takes the nearest DR3 source
of Gaia's `dr2_neighbourhood` table.

Reads the SPICY file of the stellar_parameter_catalogues provider. Writes,
below sources/stars/spicy-gaia/:
- dr2_neighbourhood.csv  the `dr2_neighbourhood` rows of each DR2 id
- metadata.json

Licence: CC BY-NC 3.0 IGO, credit ESA/Gaia/DPAC.
"""

import logging

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.catalogues.provider import (
    StellarParameterCataloguesDownloader,
)
from space_map_data.download.providers.exoplanets.gaia import (
    DR2_NEIGHBOURHOOD,
    TAP_URL,
)
from space_map_data.download.providers.exoplanets.inputs import InputReader
from space_map_data.download.providers.exoplanets.tap import tap_join, write_csv
from space_map_data.extrasolar.sources.spicy import NEIGHBOURHOOD, read_candidates
from space_map_data.utils.paths import SOURCES_CATALOGUES_DIR

logger = logging.getLogger(__name__)

ID_CHUNK = 1000


class SpicyGaiaDownloader(InputReader):
    name = PROVIDERS.SPICY_GAIA

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        group = StellarParameterCataloguesDownloader.group
        self.inputs = (SOURCES_CATALOGUES_DIR / group / "metadata.json",)
        self.out_dir = NEIGHBOURHOOD.parent
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        self.require_inputs()
        ids = read_candidates()["dr2"]
        dr2 = sorted({int(value) for value in ids[ids > 0]})
        logger.info("Sending %d SPICY Gaia DR2 ids to the Gaia archive...", len(dr2))
        header, rows = tap_join(
            self.client, TAP_URL, DR2_NEIGHBOURHOOD, "id", "long", dr2, ID_CHUNK
        )
        found = {row[header.index("dr2_source_id")] for row in rows}
        logger.info(
            "Gaia: %d DR3 neighbours for %d of %d DR2 ids; %d without one",
            len(rows),
            len(found),
            len(dr2),
            len(dr2) - len(found),
        )
        if not rows:
            raise DownloadError(f"Gaia gave no DR3 neighbour for {len(dr2)} DR2 ids")
        write_csv(NEIGHBOURHOOD, header, rows)
        self._save_metadata(
            TAP_URL,
            len(rows),
            complete=True,
            dr2_ids_sent=len(dr2),
            dr2_ids_found=len(found),
        )
