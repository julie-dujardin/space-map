"""Ingest SBDB small-bodies CSV chunks into the database."""

import csv
import logging
import multiprocessing
import re
from pathlib import Path

from sqlalchemy import insert, update
from sqlalchemy.orm import Session

from space_map_data.models import (
    Object,
    ObjectType,
    OrbitalSource,
    SBDB as SBDBRow,
)
from space_map_data.ingest.convert import bool_or_none, float_or_none, int_or_none

logger = logging.getLogger(__name__)

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
        else:
            d[col] = raw
    d["class_"] = row.get("class", "")
    return d


def _parse_chunk(chunk_path: Path, limit: int | None = None) -> list[dict]:
    """Parse a single CSV chunk into a list of prepared row dicts.

    Each dict contains:
      - sbdb: dict of SBDB mirror columns
      - body_type: str
      - spkid: int | None
      - naif_id: int | None (converted from spkid for cross-matching)
      - body: dict of Object columns (for new bodies only)
    """
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
        for row in reader:
            spkid = int_or_none(row["spkid"])
            object_type = _object_type(row)

            naif_id: int | None = None
            if spkid is not None:
                if spkid >= 20_000_000:
                    naif_id = spkid - 18_000_000
                else:
                    naif_id = spkid

            diameter = float_or_none(row.get("diameter", ""))
            radius_km = diameter / 2.0 if diameter else None

            rows.append(
                {
                    "sbdb": _sbdb_dict(row),
                    "object_type": object_type,
                    "spkid": spkid,
                    "naif_id": naif_id,
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

            if limit and len(rows) >= limit:
                break

    return rows


class SBDBIngestor:
    BATCH = 50_000

    def __init__(
        self, session: Session, download_dir: Path, *, limit: int | None = None
    ):
        self.session = session
        self.limit = limit
        self.sbdb_dir = download_dir / "sbdb"

        # Populated by each phase
        self.naif_to_object: dict[int, int] = {}
        self.all_rows: list[dict] = []
        self.new_bodies: list[dict] = []
        self.new_sbdb: list[dict] = []
        self.matched_updates: list[tuple[int, int | None]] = []
        self.matched_sbdb: list[dict] = []

    def _find_chunks(self) -> list[Path]:
        chunk_pattern = re.compile(r"small-bodies_\d+_\d+\.csv$")
        chunks = sorted(
            p for p in self.sbdb_dir.iterdir() if chunk_pattern.search(p.name)
        )
        if not chunks:
            logger.warning("No SBDB chunk CSVs found in %s, skipping", self.sbdb_dir)
        return chunks

    def _load_naif_lookup(self) -> None:
        """Build horizons_naif_id → body_id for cross-matching.

        SBDB spkid scheme differs from Horizons naif_id:
          numbered asteroids:  spkid = 20_000_000 + n,  naif_id = 2_000_000 + n
          comets:              spkid = 1_000_000 + n,   naif_id = 1_000_000 + n  (same)
        """
        for body in self.session.query(Object.id, Object.horizons_naif_id).filter(
            Object.horizons_naif_id.isnot(None)
        ):
            assert body.horizons_naif_id is not None
            self.naif_to_object[body.horizons_naif_id] = body.id

    def _parse_chunks(self, chunks: list[Path]) -> None:
        logger.info(
            "Parsing %d SBDB chunks across %d workers",
            len(chunks),
            multiprocessing.cpu_count(),
        )

        if self.limit:
            per_chunk = max(1, self.limit // len(chunks))
            args = [(c, per_chunk) for c in chunks]
        else:
            args = [(c, None) for c in chunks]

        with multiprocessing.Pool() as pool:
            chunk_results = pool.starmap(_parse_chunk, args)

        for chunk_rows in chunk_results:
            self.all_rows.extend(chunk_rows)
            if self.limit and len(self.all_rows) >= self.limit:
                self.all_rows = self.all_rows[: self.limit]
                break

        logger.info("Parsed %d SBDB rows, inserting into database", len(self.all_rows))

    def _split_matched(self) -> None:
        for row in self.all_rows:
            naif_id = row["naif_id"]
            object_id = (
                self.naif_to_object.get(naif_id) if naif_id is not None else None
            )

            if object_id is not None:
                sbdb = row["sbdb"]
                sbdb["object_id"] = object_id
                self.matched_sbdb.append(sbdb)
                self.matched_updates.append((object_id, row["spkid"]))
            else:
                self.new_bodies.append(row["object"])
                self.new_sbdb.append(row["sbdb"])

    def _insert_new(self) -> None:
        if not self.new_bodies:
            return
        for i in range(0, len(self.new_bodies), self.BATCH):
            batch = self.new_bodies[i : i + self.BATCH]
            result = self.session.execute(insert(Object).returning(Object.id), batch)
            new_ids = [r[0] for r in result]
            sbdb_batch = self.new_sbdb[i : i + self.BATCH]
            for sbdb, body_id in zip(sbdb_batch, new_ids):
                sbdb["object_id"] = body_id
            self.session.execute(insert(SBDBRow), sbdb_batch)
            self.session.commit()
            logger.info(
                "  inserted %d / %d new bodies",
                min(i + self.BATCH, len(self.new_bodies)),
                len(self.new_bodies),
            )

    def _insert_matched(self) -> None:
        if self.matched_sbdb:
            for i in range(0, len(self.matched_sbdb), self.BATCH):
                self.session.execute(
                    insert(SBDBRow), self.matched_sbdb[i : i + self.BATCH]
                )
                self.session.commit()

        if self.matched_updates:
            for body_id, spkid in self.matched_updates:
                vals: dict = {"sbdb_spkid": spkid}
                self.session.execute(
                    update(Object).where(Object.id == body_id).values(**vals)
                )
            self.session.commit()

    def run(self) -> None:
        chunks = self._find_chunks()
        if not chunks:
            return

        self._load_naif_lookup()
        self._parse_chunks(chunks)
        self._split_matched()
        self._insert_new()
        self._insert_matched()

        matched = len(self.matched_updates)
        logger.info(
            "Ingested %d SBDB bodies (%d cross-matched with Horizons)",
            len(self.all_rows),
            matched,
        )


def ingest(session: Session, download_dir: Path, *, limit: int | None = None) -> None:
    SBDBIngestor(session, download_dir, limit=limit).run()
