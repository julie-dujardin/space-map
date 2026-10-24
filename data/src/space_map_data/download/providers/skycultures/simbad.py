"""Resolve the SIMBAD identifiers of Bucur's dataset in SIMBAD.

Bucur names each star by a SIMBAD identifier. SIMBAD lists every identifier
of an object, its HIP and Gaia DR3 numbers among them, and the registry knows
those. The local SIMBAD export (catalogues/simbad) holds no single stars, so
the identifiers go to SIMBAD's TAP service.

SIMBAD often puts the HIP number of a double star on the system and not on
its components, so the parents of each matched object are fetched too.

Reads the JSON files of the bucur_constellations provider. Writes, below
sources/skycultures/bucur-simbad/:
- names.csv     one row per identifier sent; `oid` is empty when SIMBAD has none
- h_link.csv    the links of each matched object to its parents
- basic.csv     the `basic` row of each matched object and parent
- ids.csv       every identifier of the same objects, `|`-separated
- otypedef.csv  the SIMBAD type tree, to tell stars from deep-sky objects
- metadata.json

Terms: acknowledge "the SIMBAD database, CDS, Strasbourg Astronomical
Observatory, France" and cite Wenger et al. 2000. Licence: ODbL.
"""

import json
import logging
from pathlib import Path

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.exoplanets.inputs import InputReader
from space_map_data.download.providers.exoplanets.simbad import TAP_URL
from space_map_data.download.providers.exoplanets.tap import (
    tap_join,
    tap_sync,
    write_csv,
)
from space_map_data.download.providers.skycultures import bucur
from space_map_data.skycultures.refs import Kind, bucur_ref, collect
from space_map_data.utils.paths import SOURCES_SKYCULTURES_DIR

logger = logging.getLogger(__name__)

OUT_DIR = SOURCES_SKYCULTURES_DIR / "bucur-simbad"
NAMES_FILE, LINKS_FILE, BASIC_FILE, IDS_FILE, OTYPEDEF_FILE = (
    "names.csv",
    "h_link.csv",
    "basic.csv",
    "ids.csv",
    "otypedef.csv",
)
NAME_CHUNK = 2000
OID_CHUNK = 5000

_RESOLVE = (
    "select s.name, i.oidref from TAP_UPLOAD.sent as s join ident as i on i.id = s.name"
)
_BASIC = (
    "select b.oid, b.main_id, b.otype, b.ra, b.dec, b.sp_type"
    " from TAP_UPLOAD.sent as s join basic as b on b.oid = s.oid"
)
_IDS = (
    "select i.oidref, i.ids from TAP_UPLOAD.sent as s join ids as i on i.oidref = s.oid"
)
_PARENTS = (
    "select h.child, h.parent, h.membership"
    " from TAP_UPLOAD.sent as s join h_link as h on h.child = s.oid"
)


def simbad_identifiers(cultures_dir: Path) -> list[str]:
    """Every SIMBAD identifier of the cultures in `cultures_dir`, sorted."""
    found: set[str] = set()
    for path in sorted(cultures_dir.glob("*.json")):
        culture = json.loads(path.read_text())
        for ref, _ in collect(culture, bucur_ref, bucur_ref):
            if ref.kind == Kind.SIMBAD:
                found.add(ref.value)
    return sorted(found)


class SkycultureSimbadDownloader(InputReader):
    name = PROVIDERS.SKYCULTURE_SIMBAD

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.inputs = (bucur.OUT_DIR / "metadata.json",)
        self.out_dir = OUT_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        self.require_inputs()
        names = simbad_identifiers(bucur.CULTURES_DIR)
        logger.info("Resolving %d identifiers in SIMBAD...", len(names))
        _, matches = tap_join(
            self.client, TAP_URL, _RESOLVE, "name", "char", names, NAME_CHUNK
        )
        oid_of: dict[str, str] = {}
        for name, oid in matches:
            if oid_of.setdefault(name, oid) != oid:
                raise DownloadError(f"SIMBAD gives {name!r} two objects")
        missing = [name for name in names if name not in oid_of]
        for name in missing:
            logger.warning("SIMBAD has no object %r", name)
        if not oid_of:
            raise DownloadError(f"SIMBAD matched none of the {len(names)} names")

        matched = sorted({int(oid) for oid in oid_of.values()})
        links_header, links = tap_join(
            self.client, TAP_URL, _PARENTS, "oid", "long", matched, OID_CHUNK
        )
        parent = links_header.index("parent")
        oids = sorted(set(matched) | {int(link[parent]) for link in links})
        basic_header, basic = tap_join(
            self.client, TAP_URL, _BASIC, "oid", "long", oids, OID_CHUNK
        )
        ids_header, ids = tap_join(
            self.client, TAP_URL, _IDS, "oid", "long", oids, OID_CHUNK
        )
        for table, rows in (("basic", basic), ("ids", ids)):
            if len(rows) != len(oids):
                raise DownloadError(
                    f"SIMBAD {table} has {len(rows)} rows for {len(oids)} objects"
                )
        otypedef = tap_sync(self.client, TAP_URL, "SELECT * FROM otypedef")

        # Every query has passed, so the files are one generation.
        write_csv(
            self.out_dir / NAMES_FILE,
            ["name", "oid"],
            ([name, oid_of.get(name, "")] for name in names),
        )
        write_csv(self.out_dir / LINKS_FILE, links_header, links)
        write_csv(self.out_dir / BASIC_FILE, basic_header, basic)
        write_csv(self.out_dir / IDS_FILE, ids_header, ids)
        (self.out_dir / OTYPEDEF_FILE).write_text(otypedef)
        self._save_metadata(
            TAP_URL,
            len(oids),
            complete=True,
            names_sent=len(names),
            names_resolved=len(oid_of),
            parents=len(oids) - len(matched),
            bucur_commit=bucur.COMMIT,
        )
