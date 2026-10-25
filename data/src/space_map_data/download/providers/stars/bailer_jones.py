"""Download the geometric distances of the named Gaia stars without a 5σ parallax.

Bailer-Jones et al. (2021) give each Gaia EDR3 source a distance from its
parallax and a prior from a model of the Galaxy. Where the parallax is poor,
the prior sets the distance, and the model holds no Magellanic Clouds. So the
ingest takes these distances last.

ESA serves the table only through its TAP service. This provider uploads the
ids of the gaia_named rows, the SIMBAD stars that gaia_source leaves out. The
stars with a 5σ parallax have their own.

Writes, below sources/stars/gaia/gedr3/external/gaiaedr3_distance/:
- named_stars.parquet   source_id, the geometric distance with its 16th and
                        84th percentiles (pc), and the flag of the table
- metadata.json

No licence is stated. Cite Bailer-Jones et al. 2021, AJ 161, 147. The values
derive from Gaia, CC BY-NC 3.0 IGO, credit ESA/Gaia/DPAC.
https://www.cosmos.esa.int/web/gaia-users/license
"""

import logging

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.exoplanets.inputs import InputReader
from space_map_data.download.providers.stars import (
    gaia_bulk,
    gaia_fidelity,
    gaia_named,
)
from space_map_data.utils.files import write_parquet

logger = logging.getLogger(__name__)

TAP_URL = gaia_named.TAP_URL
TABLE_PATH = "gedr3/external/gaiaedr3_distance"
OUT_DIR = gaia_bulk.OUT_DIR / TABLE_PATH
OUT_FILE = "named_stars.parquet"
NAMED_FILE = gaia_named.OUT_DIR / gaia_named.SOURCE_FILE
COLUMNS: dict[str, pa.DataType] = {
    "source_id": pa.int64(),
    "r_med_geo": pa.float32(),
    "r_lo_geo": pa.float32(),
    "r_hi_geo": pa.float32(),
    "flag": pa.string(),
}
QUERY = (
    f"select {', '.join(f'd.{column}' for column in COLUMNS)}"
    " from TAP_UPLOAD.sent as u"
    " join external.gaiaedr3_distance as d on d.source_id = u.source_id"
)


class BailerJonesDistancesDownloader(InputReader):
    name = PROVIDERS.BAILER_JONES_DISTANCES
    inputs = (NAMED_FILE,)
    # The table does not change. The provider runs again when gaia_named does.
    max_age = None

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.out_dir = OUT_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        self.require_inputs()
        ids = sorted(
            pq.read_table(NAMED_FILE, columns=["source_id"])["source_id"].to_pylist()
        )
        if not ids:
            raise DownloadError(f"{NAMED_FILE} has no rows")
        rows = gaia_fidelity.ask_ids(self.client, QUERY, ids, COLUMNS)
        logger.info("%d of %d named stars have a distance", rows.num_rows, len(ids))
        write_parquet(rows, self.out_dir / OUT_FILE)
        self._save_metadata(TAP_URL, rows.num_rows, complete=True, ids_sent=len(ids))
