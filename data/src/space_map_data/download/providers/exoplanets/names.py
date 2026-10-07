"""Collect the names the exoplanet catalogues give to stars and planets.

Each catalogue names the same object in its own way. Every name and alias is
collected, so that SIMBAD can resolve at least one of them.
"""

import csv
import gzip
import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.exoplanets import (
    exoplanet_eu,
    nasa_archive,
    open_catalogue,
)

logger = logging.getLogger(__name__)

PRINTED = "printed"
NO_COMPONENT = "no_component"

# `HD 1 A` and `HD 1 (AB)`.
_COMPONENT_RE = re.compile(r"\s*\([A-D]+\)$|\s+[A-D]{1,3}$")
# The lens of a microlensing event, `OGLE-2005-BLG-390L`. A pulsar name can
# also end in `L`, and there the letter is part of the name.
_LENS_RE = re.compile(r"(BLG-\d+)L$")


@dataclass(frozen=True, order=True)
class Name:
    """One string to resolve, and the catalogue object that it names.

    `object` is the key of the star or planet in `table` of `catalogue`.
    `variant` is NO_COMPONENT when the string is a printed name without its
    component letter. Such a name can resolve to the whole system, or to
    another star of the system.
    """

    catalogue: str
    table: str
    kind: str
    object: str
    name: str
    variant: str = PRINTED


@dataclass(frozen=True)
class CsvSource:
    """The columns of one CSV file that name one kind of object."""

    catalogue: PROVIDERS
    path: Path
    kind: str
    key: str
    # Each cell is one name.
    columns: tuple[str, ...] = ()
    # Each cell is a comma-separated list of names.
    lists: tuple[str, ...] = ()
    # Each cell needs a rewrite to become a name.
    formatted: tuple[tuple[str, Callable[[str], str]], ...] = ()

    @property
    def table(self) -> str:
        return self.path.stem

    @property
    def read_columns(self) -> tuple[str, ...]:
        """Every column that `csv_names` reads."""
        rewritten = tuple(column for column, _ in self.formatted)
        return (self.key, *self.columns, *self.lists, *rewritten)


def _koi(value: str) -> str:
    """Rewrite `K00752.01` as `KOI-752.01`."""
    return f"KOI-{value[1:].lstrip('0')}"


_ARCHIVE = PROVIDERS.EXOPLANET_ARCHIVE

CSV_SOURCES: tuple[CsvSource, ...] = (
    CsvSource(
        _ARCHIVE,
        nasa_archive.OUT_DIR / "stellarhosts.csv",
        "star",
        "hostname",
        columns=("hostname", *nasa_archive.STAR_ID_COLUMNS),
    ),
    CsvSource(
        _ARCHIVE,
        nasa_archive.OUT_DIR / "pscomppars.csv",
        "planet",
        "pl_name",
        columns=("pl_name",),
    ),
    CsvSource(
        _ARCHIVE,
        nasa_archive.OUT_DIR / "toi.csv",
        "star",
        "tid",
        formatted=(("tid", "TIC {}".format), ("toipfx", "TOI-{}".format)),
    ),
    CsvSource(
        _ARCHIVE,
        nasa_archive.OUT_DIR / "toi.csv",
        "planet",
        "toi",
        formatted=(("toi", "TOI-{}".format),),
    ),
    CsvSource(
        _ARCHIVE,
        nasa_archive.OUT_DIR / "cumulative.csv",
        "star",
        "kepid",
        formatted=(("kepid", "KIC {}".format),),
    ),
    CsvSource(
        _ARCHIVE,
        nasa_archive.OUT_DIR / "cumulative.csv",
        "planet",
        "kepoi_name",
        columns=("kepler_name",),
        formatted=(("kepoi_name", _koi),),
    ),
    CsvSource(
        _ARCHIVE,
        nasa_archive.OUT_DIR / "k2pandc.csv",
        "star",
        "hostname",
        columns=("hostname", "epic_hostname", *nasa_archive.STAR_ID_COLUMNS),
    ),
    CsvSource(
        _ARCHIVE,
        nasa_archive.OUT_DIR / "k2pandc.csv",
        "planet",
        "pl_name",
        columns=("pl_name", "k2_name", "epic_candname"),
    ),
    CsvSource(
        PROVIDERS.EXOPLANET_EU,
        exoplanet_eu.OUT_DIR / exoplanet_eu.CATALOG_FILE,
        "star",
        "star_name",
        columns=("star_name",),
        lists=("star_alternate_names",),
    ),
    CsvSource(
        PROVIDERS.EXOPLANET_EU,
        exoplanet_eu.OUT_DIR / exoplanet_eu.CATALOG_FILE,
        "planet",
        "name",
        columns=("name",),
        lists=("alternate_names",),
    ),
)

OEC_FILE = open_catalogue.OUT_DIR / open_catalogue.SYSTEMS_FILE


def csv_names(source: CsvSource) -> set[Name]:
    """Read every name that `source` states."""
    names: set[Name] = set()
    keyless = 0
    with source.path.open(newline="") as fh:
        reader = csv.DictReader(fh, restval="")
        header = reader.fieldnames or []
        missing = [column for column in source.read_columns if column not in header]
        if missing:
            raise DownloadError(
                f"{source.path.name} has no column {', '.join(missing)}"
            )
        for row in reader:
            key = row[source.key].strip()
            if not key:
                keyless += 1
                continue
            values = [row[column] for column in source.columns]
            values += [
                part for column in source.lists for part in row[column].split(",")
            ]
            values += [
                rewrite(row[column].strip())
                for column, rewrite in source.formatted
                if row[column].strip()
            ]
            names.update(
                Name(source.catalogue, source.table, source.kind, key, value.strip())
                for value in values
                if value.strip()
            )
    if keyless:
        logger.debug(
            "%s: %d rows have no %s, no %s name collected",
            source.path.name,
            keyless,
            source.key,
            source.kind,
        )
    return names


def oec_names(path: Path) -> set[Name]:
    """Read the names of every binary, star and planet in the OEC file."""
    root = ET.fromstring(gzip.decompress(path.read_bytes()))
    oec = PROVIDERS.OPEN_EXOPLANET_CATALOGUE
    names: set[Name] = set()
    for kind in ("binary", "star", "planet"):
        nameless = 0
        for element in root.iter(kind):
            printed = [
                node.text.strip()
                for node in element.findall("name")
                if node.text and node.text.strip()
            ]
            if not printed:
                nameless += 1
                continue
            names.update(Name(oec, "systems", kind, printed[0], v) for v in printed)
        if nameless:
            logger.debug("OEC: %d %s elements have no name", nameless, kind)
    return names


def without_component(name: str) -> str | None:
    """Drop a trailing component letter. Return None if there is none."""
    stripped = _LENS_RE.sub(r"\1", _COMPONENT_RE.sub("", name))
    return stripped if stripped and stripped != name else None


def component_variants(names: set[Name]) -> set[Name]:
    """Add the name without its component letter for each star and binary."""
    variants: set[Name] = set()
    for name in names:
        if name.kind == "planet":
            continue
        stripped = without_component(name.name)
        if stripped is None:
            continue
        if replace(name, name=stripped) not in names:
            variants.add(replace(name, name=stripped, variant=NO_COMPONENT))
    return variants


def collect_names() -> list[Name]:
    """Every name to resolve, from the three catalogues on disk."""
    names: set[Name] = set()
    for source in CSV_SOURCES:
        names |= csv_names(source)
    names |= oec_names(OEC_FILE)
    names |= component_variants(names)
    return sorted(names)
