"""Resolve the names of the ATNF pulsars in SIMBAD.

Each ATNF pulsar has a J name, and some have a B name. SIMBAD spells them
"PSR J0146+6145" and "PSR B0531+21". The query sends both names of every
pulsar. The extrasolar ingest reads this file to join each pulsar to the
SIMBAD row of its object.

Reads the ATNF Pulsar Catalogue of the stellar_remnant_catalogues provider.
Writes, below sources/stars/atnf-simbad/:
- names.csv      one row per J or B name, without "PSR ", with the oid, main
                 identifier and object type of its object; `oid` is empty
                 when SIMBAD has no object
- metadata.json

Terms: acknowledge "the SIMBAD database, CDS, Strasbourg Astronomical
Observatory, France" and cite Wenger et al. 2000. Licence: ODbL.
"""

import logging

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.catalogues.provider import (
    StellarRemnantCataloguesDownloader,
)
from space_map_data.download.providers.exoplanets.inputs import InputReader
from space_map_data.download.providers.exoplanets.simbad import TAP_URL
from space_map_data.download.providers.exoplanets.tap import tap_join, write_csv
from space_map_data.extrasolar.sources.atnf import ATNF_FILE, SIMBAD_FILE, read_pulsars
from space_map_data.utils.paths import SOURCES_CATALOGUES_DIR

logger = logging.getLogger(__name__)

NAME_CHUNK = 2000
HEADER = ["name", "oid", "main_id", "otype"]
_PREFIX = "PSR "
_RESOLVE = (
    "select s.name, b.oid, b.main_id, b.otype"
    " from TAP_UPLOAD.sent as s join ident as i on i.id = s.name"
    " join basic as b on b.oid = i.oidref"
)


class AtnfSimbadDownloader(InputReader):
    name = PROVIDERS.ATNF_SIMBAD

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        group = StellarRemnantCataloguesDownloader.group
        self.inputs = (SOURCES_CATALOGUES_DIR / group / "metadata.json",)
        self.out_dir = SIMBAD_FILE.parent
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        self.require_inputs()
        pulsars = read_pulsars(ATNF_FILE)
        names = sorted({_PREFIX + name for pulsar in pulsars for name in pulsar.names})
        logger.info(
            "Resolving %d names of %d ATNF pulsars in SIMBAD...",
            len(names),
            len(pulsars),
        )
        header, rows = tap_join(
            self.client, TAP_URL, _RESOLVE, "name", "char", names, NAME_CHUNK
        )
        at = {column: header.index(column) for column in HEADER}
        objects: dict[str, str] = {}
        found: list[list[str]] = []
        for row in rows:
            name, oid = row[at["name"]].removeprefix(_PREFIX), row[at["oid"]]
            if objects.setdefault(name, oid) != oid:
                raise DownloadError(f"SIMBAD gives {name!r} two objects")
            found.append([name, oid, row[at["main_id"]], row[at["otype"]]])
        missing = [n.removeprefix(_PREFIX) for n in names]
        missing = [name for name in missing if name not in objects]
        logger.info(
            "SIMBAD: %d of %d names resolved, %d without an object",
            len(objects),
            len(names),
            len(missing),
        )
        if not objects:
            raise DownloadError(f"SIMBAD matched none of the {len(names)} names")
        found += [[name, "", "", ""] for name in missing]
        found.sort()
        write_csv(SIMBAD_FILE, HEADER, found)
        self._save_metadata(
            TAP_URL,
            len(names),
            complete=True,
            names_sent=len(names),
            names_resolved=len(objects),
        )
