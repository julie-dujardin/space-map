"""Hipparcos as an ingest source: the new reduction with the 1997 photometry.

The star list and the astrometry come from the new reduction (van Leeuwen
2007, I/311) at epoch J1991.25. The magnitudes, colours, spectral type and HD
number come from the catalogue of 1997 (I/239), and the Bayer or Flamsteed
designation and the iron abundance [Fe/H] from XHIP (Anderson & Francis 2012,
V/137D).

A star matches Gaia DR3 by its best neighbour first: the Gaia row claims the
HIP number, and the Hipparcos row claims the DR3 id. The DR3 id is then kept
even when that source is not stored. A star without a best neighbour matches
by position at J2016.0 and by an estimate of G from V and B-V.
"""

import logging
import re
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from space_map_data.download.cds import README, read_fixed_width
from space_map_data.download.providers.stars import cds as cds_stars
from space_map_data.extrasolar.engine import Source
from space_map_data.extrasolar.match import PositionMatcher
from space_map_data.extrasolar.sources.gaia import EPOCH as GAIA_EPOCH
from space_map_data.extrasolar.sources.gaia import BestNeighbours
from space_map_data.extrasolar.tables import CROSS_ID
from space_map_data.utils.arrays import floats

logger = logging.getLogger(__name__)

# A star without a best neighbour has its Gaia source 0.3–1″ away in most
# cases. The error floor allows for binaries and orbital motion. The
# magnitude picks between neighbours.
MATCHER = PositionMatcher(
    n_sigma=5.0,
    near_sigma=3.0,
    min_error=0.3,
    reach=0.1,
    max_mag_diff=1.0,
    mag_sigma=0.3,
)
HIPPARCOS = Source(
    name="hipparcos-2007",
    catalogue="hip",
    release="2007",
    home=1,
    matcher=MATCHER,
    kind="star",
)
GAIA_DR3 = ("gaia", "dr3")
HD = ("hd", "1949")

HIP2_DIR = cds_stars.OUT_DIR / "I/311"
HIP_MAIN_DIR = cds_stars.OUT_DIR / "I/239"
XHIP_DIR = cds_stars.OUT_DIR / "V/137D"
HIP2_FILE = "hip2.dat.gz"
HIP_MAIN_FILE = "hip_main.dat"
XHIP_FILE = "biblio.dat.gz"
XHIP_MAIN_FILE = "main.dat.gz"
XHIP_METALLICITY_FIELDS = {
    "HIP": "hip",
    "[Fe/H]": "feh_xhip",
    "e_[Fe/H]": "feh_xhip_error",
    "q_[Fe/H]": "feh_xhip_quality",
}
# XHIP writes this error where it has none (its note 14).
NO_FEH_ERROR = 9.99

EPOCH = 1991.25

HIP2_FIELDS = {
    "HIP": "hip",
    "RArad": "ra_rad",
    "DErad": "dec_rad",
    "Plx": "parallax",
    "pmRA": "pmra",
    "pmDE": "pmdec",
    "e_RArad": "ra_error",
    "e_DErad": "dec_error",
    "e_Plx": "parallax_error",
    "e_pmRA": "pmra_error",
    "e_pmDE": "pmdec_error",
}
HIP_MAIN_FIELDS = {
    "HIP": "hip",
    "Hpmag": "hp_mag",
    "e_Hpmag": "hp_mag_error",
    "Vmag": "v_mag",
    "B-V": "b_v",
    "e_B-V": "b_v_error",
    "V-I": "v_i",
    "e_V-I": "v_i_error",
    "SpType": "sp_type",
    "HD": "hd",
}

# G − V from B − V: Gaia DR2 documentation release 1.2, section 5.3.7, table
# 5.8 (Carrasco, from Landolt 2009 standards). On the 95k Hipparcos stars with
# a Gaia best neighbour at G 5–12 it is off by 0.005 mag, with a robust
# scatter of 0.034 mag.
G_MINUS_V = (-0.02907, -0.02385, -0.2297, -0.001768)
# The fit range of the relation (table 5.9). On the 132 best-neighbour pairs
# with B − V over 2.4, the estimate is a median 0.14 mag under Gaia G with this
# clip, and 0.43 mag under it with a clip at 2.75.
B_V_RANGE = (-0.3, 2.4)
# The median G − Hp of the 95k stars, for a star without V or B − V.
G_MINUS_HP = -0.28

GREEK = frozenset(
    [
        "Alpha",
        "Beta",
        "Gamma",
        "Delta",
        "Epsilon",
        "Zeta",
        "Eta",
        "Theta",
        "Iota",
        "Kappa",
        "Lambda",
        "Mu",
        "Nu",
        "Xi",
        "Omicron",
        "Pi",
        "Rho",
        "Sigma",
        "Tau",
        "Upsilon",
        "Phi",
        "Chi",
        "Psi",
        "Omega",
    ]
)
_GENITIVE = re.compile(r"[A-Z][a-z]+(?: [A-Z][a-z]+)?")
_LETTER = re.compile(r"[A-Za-z]\d?")
_VARIABLE = re.compile(r"[A-Z]{1,2}|V\d{3,4}")


def propagate(
    ra: np.ndarray,
    dec: np.ndarray,
    pmra: np.ndarray,
    pmdec: np.ndarray,
    years: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Positions in degrees moved by proper motion over `years`.

    `pmra` is on ra·cos dec, in mas/yr. The motion is straight at constant
    speed with no radial velocity, which is exact for the direction.
    """
    ra, dec = np.radians(ra), np.radians(dec)
    position = np.stack(
        [np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)]
    )
    east = np.stack([-np.sin(ra), np.cos(ra), np.zeros_like(ra)])
    north = np.stack(
        [-np.sin(dec) * np.cos(ra), -np.sin(dec) * np.sin(ra), np.cos(dec)]
    )
    rate = np.radians(1 / 3.6e6) * years
    moved = position + rate * (pmra * east + pmdec * north)
    moved /= np.linalg.norm(moved, axis=0)
    return (
        np.degrees(np.arctan2(moved[1], moved[0])) % 360,
        np.degrees(np.arcsin(np.clip(moved[2], -1, 1))),
    )


def g_estimate(v: np.ndarray, b_v: np.ndarray, hp: np.ndarray) -> np.ndarray:
    """Gaia G from Johnson V and B − V, else from Hp. NaN where neither."""
    x = np.clip(b_v, *B_V_RANGE)
    from_v = v + np.polynomial.polynomial.polyval(x, G_MINUS_V)
    return np.where(np.isfinite(from_v), from_v, hp + G_MINUS_HP)


def designation(name: str | None) -> str | None:
    """The Bayer or Flamsteed designation in an XHIP name, else None.

    A Greek Bayer letter wins over a Flamsteed number, and a Flamsteed number
    over a Latin Bayer letter: "9 Alpha Canis Majoris (Sirius)" gives
    "Alpha Canis Majoris", "98 k Tauri" gives "98 Tauri".
    """
    if not name:
        return None
    tokens = name.split(" (")[0].split()
    flamsteed = tokens.pop(0) if tokens and tokens[0].isdigit() else None
    greek = latin = None
    if len(tokens) > 1:
        letter, _, index = tokens[0].partition("-")
        if letter in GREEK and (not index or index.isdigit()):
            greek = letter + index
            tokens.pop(0)
        elif _LETTER.fullmatch(tokens[0]):
            latin = tokens.pop(0)
        elif flamsteed and _VARIABLE.fullmatch(tokens[0]):
            tokens.pop(0)
    genitive = " ".join(tokens)
    if not _GENITIVE.fullmatch(genitive):
        return None
    first = greek or flamsteed or latin
    return f"{first} {genitive}" if first else None


def _readme(directory: Path) -> str:
    return (directory / README).read_text(encoding="latin-1")


def read_stars(
    hip2_dir: Path = HIP2_DIR,
    hip_main_dir: Path = HIP_MAIN_DIR,
    xhip_dir: Path = XHIP_DIR,
) -> pa.Table:
    """The new reduction joined to the 1997 catalogue and the XHIP names."""
    stars = read_fixed_width(hip2_dir / HIP2_FILE, _readme(hip2_dir), HIP2_FIELDS)
    main = read_fixed_width(
        hip_main_dir / HIP_MAIN_FILE, _readme(hip_main_dir), HIP_MAIN_FIELDS
    )
    names = read_fixed_width(
        xhip_dir / XHIP_FILE, _readme(xhip_dir), {"HIP": "hip", "Name": "xhip_name"}
    )
    at = pc.index_in(stars["hip"], value_set=main["hip"])
    if at.null_count:
        logger.warning(
            "%d stars of %s are not in %s", at.null_count, HIP2_FILE, HIP_MAIN_FILE
        )
    for name in HIP_MAIN_FIELDS.values():
        if name != "hip":
            stars = stars.append_column(name, main[name].take(at))
    at = pc.index_in(stars["hip"], value_set=names["hip"])
    stars = stars.append_column("xhip_name", names["xhip_name"].take(at))
    feh = read_fixed_width(
        xhip_dir / XHIP_MAIN_FILE, _readme(xhip_dir), XHIP_METALLICITY_FIELDS
    )
    error = feh["feh_xhip_error"]
    feh = feh.set_column(
        feh.schema.get_field_index("feh_xhip_error"),
        "feh_xhip_error",
        pc.if_else(pc.equal(error, NO_FEH_ERROR), pa.scalar(None, error.type), error),
    )
    at = pc.index_in(stars["hip"], value_set=feh["hip"])
    for name in XHIP_METALLICITY_FIELDS.values():
        if name != "hip":
            stars = stars.append_column(name, feh[name].take(at))
    return stars


def _claims(rows: list[list[tuple[str, str, str]]]) -> pa.Array:
    return pa.array(
        [
            [dict(zip(CROSS_ID.names, claim)) for claim in claims] or None
            for claims in rows
        ],
        pa.list_(CROSS_ID),
    )


def engine_rows(stars: pa.Table, best: BestNeighbours) -> pa.Table:
    """The pass rows of the stars that `read_stars` gives."""
    hip = stars["hip"].to_numpy()
    ra = np.degrees(floats(stars, "ra_rad"))
    dec = np.degrees(floats(stars, "dec_rad"))
    years = GAIA_EPOCH - EPOCH
    ra_now, dec_now = propagate(
        ra, dec, floats(stars, "pmra"), floats(stars, "pmdec"), years
    )
    # The position error at J2016.0 grows with the proper-motion error.
    error = np.hypot(
        np.hypot(floats(stars, "ra_error"), years * floats(stars, "pmra_error")),
        np.hypot(floats(stars, "dec_error"), years * floats(stars, "pmdec_error")),
    )
    mag = g_estimate(
        floats(stars, "v_mag"), floats(stars, "b_v"), floats(stars, "hp_mag")
    )

    # An HD number on two Hipparcos stars names their system. It gives them
    # no claim and no name.
    hd = stars["hd"].fill_null(0).to_numpy()
    numbers, counts = np.unique(hd[hd > 0], return_counts=True)
    shared = np.isin(hd, numbers[counts > 1])
    if shared.any():
        logger.info(
            "%d HD numbers are on several Hipparcos stars: no HD claim or name"
            " for their %d stars",
            int((counts > 1).sum()),
            int(shared.sum()),
        )
    hd = np.where(shared, 0, hd)

    gaia_of = best.source_of()
    claims, names = [], []
    for number, hd_number, xhip_name in zip(
        hip.tolist(), hd.tolist(), stars["xhip_name"].to_pylist()
    ):
        found = []
        if number in gaia_of:
            found.append((*GAIA_DR3, str(gaia_of[number])))
        if hd_number:
            found.append((*HD, str(hd_number)))
        claims.append(found)
        names.append(
            designation(xhip_name)
            or (f"HD {hd_number}" if hd_number else f"HIP {number}")
        )

    n = stars.num_rows
    columns = {
        "catalogue_id": pc.cast(stars["hip"], pa.string()),
        "mint": pa.array(np.ones(n, bool)),
        "match_ra": pa.array(ra_now),
        "match_dec": pa.array(dec_now),
        "match_pmra": stars["pmra"],
        "match_pmdec": stars["pmdec"],
        "match_mag": pa.array(mag, pa.float32(), from_pandas=True),
        "match_error": pa.array(error / 1000, pa.float32()),
        "claims": _claims(claims),
        "ra": pa.array(ra),
        "dec": pa.array(dec),
        "epoch": pa.array(np.full(n, EPOCH, np.float32)),
        "name": pa.array(names, pa.string()),
        "class": pa.array(np.full(n, "star"), pa.string()),
    }
    copied = (
        set(HIP2_FIELDS.values())
        | set(HIP_MAIN_FIELDS.values())
        | set(XHIP_METALLICITY_FIELDS.values())
    )
    columns |= {
        name: stars[name]
        for name in sorted(copied - {"hip", "hd", "ra_rad", "dec_rad"})
    }
    return pa.table(columns)
