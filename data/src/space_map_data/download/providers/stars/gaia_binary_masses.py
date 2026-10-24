"""Download the Gaia DR3 masses of the two stars of a binary.

The orbit of the light centre alone does not tell where the companion is.
`binary_masses` gives the mass of each star, and for some the flux ratio, for
a part of the sources of `nss_two_body_orbit`. With them, the orbit of each
star about the centre of mass can be drawn. Method: Gaia Collaboration,
Arenou et al. 2023, A&A 674, A34.

Writes, below sources/stars/gaia/gdr3/Performance_verification/binary_masses/:
- BinaryMasses-001.parquet   every row of the table
- columns.json               type, unit and description of each column
- _MD5SUM.txt                the upstream file list
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

TABLE_PATH = f"{gaia_source.RELEASE}/Performance_verification/binary_masses"


class GaiaBinaryMassesDownloader(ChunkedTableDownloader):
    name = PROVIDERS.GAIA_BINARY_MASSES
    table_path = TABLE_PATH
    select = staticmethod(keep_all)
