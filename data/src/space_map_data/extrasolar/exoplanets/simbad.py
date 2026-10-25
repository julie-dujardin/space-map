"""SIMBAD as the hub between the catalogues: names to objects and their ids.

The `simbad` exoplanet provider resolved every name of the three catalogues.
A star name resolves to its SIMBAD object. The printed name counts first,
then the name without its component letter, which can name the system or
another star of it. A name that resolves to a planet object is not a star.
"""

import csv
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.providers.exoplanets import names as provider_names
from space_map_data.download.providers.exoplanets import simbad as provider
from space_map_data.extrasolar.exoplanets.catalogues import ARCHIVE, EU, OEC

logger = logging.getLogger(__name__)

SIMBAD_DIR = provider.OUT_DIR
PLANET_TYPES = frozenset({"Pl", "Pl?"})
# Object types of a system of stars, not of one star.
SYSTEM_TYPES = frozenset({"**"})
# Parents that join the stars of one system.
PARENT_TYPES = frozenset({"**", "SB*", "EB*"})
# The catalogue and table names that the provider writes, per catalogue.
TABLES = {
    ARCHIVE: (PROVIDERS.EXOPLANET_ARCHIVE.value, "stellarhosts", "pscomppars"),
    EU: (PROVIDERS.EXOPLANET_EU.value, "catalog", "catalog"),
    OEC: (PROVIDERS.OPEN_EXOPLANET_CATALOGUE.value, "systems", "systems"),
}
PULSAR = "pulsar"
CLASSES = {
    "BD*": "brown dwarf",
    "BD?": "brown dwarf",
    "WD*": "white dwarf",
    "WD?": "white dwarf",
    "Psr": PULSAR,
}


@dataclass
class Simbad:
    # (catalogue, table, kind, object) → variant → oid → count of names.
    resolved: dict[tuple[str, str, str, str], dict[str, Counter]] = field(
        default_factory=dict
    )
    otype: dict[str, str] = field(default_factory=dict)
    main_id: dict[str, str] = field(default_factory=dict)
    gaia_dr3: dict[str, int] = field(default_factory=dict)
    gaia_dr2: dict[str, int] = field(default_factory=dict)
    hip: dict[str, int] = field(default_factory=dict)
    parents: dict[str, set[str]] = field(default_factory=dict)

    def star(self, catalogue: str, obj: str) -> str | None:
        """The SIMBAD object of a catalogue star, None when not one star.

        A printed name wins over a name without its component letter. A
        name without its letter counts only for a primary, `A` or `(AB)`, or
        a lens `L`, and only when it names a star, not the system: without
        its letter `HD 1 B` names HD 1 A.
        """
        source, table, _ = TABLES[catalogue]
        by = self.resolved.get((source, table, "star", obj), {})
        variants = [provider_names.PRINTED]
        if primary_component(obj):
            variants.append(provider_names.NO_COMPONENT)
        for variant in variants:
            oids = [
                oid
                for oid in by.get(variant, {})
                if self.otype.get(oid, "") not in PLANET_TYPES
            ]
            if variant == provider_names.NO_COMPONENT:
                oids = [o for o in oids if self.otype.get(o) not in SYSTEM_TYPES]
            if len(oids) == 1:
                return oids[0]
            if len(oids) > 1:
                # Several names of the star resolve: the most named object.
                counts = by[variant]
                return max(oids, key=lambda oid: (counts[oid], -int(oid)))
        return None

    def planet(self, catalogue: str, obj: str) -> str | None:
        """The SIMBAD planet object of a catalogue planet, if one only."""
        source, _, table = TABLES[catalogue]
        by = self.resolved.get((source, table, "planet", obj), {})
        oids = [
            o
            for o in by.get(provider_names.PRINTED, {})
            if self.otype.get(o) in PLANET_TYPES
        ]
        return oids[0] if len(oids) == 1 else None

    def systems(self, oid: str) -> set[str]:
        """The double-star and binary parents of an object."""
        return {
            p for p in self.parents.get(oid, ()) if self.otype.get(p) in PARENT_TYPES
        }

    def star_class(self, oid: str | None) -> str:
        return CLASSES.get(self.otype.get(oid or "", ""), "star")


def primary_component(name: str) -> bool:
    """Whether a name ends with the letter of a primary, a pair or a lens."""
    stripped = provider_names.without_component(name)
    if stripped is None:
        return False
    suffix = name[len(stripped) :].strip(" ()")
    return suffix.startswith("A") or suffix == "L"


def _rows(path: Path):
    csv.field_size_limit(1 << 30)
    with path.open(newline="") as fh:
        yield from csv.DictReader(fh)


def read_simbad(directory: Path = SIMBAD_DIR) -> Simbad:
    hub = Simbad()
    resolved: dict = defaultdict(lambda: defaultdict(Counter))
    for row in _rows(directory / "names.csv"):
        if row["oid"]:
            key = (row["catalogue"], row["table"], row["kind"], row["object"])
            resolved[key][row["variant"]][row["oid"]] += 1
    hub.resolved = {key: dict(value) for key, value in resolved.items()}
    for row in _rows(directory / "basic.csv"):
        hub.otype[row["oid"]] = row["otype"]
        hub.main_id[row["oid"]] = row["main_id"]
    for row in _rows(directory / provider.IDS_FILE):
        for ident in row["ids"].split("|"):
            ident = ident.strip()
            if ident.startswith("Gaia DR3 "):
                hub.gaia_dr3[row["oidref"]] = int(ident.removeprefix("Gaia DR3 "))
            elif ident.startswith("Gaia DR2 "):
                hub.gaia_dr2[row["oidref"]] = int(ident.removeprefix("Gaia DR2 "))
            elif ident.startswith("HIP ") and ident[4:].strip().isdigit():
                hub.hip[row["oidref"]] = int(ident[4:].strip())
    parents: dict[str, set[str]] = defaultdict(set)
    for row in _rows(directory / "h_link.csv"):
        parents[row["child"]].add(row["parent"])
    hub.parents = dict(parents)
    logger.info(
        "SIMBAD: %d resolved objects, %d with a Gaia DR3 id",
        len(hub.otype),
        len(hub.gaia_dr3),
    )
    return hub
