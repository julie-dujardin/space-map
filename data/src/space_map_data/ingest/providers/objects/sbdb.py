"""Ingest the SBDB sqlite mirror into the database."""

import logging
import multiprocessing
import re
import sqlite3
from pathlib import Path

from space_map_data.constants.providers import ID_TYPES, make_object_id
from space_map_data.models.object.sbdb import OrbitClass
from sqlalchemy import delete, insert
from tqdm import tqdm

from space_map_data.models.object import (
    DWARF_PLANETS,
    Object,
    ObjectType,
    OrbitalSource,
    SBDB as SBDBRow,
)
from space_map_data.ingest.convert import (
    bool_or_none,
    float_or_none,
    int_or_none,
    normalize_partial_date,
    string_or_none,
)
from space_map_data.utils.db import get_session
from space_map_data.utils.naif import CHEBYSHEV_ASTEROID_WHITELIST, naif_id_from_spk

logger = logging.getLogger(__name__)

# Gravitational constant in km³ kg⁻¹ s⁻²
G_KM3_PER_KG_S2 = 6.67430e-20

SUB_CHUNK_SIZE = 10_000

# All SBDB column names, in the order they appear in the ORM model.
_SBDB_COLUMNS = [
    "spkid",
    "full_name",
    "pdes",
    "name",
    "prefix",
    "neo",
    "pha",
    "sats",
    "H",
    "G",
    "M1",
    "M2",
    "K1",
    "K2",
    "PC",
    "diameter",
    "extent",
    "albedo",
    "rot_per",
    "GM",
    "BV",
    "UB",
    "IR",
    "spec_B",
    "spec_T",
    "H_sigma",
    "diameter_sigma",
    "orbit_id",
    "epoch",
    "epoch_mjd",
    "epoch_cal",
    "equinox",
    "e",
    "a",
    "q",
    "i",
    "om",
    "w",
    "ma",
    "ad",
    "n",
    "tp",
    "tp_cal",
    "per",
    "per_y",
    "moid",
    "moid_ld",
    "moid_jup",
    "t_jup",
    "sigma_e",
    "sigma_a",
    "sigma_q",
    "sigma_i",
    "sigma_om",
    "sigma_w",
    "sigma_ma",
    "sigma_ad",
    "sigma_n",
    "sigma_tp",
    "sigma_per",
    "producer",
    "data_arc",
    "first_obs",
    "last_obs",
    "n_obs_used",
    "n_del_obs_used",
    "n_dop_obs_used",
    "condition_code",
    "rms",
    "two_body",
    "A1",
    "A1_sigma",
    "A2",
    "A2_sigma",
    "A3",
    "A3_sigma",
    "DT",
    "DT_sigma",
]

_FLOAT_COLS = {
    "H",
    "G",
    "M1",
    "M2",
    "K1",
    "K2",
    "PC",
    "diameter",
    "albedo",
    "rot_per",
    "GM",
    "BV",
    "UB",
    "IR",
    "H_sigma",
    "epoch",
    "epoch_mjd",
    "e",
    "a",
    "q",
    "i",
    "om",
    "w",
    "ma",
    "ad",
    "n",
    "tp",
    "per",
    "per_y",
    "moid",
    "moid_ld",
    "moid_jup",
    "t_jup",
    "sigma_e",
    "sigma_a",
    "sigma_q",
    "sigma_i",
    "sigma_om",
    "sigma_w",
    "sigma_ma",
    "sigma_ad",
    "sigma_n",
    "sigma_tp",
    "sigma_per",
    "rms",
    "A1",
    "A1_sigma",
    "A2",
    "A2_sigma",
    "A3",
    "A3_sigma",
    "DT",
    "DT_sigma",
}
_INT_COLS = {"sats", "data_arc", "n_obs_used", "n_del_obs_used", "n_dop_obs_used"}
_BOOL_COLS = {"neo", "pha", "two_body"}
_PARTIAL_DATE_COLS = {"first_obs", "last_obs"}  # input can be YYYY-MM-DD or YYYY-??-??
# "epoch_cal", "tp_cal": could parse to datetime but BCE dates (C/-146 P1: -146-06-28.0000000) cause issues, string is fine


SBDB_CLASS_MAP: dict[str, ObjectType] = {
    # Near-Earth asteroids
    OrbitClass.AMO.name: ObjectType.asteroid_inner,  # Amor — orbit exterior to Earth, interior to Mars (1.017 < q < 1.3 AU)
    OrbitClass.APO.name: ObjectType.asteroid_inner,  # Apollo — Earth-crossing, a > 1 AU (q < 1.017 AU)
    OrbitClass.ATE.name: ObjectType.asteroid_inner,  # Aten — a < 1 AU, Earth-crossing (Q > 0.983 AU)
    OrbitClass.IEO.name: ObjectType.asteroid_inner,  # Interior Earth Object (Atira) — orbit entirely inside Earth's (Q < 0.983 AU)
    OrbitClass.MCA.name: ObjectType.asteroid_inner,  # Mars-crossing asteroid (1.3 < q < 1.666 AU, a < 3.2 AU)
    # Main belt
    OrbitClass.MBA.name: ObjectType.asteroid_main_belt,  # Main-belt asteroid (2.0 < a < 3.2 AU)
    OrbitClass.IMB.name: ObjectType.asteroid_main_belt,  # Inner main-belt asteroid (a < 2.0 AU, q > 1.666 AU)
    OrbitClass.OMB.name: ObjectType.asteroid_main_belt,  # Outer main-belt asteroid (3.2 < a < 4.6 AU)
    # Special populations
    OrbitClass.TJN.name: ObjectType.asteroid_trojan,  # Jupiter Trojan — trapped at L4/L5 (4.6 < a < 5.5 AU, e < 0.3)
    OrbitClass.CEN.name: ObjectType.asteroid_centaur,  # Centaur — orbit between Jupiter and Neptune (5.5 < a < 30.1 AU)
    OrbitClass.TNO.name: ObjectType.asteroid_tno,  # Trans-Neptunian Object (a > 30.1 AU)
    OrbitClass.ETc.name: ObjectType.asteroid_tno,  # Encke-type comet (T_Jup > 3, a < a_Jup) — classified as TNO
    # Comets
    OrbitClass.PAR.name: ObjectType.comet,  # Parabolic comet (e ≈ 1.0)
    OrbitClass.HYP.name: ObjectType.comet,  # Hyperbolic comet (e > 1.0)
    OrbitClass.HYA.name: ObjectType.comet,  # Hyperbolic asteroid (e > 1.0)
    OrbitClass.COM.name: ObjectType.comet,  # Comet — not matching any defined class
    OrbitClass.JFC.name: ObjectType.comet,  # Jupiter-family comet, classical (P < 20 yr)
    OrbitClass.JFc.name: ObjectType.comet,  # Jupiter-family comet, Levison-Duncan (2 < T_Jup < 3)
    OrbitClass.HTC.name: ObjectType.comet,  # Halley-type comet (20 < P < 200 yr)
    OrbitClass.CTc.name: ObjectType.comet,  # Chiron-type comet (T_Jup > 3, a > a_Jup)
    # Catch-all
    OrbitClass.AST.name: ObjectType.asteroid,  # Asteroid — not matching any defined class
}


def _object_type(row: dict[str, str]) -> ObjectType:
    cls = string_or_none(row["class"])
    prefix = string_or_none(row["prefix"])
    name = string_or_none(row["name"])

    if name and name.lower() in DWARF_PLANETS:
        return ObjectType.dwarf_planet

    if cls in SBDB_CLASS_MAP:
        mapped = SBDB_CLASS_MAP[cls]
        # Comet prefix overrides asteroid classification
        if prefix and mapped.value.startswith("asteroid"):
            return ObjectType.comet
        return mapped

    return ObjectType.comet if prefix else ObjectType.asteroid


def _display_name(
    row: dict[str, str], object_type: ObjectType, provisional_designation: str | None
) -> str | None:
    """Build the display name for an SBDB object.

    Comets: full_name (e.g. "29P/Schwassmann-Wachmann 1", "C/2007 H6 (SOHO)").
    Asteroids with name: "<pdes> <name>" (e.g. "3173 McNaught").
    Asteroids unnamed: provisional designation (e.g. "1996 XG32").
    """
    if object_type == ObjectType.comet:
        return string_or_none(row["full_name"])

    name = string_or_none(row["name"])
    pdes = string_or_none(row["pdes"])
    if name and pdes:
        return f"{pdes} {name}"
    return provisional_designation


def _provisional_designation(full_name: str | None) -> str | None:
    """Extract the provisional designation from the parenthesised part of full_name."""
    if not full_name:
        return None
    m = re.search(r"\(([^)]+)\)", full_name)
    return m.group(1) if m else None


def _parent_id(naif_id: int | None) -> str:
    """Tree parent: the Sun, but SSB for Chebyshev perturbers whose ephemeris
    is SSB-relative (like Ceres) so the parent matches the position frame."""
    if naif_id in CHEBYSHEV_ASTEROID_WHITELIST:
        return "naif-0"
    return "naif-10"


def _sbdb_dict(row: dict[str, str]) -> dict:
    """Extract SBDB mirror columns as a typed dict (class → class_)."""
    d: dict = {}
    for col in _SBDB_COLUMNS:
        raw = row[col]
        if col in _FLOAT_COLS:
            d[col] = float_or_none(raw)

            # compute mass from GM
            if col == "GM" and d[col]:
                d["mass_kg"] = d[col] / G_KM3_PER_KG_S2
        elif col in _INT_COLS:
            d[col] = int_or_none(raw)
        elif col in _BOOL_COLS:
            d[col] = bool_or_none(raw)
        elif col in _PARTIAL_DATE_COLS:
            d[col] = normalize_partial_date(raw)
        else:
            d[col] = string_or_none(raw)
    d["class_"] = row.get("class", "")
    return d


def _fetch_rows(db_path: Path, lo: int, hi: int) -> list[dict[str, str]]:
    """Read a spkid range from the mirror as CSV-like string dicts."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = con.execute("SELECT * FROM bodies WHERE spkid BETWEEN ? AND ?", (lo, hi))
        cols = [d[0] for d in cur.description]
        return [
            dict(zip(cols, ("" if v is None else str(v) for v in row))) for row in cur
        ]
    finally:
        con.close()


def _parse_slice(db_path: Path, lo: int, hi: int) -> list[dict]:
    """Parse a spkid range into a list of (object_dict, sbdb_dict) pairs."""
    rows = []
    for row in _fetch_rows(db_path, lo, hi):
        spkid = int_or_none(row["spkid"])
        assert spkid is not None, f"Missing or invalid SPKID in range {lo}..{hi}"
        object_type = _object_type(row)
        object_id = make_object_id(ID_TYPES.SPKID, spkid)
        provisional_designation = _provisional_designation(row["full_name"])
        name = string_or_none(row["name"])
        if provisional_designation == name:
            provisional_designation = None
        pdes = string_or_none(row["pdes"])
        if pdes == provisional_designation:
            pdes = None

        naif_id = naif_id_from_spk(spkid, object_type)

        rows.append(
            {
                "sbdb": {
                    **_sbdb_dict(row),
                    "object_id": object_id,
                    "provisional_designation": provisional_designation,
                },
                "object": {
                    "id": object_id,
                    "name": _display_name(row, object_type, provisional_designation),
                    "object_type": object_type,
                    "provisional_designation": provisional_designation,
                    "spkid": spkid,
                    "naif_id": naif_id,
                    "mpc_designation": pdes,
                    "orbital_source": OrbitalSource.sbdb.value,
                    "parent_id": _parent_id(naif_id),
                    # SBDB rows always carry orbital elements (the mirror
                    # is the orbit catalog); condition_code=9 cases
                    # ship as MISSING_FLOAT64 in the binary, not dropped.
                    "has_position": True,
                },
            }
        )

    return rows


def _parse_slice_star(args: tuple) -> list[dict]:
    """Unpack args for multiprocessing imap_unordered."""
    db_path, lo, hi = args
    return _parse_slice(db_path, lo, hi)


class SBDBIngestor:
    BATCH = 50_000

    def __init__(self, download_dir: Path):
        self.session = get_session()
        self.sbdb_dir = download_dir / "sources" / "position" / "sbdb"
        self.total_rows = 0

    @property
    def db_file(self) -> Path:
        return self.sbdb_dir / "sbdb.sqlite"

    def _check_columns(self) -> None:
        con = sqlite3.connect(f"file:{self.db_file}?mode=ro", uri=True)
        try:
            actual_cols = {r[1] for r in con.execute("PRAGMA table_info(bodies)")}
        finally:
            con.close()
        expected_cols = {*_SBDB_COLUMNS, "class"}
        missing = expected_cols - actual_cols
        extra = actual_cols - expected_cols
        if missing or extra:
            raise ValueError(
                f"Column mismatch in {self.db_file.name}: "
                f"missing={missing or '{}'}, extra={extra or '{}'}"
            )

    def _insert(self, rows: list[dict]) -> None:
        """Insert Object + SBDB row pairs in batches."""
        if not rows:
            return
        objects = [r["object"] for r in rows]
        sbdb_rows = [r["sbdb"] for r in rows]
        for i in range(0, len(objects), self.BATCH):
            obj_batch = objects[i : i + self.BATCH]
            self.session.execute(insert(Object), obj_batch)
            sbdb_batch = sbdb_rows[i : i + self.BATCH]
            self.session.execute(insert(SBDBRow), sbdb_batch)
            self.session.commit()

    def _clear(self) -> None:
        self.session.execute(delete(SBDBRow))
        self.session.execute(
            delete(Object).where(Object.orbital_source == OrbitalSource.sbdb)
        )
        self.session.commit()

    def run(self) -> None:
        if not self.db_file.exists():
            logger.warning("No SBDB mirror at %s, skipping", self.db_file)
            return
        self._check_columns()
        self._clear()

        # Slice the spkid space into work items: (db, first spkid, last spkid)
        con = sqlite3.connect(f"file:{self.db_file}?mode=ro", uri=True)
        try:
            spkids = [
                r[0] for r in con.execute("SELECT spkid FROM bodies ORDER BY spkid")
            ]
        finally:
            con.close()
        work_items: list[tuple[Path, int, int]] = [
            (self.db_file, batch[0], batch[-1])
            for batch in (
                spkids[i : i + SUB_CHUNK_SIZE]
                for i in range(0, len(spkids), SUB_CHUNK_SIZE)
            )
        ]

        logger.info(
            "Processing %d slices across %d workers",
            len(work_items),
            multiprocessing.cpu_count(),
        )

        with multiprocessing.Pool() as pool:
            results = pool.imap_unordered(_parse_slice_star, work_items)
            for rows in tqdm(results, total=len(work_items), desc="SBDB ingest"):
                self._insert(rows)
                self.total_rows += len(rows)

        logger.info("Ingested %d SBDB bodies", self.total_rows)


def ingest(download_dir: Path) -> None:
    SBDBIngestor(download_dir).run()
