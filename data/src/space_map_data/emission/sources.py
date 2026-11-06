"""The inputs of the emission as stored under `sources/emission/`.

McCallum's cube is 4.3 GB of float32, so it is read in slabs through a memory map
and reduced as it goes.
"""

import csv
from dataclasses import dataclass

import numpy as np
from astropy.io import fits

from space_map_data.utils.paths import SOURCES_EMISSION_DIR

MCCALLUM_DIR = SOURCES_EMISSION_DIR / "mccallum-2025"
FINKBEINER_DIR = SOURCES_EMISSION_DIR / "finkbeiner-2003"
WISE_FILE = SOURCES_EMISSION_DIR / "wise-hii-v3" / "WISE_HII_V3.0_website.csv"
CUBE_FILE = MCCALLUM_DIR / "ha_grid.fits"
FINKBEINER_FILE = FINKBEINER_DIR / "Halpha_fwhm06_1024.fits"

# McCallum's box: a cube of 2.5 kpc about the Sun, on Galactic axes.
CUBE_HALF_PC = 1250.0
CUBE_SIZE = 1024


def cube_blocks(factor: int) -> np.ndarray:
    """McCallum's H-alpha emissivity as means over blocks of `factor`^3 voxels, in
    W m^-3, index order [x, y, z]. Reads `factor` planes at a time."""
    size = CUBE_SIZE // factor
    out = np.zeros((size, size, size), np.float64)
    with fits.open(CUBE_FILE, memmap=True) as handle:
        data = handle[0].data
        if data.shape != (CUBE_SIZE,) * 3:
            raise ValueError(f"{CUBE_FILE}: shape {data.shape}")
        for k in range(size):
            slab = np.asarray(data[k * factor : (k + 1) * factor], np.float64)
            # The file is [z, y, x].
            mean = slab.reshape(factor, size, factor, size, factor).mean(axis=(0, 2, 4))
            out[:, :, k] = mean.T
    return out


def finkbeiner_sky() -> np.ndarray:
    """Finkbeiner 2003 in R, HEALPix Nside 1024, NESTED, Galactic."""
    with fits.open(FINKBEINER_FILE, memmap=True) as handle:
        return np.asarray(handle[1].data.field(0), np.float64).ravel()


@dataclass(frozen=True)
class WiseRow:
    name: str
    catalog: str
    l_deg: float
    b_deg: float
    radius_arcsec: float
    distance_kpc: float
    distance_method: str
    # Jy, NaN where the catalogue has none.
    vgps: float
    magpis: float
    mipsgal: float
    wise4: float
    wise3: float
    glimpse: float
    names: str


def _value(text: str) -> float:
    try:
        return float(text)
    except ValueError:
        return np.nan


def wise_rows() -> list[WiseRow]:
    """Every row of the WISE catalogue with a distance."""
    with WISE_FILE.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    out = []
    for row in rows:
        distance = _value(row["Distance"])
        if not np.isfinite(distance):
            continue
        out.append(
            WiseRow(
                row["WISE_Name"],
                row["Catalog"],
                float(row["GLong"]),
                float(row["GLat"]),
                float(row["Radius"]),
                distance,
                row["DMethod"],
                _value(row["VGPS_Flux"]),
                _value(row["MAGPIS_Flux"]),
                _value(row["MIPSGal_Flux"]),
                _value(row["WISE4_Flux"]),
                _value(row["WISE3_Flux"]),
                _value(row["GLIMPSE_Flux"]),
                row["All_Names"],
            )
        )
    return out
