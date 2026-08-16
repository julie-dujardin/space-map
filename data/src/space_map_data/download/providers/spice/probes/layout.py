"""On-disk layout for probe SPKs.

Probe kernels share the SPICE tree because the runtime furnishes generic
kernels (lsk/pck/de/satellite ephemerides) and mission-trajectory kernels
together.

Surface/post-touchdown kernels live in a sibling tree: mixing `*_atls_*`
into the same furnish as `*_cruise_*` lets SPICE's last-loaded-wins paint
the cruise NAIF at the surface during EDL, contaminating landed-detection;
keeping them apart also stops cruise/EDL motion bleeding into the landed
exporter's surface trace. Each mission has its own `_index.json` in both
trees.
"""

from space_map_data.utils.paths import SOURCES_POSITION_DIR

_KERNELS_DIR = SOURCES_POSITION_DIR / "spice-kernels"
MISSIONS_DIR = _KERNELS_DIR / "missions"
LANDED_MISSIONS_DIR = _KERNELS_DIR / "landed-missions"
