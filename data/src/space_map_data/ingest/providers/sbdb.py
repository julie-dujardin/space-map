"""Ingest SBDB small-bodies CSV chunks into the database."""

import csv
import logging
import multiprocessing
import re
from pathlib import Path

from sqlalchemy import and_, case, delete, insert, or_, update
from sqlalchemy.orm import aliased
from sqlalchemy.orm import Session
from tqdm import tqdm

from space_map_data.models.body import (
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
)

logger = logging.getLogger(__name__)

SUB_CHUNK = 10_000

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
    cls = row.get("class", "").strip()
    prefix = row.get("prefix", "").strip()
    name = row.get("name", "").strip()

    if name.lower() in DWARF_PLANETS:
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
            d[col] = raw or None  # treat empty strings as None
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
                        "name": row.get("name", "").strip() or None,
                        "object_type": object_type,
                        "sbdb_spkid": spkid,
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

    def __init__(
        self, session: Session, download_dir: Path, *, limit: int | None = None
    ):
        self.session = session
        self.limit = limit
        self.sbdb_dir = download_dir / "sbdb"
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

    def _reconcile(self) -> None:
        """Merge SBDB-created Objects with existing Horizons Objects via NAIF ID.

        SBDB spkid → Horizons naif_id mapping:
          numbered asteroids        spkid = 20_000_000 + n, naif_id = 2_000_000 + n
          comets                    spkid = 1_000_000 + n,  naif_id = 1_000_000 + n  (same)
          binary system primaries   spkid = 20_000_000 + n, naif_id = 920_000_000 + n  (NAIF ID = spkid -> barycenter)
          pluto (special case)      spkid = 20_134_340,     naif_id = 999
        """
        dup = aliased(Object)
        existing = aliased(Object)
        # Regular asteroid mapping: spkid 20_000_000+n → naif_id 2_000_000+n
        # Pluto is a special case: spkid 20134340, naif_id 999
        naif_from_spkid = case(
            (dup.sbdb_spkid == 20_134_340, 999),
            (dup.sbdb_spkid >= 20_000_000, dup.sbdb_spkid - 18_000_000),
            else_=dup.sbdb_spkid,
        )
        # Binary primary mapping: spkid 20_000_000+n → naif_id 920_000_000+n
        naif_binary_primary = dup.sbdb_spkid + 900_000_000

        # Find (dup_id, existing_id, sbdb_spkid) for SBDB objects matching Horizons
        pairs = (
            self.session.query(dup.id, existing.id, dup.sbdb_spkid)
            .select_from(dup)
            .join(
                existing,
                and_(
                    existing.horizons_naif_id.isnot(None),
                    or_(
                        existing.horizons_naif_id == naif_from_spkid,
                        existing.horizons_naif_id == naif_binary_primary,
                    ),
                ),
            )
            .filter(dup.orbital_source == OrbitalSource.sbdb.value)
            .all()
        )

        if not pairs:
            logger.info("No SBDB/Horizons matches to reconcile")
            return

        # Repoint SBDB rows to the existing Horizons objects
        for dup_id, existing_id, _ in pairs:
            self.session.execute(
                update(SBDBRow)
                .where(SBDBRow.object_id == dup_id)
                .values(object_id=existing_id)
            )

        # Delete duplicate SBDB-created Object rows (frees unique sbdb_spkid)
        dup_ids = [p[0] for p in pairs]
        self.session.execute(delete(Object).where(Object.id.in_(dup_ids)))

        # Set sbdb_spkid on the kept Horizons objects
        for _, existing_id, spkid in pairs:
            self.session.execute(
                update(Object).where(Object.id == existing_id).values(sbdb_spkid=spkid)
            )

        self.session.commit()
        logger.info("Reconciled %d SBDB bodies with Horizons", len(pairs))

    def run(self) -> None:
        chunks = self._find_chunks()
        if not chunks:
            return

        # Build sub-chunk work items: (file, skip_rows, max_rows)
        work_items: list[tuple[Path, int, int]] = []
        for chunk_path in chunks:
            n_rows = _count_csv_rows(chunk_path)
            for offset in range(0, n_rows, SUB_CHUNK):
                work_items.append((chunk_path, offset, SUB_CHUNK))

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

        self._reconcile()

        logger.info("Ingested %d SBDB bodies", self.total_rows)


def ingest(session: Session, download_dir: Path, *, limit: int | None = None) -> None:
    SBDBIngestor(session, download_dir, limit=limit).run()
