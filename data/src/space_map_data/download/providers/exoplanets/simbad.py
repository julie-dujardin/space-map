"""Resolve the exoplanet catalogue names to SIMBAD objects.

SIMBAD holds every identifier of an object. One resolved name gives the Gaia
DR3, Gaia DR2, HIP, HD and TIC ids of a star, so SIMBAD joins catalogues that
name the same star differently. Name comparison in SIMBAD ignores case and
spacing.

Reads the files of the three catalogue providers. Writes:
- names.csv   one row per name sent. `oid` is empty when SIMBAD has no match.
- h_link.csv  the links of each matched object and of each SIMBAD planet to
              its parents and to its children
- basic.csv   the `basic` row of each of those objects, parents and children
- ids.csv     all identifiers of the same objects, `|`-separated

Terms: acknowledge "the SIMBAD database, CDS, Strasbourg Astronomical
Observatory, France" and cite Wenger et al. 2000.
"""

import logging
from collections import Counter, defaultdict
from dataclasses import astuple, fields
from datetime import timedelta

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.exoplanets.inputs import InputReader
from space_map_data.download.providers.exoplanets.names import (
    CSV_SOURCES,
    OEC_FILE,
    PRINTED,
    Name,
    collect_names,
)
from space_map_data.download.providers.exoplanets.tap import (
    Rows,
    tap_join,
    tap_rows,
    write_csv,
)
from space_map_data.utils.paths import SOURCES_EXOPLANETS_DIR

logger = logging.getLogger(__name__)

TAP_URL = "https://simbad.cds.unistra.fr/simbad/sim-tap/sync"
OUT_DIR = SOURCES_EXOPLANETS_DIR / "simbad"
IDS_FILE = "ids.csv"

NAME_CHUNK = 2000
OID_CHUNK = 5000
# A star system has few components. A parent with more children is a cluster
# or a galaxy, and its members are not fetched.
MAX_CHILDREN = 50

_RESOLVE = (
    "select s.name, i.oidref from TAP_UPLOAD.sent as s join ident as i on i.id = s.name"
)
_PLANETS = "select oid from basic where otype in ('Pl', 'Pl?')"
_BASIC = "select b.* from TAP_UPLOAD.sent as s join basic as b on b.oid = s.oid"
_IDS = (
    "select i.oidref, i.ids from TAP_UPLOAD.sent as s join ids as i on i.oidref = s.oid"
)
_LINKS = "select h.* from TAP_UPLOAD.sent as s join h_link as h on h.{} = s.oid"


def log_coverage(names: list[Name], oid_of: dict[str, str]) -> None:
    """Log how many objects of each catalogue and kind have a SIMBAD match.

    A match on a name without its component letter is counted apart. It can
    be another star of the system.
    """
    printed: dict[tuple[str, str], set[str]] = defaultdict(set)
    matched: dict[tuple[str, str], set[str]] = defaultdict(set)
    objects: dict[tuple[str, str], set[str]] = defaultdict(set)
    for name in names:
        group = name.catalogue, name.kind
        key = f"{name.table}/{name.object}"
        objects[group].add(key)
        if name.name in oid_of:
            matched[group].add(key)
            if name.variant == PRINTED:
                printed[group].add(key)
    for group in sorted(objects):
        logger.info(
            "  %s %s: %d of %d in SIMBAD, %d more without the component letter",
            *group,
            len(printed[group]),
            len(objects[group]),
            len(matched[group] - printed[group]),
        )


def drop_large_parents(header: list[str], links: list[list[str]]) -> list[list[str]]:
    """Drop the child links of each parent with more than MAX_CHILDREN children."""
    parent = header.index("parent")
    children = Counter(link[parent] for link in links)
    large = {oid: count for oid, count in children.items() if count > MAX_CHILDREN}
    for oid, count in sorted(large.items()):
        logger.info("SIMBAD object %s has %d children, none fetched", oid, count)
    return [link for link in links if link[parent] not in large]


class ExoplanetSimbadDownloader(InputReader):
    name = PROVIDERS.EXOPLANET_SIMBAD
    inputs = (*sorted({source.path for source in CSV_SOURCES}), OEC_FILE)
    # SIMBAD gains identifiers between two changes of the catalogues.
    max_age = timedelta(days=7)

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = OUT_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def _by_oid(self, query: str, oids: list[int]) -> Rows:
        return tap_join(self.client, TAP_URL, query, "oid", "long", oids, OID_CHUNK)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        self.require_inputs()
        names = collect_names()
        strings = sorted({name.name for name in names})
        logger.info("Resolving %d names in SIMBAD...", len(strings))
        _, matches = tap_join(
            self.client, TAP_URL, _RESOLVE, "name", "char", strings, NAME_CHUNK
        )
        oid_of = dict(matches)
        if not oid_of:
            raise DownloadError(f"SIMBAD matched none of the {len(strings)} names")
        log_coverage(names, oid_of)

        _, planets = tap_rows(self.client, TAP_URL, _PLANETS)
        oids = sorted(
            {int(oid) for oid in oid_of.values()} | {int(p[0]) for p in planets}
        )

        link_header, to_parents = self._by_oid(_LINKS.format("child"), oids)
        _, to_children = self._by_oid(_LINKS.format("parent"), oids)
        # A link between two of the objects comes back from both sides.
        links = dict.fromkeys(
            map(tuple, [*to_parents, *drop_large_parents(link_header, to_children)])
        )
        ends = (link_header.index("child"), link_header.index("parent"))
        linked = sorted({int(link[end]) for link in links for end in ends} | set(oids))
        logger.info(
            "Fetching %d SIMBAD objects: %d matched or planets, %d linked to them...",
            len(linked),
            len(oids),
            len(linked) - len(oids),
        )
        basic_header, basic = self._by_oid(_BASIC, linked)
        ids_header, ids = self._by_oid(_IDS, linked)
        for table, rows in (("basic", basic), ("ids", ids)):
            if len(rows) != len(linked):
                raise DownloadError(
                    f"SIMBAD {table} has {len(rows)} rows for {len(linked)} objects"
                )

        # Every query has passed, so the four files are one generation.
        write_csv(
            self.out_dir / "names.csv",
            [*(field.name for field in fields(Name)), "oid"],
            ([*astuple(name), oid_of.get(name.name, "")] for name in names),
        )
        write_csv(self.out_dir / "h_link.csv", link_header, links)
        write_csv(self.out_dir / "basic.csv", basic_header, basic)
        write_csv(self.out_dir / IDS_FILE, ids_header, ids)
        self._save_metadata(
            TAP_URL,
            len(linked),
            complete=True,
            names_sent=len(strings),
            names_resolved=len(oid_of),
            planets=len(planets),
            links=len(links),
        )
