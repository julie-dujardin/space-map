"""SIMBAD's hierarchy as a tree source, and SIMBAD as a hub of identifiers.

A tree is the objects that `h_link.csv` links, from an object with no
listed parent down. An object with two parents stays under the first by oid.
The brightest child of a node is its primary: the separations of the other
children are from it, at J2000.

`SimbadIndex` gives the SIMBAD objects that carry a catalogue id. Another
source reaches a component through it: SIMBAD lists the components of close
pairs as their own objects, where Hipparcos has one entry for both.
"""

import logging
import re
from collections import defaultdict
from dataclasses import dataclass

import numpy as np
import pyarrow as pa

from space_map_data.extrasolar.sky import separation
from space_map_data.extrasolar.sources.simbad import SimbadList, normal
from space_map_data.extrasolar.systems.nodes import (
    CATALOGUE,
    GAIA_DR3,
    GCVS,
    HD,
    HIP,
    HR,
    SIMBAD,
    SIMBAD_OID,
    NodeList,
)

logger = logging.getLogger(__name__)

_HR = re.compile(r"HR (\d+)")
_GCVS = re.compile(r"V\* [A-Za-z0-9]+ [A-Z][a-z]{2}")
# A component letter at the end of a main identifier: "* alf Cen A", "Aa".
LETTER = re.compile(r"\s(?P<letter>[A-Z][a-z]?\d?)$")
EPOCH = 2000.0


def letter(main_id: str) -> str | None:
    found = LETTER.search(main_id)
    return found[1] if found else None


@dataclass
class SimbadIndex:
    """The SIMBAD objects of each catalogue id, and which of them are rows."""

    stars: SimbadList
    by_id: dict[tuple[str, str, str], list[int]]

    @classmethod
    def build(cls, stars: SimbadList) -> SimbadIndex:
        by_id: dict[tuple[str, str, str], list[int]] = defaultdict(list)
        for oid in sorted(stars.objects):
            found = stars.objects[oid]
            for kind, value in (
                (GAIA_DR3, found.gaia),
                (HIP, found.hip),
                (HD, found.hd),
            ):
                if value:
                    by_id[(*kind, value)].append(oid)
            for text in set(found.identifiers):
                if hr := _HR.fullmatch(text):
                    by_id[(*HR, hr[1])].append(oid)
                elif _GCVS.fullmatch(text):
                    by_id[(*GCVS, text)].append(oid)
        return cls(stars, dict(by_id))

    @classmethod
    def empty(cls) -> SimbadIndex:
        return cls(SimbadList({}, {}, {}), {})

    def components(self, catalogue: str, release: str, value: str) -> list[int]:
        """The rows with no listed children that carry this id."""
        return [
            oid
            for oid in self.by_id.get((catalogue, release, value), [])
            if oid not in self.stars.children and self.stars.is_row(oid)
        ]


def read_simbad(stars: SimbadList) -> pa.Table:
    """The nodes of SIMBAD's trees."""
    parent_of = {}
    several = 0
    for child, parents in stars.parents.items():
        parent_of[child] = min(parents)
        several += len(parents) > 1
    roots = sorted(oid for oid in stars.children if oid not in parent_of)
    out = NodeList(SIMBAD)
    seen: set[int] = set()

    def brightness(oid: int) -> float:
        found = stars.objects[oid]
        for value in (_float(found.row.get("G")), found.v):
            if value is not None:
                return value
        return np.inf

    def add(oid: int, parent: int, system: str, primary: int | None) -> None:
        if oid in seen:
            return
        seen.add(oid)
        found = stars.objects[oid]
        row = found.row
        apart = None
        if primary is not None and primary != oid:
            other = stars.objects[primary]
            ra, dec, ra2, dec2 = found.ra, found.dec, other.ra, other.dec
            if (
                ra is not None
                and dec is not None
                and ra2 is not None
                and dec2 is not None
            ):
                apart = float(separation(ra, dec, ra2, dec2))
        ids = [(*SIMBAD_OID, str(oid))]
        for kind, value in ((GAIA_DR3, found.gaia), (HIP, found.hip), (HD, found.hd)):
            if value:
                ids.append((*kind, value))
        node = out.add(
            system,
            parent,
            normal(found.main_id),
            ids,
            ra=found.ra,
            dec=found.dec,
            epoch=EPOCH,
            pmra=_float(row.get("pmra")),
            pmdec=_float(row.get("pmdec")),
            parallax=_float(row.get("plx_value")),
            v_mag=found.v,
            g_mag=_float(row.get("G")),
            spectral_type=row.get("sp_type") or None,
            separation=apart,
            known=[CATALOGUE] if parent >= 0 else None,
        )
        kids = [c for c in stars.children.get(oid, []) if parent_of.get(c) == oid]
        kids = sorted(set(kids), key=lambda c: (brightness(c), c))
        for child in kids:
            add(child, node, system, kids[0])

    for root in roots:
        add(root, -1, str(root), None)
    logger.info(
        "SIMBAD trees: %d roots, %d nodes, %d objects with several parents",
        len(roots),
        len(out),
        several,
    )
    return out.table()


def _float(text: str | None) -> float | None:
    return float(text) if text and text.strip() else None
