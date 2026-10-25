"""The IAU star names (WGSN) as an ingest source.

A name never mints. It reaches its star by a claim of its HIP number. Several
names on one HIP number name its components: the brightest keeps the claim. A
name without a HIP claim claims the SIMBAD row that stands for its SIMBAD
object, and the HD number in its designation, else it goes by position and
magnitude. A fainter component claims only a SIMBAD row of its own. A SIMBAD
row takes one name, and never one when a name claims its HIP number. A
claimed star gives the name its position. A name that reaches no star is a
new object that never mints, so the report counts it as unplaced.
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
from space_map_data.extrasolar.exoplanets.names import WgsnName
from space_map_data.extrasolar.match import PositionMatcher
from space_map_data.extrasolar.sources.hipparcos import HD
from space_map_data.extrasolar.sources.simbad import IauRow
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
# Arcsec between a listed position and its claimed star that the log reports.
# The proper motion between the epochs stays under it, Barnard's Star too.
MAX_OFFSET = 300.0
# Bands whose magnitude compares with Gaia G and the Hipparcos G estimate.
OPTICAL_BANDS = frozenset({"", "V", "G"})
HIP = ("hip", "2007")
SIMBAD_OID = ("simbad", "oid")

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


def read_designations(path: Path = NAMES_FILE) -> list[tuple[str, str]]:
    """The name and designation of each entry."""
    return [
        (entry[iau_names.NAME_COLUMN], entry["Designation"])
        for entry in json.loads(path.read_text())
    ]


def _simbad_claims(
    entries: list[dict], by_hip: dict[str, dict], simbad: dict[str, IauRow]
) -> dict[str, IauRow]:
    """The SIMBAD row that each name claims, one name per row.

    A row of its own comes first, then the brightest name.
    """
    candidates = []
    for entry in entries:
        found = simbad.get(entry[iau_names.NAME_COLUMN])
        if found is None or found.hip in by_hip:
            continue
        if entry["HIP"] and (by_hip[entry["HIP"]] is entry or not found.own):
            continue
        candidates.append((not found.own, _brightness(entry), entry, found))
    claimed: dict[str, IauRow] = {}
    holders: dict[str, str] = {}
    for _, _, entry, found in sorted(candidates, key=lambda c: c[:2]):
        name = entry[iau_names.NAME_COLUMN]
        if found.oid in holders:
            logger.info(
                "%s: SIMBAD %s is also %s; it matches by position",
                name,
                found.oid,
                holders[found.oid],
            )
            continue
        holders[found.oid] = name
        claimed[name] = found
    return claimed


def engine_rows(
    hip_positions: dict[str, tuple[float, float]],
    path: Path = NAMES_FILE,
    simbad: dict[str, IauRow] | None = None,
) -> pa.Table:
    """The pass rows of the names, one per name with a position.

    A name that claims a HIP number takes the J2016.0 position of that star
    from `hip_positions`: the claim is looked up near the row, and the list
    has wrong positions. `simbad` gives the SIMBAD row of a name.
    """
    entries = json.loads(path.read_text())
    by_hip: dict[str, dict] = {}
    for entry in entries:
        if entry["HIP"]:
            kept = by_hip.get(entry["HIP"])
            if kept is None or _brightness(entry) < _brightness(kept):
                by_hip[entry["HIP"]] = entry
    simbad = _simbad_claims(entries, by_hip, simbad or {})
    rows = []
    for entry in entries:
        name = entry[iau_names.NAME_COLUMN]
        claims = []
        if entry["HIP"] and by_hip[entry["HIP"]] is entry:
            claims.append(dict(zip(CROSS_ID.names, (*HIP, entry["HIP"]))))
        elif name in simbad:
            claims.append(dict(zip(CROSS_ID.names, (*SIMBAD_OID, simbad[name].oid))))
        elif entry["HIP"]:
            logger.info(
                "%s: HIP %s is also %s; it matches by position",
                name,
                entry["HIP"],
                by_hip[entry["HIP"]][iau_names.NAME_COLUMN],
            )
        if hd := _HD.fullmatch(entry["Designation"]):
            claims.append(dict(zip(CROSS_ID.names, (*HD, hd[1]))))
        ra, dec = _number(entry["RA"]), _number(entry["DEC"])
        # A claim is looked up near the row, and the list has wrong positions,
        # so a claim gives its position.
        known = None
        if claims and claims[0]["catalogue"] == HIP[0]:
            known = hip_positions.get(entry["HIP"])
        elif claims and claims[0]["catalogue"] == SIMBAD_OID[0]:
            known = simbad[name].ra, simbad[name].dec
        if known is not None:
            if ra is not None and dec is not None:
                apart = float(sky.separation(ra, dec, *known))
                if apart > MAX_OFFSET:
                    logger.warning(
                        "%s: the list puts it %.2f° from its %s star; it takes"
                        " the position of that star",
                        name,
                        apart / 3600,
                        claims[0]["catalogue"],
                    )
            ra, dec = known
        if ra is None or dec is None:
            logger.info(
                "%s (%s) has no position and no claimed star: unplaced",
                name,
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


def claimed(
    rows: pa.Table, simbad: dict[str, IauRow], path: Path = NAMES_FILE
) -> list[WgsnName]:
    """The names of the pass rows `rows`, with the ids of the star that each
    claims. `simbad` gives the SIMBAD row of a name."""
    designations = dict(read_designations(path))
    found = []
    for name, claims in zip(
        rows["catalogue_id"].to_pylist(), rows["claims"].to_pylist(), strict=True
    ):
        by = {claim["catalogue"]: claim["catalogue_id"] for claim in claims or []}
        hip, row = by.get(HIP[0]), None
        if SIMBAD_OID[0] in by:
            row = simbad[name]
            hip = row.hip
        found.append(
            WgsnName(
                name,
                designations[name],
                hip=int(hip) if hip else None,
                oid=row.oid if row else None,
                gaia_dr3=int(row.gaia) if row and row.gaia else None,
            )
        )
    return found
