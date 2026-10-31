"""Where the deep-sky objects of the sky cultures lie, until the registry holds
them.

The direction is SIMBAD's, from the local export (catalogues/simbad), else
OpenNGC's: the export leaves out some nebula types. The distance is that of
the first catalogue of `_distances` that lists an identifier of the object. A
redshift gives none, since it needs a choice of cosmology. An object with no
distance gets one at export (`export/extrasolar/skycultures.py`).
"""

import csv
import io
import logging
import re
import tarfile
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pa_csv

from space_map_data.download.cds import README, read_fixed_width
from space_map_data.download.downloader import DownloadError, require_inputs
from space_map_data.extrasolar.exoplanets.catalogues import sexagesimal
from space_map_data.extrasolar.sources.distances import CLUSTER_TYPES
from space_map_data.utils.paths import SOURCES_CATALOGUES_DIR

logger = logging.getLogger(__name__)

HUNT_REFFERT, BAUMGARDT, HECATE = (
    "hunt-reffert-2024",
    "baumgardt-globular-clusters",
    "hecate",
)
HUNT_REFFERT_FILE, BAUMGARDT_FILE, HECATE_FILE = (
    "clusters.dat.gz",
    "combined_table.txt",
    "hecate.dat.gz",
)
OPENNGC_FILES = ("NGC.csv", "addendum.csv")
PC_PER_MPC = 1e6
PC_PER_KPC = 1e3
# A compact identifier as the sources write it, and as SIMBAD does.
_SPELLINGS = (
    (re.compile(r"COALSACKNEBULA"), "NAMECOALSACKNEBULA"),
    (re.compile(r"B(\d+)"), r"BARNARD\1"),
    (re.compile(r"CR(\d+)"), r"CLCOLLINDER\1"),
    (re.compile(r"MEL(\d+)"), r"CLMELOTTE\1"),
    (re.compile(r"ST(\d+)"), r"CLSTOCK\1"),
    (re.compile(r"PGC(\d+)"), r"LEDA\1"),
    (re.compile(r"PK(\d+[-+]\d+)\.(\d+)"), r"PK\1\2"),
)
_SEPARATORS = re.compile(r"[\s_]+")
_OPENNGC_NAME = re.compile(r"(NGC|IC)0*(\d+.*)")


class Place(NamedTuple):
    """ICRS degrees; pc and its catalogue, None when no catalogue lists one."""

    ra: float
    dec: float
    distance: float | None = None
    source: str | None = None


def compact(identifier: str) -> str:
    """An identifier with no spaces or padding, in upper case."""
    return _SEPARATORS.sub("", identifier).upper()


def simbad_key(designation: str) -> str:
    """The compact SIMBAD identifier of a designation of a culture."""
    key = compact(designation.removeprefix("DSO:"))
    for pattern, spelling in _SPELLINGS:
        if pattern.fullmatch(key):
            return pattern.sub(spelling, key)
    return key


def _catalogue_key(identifier: str) -> str:
    return compact(identifier).removeprefix("CL")


@dataclass
class _Found:
    oid: int
    identifiers: list[str]


def _files(directory: Path, pattern: str) -> list[Path]:
    paths = sorted(directory.glob(pattern))
    if not paths:
        raise DownloadError(f"{directory} has no {pattern}, run its provider first")
    return paths


def _simbad_objects(keys: set[str], directory: Path) -> dict[str, _Found]:
    """The object of each compact identifier that the local SIMBAD holds.

    The files hold rows by oid, so an object's identifiers share a file.
    """
    wanted = pa.array(sorted(keys), pa.string())
    found: dict[str, _Found] = {}
    for path in _files(directory / "ident", "*.csv.gz"):
        table = pa_csv.read_csv(path)
        names = pc.utf8_upper(pc.replace_substring_regex(table["id"], r"\s+", ""))
        hit = pc.is_in(names, value_set=wanted)
        oids = table["oidref"].filter(hit)
        if not len(oids):
            continue
        rows = table.filter(pc.is_in(table["oidref"], value_set=oids.unique()))
        by_oid: dict[int, list[str]] = defaultdict(list)
        for oid, identifier in zip(rows["oidref"].to_pylist(), rows["id"].to_pylist()):
            by_oid[oid].append(identifier)
        for name, oid in zip(names.filter(hit).to_pylist(), oids.to_pylist()):
            found[name] = _Found(oid, by_oid[oid])
    return found


def _holds_an_oid(path: Path, oids: list[int]) -> bool:
    """Whether the oid range in the name of `path` holds one of the sorted `oids`."""
    first, last = map(int, path.name.removesuffix(".csv.gz").split("-"))
    index = bisect_left(oids, first)
    return index < len(oids) and oids[index] <= last


def _simbad_positions(
    oids: Iterable[int], directory: Path
) -> dict[int, tuple[float, float]]:
    ordered = sorted(set(oids))
    wanted = pa.array(ordered, pa.int64())
    found: dict[int, tuple[float, float]] = {}
    for path in _files(directory / "basic", "*.csv.gz"):
        if not _holds_an_oid(path, ordered):
            continue
        table = pa_csv.read_csv(
            path,
            convert_options=pa_csv.ConvertOptions(include_columns=["oid", "ra", "dec"]),
        )
        rows = table.filter(pc.is_in(table["oid"], value_set=wanted))
        for oid, ra, dec in zip(
            rows["oid"].to_pylist(), rows["ra"].to_pylist(), rows["dec"].to_pylist()
        ):
            if ra is not None and dec is not None:
                found[oid] = (ra, dec)
    return found


def _openngc(path: Path) -> dict[str, tuple[float, float]]:
    """The position of each object of OpenNGC, by compact name."""
    found = {}
    with tarfile.open(path) as archive:
        for member in archive.getmembers():
            if Path(member.name).name not in OPENNGC_FILES:
                continue
            handle = archive.extractfile(member)
            if handle is None:
                continue
            text = io.TextIOWrapper(handle, encoding="utf-8")
            for row in csv.DictReader(text, delimiter=";"):
                ra = sexagesimal(row["RA"], hours=True)
                dec = sexagesimal(row["Dec"], hours=False)
                if ra is not None and dec is not None:
                    found[_OPENNGC_NAME.sub(r"\1\2", compact(row["Name"]))] = (ra, dec)
    return found


def _hunt_reffert(directory: Path) -> dict[str, float]:
    """The distance of each cluster by name and by alias.

    Rows can share an alias, so a row's own name wins, then its first row.
    """
    readme = (directory / README).read_text(encoding="latin-1")
    table = read_fixed_width(
        directory / HUNT_REFFERT_FILE,
        readme,
        {"Name": "name", "Type": "kind", "AllNames": "names", "dist50": "pc"},
    )
    own: dict[str, float] = {}
    aliases: dict[str, float] = {}
    for name, kind, names, distance in zip(
        *(table[c].to_pylist() for c in ("name", "kind", "names", "pc"))
    ):
        if kind in CLUSTER_TYPES and distance is not None:
            own[_catalogue_key(name)] = distance
            for alias in names.split(","):
                aliases.setdefault(_catalogue_key(alias), distance)
    return aliases | own


def _baumgardt(directory: Path) -> dict[str, float]:
    found = {}
    lines = (directory / BAUMGARDT_FILE).read_text(errors="replace")
    for line in lines.splitlines():
        if line.strip() and not line.startswith("#"):
            name, _, _, kpc = line[:42].rsplit(maxsplit=3)
            found[_catalogue_key(name)] = float(kpc) * PC_PER_KPC
    return found


def _hecate(directory: Path) -> dict[str, float]:
    readme = (directory / README).read_text(encoding="latin-1")
    table = read_fixed_width(directory / HECATE_FILE, readme, {"PGC": "pgc", "D": "d"})
    return {
        f"LEDA{pgc}": mpc * PC_PER_MPC
        for pgc, mpc in zip(table["pgc"].to_pylist(), table["d"].to_pylist())
        if pgc is not None and mpc is not None
    }


def _distances(catalogues: Path) -> list[tuple[str, dict[str, float]]]:
    """The distance (pc) of each object of a catalogue by key, in order."""
    return [
        (BAUMGARDT, _baumgardt(catalogues / "star-clusters" / BAUMGARDT)),
        (HUNT_REFFERT, _hunt_reffert(catalogues / "star-clusters" / HUNT_REFFERT)),
        (HECATE, _hecate(catalogues / "galaxies" / HECATE)),
    ]


def read_places(
    designations: Iterable[str], catalogues: Path = SOURCES_CATALOGUES_DIR
) -> dict[str, Place]:
    """The place of each designation that a catalogue positions, by designation."""
    clusters, galaxies = catalogues / "star-clusters", catalogues / "galaxies"
    require_inputs(
        (
            clusters / HUNT_REFFERT / README,
            clusters / HUNT_REFFERT / HUNT_REFFERT_FILE,
            clusters / BAUMGARDT / BAUMGARDT_FILE,
            galaxies / HECATE / README,
            galaxies / HECATE / HECATE_FILE,
        )
    )
    designations = sorted(set(designations))
    keys = {name: simbad_key(name) for name in designations}
    objects = _simbad_objects(set(keys.values()), catalogues / "simbad")
    positions = _simbad_positions(
        (found.oid for found in objects.values()), catalogues / "simbad"
    )
    # A release is named by its date, so the last name is the newest.
    fallback = _openngc(_files(galaxies / "openngc", "*.tar.gz")[-1])
    tables = _distances(catalogues)
    places: dict[str, Place] = {}
    for name in designations:
        key = keys[name]
        found = objects.get(key)
        position = positions.get(found.oid) if found else None
        if position is None:
            position = fallback.get(_OPENNGC_NAME.sub(r"\1\2", key))
        if position is None:
            logger.warning("sky cultures: no catalogue places %s", name)
            continue
        ids = {_catalogue_key(i) for i in found.identifiers} if found else {key}
        for source, table in tables:
            hit = next((table[i] for i in sorted(ids) if i in table), None)
            if hit is not None:
                places[name] = Place(*position, hit, source)
                break
        else:
            places[name] = Place(*position)
    return places
