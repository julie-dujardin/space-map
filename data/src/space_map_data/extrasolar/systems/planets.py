"""The planet catalogues' systems as a tree source, and the planets.

A system is the star identities that the archive or OEC put in one system
(`hosts.group_systems`). OEC's hierarchy of binaries gives its levels. A
star that OEC does not place in it is one more member of the system's root.
A system of one star is no tree.

The stars of one OEC system share one position, so a member joins by its
ids only: its rows in the catalogues, its Gaia DR3 id, HIP number and SIMBAD
object.

PLANETS is the planets table as the builder reads it. `star_ids` are the ids
under which the planet is also a star of a star catalogue: its SIMBAD object
when that is not of a planet type, and that object's Gaia DR3 id.
"""

import gzip
import logging
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow as pa

from space_map_data.download.providers.exoplanets import names as provider_names
from space_map_data.extrasolar.exoplanets.catalogues import OEC, OEC_SYSTEMS
from space_map_data.extrasolar.exoplanets.hosts import Identity, Stars, Systems
from space_map_data.extrasolar.exoplanets.simbad import TABLES, Simbad
from space_map_data.extrasolar.systems.nodes import (
    CATALOGUE,
    GAIA_DR3,
    HIP,
    PLANET_HOSTS,
    PLANETS,
    SIMBAD_OID,
    NodeList,
)
from space_map_data.extrasolar.tables import CROSS_ID

logger = logging.getLogger(__name__)

PLANETS_INPUT = pa.schema(
    [
        ("host", pa.int64()),
        ("number", pa.uint16()),
        ("designation", pa.string()),
        ("class", pa.string()),
        # Jupiter masses and days.
        ("mass", pa.float64()),
        ("period", pa.float64()),
        ("binary_type", pa.string()),
        ("star_ids", pa.list_(CROSS_ID)),
    ]
)
RELEASE = dict(PLANET_HOSTS)
# A planet's name often resolves to its host star in SIMBAD, so only an
# object that SIMBAD types as a brown dwarf counts as the planet's own star.
BROWN_DWARF_TYPES = frozenset({"BD*", "BD?"})
ARCSEC = "arcsec"


@dataclass
class _Element:
    """A binary or a star of OEC's hierarchy."""

    names: list[str]
    star: bool
    period: float | None = None
    separation: float | None = None
    children: list[_Element] = field(default_factory=list)


def _number(element: ET.Element, tag: str) -> float | None:
    text = element.findtext(tag)
    try:
        return float(text) if text else None
    except ValueError:
        return None


def _element(element: ET.Element) -> _Element:
    names = [n.text for n in element.findall("name") if n.text]
    separation = None
    for found in element.findall("separation"):
        if found.get("unit") == ARCSEC and found.text:
            try:
                separation = float(found.text)
            except ValueError:
                logger.debug("OEC: separation %r", found.text)
    node = _Element(
        names,
        element.tag == "star",
        _number(element, "period"),
        separation,
    )
    for child in element:
        if child.tag in ("star", "binary"):
            node.children.append(_element(child))
    return node


def read_oec_trees(path: Path = OEC_SYSTEMS) -> list[_Element]:
    """The top binary or star of each OEC system."""
    root = ET.fromstring(gzip.decompress(path.read_bytes()))
    trees = []
    for system in root.iter("system"):
        top = [_element(c) for c in system if c.tag in ("star", "binary")]
        if len(top) == 1:
            trees.append(top[0])
        elif top:
            names = [n.text for n in system.findall("name") if n.text]
            trees.append(_Element(names, False, None, None, top))
    return trees


def _stars(element: _Element) -> list[str]:
    if element.star:
        return element.names[:1]
    return [name for child in element.children for name in _stars(child)]


def _identity_ids(identity: Identity) -> list[tuple[str, str, str]]:
    ids = []
    if identity.oid:
        ids.append((*SIMBAD_OID, str(identity.oid)))
    if identity.gaia_dr3:
        ids.append((*GAIA_DR3, str(identity.gaia_dr3)))
    for catalogue, star in identity.members.items():
        ids.append((catalogue, RELEASE[catalogue], star.key))
    if identity.hip:
        ids.append((*HIP, str(identity.hip)))
    return ids


@dataclass
class _Writer:
    """Writes the nodes of one system."""

    out: NodeList
    stars: Stars
    key: str
    placed: set[int] = field(default_factory=set)

    def identity(self, index: int, parent: int, element: _Element | None) -> None:
        identity = self.stars.identities[index]
        self.placed.add(index)
        self.out.add(
            self.key,
            parent,
            identity.name,
            _identity_ids(identity),
            v_mag=identity.value("v_mag"),
            spectral_type=identity.first.spectral_type,
            mass=identity.value("mass"),
            separation=element.separation if element else None,
            period=element.period if element else None,
            known=[CATALOGUE],
        )

    def element(self, element: _Element, parent: int) -> None:
        if element.star:
            names = element.names
            at = self.stars.of.get((OEC, names[0])) if names else None
            if at is not None and at not in self.placed:
                self.identity(at, parent, element)
            return
        node = self.out.add(
            self.key,
            parent,
            element.names[0] if element.names else None,
            separation=element.separation,
            period=element.period,
            known=[CATALOGUE] if parent >= 0 else None,
        )
        for child in element.children:
            self.element(child, node)


def read_planet_systems(
    stars: Stars, systems: Systems, oec_trees: list[_Element]
) -> pa.Table:
    """The nodes of the systems of two or more star identities."""
    groups: dict[int, list[int]] = defaultdict(list)
    for identity in stars.identities:
        groups[systems.of[identity.index]].append(identity.index)
    tree_of: dict[int, _Element] = {}
    for tree in oec_trees:
        for name in _stars(tree):
            at = stars.of.get((OEC, name))
            if at is not None:
                tree_of.setdefault(systems.of[at], tree)
    out = NodeList(PLANETS)
    for system in sorted(groups):
        members = groups[system]
        if len(members) < 2:
            continue
        first = stars.identities[members[0]]
        name = first.first.system or first.name
        writer = _Writer(out, stars, f"{first.first.catalogue}:{name}")
        tree = tree_of.get(system)
        if tree is not None and not tree.star:
            root = len(out)
            writer.element(tree, -1)
        else:
            root = out.add(writer.key, -1, name, flat=True)
        for index in members:
            if index not in writer.placed:
                writer.identity(index, root, None)
    logger.info("planet catalogues: %d nodes", len(out))
    return out.table()


def planet_star_ids(
    hub: Simbad, names: Iterable[tuple[str, str]]
) -> list[tuple[str, str, str]]:
    """The star ids of a planet from its (catalogue, name) pairs."""
    found: list[tuple[str, str, str]] = []
    for catalogue, name in names:
        source, _, table = TABLES[catalogue]
        by = hub.resolved.get((source, table, "planet", name), {})
        for oid in sorted(by.get(provider_names.PRINTED, {})):
            if hub.otype.get(oid, "") not in BROWN_DWARF_TYPES:
                continue
            items = [(*SIMBAD_OID, oid)]
            if (dr3 := hub.gaia_dr3.get(oid)) is not None:
                items.append((*GAIA_DR3, str(dr3)))
            found += [item for item in items if item not in found]
    return found
