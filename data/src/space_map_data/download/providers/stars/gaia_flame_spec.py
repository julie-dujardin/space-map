"""Download FLAME's run on the GSP-Spec parameters of the positionable stars.

`astrophysical_parameters_supp` holds a second FLAME result for about 5
million stars, from the temperature, gravity and metallicity that GSP-Spec
measured on the RVS spectra (Creevey et al. 2023, A&A 674, A26, Sect. 6.4.1).
It also repeats GSP-Phot for every model library, which nothing reads, so
only FLAME's columns are kept, and only the rows of the stars that
`gaia_source` kept and that have a FLAME value. It has the same chunks as
`gaia_source`.

Writes, below sources/stars/gaia/gdr3/Astrophysical_parameters/astrophysical_parameters_supp/:
- AstrophysicalParametersSupp_<pixels>.parquet   the kept rows of one chunk
- columns.json                                   type, unit and description of each column
- _MD5SUM.txt                                    the upstream chunk list
- metadata.json

Licence: CC BY-NC 3.0 IGO, credit ESA/Gaia/DPAC.
https://www.cosmos.esa.int/web/gaia-users/license
"""

from functools import reduce

import pyarrow as pa
import pyarrow.compute as pc

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.providers.stars import gaia_source
from space_map_data.download.providers.stars.gaia_astrophysical_parameters import (
    GaiaAstrophysicalParametersDownloader,
    select_kept_stars,
)
from space_map_data.download.providers.stars.gaia_bulk import ChunkJob

TABLE_PATH = (
    f"{gaia_source.RELEASE}/Astrophysical_parameters/astrophysical_parameters_supp"
)
CHUNK_PREFIX = "AstrophysicalParametersSupp_"
# The names of the Point source group `flame_spec`.
FLAME_SPEC_COLUMNS = (
    *(
        f"{name}_flame_spec{bound}"
        for name in ("radius", "lum", "mass", "age", "gravredshift")
        for bound in ("", "_lower", "_upper")
    ),
    "bc_flame_spec",
    "evolstage_flame_spec",
    "flags_flame_spec",
)


def select_flame_rows(
    table: pa.Table, job: ChunkJob
) -> tuple[pa.Table, dict[str, float]]:
    kept, stats = select_kept_stars(table, job)
    has_value = reduce(pc.or_, (pc.is_valid(kept[name]) for name in FLAME_SPEC_COLUMNS))
    return kept.filter(has_value), stats


class GaiaFlameSpecDownloader(GaiaAstrophysicalParametersDownloader):
    name = PROVIDERS.GAIA_FLAME_SPEC
    table_path = TABLE_PATH
    chunk_prefix = CHUNK_PREFIX
    columns = ("source_id", *FLAME_SPEC_COLUMNS)
    exclude = ()
    select = staticmethod(select_flame_rows)
