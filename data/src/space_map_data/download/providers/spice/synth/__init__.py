"""Horizons → synthetic SPK kernels.

For spacecraft Horizons can compute state vectors for but JPL/NAIF doesn't
publish a binary SPK for (~200 in the Horizons MB list), fetch VECTORS at an
adaptive cadence and pack them into a binary SPK locally via `spkw13`.

The cache is the source of truth: raw Horizons CSV per `(naif_id, window,
cadence)`. SPK files are derived artifacts, fully regenerable offline. Refresh
is gated by Horizons' `Revised :` header so repeated runs only re-hit the API
when the spacecraft solution actually changes.
"""

from .downloader import HorizonsSyntheticDownloader
from .index import qid_deduped_synth_naifs
from .layout import SYNTH_CACHE_ROOT, SYNTH_KERNELS_DIR

__all__ = [
    "HorizonsSyntheticDownloader",
    "SYNTH_CACHE_ROOT",
    "SYNTH_KERNELS_DIR",
    "qid_deduped_synth_naifs",
]
