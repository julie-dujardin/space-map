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

from space_map_data.utils.paths import SOURCES_POSITION_DIR

_KERNELS_DIR = SOURCES_POSITION_DIR / "spice-kernels"
MISSIONS_DIR = _KERNELS_DIR / "missions"
LANDED_MISSIONS_DIR = _KERNELS_DIR / "landed-missions"
