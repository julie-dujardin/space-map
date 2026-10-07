"""Download the Gaia DR3 astrophysical parameters of the positionable stars.

`astrophysical_parameters` holds what the main table does not: luminosity,
radius, mass, age, spectral type, and the temperature, metallicity and
abundances measured from spectra. It has the same chunks as `gaia_source`.
This provider keeps the rows of the stars that `gaia_source` kept, so it
reads the chunks that provider wrote. It does not repeat the columns that
`gaia_source` keeps.

Writes, below sources/stars/gaia/gdr3/Astrophysical_parameters/astrophysical_parameters/:
- AstrophysicalParameters_<pixels>.parquet   the kept rows of one chunk
- columns.json                               type, unit and description of each column
- _MD5SUM.txt                                the upstream chunk list
- metadata.json

Licence: CC BY-NC 3.0 IGO, credit ESA/Gaia/DPAC.
https://www.cosmos.esa.int/web/gaia-users/license
"""

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.stars import gaia_bulk, gaia_source
from space_map_data.download.providers.stars.gaia_bulk import (
    CHUNK_SUFFIX,
    STATS_KEY,
    ChunkedTableDownloader,
    ChunkJob,
)

TABLE_PATH = f"{gaia_source.RELEASE}/Astrophysical_parameters/astrophysical_parameters"
CHUNK_PREFIX = "AstrophysicalParameters_"


def select_kept_stars(
    table: pa.Table, job: ChunkJob
) -> tuple[pa.Table, dict[str, float]]:
    assert job.companion is not None
    stars = pq.read_table(job.companion, columns=["source_id"])
    selection = json.loads(stars.schema.metadata[STATS_KEY])
    if selection["min_parallax_over_error"] != gaia_source.MIN_PARALLAX_OVER_ERROR:
        raise DownloadError(
            f"{job.companion.name} is from another threshold: run gaia_source first"
        )
    kept = table.filter(pc.field("source_id").isin(stars["source_id"].combine_chunks()))
    return kept, {
        "stars": stars.num_rows,
        "stars_without_row": stars.num_rows - kept.num_rows,
        "min_parallax_over_error": selection["min_parallax_over_error"],
    }


class GaiaAstrophysicalParametersDownloader(ChunkedTableDownloader):
    name = PROVIDERS.GAIA_ASTROPHYSICAL_PARAMETERS
    table_path = TABLE_PATH
    exclude = (
        "solution_id",
        *(column for column in gaia_source.COLUMNS if column != "source_id"),
    )
    count_keys = ("stars", "stars_without_row")
    select = staticmethod(select_kept_stars)

    def companion(self, chunk: str) -> Path:
        pixels = chunk.removeprefix(CHUNK_PREFIX).removesuffix(CHUNK_SUFFIX)
        return (
            gaia_bulk.OUT_DIR
            / gaia_source.TABLE_PATH
            / f"{gaia_source.CHUNK_PREFIX}{pixels}.parquet"
        )

    def selection(self) -> dict[str, object]:
        return super().selection() | {
            "min_parallax_over_error": gaia_source.MIN_PARALLAX_OVER_ERROR
        }

    def is_current(self, stats: dict) -> bool:
        return stats["min_parallax_over_error"] == gaia_source.MIN_PARALLAX_OVER_ERROR
