"""SPICE-tree downloaders.

`bodies/` extracts per-body Keplerian / orientation / GM / shape data from
NAIF generic kernels; `probes/` mirrors per-mission spacecraft SPKs from
NAIF, ESA, and PDS archives; `synth/` synthesizes per-spacecraft SPKs from
Horizons VECTORS for probes with no published NAIF kernel. All three write
into the same on-disk SPICE tree under `DOWNLOAD_DIR/spice/`.
"""

from .bodies import SpiceDownloader
from .probes import ProbesDownloader
from .synth import HorizonsSyntheticDownloader

__all__ = ["HorizonsSyntheticDownloader", "ProbesDownloader", "SpiceDownloader"]
