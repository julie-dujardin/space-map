"""Resolve the GCVS designations in SIMBAD.

The simbad_stars list holds only part of the GCVS stars. SIMBAD knows the
object of most other designations, with its Gaia DR3 id and HIP number. The
extrasolar ingest reads this file for the designations that the list does
not hold.

Reads the GCVS file of the stellar_parameter_catalogues provider. Writes,
below sources/stars/gcvs-simbad/:
- names.csv      one row per designation and ids of its object; `oid` is
                 empty when SIMBAD has no object, `gaia_dr3` and `hip` when
                 the object has no such id
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
from space_map_data.extrasolar.sources.gcvs import SIMBAD_FILE, read_entries
from space_map_data.utils.paths import SOURCES_CATALOGUES_DIR

logger = logging.getLogger(__name__)

NAME_CHUNK = 1000
HEADER = ["name", "oid", "main_id", "otype", "gaia_dr3", "hip"]
_PREFIX = "V* "
_RESOLVE = (
    "select s.name, b.oid, b.main_id, b.otype, g.id as gaia, h.id as hip"
    " from TAP_UPLOAD.sent as s join ident as i on i.id = s.name"
    " join basic as b on b.oid = i.oidref"
    " left outer join ident as g on g.oidref = b.oid and g.id like 'Gaia DR3 %'"
    " left outer join ident as h on h.oidref = b.oid and h.id like 'HIP %'"
)


class GcvsSimbadDownloader(InputReader):
    name = PROVIDERS.GCVS_SIMBAD

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        group = StellarParameterCataloguesDownloader.group
        self.inputs = (SOURCES_CATALOGUES_DIR / group / "metadata.json",)
        self.out_dir = SIMBAD_FILE.parent
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        self.require_inputs()
        names = sorted({_PREFIX + name for name, _ in read_entries()})
        logger.info("Resolving %d GCVS designations in SIMBAD...", len(names))
        header, rows = tap_join(
            self.client, TAP_URL, _RESOLVE, "name", "char", names, NAME_CHUNK
        )
        at = {column: header.index(column) for column in header}
        objects: dict[str, str] = {}
        found: list[list[str]] = []
        for row in rows:
            name, oid = row[at["name"]].removeprefix(_PREFIX), row[at["oid"]]
            if objects.setdefault(name, oid) != oid:
                raise DownloadError(f"SIMBAD gives {name!r} two objects")
            gaia = row[at["gaia"]].removeprefix("Gaia DR3 ").strip()
            hip = row[at["hip"]].removeprefix("HIP ").strip()
            found.append([name, oid, row[at["main_id"]], row[at["otype"]], gaia, hip])
        missing = [n.removeprefix(_PREFIX) for n in names]
        missing = [name for name in missing if name not in objects]
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
        write_csv(SIMBAD_FILE, HEADER, found)
        self._save_metadata(
            TAP_URL,
            len(names),
            complete=True,
            names_sent=len(names),
            names_resolved=len(objects),
        )
