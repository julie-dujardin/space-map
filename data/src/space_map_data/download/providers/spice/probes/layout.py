"""On-disk layout for probe SPKs.

Probe kernels share the SPICE on-disk tree because the runtime needs both
generic kernels (lsk/pck/de/satellite ephemerides) and mission-trajectory
kernels furnished together.

Surface / post-touchdown kernels live in a sibling tree. Two reasons for
splitting them out: (1) the trajectory exporter explicitly does NOT want
them — loading a `*_atls_*` next to `*_cruise_*` makes SPICE last-loaded-
wins paint the cruise NAIF at the surface during EDL, contaminating the
classify_trace landed-detection signal; (2) the landed exporter wants
them in isolation so cruise/EDL motion doesn't bleed into the surface
trace. Each mission lives at the same key in both trees, with its own
_index.json.
"""

from space_map_data.constants.providers import PROVIDERS
from space_map_data.utils.paths import DOWNLOAD_DIR

MISSIONS_DIR = DOWNLOAD_DIR / PROVIDERS.SPICE / "kernels" / "missions"
LANDED_MISSIONS_DIR = DOWNLOAD_DIR / PROVIDERS.SPICE / "kernels" / "landed_missions"
