"""Local copies of the dust maps, in native byte order and mag/pc.

A step reads these copies, so a build does not read the NAS at each run.
"""

import json
import logging
import os
from pathlib import Path

import numpy as np
from astropy.io import fits

from space_map_data.extrasolar.store import write_json
from space_map_data.utils.paths import CACHE_DIR, SOURCES_DUST_MAPS_DIR

logger = logging.getLogger(__name__)

BUILD_DIR = CACHE_DIR / "milky-way-3d" / "nest-build"
SOURCE_DIR = BUILD_DIR / "sources"

# A per ZGR23 unit at 550 nm, from the ZGR23 curve (Zenodo 7811871).
K550 = 2.6797492504119873
# The ZGR23 curve at 550 nm over the curve at 541.4 nm, the wavelength of Gaia TGE.
TGE_TO_550 = 2.680 / 2.770
NSIDE_EDENHOFER = 256


def atomic_npy(path: Path, array: np.ndarray) -> None:
    """Write an .npy file that takes its name only when complete."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.npy")
    np.save(temporary, array)
    os.replace(temporary, path)


def copy_key(source: Path) -> dict:
    """What a copy of `source` depends on."""
    stat = source.stat()
    return {
        "source": source.name,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "k550": K550,
    }


def _edenhofer_copy(fits_name: str, stem: str) -> None:
    """Copy one Edenhofer file to `<stem>.edges.npy`, `.inner.npy` and `.mean.npy`.

    A copy is complete when `<stem>.copy.json` holds the key of the source now. It
    lands last, so a stopped copy, a changed source or a changed K550 copies again.
    """
    source = SOURCES_DUST_MAPS_DIR / "edenhofer-2024" / fits_name
    key = copy_key(source)
    marker = SOURCE_DIR / f"{stem}.copy.json"
    if marker.exists() and json.loads(marker.read_text()) == key:
        return
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    marker.unlink(missing_ok=True)
    with fits.open(source, memmap=True) as h:
        edges = h["RADIAL PIXEL BOUNDARIES"].data["radial pixel boundaries"]
        atomic_npy(SOURCE_DIR / f"{stem}.edges.npy", np.asarray(edges, dtype="f8"))
        inner = next(x for x in h if x.name.startswith("MEAN OF INTEGRATED INNER"))
        atomic_npy(
            SOURCE_DIR / f"{stem}.inner.npy", np.asarray(inner.data, dtype="f4") * K550
        )
        mean = h["MEAN"].data
        out = SOURCE_DIR / f"{stem}.mean.npy"
        temporary = out.with_suffix(".tmp.npy")
        copy = np.lib.format.open_memmap(
            temporary, mode="w+", dtype="f4", shape=mean.shape
        )
        for i in range(mean.shape[0]):
            copy[i] = np.asarray(mean[i], dtype="f4") * K550
        copy.flush()
        del copy
        os.replace(temporary, out)
    write_json(marker, key)
    logger.info("copied %s", fits_name)


def prepare_edenhofer() -> None:
    _edenhofer_copy("mean_and_std_healpix.fits", "e24")
    _edenhofer_copy(
        "validation_with_less_data_but_2kpc_mean_and_std_healpix.fits", "e2k"
    )


def source_terms(directory: str) -> dict:
    """The `terms` block and the licence that a dust map's download recorded."""
    meta = json.loads((SOURCES_DUST_MAPS_DIR / directory / "metadata.json").read_text())
    return meta["terms"]
