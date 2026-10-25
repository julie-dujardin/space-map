"""Download the well-known stars of SIMBAD.

SIMBAD lists every identifier of an object, so one object joins the Gaia DR3,
Hipparcos and HD numbers and the traditional designations of a star. The
extrasolar ingest takes from it the famous stars that Gaia and Hipparcos do
not position, and the designations that XHIP does not give.

The list holds the objects whose main type is below `*` in the type tree,
except the types in EXCLUDED_TYPES, and that are well known: they have an
identifier that starts with one of TRADITIONAL, or at least MIN_REFERENCES
references. The list also holds the stars below a listed object in SIMBAD's
hierarchy (the components of a system), and the object of each IAU star name,
of any type.

SIMBAD has no bulk file, so the rows come from its TAP service. A selection
query sends MAX_ROWS as its row limit; the per-object queries upload the oids
OID_CHUNK at a time.

Writes, below sources/stars/simbad/:
- otypedef.csv  the type tree
- basic.csv     the position (ICRS, J2000), proper motion, parallax, spectral
                type and reference count of each listed object
- fluxes.csv    its B, V and Gaia G magnitudes, where SIMBAD has them
- ident.csv     its identifiers that start with one of IDENTIFIERS
- h_link.csv    the links between two listed objects
- iau.csv       each IAU star name, the first of its SIMBAD spelling,
                designation, Bayer ID and HIP number that SIMBAD knows, and
                the oid; both are empty when none is known
- metadata.json

Terms: acknowledge "the SIMBAD database, CDS, Strasbourg Astronomical
Observatory, France" and cite Wenger et al. 2000, A&AS 143, 9. Licence: ODbL.
"""

import csv
import io
import json
import logging
import re
from collections import Counter
from datetime import timedelta

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.exoplanets.inputs import InputReader
from space_map_data.download.providers.exoplanets.simbad import TAP_URL
from space_map_data.download.providers.exoplanets.tap import (
    Rows,
    tap_join,
    tap_rows,
    tap_sync,
    write_csv,
)
from space_map_data.download.providers.stars import iau_names
from space_map_data.utils.paths import SOURCES_STARS_DIR

logger = logging.getLogger(__name__)

OUT_DIR = SOURCES_STARS_DIR / "simbad"
OTYPEDEF_FILE, BASIC_FILE, FLUXES_FILE, IDENT_FILE, LINKS_FILE, IAU_FILE = (
    "otypedef.csv",
    "basic.csv",
    "fluxes.csv",
    "ident.csv",
    "h_link.csv",
    "iau.csv",
)
NAMES_FILE = iau_names.OUT_DIR / "names.json"

# Below `*` but not a star: planets, supernovae, planetary nebulae, outflows.
EXCLUDED_TYPES = frozenset({"Pl", "Pl?", "SN*", "SN?", "PN", "PN?", "out", "of?", "HH"})
# Bayer and Flamsteed, GCVS variable-star names, SIMBAD names, the Bright Star
# Catalogue, Wolf-Rayet stars and the Gliese-Jahreiss nearby stars.
TRADITIONAL = ("* ", "V* ", "NAME ", "HR ", "WR ", "GJ ")
# Measured on the Wikidata star items with an article in 12 languages, as a
# yardstick only. Of the 1,058 such stars that Gaia and Hipparcos do not
# give an ID, 20 references keep 997 for 130k objects, 10 keep 1,020 for
# 404k, 50 keep 954 for 73k.
MIN_REFERENCES = 20
# The identifiers that the ingest reads.
IDENTIFIERS = (
    "Gaia DR3 ",
    "HIP ",
    "HD ",
    "HR ",
    "* ",
    "V* ",
    "NAME ",
    "WR ",
    "GJ ",
    "Cl* ",
)
# Levels of components below a listed object.
COMPONENT_LEVELS = 2
# A star with more children holds a cluster. Its children are not listed.
MAX_CHILDREN = 20
MAX_ROWS = 2_000_000
NAME_CHUNK = 2000
OID_CHUNK = 5000

# The Greek letters of the IAU list, as SIMBAD abbreviates them.
GREEK = dict(
    zip(
        "αβγδεϵζηθικλμµνξοπρστυφϕχψω",
        [
            "alf",
            "bet",
            "gam",
            "del",
            "eps",
            "eps",
            "zet",
            "eta",
            "tet",
            "iot",
            "kap",
            "lam",
            "mu.",
            "mu.",
            "nu.",
            "ksi",
            "omi",
            "pi.",
            "rho",
            "sig",
            "tau",
            "ups",
            "phi",
            "phi",
            "chi",
            "psi",
            "ome",
        ],
        strict=True,
    )
)
_BAYER_ID = re.compile(
    r"(?:(?P<letter>[αβγδεϵζηθικλμµνξοπρστυφϕχψω])|(?P<number>\d+))"
    r"(?P<index>\d?) (?P<rest>[A-Z][A-Za-z]{2}(?: [A-Z][a-z]?)?)"
)

_BY_REFERENCES = "select oid from basic where otype in ({types}) and nbref >= {n}"
_BY_IDENTIFIER = (
    "select distinct i.oidref from ident as i join basic as b on b.oid = i.oidref"
    " where i.id like '{prefix}%' and b.otype in ({types})"
)
_RESOLVE = (
    "select s.name, i.oidref from TAP_UPLOAD.sent as s join ident as i on i.id = s.name"
)
_CHILDREN = (
    "select h.parent, h.child from TAP_UPLOAD.sent as s"
    " join h_link as h on h.parent = s.oid"
    " join basic as c on c.oid = h.child where c.otype in ({types})"
)
_BASIC = (
    "select b.oid, b.main_id, b.otype, b.ra, b.dec, b.coo_err_maj, b.coo_err_min,"
    " b.coo_qual, b.pmra, b.pmdec, b.pm_err_maj, b.pm_err_min, b.plx_value,"
    " b.plx_err, b.sp_type, b.nbref"
    " from TAP_UPLOAD.sent as s join basic as b on b.oid = s.oid"
)
_FLUXES = (
    "select f.oidref, f.B, f.V, f.G"
    " from TAP_UPLOAD.sent as s join allfluxes as f on f.oidref = s.oid"
)
_IDENT = (
    "select i.oidref, i.id from TAP_UPLOAD.sent as s"
    " join ident as i on i.oidref = s.oid where {kinds}"
)
_PARENTS = (
    "select h.child, h.parent from TAP_UPLOAD.sent as s"
    " join h_link as h on h.child = s.oid"
)


def _quoted(values: list[str]) -> str:
    return ",".join("'" + value.replace("'", "''") + "'" for value in values)


def star_types(otypedef: str) -> list[str]:
    """The type codes below `*` in the `otypedef` CSV, except EXCLUDED_TYPES."""
    found = [
        row["otype"]
        for row in csv.DictReader(io.StringIO(otypedef))
        if row["path"].strip().split(" > ")[0] == "*"
    ]
    if "*" not in found:
        raise DownloadError("SIMBAD type tree has no node `*`")
    return sorted(set(found) - EXCLUDED_TYPES)


def simbad_bayer(text: str) -> str:
    """A Bayer or Flamsteed designation as SIMBAD writes it: "τ2 Aqr" is
    "* tau02 Aqr". Other text stays as it is."""
    match = _BAYER_ID.fullmatch(text.strip())
    if match is None:
        return text.strip()
    first = match["number"] or GREEK[match["letter"]]
    if match["index"]:
        first += f"{int(match['index']):02d}"
    return " ".join(part for part in ("*", first, match["rest"]) if part)


def iau_identifiers(entry: dict[str, str]) -> list[str]:
    """The SIMBAD identifiers to try for one IAU name, best first."""
    found = []
    if spelling := entry.get("Simbad spelling", "").strip():
        found.append(f"NAME {spelling}")
    for key in ("Designation", "Bayer ID"):
        text = entry.get(key, "").strip()
        if text and text != "-":
            found.append(simbad_bayer(text))
    if hip := entry.get("HIP", "").strip():
        found.append(f"HIP {hip}")
    return list(dict.fromkeys(found))


def components(links: list[tuple[int, int]]) -> set[int]:
    """The children in `links` of parents with at most MAX_CHILDREN of them."""
    children = Counter(parent for parent, _ in links)
    for parent, count in sorted(children.items()):
        if count > MAX_CHILDREN:
            logger.info("SIMBAD %d has %d stars below it, none listed", parent, count)
    return {child for parent, child in links if children[parent] <= MAX_CHILDREN}


class SimbadStarsDownloader(InputReader):
    name = PROVIDERS.SIMBAD_STARS
    inputs = (NAMES_FILE,)
    # The list moves slowly. A new IAU name list runs it again.
    max_age = timedelta(days=30)

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.out_dir = OUT_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def _by_oid(self, query: str, oids: list[int]) -> Rows:
        return tap_join(self.client, TAP_URL, query, "oid", "long", oids, OID_CHUNK)

    def _oids(self, query: str) -> set[int]:
        _, rows = tap_rows(self.client, TAP_URL, query, max_rows=MAX_ROWS)
        return {int(row[0]) for row in rows}

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        self.require_inputs()
        otypedef = tap_sync(self.client, TAP_URL, "select * from otypedef")
        types = _quoted(star_types(otypedef))

        counts: dict[str, int] = {}
        listed = self._oids(_BY_REFERENCES.format(types=types, n=MIN_REFERENCES))
        counts["references"] = len(listed)
        for prefix in TRADITIONAL:
            found = self._oids(_BY_IDENTIFIER.format(prefix=prefix, types=types))
            counts[prefix.strip()] = len(found)
            listed |= found
        counts["well_known"] = len(listed)

        iau = self._resolve_iau()
        listed |= {int(oid) for _, _, oid in iau if oid}
        counts["iau"] = len(listed) - counts["well_known"]

        added = set(listed)
        for _ in range(COMPONENT_LEVELS):
            if not added:
                break
            _, links = self._by_oid(_CHILDREN.format(types=types), sorted(added))
            added = components([(int(p), int(c)) for p, c in links]) - listed
            listed |= added
        counts["components"] = len(listed) - counts["well_known"] - counts["iau"]
        oids = sorted(listed)
        logger.info("SIMBAD: %d stars listed, %s", len(oids), counts)

        basic_header, basic = self._by_oid(_BASIC, oids)
        if len(basic) != len(oids):
            raise DownloadError(f"SIMBAD basic has {len(basic)} rows for {len(oids)}")
        flux_header, fluxes = self._by_oid(_FLUXES, oids)
        kinds = " or ".join(f"i.id like '{prefix}%'" for prefix in IDENTIFIERS)
        ident_header, ident = self._by_oid(_IDENT.format(kinds=kinds), oids)
        link_header, links = self._by_oid(_PARENTS, oids)
        parent = link_header.index("parent")
        links = [link for link in links if int(link[parent]) in listed]

        # Every query has passed, so the files are one generation.
        (self.out_dir / OTYPEDEF_FILE).write_text(otypedef)
        write_csv(self.out_dir / BASIC_FILE, basic_header, basic)
        write_csv(self.out_dir / FLUXES_FILE, flux_header, fluxes)
        write_csv(self.out_dir / IDENT_FILE, ident_header, ident)
        write_csv(self.out_dir / LINKS_FILE, link_header, links)
        write_csv(self.out_dir / IAU_FILE, ["name", "identifier", "oid"], iau)
        self._save_metadata(
            TAP_URL,
            len(oids),
            complete=True,
            selection={
                "excluded_types": sorted(EXCLUDED_TYPES),
                "traditional": list(TRADITIONAL),
                "min_references": MIN_REFERENCES,
                "component_levels": COMPONENT_LEVELS,
            },
            counts=counts,
            identifiers=len(ident),
            links=len(links),
            iau_names=len(iau),
            iau_resolved=sum(1 for _, _, oid in iau if oid),
        )

    def _resolve_iau(self) -> list[tuple[str, str, str]]:
        """Each IAU name with the first of its identifiers that SIMBAD knows."""
        entries = json.loads(NAMES_FILE.read_text())
        tried = {e[iau_names.NAME_COLUMN]: iau_identifiers(e) for e in entries}
        strings = sorted({text for texts in tried.values() for text in texts})
        _, matches = tap_join(
            self.client, TAP_URL, _RESOLVE, "name", "char", strings, NAME_CHUNK
        )
        oid_of = dict(matches)
        found = []
        for name, texts in tried.items():
            hit = next((text for text in texts if text in oid_of), None)
            if hit is None:
                logger.warning("SIMBAD knows no identifier of %s: %s", name, texts)
            found.append((name, hit or "", oid_of[hit] if hit else ""))
        return found
