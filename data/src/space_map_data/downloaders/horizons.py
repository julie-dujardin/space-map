import csv
import json
import logging
import re
import time
from datetime import date
from enum import StrEnum

from tqdm import tqdm

from . import Downloader

logger = logging.getLogger(__name__)

URL = "https://ssd.jpl.nasa.gov/api/horizons.api"

_BASE_PARAMS = {
    "format": "json",
    "OBJ_DATA": "NO",
    "MAKE_EPHEM": "YES",
    "EPHEM_TYPE": "ELEMENTS",
    "CSV_FORMAT": "YES",
    "OUT_UNITS": "AU-D",
    "REF_PLANE": "ECLIPTIC",
    "REF_SYSTEM": "J2000",
}


class BodyType(StrEnum):
    BARYCENTER = "barycenter"
    STAR = "star"
    PLANET = "planet"
    DWARF_PLANET = "dwarf_planet"
    MOON = "moon"
    ASTEROID = "asteroid"
    COMET = "comet"
    SPACECRAFT = "spacecraft"


# Sort priority for output ordering (barycenters first)
_TYPE_SORT_ORDER = {
    BodyType.BARYCENTER: 0,
    BodyType.STAR: 1,
    BodyType.PLANET: 2,
    BodyType.DWARF_PLANET: 3,
    BodyType.MOON: 4,
    BodyType.ASTEROID: 5,
    BodyType.COMET: 6,
    BodyType.SPACECRAFT: 7,
}


def _date_to_jd(d: date) -> str:
    """Convert a date to a Julian Date string."""
    return f"{d.toordinal() + 1721424.5:.1f}"


def _classify_body(naif_id: int, name: str) -> BodyType:
    """Classify a body by its NAIF ID and name."""
    if 1 <= naif_id <= 9:
        return BodyType.BARYCENTER
    if naif_id == 10:
        return BodyType.STAR
    if 100 <= naif_id <= 999:
        if naif_id % 100 == 99:
            return BodyType.DWARF_PLANET if naif_id == 999 else BodyType.PLANET
        return BodyType.MOON
    if "barycenter" in name.lower():
        return BodyType.BARYCENTER
    if 90_000_000 <= naif_id < 99_000_000:
        return BodyType.COMET
    if naif_id >= 99_000_000:
        return BodyType.SPACECRAFT
    return BodyType.ASTEROID


def _center_for_body(naif_id: int) -> tuple[str, int]:
    """Return (CENTER param, parent_naif_id) for a body.

    Everything is ultimately relative to the Solar System Barycenter (SSB).
    Bodies within a planetary system (100–999) are relative to their planet barycenter.
    """
    if 100 <= naif_id <= 999:
        planet_bc = naif_id // 100
        return f"500@{planet_bc}", planet_bc
    return "500@0", 0


class HorizonsDownloader(Downloader):
    name = "horizons"

    def _fetch_body_list(self) -> list[tuple[str, str]]:
        """Return (name, naif_id) for all major bodies, sorted by type then ID."""
        response = self.client.get(
            URL,
            params={
                "format": "json",
                "COMMAND": "'MB'",
                "OBJ_DATA": "YES",
                "MAKE_EPHEM": "NO",
            },
        )
        response.raise_for_status()
        text = response.json()["result"]

        bodies = []
        for line in text.splitlines():
            m = re.match(r"^\s*(-?\d+)\s{2,}(\S.*?)(?:\s{3,}.*)?$", line)
            if not m:
                continue
            naif_id_str, name = m.group(1), m.group(2).strip()
            naif_id = int(naif_id_str)
            if naif_id <= 0:
                continue  # skip SSB (origin) and negative alternate IDs
            bodies.append((name, naif_id_str))

        bodies.sort(
            key=lambda b: (
                _TYPE_SORT_ORDER.get(_classify_body(int(b[1]), b[0]), 99),
                int(b[1]),
            )
        )
        return bodies

    @staticmethod
    def _parse_elements(result_text: str, name: str, naif_id: str) -> dict:
        """Extract one row of osculating elements from a Horizons text response."""
        header_match = re.search(r"^\s*(JDTDB,.+)$", result_text, re.MULTILINE)
        data_match = re.search(r"\$\$SOE\n(.*?)\$\$EOE", result_text, re.DOTALL)

        if not header_match or not data_match:
            raise ValueError(f"Unexpected Horizons response for {name} ({naif_id})")

        cols = [c.strip() for c in header_match.group(1).split(",") if c.strip()]
        data_lines = [line for line in data_match.group(1).splitlines() if line.strip()]

        if not data_lines:
            raise ValueError(f"No element data for {name} ({naif_id})")

        vals = [v.strip() for v in data_lines[0].split(",")]
        row = dict(zip(cols, vals))
        row["name"] = name
        row["naif_id"] = naif_id
        return row

    def get_bodies(self, limit: int | None = None) -> tuple[list[tuple[str, str]], int]:
        logger.info("Fetching body list...")
        available_bodies = self._fetch_body_list()
        total_available = len(available_bodies)
        logger.info("%d natural bodies found", total_available)

        body_list_file = self.out_dir / "body_list.json"
        with body_list_file.open("w") as f:
            json.dump(
                [{"name": name, "naif_id": int(nid)} for name, nid in available_bodies],
                f,
                indent=2,
            )
        logger.info("Saved body list -> %s", body_list_file.relative_to(self.out_dir))

        if limit is not None and limit < total_available:
            logger.info("Limiting to %d bodies", limit)
            return available_bodies[:limit], total_available
        return available_bodies, total_available

    def download(
        self, limit: int | None = None, epoch: date | None = None, **kwargs: object
    ) -> None:
        if epoch is None:
            epoch = date.today()
        epoch_jd = _date_to_jd(epoch)
        logger.info("Using epoch %s (JD %s)", epoch.isoformat(), epoch_jd)

        out_file = self.out_dir / "bodies.csv"

        available_bodies, total_available = self.get_bodies(limit=limit)
        rows = []
        fieldnames: list[str] | None = None

        meta_fields = ("name", "naif_id", "type", "center", "parent_naif_id")

        for name, naif_id in tqdm(
            available_bodies, desc="Horizons", unit="body", dynamic_ncols=True
        ):
            nid = int(naif_id)
            body_type = _classify_body(nid, name)
            center, parent_id = _center_for_body(nid)

            response = self.client.get(
                URL,
                params={
                    **_BASE_PARAMS,
                    "TLIST": epoch_jd,
                    "CENTER": center,
                    "COMMAND": f"'{naif_id}'",
                },
            )
            response.raise_for_status()
            payload = response.json()

            if "error" in payload:
                logger.warning("%s (%s): %s", name, naif_id, payload["error"])
                continue

            row = self._parse_elements(payload["result"], name, naif_id)
            row["type"] = body_type
            row["center"] = center
            row["parent_naif_id"] = str(parent_id)

            if fieldnames is None:
                fieldnames = [*meta_fields, *(k for k in row if k not in meta_fields)]

            rows.append(row)
            time.sleep(0.5)

        if fieldnames and rows:
            with out_file.open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)

        logger.info(
            "Saved %d bodies -> %s", len(rows), out_file.relative_to(self.out_dir)
        )
        self._save_metadata(
            URL,
            len(rows),
            complete=len(rows) == total_available,
            epoch=epoch.isoformat(),
            epoch_jd=epoch_jd,
        )
