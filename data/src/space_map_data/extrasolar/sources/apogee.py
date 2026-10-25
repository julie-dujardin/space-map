"""APOGEE DR17 (Abdurro'uf et al. 2022) as an ingest source.

The rows are the named ASPCAP values of allStarLite: SDSS blanks them for a
star with STAR_BAD or CHI2_BAD, so a row has [M/H] or [Fe/H] only where SDSS
trusts it. A star observed again has a duplicate row (EXTRATARG bit 4); the
row with the best S/N stays.

A row joins the Gaia row of its Gaia EDR3 id, which is the Gaia DR3 id, at
each ingest. APOGEE took the id from a cross-match of its 2MASS source. In
crowded fields that match can be another star, so a row is dropped when its
own photometry disagrees with the Gaia source: G far too faint for H at the
source's colour, or a source far bluer than the ASPCAP Teff allows.

Licence: none stated, so the data are non-commercial. SDSS asks for the
data-release papers and the SDSS-IV acknowledgement.
"""

import logging
from pathlib import Path

import numpy as np
import pyarrow as pa
from astropy.io import fits

from space_map_data.utils.paths import SOURCES_CATALOGUES_DIR

logger = logging.getLogger(__name__)

APOGEE_FILE = (
    SOURCES_CATALOGUES_DIR
    / "stellar-parameters"
    / "apogee-dr17"
    / "allStarLite-dr17-synspec_rev1.fits"
)
DUPLICATE = 1 << 4
# FITS column of each table column.
VALUES = {
    "mh_apogee": "M_H",
    "mh_apogee_error": "M_H_ERR",
    "feh_apogee": "FE_H",
    "feh_apogee_error": "FE_H_ERR",
    "teff_apogee": "TEFF",
    "teff_apogee_error": "TEFF_ERR",
    "logg_apogee": "LOGG",
    "logg_apogee_error": "LOGG_ERR",
    "snr_apogee": "SNR",
}
COLUMNS = ("apogee_id", *VALUES)
# allStar writes a large negative number or NaN where a value is blank.
BLANK_BELOW = -9000.0
# G - H minus its median at the same BP - RP, in mag. 99.9% of the rows are
# under 1.5; the audit's 50 worst matches are all over 3.
TOO_FAINT = 2.0
# A row this much too faint is dropped when it is also too blue for its Teff.
FAINT_AND_BLUE = 1.0
COLOUR_BINS = 60
# The BP - RP of a dwarf at each Teff (Pecaut & Mamajek 2013, version of
# 2022). Extinction only reddens, so a Gaia source much bluer than this is
# another star or a blend with a hotter one.
DWARF_TEFF = (
    3060,
    3210,
    3430,
    3560,
    3660,
    3850,
    4050,
    4440,
    5040,
    5270,
    5770,
    6000,
    6550,
    7300,
    8500,
    10000,
)
DWARF_BP_RP = (
    3.10,
    2.78,
    2.42,
    2.19,
    2.05,
    1.84,
    1.70,
    1.43,
    1.10,
    0.99,
    0.82,
    0.75,
    0.61,
    0.43,
    0.20,
    0.0,
)
TOO_BLUE = 0.35


def _values(data: fits.FITS_rec, name: str) -> np.ndarray:
    values = np.asarray(data[name]).astype(np.float64)
    values[~np.isfinite(values) | (values < BLANK_BELOW)] = np.nan
    return values


def faintness(g: np.ndarray, h: np.ndarray, bp_rp: np.ndarray) -> np.ndarray:
    """G - H minus its median in the BP - RP quantile bin of each row."""
    gh = g - h
    ok = np.isfinite(gh) & np.isfinite(bp_rp)
    out = np.full(g.size, np.nan)
    if ok.sum() < COLOUR_BINS:
        return out
    edges = np.unique(np.percentile(bp_rp[ok], np.linspace(0, 100, COLOUR_BINS + 1)))
    bins = np.clip(np.searchsorted(edges, bp_rp, "right") - 1, 0, edges.size - 2)
    median = np.full(edges.size - 1, np.nan)
    for k in range(edges.size - 1):
        inside = ok & (bins == k)
        if inside.any():
            median[k] = np.median(gh[inside])
    out[ok] = gh[ok] - median[bins[ok]]
    return out


def too_blue(bp_rp: np.ndarray, teff: np.ndarray) -> np.ndarray:
    dwarf = np.interp(
        np.clip(teff, DWARF_TEFF[0], DWARF_TEFF[-1]), DWARF_TEFF, DWARF_BP_RP
    )
    return np.isfinite(teff) & np.isfinite(bp_rp) & (bp_rp < dwarf - TOO_BLUE)


def read_stars(path: Path = APOGEE_FILE) -> pa.Table:
    """One row per Gaia source with a named [M/H] or [Fe/H], best S/N first."""
    with fits.open(path, memmap=True) as hdul:
        data = hdul[1].data
        source_id = np.asarray(data["GAIAEDR3_SOURCE_ID"]).astype(np.int64)
        extra = np.asarray(data["EXTRATARG"]).astype(np.int64)
        columns = {name: _values(data, column) for name, column in VALUES.items()}
        apogee_id = np.asarray(data["APOGEE_ID"]).astype(str)
        g = _values(data, "GAIAEDR3_PHOT_G_MEAN_MAG")
        bp_rp = _values(data, "GAIAEDR3_PHOT_BP_MEAN_MAG") - _values(
            data, "GAIAEDR3_PHOT_RP_MEAN_MAG"
        )
        h = _values(data, "H")
    h[h > 50] = np.nan
    keep = (
        (source_id > 0)
        & ((extra & DUPLICATE) == 0)
        & (np.isfinite(columns["mh_apogee"]) | np.isfinite(columns["feh_apogee"]))
    )
    at = np.flatnonzero(keep)
    at = at[np.lexsort((-np.nan_to_num(columns["snr_apogee"][at]), source_id[at]))]
    at = at[np.r_[True, source_id[at][1:] != source_id[at][:-1]]]
    faint = faintness(g[at], h[at], bp_rp[at])
    blue = too_blue(bp_rp[at], columns["teff_apogee"][at])
    wrong = (faint > TOO_FAINT) | (blue & (faint > FAINT_AND_BLUE))
    logger.info(
        "APOGEE DR17: %d rows, %d Gaia stars with a named metallicity; %d dropped"
        " as another star (%d far too faint for H, %d too faint and too blue)",
        source_id.size,
        at.size,
        int(wrong.sum()),
        int((faint > TOO_FAINT).sum()),
        int((blue & (faint > FAINT_AND_BLUE) & ~(faint > TOO_FAINT)).sum()),
    )
    at = at[~wrong]
    table = {
        "source_id": pa.array(source_id[at]),
        "apogee_id": pa.array(apogee_id[at]),
    }
    table |= {
        name: pa.array(values[at], pa.float32(), from_pandas=True)
        for name, values in columns.items()
    }
    return pa.table(table)
