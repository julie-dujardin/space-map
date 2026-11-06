"""Whole-sky columns: the Planck total and the Gaia total extinction map."""

import gzip
import io
import logging

import numpy as np
import pyarrow.csv as pacsv
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from cdshealpix import nested

from space_map_data.dust.resample import pixels
from space_map_data.dust.sources import BUILD_DIR, TGE_TO_550, atomic_npy
from space_map_data.utils.paths import SOURCES_DUST_MAPS_DIR

logger = logging.getLogger(__name__)

SKY_DIR = BUILD_DIR / "sky"
# Planck 2013 XI, section 6.1.
EBV_LIMIT = 0.3
EBV_PER_TAU = 1.49e4
R_V = 3.1
SKY_NSIDE = 256
TGE_DEPTH = 7
TGE_FILE = (
    "gaia-dr3-extinction/total_galactic_extinction_map_opt/"
    "TotalGalacticExtinctionMapOpt_001.csv.gz"
)


def planck_a0(ebv: np.ndarray, tau: np.ndarray) -> np.ndarray:
    """A0 by the paper's route: radiance at low column, tau353 elsewhere."""
    return R_V * np.where(ebv < EBV_LIMIT, ebv, EBV_PER_TAU * tau)


def prepare_planck() -> None:
    """Write the Nside 256 means of the total and of each of the two routes."""
    path = (
        SOURCES_DUST_MAPS_DIR
        / "planck-2013"
        / "HFI_CompMap_ThermalDustModel_2048_R1.20.fits"
    )
    with fits.open(path, memmap=True) as handle:
        table = handle[1].data
        ebv = np.asarray(table["EBV"], dtype="f8")
        tau = np.asarray(table["TAU353"], dtype="f8")
    per_pixel = (2048 // SKY_NSIDE) ** 2
    total = planck_a0(ebv, tau).reshape(-1, per_pixel).mean(axis=1)
    atomic_npy(SKY_DIR / "planck.total.npy", total.astype("f4"))
    atomic_npy(
        SKY_DIR / "planck.radiance.npy",
        (R_V * ebv).reshape(-1, per_pixel).mean(axis=1).astype("f4"),
    )
    atomic_npy(
        SKY_DIR / "planck.tau.npy",
        (R_V * EBV_PER_TAU * tau).reshape(-1, per_pixel).mean(axis=1).astype("f4"),
    )
    share = (ebv < EBV_LIMIT).astype("f4").reshape(-1, per_pixel).mean(axis=1)
    atomic_npy(SKY_DIR / "planck.radiance_share.npy", share)


def prepare_tge() -> None:
    """Write Gaia TGE as A0 at 550 nm on Galactic Nside 128 pixels, NaN with no value.

    The file holds nested ICRS pixels at level 9, with A0 at 541.4 nm.
    """
    with gzip.open(SOURCES_DUST_MAPS_DIR / TGE_FILE) as handle:
        raw = handle.read()
    header = raw[: raw.index(b"\nsolution_id") + 1].count(b"\n")
    table = pacsv.read_csv(
        io.BytesIO(raw), read_options=pacsv.ReadOptions(skip_rows=header)
    )
    level9 = table["healpix_id"].to_numpy().astype(np.uint64)
    a0 = table["a0"].to_numpy(zero_copy_only=False).astype("f8")
    lon, lat = nested.healpix_to_lonlat(level9, 9)
    galactic = SkyCoord(ra=lon, dec=lat, frame="icrs").galactic
    pixel = pixels(galactic.l.to_value(u.rad), galactic.b.to_value(u.rad), TGE_DEPTH)
    valid = np.isfinite(a0)
    size = 12 * 4**TGE_DEPTH
    count = np.bincount(pixel, minlength=size).astype("f8")
    held = np.bincount(pixel[valid], minlength=size).astype("f8")
    total = np.bincount(pixel[valid], weights=a0[valid], minlength=size)
    mean = np.divide(total, held, out=np.full(size, np.nan), where=held > 0)
    mean[held < 0.5 * count] = np.nan
    atomic_npy(SKY_DIR / "tge.a0_550.npy", (mean * TGE_TO_550).astype("f4"))
