"""Ingest SBDB per-object satellite payloads (asteroid moons).

Reads the per-parent JSON files written by `SBDBSatellitesDownloader`
(`space-map-downloads/sbdb_satellites/{parent_spkid}.json`) and writes:

  - One ``Object`` row per satellite, keyed
    ``sbdb_satellite-<parent_spkid>-<sat_index>``.
  - One ``SBDBSatellite`` row per satellite, holding identity + orbital
    elements + uncertainties + provenance.

Many satellite entries are sparse — discovery-paper placeholders with no
name and no orbit. We persist them all per the catalog policy: presence in
SBDB's `sat` array is itself a fact worth recording.
"""

import json
import logging
from pathlib import Path

from sqlalchemy import delete, insert, select
from tqdm import tqdm

from space_map_data.constants.providers import ID_TYPES, PROVIDERS, make_object_id
from space_map_data.ingest.convert import string_or_none
from space_map_data.models.object import (
    ElementsScale,
    Object,
    ObjectType,
    OrbitalSource,
    SBDBSatellite,
)
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)

# SBDB element name -> column name on SBDBSatellite for value/sigma extraction.
_ELEMENT_VALUE_COLS = {
    "a": "a_km",
    "q": "q_km",
    "e": "e",
    "i": "i",
    "om": "om",
    "w": "w",
    "ma": "ma",
    "n": "n",
    "per": "per_h",
    "tp": "tp_jd",
    "dn_dt": "dn_dt",
    "a_D": "a_d",
}
_ELEMENT_SIGMA_COLS = {
    "a": "sigma_a",
    "e": "sigma_e",
    "i": "sigma_i",
    "om": "sigma_om",
    "w": "sigma_w",
    "ma": "sigma_ma",
    "per": "sigma_per",
    "tp": "sigma_tp",
}


def _coerce_int(val: int | str | None) -> int | None:
    """Year/iau_num/oid arrive as int or numeric string. Empty → None."""
    if val is None or val == "":
        return None
    return int(val)


def _coerce_float(val: int | float | str | None) -> float | None:
    """SBDB satellite element values may use approximation/locale markers
    that ``float_or_none`` rejects: a leading ``~`` (approximate, e.g. ``~38``)
    or a comma decimal separator (e.g. ``119,7``). Strip those, then parse.
    Anything still non-numeric returns None with a warning — better than
    aborting the whole ingest over one bad cell.
    """
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    if s.startswith("~"):
        s = s[1:].lstrip()
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        logger.warning("Dropping unparseable orbital value %r", val)
        return None


def _coerce_bool(val: str | None) -> bool | None:
    """SBDB `confirmed` is 'Y' / 'N' (or absent)."""
    if val == "Y":
        return True
    if val == "N":
        return False
    return None


def _parse_orbit(orbit: dict | None) -> dict:
    """Flatten the first orbit solution into SBDBSatellite columns.

    SBDB returns ``orbit`` as ``{"0": {...}, "1": {...}}``. 99% have just
    one key; for the 3 with two solutions we keep the first (sorted) and
    log the extras count at the call site.
    """
    if not orbit:
        return {}
    first_key = sorted(orbit.keys())[0]
    sol = orbit[first_key]
    elements = sol.get("elements") or []
    elem_map = {e["name"]: e for e in elements}

    out: dict = {
        "epoch_jd": _coerce_float(sol.get("epoch")),
        "frame": string_or_none(sol.get("frame")),
        "equinox": string_or_none(sol.get("equinox")),
        "orbit_ref": string_or_none(sol.get("ref")),
        "orbit_notes": string_or_none(sol.get("notes")),
    }
    for api_name, col in _ELEMENT_VALUE_COLS.items():
        elem = elem_map.get(api_name)
        if elem is not None:
            out[col] = _coerce_float(elem.get("value"))
    for api_name, col in _ELEMENT_SIGMA_COLS.items():
        elem = elem_map.get(api_name)
        if elem is not None:
            out[col] = _coerce_float(elem.get("sigma"))
    return out


class SBDBSatellitesIngestor:
    BATCH = 5_000

    def __init__(self, download_dir: Path):
        self.session = get_session()
        self.dir = download_dir / PROVIDERS.SBDB_SATELLITES
        self.total_rows = 0
        self.no_parent_files = 0
        self.alt_orbits_dropped = 0

    def _clear(self) -> None:
        self.session.execute(delete(SBDBSatellite))
        self.session.execute(
            delete(Object).where(Object.orbital_source == OrbitalSource.sbdb_satellite)
        )
        self.session.commit()

    def _load_parent_index(self) -> dict[int, tuple[str, int | None]]:
        """Map parent SPK-ID -> (object_id, naif_id) for parents in DB."""
        rows = self.session.execute(
            select(Object.id, Object.spkid, Object.naif_id).where(
                Object.spkid.is_not(None)
            )
        ).all()
        return {spkid: (oid, naif) for oid, spkid, naif in rows}

    def _build_rows(
        self,
        parent_spkid: int,
        parent_object_id: str,
        parent_naif_id: int | None,
        sat_index: int,
        sat: dict,
    ) -> tuple[dict, dict]:
        sat_id = make_object_id(ID_TYPES.SBDB_SATELLITE, f"{parent_spkid}-{sat_index}")

        fullname = string_or_none(sat.get("fullname"))
        iau_name = string_or_none(sat.get("iau_name"))
        prov_des = string_or_none(sat.get("prov_des"))
        # Prefer IAU name, fall back to fullname, then provisional designation.
        display_name = iau_name or fullname or prov_des

        elements = _parse_orbit(sat.get("orbit"))

        obj_row = dict(
            id=sat_id,
            name=display_name,
            object_type=ObjectType.moon,
            provisional_designation=prov_des,
            scale=ElementsScale.planet,
            parent_naif_id=parent_naif_id,
            orbital_source=OrbitalSource.sbdb_satellite.value,
        )
        sat_row = dict(
            object_id=sat_id,
            parent_object_id=parent_object_id,
            parent_spkid=parent_spkid,
            sat_index=sat_index,
            fullname=fullname,
            iau_num=_coerce_int(sat.get("iau_num")),
            iau_name=iau_name,
            prov_des=prov_des,
            oid=_coerce_int(sat.get("oid")),
            year=_coerce_int(sat.get("year")),
            confirmed=_coerce_bool(sat.get("confirmed")),
            discovery_ref=string_or_none(sat.get("ref")),
            notes=string_or_none(sat.get("notes")),
            **elements,
        )
        return obj_row, sat_row

    def _flush(self, objects: list[dict], sats: list[dict]) -> None:
        if not objects:
            return
        self.session.execute(insert(Object), objects)
        self.session.execute(insert(SBDBSatellite), sats)
        self.session.commit()

    def run(self) -> None:
        if not self.dir.exists():
            logger.warning("%s not found, skipping", self.dir)
            return
        # Skip metadata.json — only per-parent payloads are named like SPK-IDs.
        files = sorted(p for p in self.dir.glob("*.json") if p.name != "metadata.json")
        if not files:
            logger.warning("No SBDB satellite JSONs in %s, skipping", self.dir)
            return

        self._clear()
        parent_index = self._load_parent_index()

        objects: list[dict] = []
        sats: list[dict] = []
        for path in tqdm(files, desc="SBDB satellites ingest", unit="file"):
            try:
                payload = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to read %s: %s", path, exc)
                continue

            # Use the filename SPK-ID, not the response's. SBDB sometimes
            # normalizes to an alternate primary SPK-ID for fragmented comets
            # (e.g. file 3564177.json carries object.spkid=50564200, but only
            # the 3564177 form is present in the bulk SBDB Query CSV that
            # backs the objects table).
            try:
                parent_spkid = int(path.stem)
            except ValueError:
                logger.warning("%s: filename is not an SPK-ID, skipping", path.name)
                continue

            parent = parent_index.get(parent_spkid)
            if parent is None:
                self.no_parent_files += 1
                logger.warning(
                    "%s: parent spkid %d not in objects table, skipping",
                    path.name,
                    parent_spkid,
                )
                continue
            parent_object_id, parent_naif_id = parent

            sat_array = payload.get("sat") or []
            for idx, sat in enumerate(sat_array):
                orbit = sat.get("orbit") or {}
                if len(orbit) > 1:
                    extras = len(orbit) - 1
                    self.alt_orbits_dropped += extras
                    logger.info(
                        "%s sat %d: %d alternate orbit solution(s) dropped",
                        path.name,
                        idx,
                        extras,
                    )

                obj_row, sat_row = self._build_rows(
                    parent_spkid,
                    parent_object_id,
                    parent_naif_id,
                    idx,
                    sat,
                )
                objects.append(obj_row)
                sats.append(sat_row)

                if len(objects) >= self.BATCH:
                    self._flush(objects, sats)
                    self.total_rows += len(objects)
                    objects.clear()
                    sats.clear()

        self._flush(objects, sats)
        self.total_rows += len(objects)

        logger.info(
            "Ingested %d SBDB satellites across %d parents",
            self.total_rows,
            len(files) - self.no_parent_files,
        )
        if self.no_parent_files:
            logger.warning(
                "%d/%d parent files skipped (parent spkid not in objects)",
                self.no_parent_files,
                len(files),
            )
        if self.alt_orbits_dropped:
            logger.info(
                "%d alternate orbit solutions dropped (kept first per sat)",
                self.alt_orbits_dropped,
            )


def ingest(download_dir: Path) -> None:
    SBDBSatellitesIngestor(download_dir).run()
