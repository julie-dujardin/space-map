"""On-disk layout for Horizons-synthesized SPKs.

The CSV cache and the built SPK live in two trees: raw Horizons CSV per
`(naif_id, window, cadence)` under `SYNTH_CACHE_ROOT` is the source of truth,
and `SYNTH_KERNELS_DIR` (under the `missions/` tree so the existing ingest
walker finds it) holds the derived `.bsp` files.
"""

from space_map_data.constants.providers import PROVIDERS
from space_map_data.utils.paths import DOWNLOAD_DIR

SYNTH_CACHE_ROOT = DOWNLOAD_DIR / PROVIDERS.SPICE / "horizons-synth"
SYNTH_KERNELS_DIR = (
    DOWNLOAD_DIR / PROVIDERS.SPICE / "kernels" / "missions" / "HORIZONS-SYNTH"
)
