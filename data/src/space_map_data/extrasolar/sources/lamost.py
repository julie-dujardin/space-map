"""The LAMOST DR10 M dwarfs of Zhang et al. (2025) as an ingest source.

Cycle-StarNet fits Teff, log g and [M/H] to 507,513 low-resolution LAMOST
spectra of M dwarfs. One row is one spectrum, with the Gaia DR3 photometry
and parallax of its star. The LAMOST DR10 v2.0 catalogue of M stars gives
the Gaia id of each spectrum, by obsid, with the G of that source. A spectrum
is dropped without a Gaia id, or when that G is not the row's own: the id
then names another star, farther from the fibre. A G missing on either side
fails that check. A Gaia source with several
spectra keeps the one with the best S/N in i, then the lowest obsid.

The rows join the Gaia rows by source_id at each ingest. They hold no
catalogue id in the registry.

Licence: CC BY 4.0. Cite Zhang, Zhang, Ting et al. 2025, ApJS 277, 47. The
M-star catalogue states no licence; only its Gaia ids are used.
"""

import logging
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pcsv
from astropy.io import fits

from space_map_data.utils.paths import SOURCES_CATALOGUES_DIR

logger = logging.getLogger(__name__)

LAMOST_DIR = SOURCES_CATALOGUES_DIR / "stellar-parameters"
LAMOST_FILE = LAMOST_DIR / "lamost-dr10-m-dwarfs" / "DR10_Cycle-SN_M_dwarfs.csv"
MSTELLAR_FILE = LAMOST_DIR / "lamost-dr10-mstellar" / "dr10_v2.0_LRS_mstellar.fits.gz"
# Table column of each catalogue column.
VALUES = {
    "[M/H]": "mh_lamost",
    "e_[M/H]": "mh_lamost_error",
    "Teff": "teff_lamost",
    "e_Teff": "teff_lamost_error",
    "Logg": "logg_lamost",
    "e_Logg": "logg_lamost_error",
    "SNRi": "snr_i_lamost",
}
COLUMNS = ("lamost_id", *VALUES.values(), "activity_lamost", "vbflag_lamost")
# Both G are the DR3 value of one source, so they differ only for two sources.
MAX_G_DIFF = 1e-4


def read_gaia_ids(
    path: Path = MSTELLAR_FILE,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """obsid, Gaia DR3 source_id and its G of each spectrum that has an id."""
    with fits.open(path) as hdul:
        data = hdul[1].data
        obsid = np.asarray(data["obsid"]).astype(np.int64)
        text = np.char.strip(np.asarray(data["gaia_source_id"]).astype(str))
        g = np.asarray(data["gaia_g_mean_mag"]).astype(np.float64)
    has = np.char.isdigit(text)
    source_id = np.zeros(obsid.size, np.int64)
    source_id[has] = text[has].astype(np.int64)
    keep = source_id > 0
    return obsid[keep], source_id[keep], g[keep]


def one_per_source(
    source_id: np.ndarray, snr: np.ndarray, obsid: np.ndarray
) -> np.ndarray:
    """Rows to keep: the best S/N in i of each source, then the lowest obsid."""
    order = np.lexsort((obsid, -np.nan_to_num(snr, nan=-np.inf), source_id))
    first = np.r_[True, source_id[order][1:] != source_id[order][:-1]]
    return np.sort(order[first])


def read_stars(path: Path = LAMOST_FILE, mstellar: Path = MSTELLAR_FILE) -> pa.Table:
    """One row per Gaia source, from its spectrum with the best S/N in i."""
    rows = pcsv.read_csv(path)
    rows = rows.filter(pc.is_valid(rows["[M/H]"]))
    obsid, gaia, g = read_gaia_ids(mstellar)
    order = np.argsort(obsid)
    obsid, gaia, g = obsid[order], gaia[order], g[order]
    theirs = rows["obsid"].to_numpy()
    at = np.minimum(np.searchsorted(obsid, theirs), max(obsid.size - 1, 0))
    hit = (obsid.size > 0) & (obsid[at] == theirs)
    source_id = np.where(hit, gaia[at], 0)
    own_g = rows["Gmag"].to_numpy(zero_copy_only=False).astype(float)
    their_g = g[at]
    no_g = hit & (np.isnan(own_g) | np.isnan(their_g))
    other = hit & (np.abs(their_g - own_g) > MAX_G_DIFF)
    source_id[no_g | other] = 0
    with_id = np.flatnonzero(source_id > 0)
    best = with_id[
        one_per_source(
            source_id[with_id],
            rows["SNRi"].to_numpy(zero_copy_only=False)[with_id].astype(float),
            theirs[with_id],
        )
    ]
    logger.info(
        "LAMOST DR10 M dwarfs: %d spectra with [M/H], %d with a Gaia id, %d Gaia"
        " sources; dropped: %d without a G to compare, %d with the Gaia id of"
        " another star",
        rows.num_rows,
        with_id.size,
        best.size,
        int(no_g.sum()),
        int(other.sum()),
    )
    chosen = rows.take(pa.array(best))
    columns = {
        "source_id": pa.array(source_id[best]),
        "lamost_id": chosen["ID"],
        **{
            name: pc.cast(chosen[column], pa.float32())
            for column, name in VALUES.items()
        },
        "activity_lamost": pc.equal(chosen["Activity"], 1),
        "vbflag_lamost": pc.cast(chosen["VBFlag"], pa.int8()),
    }
    return pa.table(columns)
