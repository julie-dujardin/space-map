"""Ingest SBDB small-bodies CSV chunks into the database."""

import csv
import logging
import multiprocessing
import re
from pathlib import Path

from space_map_data.constants.providers import ID_TYPES, PROVIDERS
from sqlalchemy import insert
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

logger = logging.getLogger(__name__)

SUB_CHUNK_SIZE = 10_000

# All SBDB CSV column names, in the order they appear in the ORM model.
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


# -- SBDB orbit class → ObjectType --

SBDB_CLASS_MAP: dict[str, ObjectType] = {
    # Near-Earth asteroids
    "AMO": ObjectType.asteroid_inner,  # Amor — orbit exterior to Earth, interior to Mars (1.017 < q < 1.3 AU)
    "APO": ObjectType.asteroid_inner,  # Apollo — Earth-crossing, a > 1 AU (q < 1.017 AU)
    "ATE": ObjectType.asteroid_inner,  # Aten — a < 1 AU, Earth-crossing (Q > 0.983 AU)
    "IEO": ObjectType.asteroid_inner,  # Interior Earth Object (Atira) — orbit entirely inside Earth's (Q < 0.983 AU)
    "MCA": ObjectType.asteroid_inner,  # Mars-crossing asteroid (1.3 < q < 1.666 AU, a < 3.2 AU)
    # Main belt
    "MBA": ObjectType.asteroid_main_belt,  # Main-belt asteroid (2.0 < a < 3.2 AU)
    "IMB": ObjectType.asteroid_main_belt,  # Inner main-belt asteroid (a < 2.0 AU, q > 1.666 AU)
    "OMB": ObjectType.asteroid_main_belt,  # Outer main-belt asteroid (3.2 < a < 4.6 AU)
    # Special populations
    "TJN": ObjectType.asteroid_trojan,  # Jupiter Trojan — trapped at L4/L5 (4.6 < a < 5.5 AU, e < 0.3)
    "CEN": ObjectType.asteroid_centaur,  # Centaur — orbit between Jupiter and Neptune (5.5 < a < 30.1 AU)
    "TNO": ObjectType.asteroid_tno,  # Trans-Neptunian Object (a > 30.1 AU)
    "ETc": ObjectType.asteroid_tno,  # Encke-type comet (T_Jup > 3, a < a_Jup) — classified as TNO
    # Comets
    "PAR": ObjectType.comet,  # Parabolic comet (e ≈ 1.0)
    "HYP": ObjectType.comet,  # Hyperbolic comet (e > 1.0)
    "HYA": ObjectType.comet,  # Hyperbolic asteroid (e > 1.0)
    "COM": ObjectType.comet,  # Comet — not matching any defined class
    "JFC": ObjectType.comet,  # Jupiter-family comet, classical (P < 20 yr)
    "JFc": ObjectType.comet,  # Jupiter-family comet, Levison-Duncan (2 < T_Jup < 3)
    "HTC": ObjectType.comet,  # Halley-type comet (20 < P < 200 yr)
    "CTc": ObjectType.comet,  # Chiron-type comet (T_Jup > 3, a > a_Jup)
    # Catch-all
    "AST": ObjectType.asteroid,  # Asteroid — not matching any defined class
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


def _sbdb_dict(row: dict[str, str]) -> dict:
    """Extract SBDB mirror columns as a typed dict (class → class_)."""
    d: dict = {}
    for col in _SBDB_COLUMNS:
        raw = row[col]
        if col in _FLOAT_COLS:
            d[col] = float_or_none(raw)
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


def _parse_chunk(
    chunk_path: Path, *, skip_rows: int = 0, max_rows: int | None = None
) -> list[dict]:
    """Parse a slice of a CSV chunk into a list of (object_dict, sbdb_dict) pairs."""
    rows = []
    expected_cols = {*_SBDB_COLUMNS, "class"}
    with open(chunk_path, newline="") as f:
        reader = csv.DictReader(f)
        actual_cols = set(reader.fieldnames or [])
        missing = expected_cols - actual_cols
        extra = actual_cols - expected_cols
        if missing or extra:
            raise ValueError(
                f"Column mismatch in {chunk_path.name}: "
                f"missing={missing or '{}'}, extra={extra or '{}'}"
            )
        for idx, row in enumerate(reader):
            if idx < skip_rows:
                continue
            if max_rows is not None and len(rows) >= max_rows:
                break

            spkid = int_or_none(row["spkid"])
            object_type = _object_type(row)
            diameter = float_or_none(row.get("diameter", ""))
            radius_km = diameter / 2.0 if diameter else None

            rows.append(
                {
                    "sbdb": _sbdb_dict(row),
                    "object": {
                        "id": f"{ID_TYPES.SPKID}-{spkid}" if spkid else None,
                        "name": string_or_none(row["name"]),
                        "object_type": object_type,
                        "sbdb_spkid": spkid,
                        "sbdb_mcp_designation": string_or_none(row["full_name"]),
                        "epoch_jd": float_or_none(row["epoch"]),
                        "a": float_or_none(row["a"]),
                        "e": float_or_none(row["e"]),
                        "i": float_or_none(row["i"]),
                        "om": float_or_none(row["om"]),
                        "w": float_or_none(row["w"]),
                        "ma": float_or_none(row["ma"]),
                        "n": float_or_none(row["n"]),
                        "radius_km": radius_km,
                        "orbital_source": OrbitalSource.sbdb.value,
                    },
                }
            )

    return rows


def _parse_chunk_star(args: tuple) -> list[dict]:
    """Unpack args for multiprocessing imap_unordered."""
    path, skip, max_rows = args
    return _parse_chunk(path, skip_rows=skip, max_rows=max_rows)


def _count_csv_rows(path: Path) -> int:
    """Count data rows in a CSV file (excludes header)."""
    with open(path) as f:
        return sum(1 for _ in f) - 1


class SBDBIngestor:
    BATCH = 50_000

    def __init__(self, download_dir: Path, *, limit: int | None = None):
        self.session = get_session()
        self.limit = limit
        self.sbdb_dir = download_dir / PROVIDERS.SBDB
        self.total_rows = 0

    def _find_chunks(self) -> list[Path]:
        chunk_pattern = re.compile(r"small-bodies_\d+_\d+\.csv$")
        chunks = sorted(
            p for p in self.sbdb_dir.iterdir() if chunk_pattern.search(p.name)
        )
        if not chunks:
            logger.warning("No SBDB chunk CSVs found in %s, skipping", self.sbdb_dir)
        return chunks

    def _insert(self, rows: list[dict]) -> None:
        """Insert Object + SBDB row pairs in batches."""
        if not rows:
            return
        objects = [r["object"] for r in rows]
        sbdb_rows = [r["sbdb"] for r in rows]
        for i in range(0, len(objects), self.BATCH):
            obj_batch = objects[i : i + self.BATCH]
            result = self.session.execute(
                insert(Object).returning(Object.id), obj_batch
            )
            new_ids = [r[0] for r in result]
            sbdb_batch = sbdb_rows[i : i + self.BATCH]
            for sbdb, body_id in zip(sbdb_batch, new_ids):
                sbdb["object_id"] = body_id
            self.session.execute(insert(SBDBRow), sbdb_batch)
            self.session.commit()

    def run(self) -> None:
        chunks = self._find_chunks()
        if not chunks:
            return

        # Build sub-chunk work items: (file, skip_rows, max_rows)
        work_items: list[tuple[Path, int, int]] = []
        for chunk_path in chunks:
            n_rows = _count_csv_rows(chunk_path)
            for offset in range(0, n_rows, SUB_CHUNK_SIZE):
                work_items.append((chunk_path, offset, SUB_CHUNK_SIZE))

        logger.info(
            "Processing %d sub-chunks (%d files) across %d workers",
            len(work_items),
            len(chunks),
            multiprocessing.cpu_count(),
        )

        with multiprocessing.Pool() as pool:
            results = pool.imap_unordered(_parse_chunk_star, work_items)
            for rows in tqdm(results, total=len(work_items), desc="SBDB ingest"):
                self._insert(rows)
                self.total_rows += len(rows)

                if self.limit and self.total_rows >= self.limit:
                    break

        logger.info("Ingested %d SBDB bodies", self.total_rows)


def ingest(download_dir: Path, *, limit: int | None = None) -> None:
    SBDBIngestor(download_dir, limit=limit).run()
