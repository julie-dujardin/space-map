"""Download the Gaia DR3 golden sample of OBA stars.

`gold_sample_oba_stars` lists 3,023,388 sources with an ESP-HS or GSP-Phot
temperature above 7,500 K, after filters that remove most other kinds of
source (Gaia Collaboration, Creevey et al. 2023, A&A 674, A39). Andrae, Rix &
Chandra (2023) use it to remove the OBA stars from their XP metallicities.
The list is complete, so the ingest flags every Gaia DR3 row true or false.
The table is kept whole, also the rows of the stars that are not
positionable, because the SIMBAD stars and the planet hosts without a 5σ
parallax get the flag too.

Writes, below sources/stars/gaia/gdr3/Performance_verification/gold_sample_oba_stars/:
- GoldSampleObaStars.parquet   every row of the table
- columns.json                 type, unit and description of each column
- _MD5SUM.txt                  the upstream file list
- metadata.json

Licence: CC BY-NC 3.0 IGO, credit ESA/Gaia/DPAC.
https://www.cosmos.esa.int/web/gaia-users/license
"""

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.providers.stars import gaia_source
from space_map_data.download.providers.stars.gaia_bulk import (
    ChunkedTableDownloader,
    keep_all,
)

TABLE_PATH = f"{gaia_source.RELEASE}/Performance_verification/gold_sample_oba_stars"
CHUNK_PREFIX = "GoldSampleObaStars"


class GaiaOBAGoldenSampleDownloader(ChunkedTableDownloader):
    name = PROVIDERS.GAIA_OBA_GOLDEN_SAMPLE
    table_path = TABLE_PATH
    select = staticmethod(keep_all)
