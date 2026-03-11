import csv
import json
import logging
import re
import time
from dataclasses import dataclass
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
    LAGRANGE_POINT = "lagrange_point"


def _date_to_jd(d: date) -> str:
    """Convert a date to a Julian Date string."""
    return f"{d.toordinal() + 1721424.5:.1f}"


def _classify_body(
    naif_id: int, name: str, designation: str | None, extra: str | None
) -> tuple[BodyType, int]:
    """Classify a body by its NAIF ID and name.

    Returns (body_type, parent_naif_id) where parent is the NAIF ID of the
    body this object orbits (0 = SSB).

    NAIF ID ranges (https://naif.jpl.nasa.gov/pub/naif/toolkit_docs/C/req/naif_ids.html):
        negative        spacecraft
        0               SSB (excluded)
        1–9             planetary system barycenters
        10              Sun
        100–999         planets (P99) and moons (PNN), parent = barycenter P
        10000–99999     extended moon IDs (PXNNN), parent = barycenter P
        1000000–        comets (1M + periodic number)
        2000000–        asteroids (2M + catalog number)
        20000000–       asteroid system barycenters (20M + catalog number)
        100000000–      satellite in binary system (1 + barycenter ID)
        900000000–      primary in binary system (9 + barycenter ID)
    """
    if naif_id < 0:
        return BodyType.SPACECRAFT, 0
    if 1 <= naif_id <= 9 or "barycenter" in name.lower():
        # Planetary & asteroid system barycenters
        return BodyType.BARYCENTER, 0
    if naif_id == 10:
        # The Sun
        return BodyType.STAR, 0
    if 100 <= naif_id <= 999:
        # Planets (P99) and moons (PNN), parent = planet barycenter P
        barycenter = naif_id // 100
        if naif_id % 100 == 99:  # Planet
            if naif_id == 999:  # rip pluto
                return BodyType.DWARF_PLANET, barycenter
            return BodyType.PLANET, barycenter
        return BodyType.MOON, barycenter
    if 10_000 <= naif_id < 100_000:
        # Extended moon IDs: PXNNN (e.g. 65088 = 2004S17)
        return BodyType.MOON, naif_id // 10_000
    if extra and "lagrange" in extra.lower():
        return BodyType.LAGRANGE_POINT, 0
    if 1_000_000 <= naif_id < 2_000_000:
        return BodyType.COMET, 0
    if 2_000_000 <= naif_id < 10_000_000:
        return BodyType.ASTEROID, 0
    if naif_id >= 100_000_000:
        # Binary system members: satellite (1xx) or primary (9xx)
        barycenter_id = naif_id % 100_000_000
        if naif_id >= 900_000_000:
            # Primary body — classify as asteroid (could be dwarf planet,
            # but we can't distinguish from NAIF ID alone)
            return BodyType.ASTEROID, barycenter_id
        # Satellite
        return BodyType.MOON, barycenter_id
    if "spacecraft" in name.lower():
        return BodyType.SPACECRAFT, 0
    raise ValueError(
        f"Could not classify body with NAIF ID {naif_id} and name '{name}'"
    )


@dataclass
class MajorBody:
    name: str
    naif_id: int
    parent_naif_id: int
    type: BodyType
    designation: str | None = None
    extra: str | None = None


class HorizonsDownloader(Downloader):
    name = "horizons"

    def _fetch_horizons_bodies(self) -> str:
        """Fetch the list of major bodies from Horizons, using a cached file if available."""
        cache_file = self.out_dir / "major_bodies.txt"
        if cache_file.exists():
            logger.info("Using cached body list from %s", cache_file.name)
            text = cache_file.read_text()
        else:
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
            cache_file.write_text(text)
            logger.info("Cached body list -> %s", cache_file.name)
        return text

    def _fetch_body_list(self) -> list[MajorBody]:
        """Return all major bodies, sorted by type then NAIF ID.

        Center/parent relationships are computed after sorting so that
        barycenters are registered before their children are processed.
        """
        text = self._fetch_horizons_bodies()

        # Find column boundaries from the dashed header line
        #   ID#      Name                               Designation  IAU/aliases/other
        #   -------  ---------------------------------- -----------  -------------------
        # the lines can extend beyond the limit:
        #   -125544  International Space Station (spacec1998-067A    ISS
        lines = text.splitlines()
        cols: list[int] = []
        for i, line in enumerate(lines):
            if re.match(r"^\s*-{4,}\s", line):
                for m in re.finditer(r"-+", line):
                    cols.append(m.start())
                lines = lines[i + 1 :]
                break

        if len(cols) < 4:
            raise ValueError("Could not find column header in Horizons body list")

        id_sl = slice(0, cols[1] - 1)
        name_sl = slice(cols[1], cols[2] - 1)
        designation_sl = slice(cols[2], cols[3] - 1)
        extra_start = cols[3]

        bodies: list[MajorBody] = []
        for line in lines:
            id_str = line[id_sl].strip()
            if not id_str or not id_str.lstrip("-").isdigit():
                continue
            naif_id = int(id_str)
            name = line[name_sl].strip().removeprefix("(primary body)").strip()
            designation = line[designation_sl].strip() or None
            extra = line[extra_start:].strip() or None
            body_type, parent_id = _classify_body(naif_id, name, designation, extra)
            bodies.append(
                MajorBody(name, naif_id, parent_id, body_type, designation, extra)
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

    def get_bodies(self, limit: int | None = None) -> tuple[list[MajorBody], int]:
        logger.info("Fetching body list...")
        available_bodies = self._fetch_body_list()
        total_available = len(available_bodies)
        logger.info("%d major bodies found", total_available)

        body_list_file = self.out_dir / "body_list.json"
        with body_list_file.open("w") as f:
            json.dump(
                [
                    {
                        "name": b.name,
                        "naif_id": b.naif_id,
                        "parent_naif_id": b.parent_naif_id,
                        "type": b.type,
                        "designation": b.designation,
                        "extra": b.extra,
                    }
                    for b in available_bodies
                ],
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

        meta_fields = (
            "name",
            "naif_id",
            "type",
            "center",
            "parent_naif_id",
            "designation",
            "extra",
        )

        for body in tqdm(
            available_bodies, desc="Horizons", unit="body", dynamic_ncols=True
        ):
            response = self.client.get(
                URL,
                params={
                    **_BASE_PARAMS,
                    "TLIST": epoch_jd,
                    "CENTER": f"500@{body.parent_naif_id}",
                    "COMMAND": f"'{body.naif_id}'",
                },
            )
            response.raise_for_status()
            payload = response.json()

            if "error" in payload:
                logger.warning("%s (%s): %s", body.name, body.naif_id, payload["error"])
                continue

            row = self._parse_elements(payload["result"], body.name, str(body.naif_id))
            row["type"] = body.type
            row["parent_naif_id"] = str(body.parent_naif_id)
            row["designation"] = body.designation
            row["extra"] = body.extra

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
