"""The Spitzer/IRAC candidate young stellar objects of SPICY (Kuhn et al.
2021) as an ingest source.

SPICY classifies each candidate by the slope of its infrared SED: Class I,
flat spectrum (FS), Class II, Class III or uncertain. A candidate takes the
Gaia DR2 counterpart that SPICY gives it, and that id goes to the nearest
Gaia DR3 source of `dr2_neighbourhood` (download spicy_gaia). A candidate
without a DR2 counterpart, or whose DR2 id has no DR3 neighbour, is left out.
Two candidates with one DR3 source keep the one whose DR2 source is nearer.

The rows join the Gaia rows by source_id at each ingest. They hold no
catalogue id in the registry.

Licence: none stated. Cite Kuhn et al. 2021, ApJS 254, 33 and the IRSA
dataset doi:10.26131/IRSA556.
"""

import logging
from pathlib import Path

import numpy as np
import pyarrow as pa
from astropy.io import fits

from space_map_data.extrasolar.exoplanets.hosts import read_nearest
from space_map_data.utils.paths import SOURCES_CATALOGUES_DIR, SOURCES_STARS_DIR

logger = logging.getLogger(__name__)

SPICY_FILE = SOURCES_CATALOGUES_DIR / "stellar-parameters" / "spicy" / "table1.fits"
NEIGHBOURHOOD = SOURCES_STARS_DIR / "spicy-gaia" / "dr2_neighbourhood.csv"
COLUMNS = ("spicy_id", "class_spicy", "alpha_spicy")
# Rows of table1 (Kuhn et al. 2021, Table 1).
ROWS = 117_446


def read_candidates(path: Path = SPICY_FILE) -> dict[str, np.ndarray]:
    """The SPICY id, Gaia DR2 id (0 for none), class and spectral index of
    each candidate."""
    with fits.open(path) as hdul:
        data = hdul[1].data
        candidates = {
            "spicy": np.asarray(data["SPICY"]).astype(np.int64),
            "dr2": np.asarray(data["GaiaDR2"]).astype(np.int64),
            "class": np.char.strip(np.asarray(data["class"]).astype(str)),
            "alpha": np.asarray(data["alpha"]).astype(np.float64),
        }
    if candidates["spicy"].size != ROWS:
        raise ValueError(f"{path}: {candidates['spicy'].size} rows, SPICY has {ROWS}")
    return candidates


def read_stars(
    path: Path = SPICY_FILE, neighbourhood: Path = NEIGHBOURHOOD
) -> pa.Table:
    """One row per Gaia DR3 source: its SPICY id, class and spectral index."""
    candidates = read_candidates(path)
    spicy, dr2 = candidates["spicy"], candidates["dr2"]
    nearest = read_nearest(neighbourhood)
    with_dr2 = np.flatnonzero(dr2 > 0)
    found = np.array([i for i in with_dr2 if int(dr2[i]) in nearest], np.int64)
    dr3 = np.array([nearest[int(dr2[i])][0] for i in found], np.int64)
    distance = np.array([nearest[int(dr2[i])][1] for i in found], np.float64)
    order = np.lexsort((spicy[found], distance, dr3))
    first = np.ones(order.size, bool)
    first[1:] = dr3[order][1:] != dr3[order][:-1]
    kept = np.sort(order[first])
    logger.info(
        "SPICY: %d candidates, %d with a Gaia DR2 id, %d with a DR3 neighbour,"
        " %d Gaia DR3 sources; left out %d whose DR3 source a nearer candidate"
        " takes",
        spicy.size,
        with_dr2.size,
        found.size,
        kept.size,
        found.size - kept.size,
    )
    rows = found[kept]
    return pa.table(
        {
            "source_id": pa.array(dr3[kept]),
            "spicy_id": pa.array(spicy[rows].astype(np.int32)),
            "class_spicy": pa.array(candidates["class"][rows].tolist(), pa.string()),
            "alpha_spicy": pa.array(
                candidates["alpha"][rows], pa.float32(), from_pandas=True
            ),
        }
    )
