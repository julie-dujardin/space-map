import csv
import hashlib
import json
import logging
import re
import time
from datetime import date

from space_map_data.models.object import ObjectType
from space_map_data.utils.convert import date_to_julian
from space_map_data.utils.naif import classify_object, MajorBody
from tqdm import tqdm

from space_map_data.constants.providers import PROVIDERS
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
_ELEMENT_FIELDS = ("EC", "QR", "IN", "OM", "W", "Tp", "N", "MA", "TA", "A", "AD", "PR")


class HorizonsDownloader(Downloader):
    name = PROVIDERS.HORIZONS

    def _previous_mb_hash(self) -> str | None:
        """Read the last-fetched major_bodies.txt sha256 from metadata."""
        if not self.metadata_file.exists():
            return None
        try:
            meta = json.loads(self.metadata_file.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        return meta.get("major_bodies_sha256")

    def _fetch_horizons_bodies(self) -> tuple[str, str, bool]:
        """Re-fetch the major bodies list every run; signal whether it changed.

        Returns ``(text, sha256, changed)``. The on-disk cache is overwritten
        only when the hash differs from the previous run, so the file's mtime
        tracks actual upstream changes.
        """
        cache_file = self.out_dir / "major_bodies.txt"
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
        text: str = response.json()["result"]
        new_hash = hashlib.sha256(text.encode()).hexdigest()
        prev_hash = self._previous_mb_hash()
        changed = prev_hash != new_hash

        if changed:
            cache_file.write_text(text)
            if prev_hash is None:
                logger.info(
                    "Fetched body list -> %s (sha256=%s)",
                    cache_file.name,
                    new_hash[:12],
                )
            else:
                logger.info(
                    "Body list changed -> %s (sha256 %s -> %s)",
                    cache_file.name,
                    prev_hash[:12],
                    new_hash[:12],
                )
        else:
            logger.info("Body list unchanged (sha256=%s)", new_hash[:12])

        return text, new_hash, changed

    def _parse_body_list(self, text: str) -> list[MajorBody]:
        """Parse the major bodies list text into MajorBody objects."""
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
            body_type, parent_id = classify_object(naif_id, name, name_pretty, extra)

            # Drop unterminated parenthesis from column overflow
            # e.g. "Hubble Space Telescope (spacecraft" -> "Hubble Space Telescope"
            name_pretty = re.sub(r"\s*\([^)]*$", "", name_pretty)
            bodies.append(
                MajorBody(
                    name_pretty, naif_id, parent_id, body_type, designation, extra
                )
            )

        return bodies

    def get_bodies(
        self, text: str, limit: int | None = None
    ) -> tuple[list[MajorBody], int]:
        available_bodies = self._parse_body_list(text)
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

        text, mb_hash, mb_changed = self._fetch_horizons_bodies()
        available_bodies, total_available = self.get_bodies(text, limit=limit)

        # Upstream body list changed (new ID, rename, retired ID): drop the
        # cached per-body elements so renames refill on this pass.
        if mb_changed and out_file.exists():
            logger.info("Body list changed; dropping %s for full refill", out_file.name)
            out_file.unlink()

        meta_fields = (
            "name",
            "naif_id",
            "type",
            "center",
            "parent_naif_id",
            "designation",
            "extra",
        )

        # Load already-downloaded bodies from a previous (possibly partial) run.
        # Drop pre-existing non-spacecraft rows left over from older runs.
        existing: dict[str, dict] = {}
        fieldnames: list[str] | None = None
        if out_file.exists():
            with out_file.open(newline="") as f:
                reader = csv.DictReader(f)
                fieldnames = list(reader.fieldnames) if reader.fieldnames else None
                for row in reader:
                    if (
                        row.get("type") == ObjectType.spacecraft
                        or row.get("naif_id") == "0"
                    ):
                        existing[row["naif_id"]] = row
            if existing:
                logger.info("Loaded %d already-downloaded bodies", len(existing))

        new_rows: dict[str, dict] = {}
        skipped = 0

        # Spacecraft only: planets, moons, barycenters, asteroids/comets, and
        # lagrange points are sourced elsewhere (SPICE / SBDB) and don't need
        # Horizons osculating elements.
        spacecraft_bodies = [
            b
            for b in available_bodies
            if b.object_type == ObjectType.spacecraft or b.naif_id == 0
        ]
        for body in tqdm(
            spacecraft_bodies, desc="Horizons", unit="body", dynamic_ncols=True
        ):
            if body.naif_id == 0:
                # SSB is the coordinate origin — synthesize a zero-filled row, no API call needed
                row = {
                    "name": body.name,
                    "naif_id": "0",
                    "type": str(body.object_type),
                    "center": "",
                    "parent_naif_id": "0",
                    "designation": body.designation or "",
                    "extra": body.extra or "",
                    "JDTDB": epoch_jd,
                    "Calendar Date (TDB)": epoch.isoformat(),
                    **{k: "0" for k in _ELEMENT_FIELDS},
                }
                if fieldnames is None:
                    fieldnames = [
                        *meta_fields,
                        "JDTDB",
                        "Calendar Date (TDB)",
                        *_ELEMENT_FIELDS,
                    ]
                new_rows["0"] = row
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
            complete=False,
            epoch=epoch.isoformat(),
            epoch_jd=epoch_jd,
            major_bodies_sha256=mb_hash,
        )
