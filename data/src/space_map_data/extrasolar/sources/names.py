"""The IAU star names (WGSN) as an ingest source.

A name never mints. It reaches its star by a claim of its HIP number, or of
the HD number in its designation, else by position and magnitude. A name
that reaches no star is a new object that never mints, so the report counts
it as unplaced.
"""

import json
import logging
import re
from pathlib import Path

import numpy as np
import pyarrow as pa

from space_map_data.download.providers.stars import iau_names
from space_map_data.extrasolar import sky
from space_map_data.extrasolar.engine import Source
from space_map_data.extrasolar.match import PositionMatcher
from space_map_data.extrasolar.sources.hipparcos import HD
from space_map_data.extrasolar.tables import CROSS_ID

logger = logging.getLogger(__name__)

NAMES_FILE = iau_names.OUT_DIR / "names.json"

# The list gives no epoch. A position counts as good to 1″, and beyond 3″ the
# magnitudes must agree.
MATCHER = PositionMatcher(
    n_sigma=5.0,
    near_sigma=3.0,
    min_error=0.1,
    reach=0.1,
    max_mag_diff=1.5,
    mag_sigma=0.5,
)
IAU_WGSN = Source(
    name="iau-wgsn", catalogue="iau", release="wgsn", home=1, matcher=MATCHER
)
POSITION_ERROR = 1.0
# Arcsec between a listed position and its HIP star that the log reports.
# The proper motion between the epochs stays under it, Barnard's Star too.
MAX_OFFSET = 300.0
# Bands whose magnitude compares with Gaia G and the Hipparcos G estimate.
OPTICAL_BANDS = frozenset({"", "V", "G"})
HIP = ("hip", "2007")

_HD = re.compile(r"HD (\d+)")


def _number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def _brightness(entry: dict) -> float:
    mag = _number(entry["mag"])
    return np.inf if mag is None else mag


def read_names(path: Path = NAMES_FILE) -> list[str]:
    return [entry[iau_names.NAME_COLUMN] for entry in json.loads(path.read_text())]


def engine_rows(
    hip_positions: dict[str, tuple[float, float]], path: Path = NAMES_FILE
) -> pa.Table:
    """The pass rows of the names, one per name with a position.

    A name that claims a HIP number takes the J2016.0 position of that star
    from `hip_positions`: the claim is looked up near the row, and the list
    has wrong positions.
    """
    entries = json.loads(path.read_text())
    # Several names on one HIP number name its components. The brightest
    # keeps the claim and the others go by position.
    by_hip: dict[str, dict] = {}
    for entry in entries:
        if entry["HIP"]:
            kept = by_hip.get(entry["HIP"])
            if kept is None or _brightness(entry) < _brightness(kept):
                by_hip[entry["HIP"]] = entry
    rows = []
    for entry in entries:
        claims = []
        if entry["HIP"] and by_hip[entry["HIP"]] is entry:
            claims.append(dict(zip(CROSS_ID.names, (*HIP, entry["HIP"]))))
        elif entry["HIP"]:
            logger.info(
                "%s: HIP %s is also %s; it matches by position",
                entry[iau_names.NAME_COLUMN],
                entry["HIP"],
                by_hip[entry["HIP"]][iau_names.NAME_COLUMN],
            )
        if hd := _HD.fullmatch(entry["Designation"]):
            claims.append(dict(zip(CROSS_ID.names, (*HD, hd[1]))))
        ra, dec = _number(entry["RA"]), _number(entry["DEC"])
        if (
            claims
            and claims[0]["catalogue"] == HIP[0]
            and entry["HIP"] in hip_positions
        ):
            hip_ra, hip_dec = hip_positions[entry["HIP"]]
            if ra is not None and dec is not None:
                apart = float(sky.separation(ra, dec, hip_ra, hip_dec))
                if apart > MAX_OFFSET:
                    logger.warning(
                        "%s: the list puts it %.2f° from HIP %s; it takes the"
                        " Hipparcos position",
                        entry[iau_names.NAME_COLUMN],
                        apart / 3600,
                        entry["HIP"],
                    )
            ra, dec = hip_ra, hip_dec
        if ra is None or dec is None:
            logger.info(
                "%s (%s) has no position and no HIP position: unplaced",
                entry[iau_names.NAME_COLUMN],
                entry["Designation"],
            )
            continue
        mag = _number(entry["mag"]) if entry["band"] in OPTICAL_BANDS else None
        rows.append(
            {
                "catalogue_id": entry[iau_names.NAME_COLUMN],
                "match_ra": ra,
                "match_dec": dec,
                "match_mag": mag,
                "claims": claims or None,
            }
        )
    n = len(rows)
    table = pa.Table.from_pylist(
        rows,
        pa.schema(
            [
                ("catalogue_id", pa.string()),
                ("match_ra", pa.float64()),
                ("match_dec", pa.float64()),
                ("match_mag", pa.float32()),
                ("claims", pa.list_(CROSS_ID)),
            ]
        ),
    )
    return (
        table.append_column("mint", pa.array(np.zeros(n, bool)))
        .append_column("match_error", pa.array(np.full(n, POSITION_ERROR, np.float32)))
        .append_column("name", table["catalogue_id"])
    )
