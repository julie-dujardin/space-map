"""Resolve the PASTEL designations in SIMBAD.

PASTEL names each star as the paper did. SIMBAD knows the object of most
names, its position and its Gaia DR3 id, also for one component of a double
star where Hipparcos and HD name the system. The extrasolar ingest reads this
file to place the designations that no HD or HIP number places, and to check
the ones that it does.

Reads the PASTEL file of the stellar_parameter_catalogues provider. Writes,
below sources/stars/pastel-simbad/:
- names.csv      one row per designation and Gaia DR3 id of its object; `oid`
                 is empty when SIMBAD has no object, `gaia_dr3` when the
                 object has no Gaia DR3 id
- metadata.json

Terms: acknowledge "the SIMBAD database, CDS, Strasbourg Astronomical
Observatory, France" and cite Wenger et al. 2000. Licence: ODbL.
"""

import logging

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.catalogues.provider import (
    StellarParameterCataloguesDownloader,
)
from space_map_data.download.providers.exoplanets.inputs import InputReader
from space_map_data.download.providers.exoplanets.simbad import TAP_URL
from space_map_data.download.providers.exoplanets.tap import tap_join, write_csv
from space_map_data.extrasolar.sources.pastel import PASTEL_DIR, read_determinations
from space_map_data.utils.paths import SOURCES_CATALOGUES_DIR, SOURCES_STARS_DIR

logger = logging.getLogger(__name__)

OUT_DIR = SOURCES_STARS_DIR / "pastel-simbad"
NAMES_FILE = "names.csv"
NAME_CHUNK = 2000
HEADER = ["name", "oid", "main_id", "ra", "dec", "gaia_dr3"]
_RESOLVE = (
    "select s.name, b.oid, b.main_id, b.ra, b.dec, g.id as gaia"
    " from TAP_UPLOAD.sent as s join ident as i on i.id = s.name"
    " join basic as b on b.oid = i.oidref"
    " left outer join ident as g on g.oidref = b.oid and g.id like 'Gaia DR3 %'"
)


class PastelSimbadDownloader(InputReader):
    name = PROVIDERS.PASTEL_SIMBAD

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        group = StellarParameterCataloguesDownloader.group
        self.inputs = (SOURCES_CATALOGUES_DIR / group / "metadata.json",)
        self.out_dir = OUT_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        self.require_inputs()
        names = sorted(set(read_determinations(PASTEL_DIR)["designation"].to_pylist()))
        logger.info("Resolving %d PASTEL designations in SIMBAD...", len(names))
        header, rows = tap_join(
            self.client, TAP_URL, _RESOLVE, "name", "char", names, NAME_CHUNK
        )
        at = {column: header.index(column) for column in ("name", "oid", "gaia")}
        objects: dict[str, str] = {}
        found: list[list[str]] = []
        for row in rows:
            name, oid = row[at["name"]], row[at["oid"]]
            if objects.setdefault(name, oid) != oid:
                raise DownloadError(f"SIMBAD gives {name!r} two objects")
            gaia = row[at["gaia"]].removeprefix("Gaia DR3 ").strip()
            found.append([name, oid, *row[2:5], gaia])
        missing = [name for name in names if name not in objects]
        logger.info(
            "SIMBAD: %d of %d designations resolved, %d without an object",
            len(objects),
            len(names),
            len(missing),
        )
        if not objects:
            raise DownloadError(f"SIMBAD matched none of the {len(names)} names")
        found += [[name, "", "", "", "", ""] for name in missing]
        found.sort()
        write_csv(self.out_dir / NAMES_FILE, HEADER, found)
        self._save_metadata(
            TAP_URL,
            len(names),
            complete=True,
            names_sent=len(names),
            names_resolved=len(objects),
        )
