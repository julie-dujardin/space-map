"""JMDC (Duvert 2016, VizieR II/345) as an ingest source.

JMDC lists the angular diameters measured directly, by interferometry and
lunar occultation, of about a thousand stars. Gaia saturates on most of them.
A row claims the star of its HD number, never mints and never matches by
position. A row names one star, so the rows of a star become one: the median
of its diameters, limb-darkened where JMDC gives one, else uniform-disk. The
rows run from Michelson's to CHARA's, and a star's rows can disagree.

Rows from 8 µm see the dust around a giant, not its surface, and are left out.
The reader turns a diameter into a radius at the star's distance.
"""

import gzip
import re
import statistics
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pyarrow as pa

from space_map_data.extrasolar.engine import Source
from space_map_data.extrasolar.sources.hipparcos import HD, claim_lists
from space_map_data.utils.paths import SOURCES_STARS_DIR

JMDC = Source(
    name="jmdc", catalogue="jmdc", release="2021", home=1, permanent=False, labels=True
)
JMDC_FILE = SOURCES_STARS_DIR / "cds" / "II" / "345" / "jmdc.dat.gz"
FIRST_DUST_BAND = 11
# The name of a row that holds no HD number, with that number.
HD_OF_NAME = {"CCDM J16294-2626 AB": "148478"}  # Antares


def _float(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def read_diameters(path: Path = JMDC_FILE) -> dict[str, tuple[float, int]]:
    """The median angular diameter (mas) of each star by HD number, and the
    number of rows behind it."""
    rows: dict[str, list[float]] = defaultdict(list)
    with gzip.open(path, "rt", encoding="latin-1") as lines:
        for line in lines:
            band = line[106:108].strip()
            if band.isdigit() and int(band) >= FIRST_DUST_BAND:
                continue
            value = _float(line[68:75]) or _float(line[58:67])
            name = line[:28].strip()
            match = re.fullmatch(r"HD\s*0*(\d+)", name)
            hd = match[1] if match else HD_OF_NAME.get(name)
            if value and hd:
                rows[hd].append(value)
    return {hd: (statistics.median(v), len(v)) for hd, v in rows.items()}


def engine_rows(
    hd_positions: Mapping[str, tuple[float, float]],
    diameters: Mapping[str, tuple[float, int]] | None = None,
) -> pa.Table:
    """A row for each star of JMDC with an HD number that a star holds."""
    found = read_diameters() if diameters is None else diameters
    numbers = [hd for hd in found if hd in hd_positions]
    at = np.array([hd_positions[hd] for hd in numbers], np.float64).reshape(-1, 2)
    n = len(numbers)
    nan = np.full(n, np.nan, np.float32)
    return pa.table(
        {
            "catalogue_id": pa.array(numbers, pa.string()),
            "mint": pa.array(np.zeros(n, bool)),
            "match_ra": pa.array(at[:, 0]),
            "match_dec": pa.array(at[:, 1]),
            "match_mag": pa.array(nan),
            "match_error": pa.array(nan),
            "claims": claim_lists([[(*HD, hd)] for hd in numbers]),
            "angular_diameter": pa.array(
                [found[hd][0] for hd in numbers], pa.float32()
            ),
            "angular_diameter_count": pa.array(
                [found[hd][1] for hd in numbers], pa.int16()
            ),
        }
    )
