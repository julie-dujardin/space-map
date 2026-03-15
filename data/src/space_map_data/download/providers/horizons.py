import csv
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date

from space_map_data.models.body import ObjectType, DWARF_PLANETS
from space_map_data.utils.convert import date_to_julian
from tqdm import tqdm

from space_map_data.download.downloader import Downloader

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
DROP_PREFIX = ("(primary body)", "(spacecraft)", "(Spacecraft)", "(system barycenter)")


# To retrieve the orbital elements, we need to determnine the barycenter, which requires some classification
# So we do this step here, not in ingest.
def _classify_object(
    naif_id: int, name: str, name_pretty: str, extra: str | None
) -> tuple[ObjectType, int]:
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
        return ObjectType.spacecraft, 0

    if 1 <= naif_id <= 9 or "barycenter" in name.lower():
        # Planetary & asteroid system barycenters
        return ObjectType.barycenter, 0

    if naif_id == 10:
        # The Sun
        return ObjectType.star, 0

    if 100 <= naif_id <= 999:
        # Planets (P99) and moons (PNN), parent = planet barycenter P
        barycenter = naif_id // 100
        if naif_id % 100 == 99:  # Planet
            if naif_id == 999:  # rip pluto
                return ObjectType.dwarf_planet, barycenter
            if naif_id < 300:
                # mercury, venus: no moons, barycenter = planet, target cystem barycenter instead
                return ObjectType.planet, 0
            return ObjectType.planet, barycenter
        return ObjectType.moon, barycenter
    if 10_000 <= naif_id < 100_000:
        # Extended moon IDs: PXNNN (e.g. 65088 = 2004S17)
        return ObjectType.moon, naif_id // 10_000

    if extra and "lagrange" in extra.lower():
        return ObjectType.lagrange_point, 0

    if 1_000_000 <= naif_id < 2_000_000:
        return ObjectType.comet, 0
    if 2_000_000 <= naif_id < 10_000_000:
        if name_pretty.lower() in DWARF_PLANETS:
            return ObjectType.dwarf_planet, 0
        return ObjectType.asteroid, 0
    if naif_id >= 100_000_000:
        # Binary system members: satellite (1xx) or primary (9xx)
        barycenter_id = naif_id % 100_000_000
        if naif_id >= 900_000_000:
            # Primary body in binary system
            if name_pretty.lower() in DWARF_PLANETS:
                return ObjectType.dwarf_planet, barycenter_id
            return ObjectType.asteroid, barycenter_id
        # Satellite
        return ObjectType.moon, barycenter_id

    if "spacecraft" in name.lower():
        return ObjectType.spacecraft, 0
    if 990_000 <= naif_id < 1_000_000:
        # WT1190F
        return ObjectType.debris, 0

    if 20_000_000 <= naif_id < 100_000_000:
        # 20152830...: no idea
        return ObjectType.undocumented, 0

    raise ValueError(
        f"Could not classify body with NAIF ID {naif_id} and name '{name}'"
    )


@dataclass
class MajorBody:
    name: str
    naif_id: int
    parent_naif_id: int
    object_type: ObjectType
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
            name = line[name_sl].strip()
            designation = line[designation_sl].strip() or None
            extra = line[extra_start:].strip() or None

            name_pretty = name
            for suffix in DROP_PREFIX:
                name_pretty = name_pretty.removesuffix(suffix).strip()
            body_type, parent_id = _classify_object(naif_id, name, name_pretty, extra)

            # Drop unterminated parenthesis from column overflow
            # e.g. "Hubble Space Telescope (spacecraft" -> "Hubble Space Telescope"
            name_pretty = re.sub(r"\s*\([^)]*$", "", name_pretty)
            bodies.append(
                MajorBody(
                    name_pretty, naif_id, parent_id, body_type, designation, extra
                )
            )

        return bodies

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
                        "type": b.object_type,
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

    def download(
        self, limit: int | None = None, epoch: date | None = None, **kwargs: object
    ) -> None:
        if epoch is None:
            epoch = date.today()
        epoch_jd = f"{date_to_julian(epoch):.1f}"
        logger.info("Using epoch %s (JD %s)", epoch.isoformat(), epoch_jd)

        out_file = self.out_dir / "bodies.csv"

        available_bodies, total_available = self.get_bodies(limit=limit)

        meta_fields = (
            "name",
            "naif_id",
            "type",
            "center",
            "parent_naif_id",
            "designation",
            "extra",
        )

        # Load already-downloaded bodies from a previous (possibly partial) run
        existing: dict[str, dict] = {}
        fieldnames: list[str] | None = None
        if out_file.exists():
            with out_file.open(newline="") as f:
                reader = csv.DictReader(f)
                fieldnames = list(reader.fieldnames) if reader.fieldnames else None
                for row in reader:
                    existing[row["naif_id"]] = row
            if existing:
                logger.info("Loaded %d already-downloaded bodies", len(existing))

        new_rows: dict[str, dict] = {}
        skipped = 0

        for body in tqdm(
            available_bodies, desc="Horizons", unit="body", dynamic_ncols=True
        ):
            if body.object_type == ObjectType.lagrange_point or body.naif_id == 0:
                continue
            if str(body.naif_id) in existing:
                skipped += 1
                continue
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
            row["type"] = body.object_type
            row["parent_naif_id"] = str(body.parent_naif_id)
            row["designation"] = body.designation
            row["extra"] = body.extra

            if fieldnames is None:
                fieldnames = [*meta_fields, *(k for k in row if k not in meta_fields)]

            new_rows[str(body.naif_id)] = row
            time.sleep(0.5)

        if skipped:
            logger.info("Skipped %d already-downloaded bodies", skipped)

        # Merge existing + new, ordered by the body list
        all_data = existing | new_rows
        rows = [
            all_data[str(b.naif_id)]
            for b in available_bodies
            if str(b.naif_id) in all_data
        ]

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
