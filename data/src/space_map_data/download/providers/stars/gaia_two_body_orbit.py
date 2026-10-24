"""Download the Gaia DR3 orbits of binary stars.

`nss_two_body_orbit` has one row per orbit solution. An astrometric solution
(`Orbital*`, `AstroSpectroSB1`) gives the orbit of the light centre with its
orientation on the sky, so it can be drawn in space. A spectroscopic or
eclipsing solution gives no orientation on the sky.

The table is kept whole, also the rows of stars that are not positionable, so
a change of the star selection needs no new download.

Writes, below sources/stars/gaia/gdr3/Non-single_stars/nss_two_body_orbit/:
- NssTwoBodyOrbit_1.parquet   every row of the table
- columns.json                type, unit and description of each column
- _MD5SUM.txt                 the upstream file list
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

TABLE_PATH = f"{gaia_source.RELEASE}/Non-single_stars/nss_two_body_orbit"


class GaiaTwoBodyOrbitDownloader(ChunkedTableDownloader):
    name = PROVIDERS.GAIA_TWO_BODY_ORBIT
    table_path = TABLE_PATH
    select = staticmethod(keep_all)
