"""SIMBAD's well-known stars as an ingest source.

A Gaia DR3 source is one point. So each listed object with a Gaia DR3 id is
a row. A listed object without one is a row only when no listed object is
below it and no object with a Gaia id is above it. A system without a Gaia id
is not a row: its components are the points. A component below an object
with a Gaia id is inside that point when its light adds to that of the point.
A system gives its HIP and HD numbers and its designation to its brightest
component row, when that row has none of its own. A system that has other
HIP or HD numbers than that row is a catalogued star itself, and keeps its
designation. A row does not claim the number of a Hipparcos star that is far
from it.

A row with a Gaia DR3 id claims it. A row without one claims its HIP number.
A row claims its HD number only when no Hipparcos star has that number:
Hipparcos and SIMBAD put the HD numbers of a close pair on different stars. A
row with no link matches by position at J2016.0 and by an estimate of G, else
it is a new object.

SIMBAD_HIP is a second pass. Its rows are the rows with a Gaia DR3 id and a
HIP number, and they claim the HIP number. In the first pass that claim could
take the star of another row, which a claim of the same pass then cannot
link. Two objects that hold ids of one catalogue are never joined, so the
second pass joins a Gaia star only to a star with no Gaia id and no SIMBAD
row, such as an entry of Hipparcos 1997 with a rough position. A row does not
claim a HIP number whose Gaia best neighbour is another star, when the row has
a Gaia id or another row has that neighbour: that join never happens.

The name is the first of:
1. a Bayer designation with a Greek letter, a Flamsteed number, a Bayer
   designation with a Latin letter, a number in the catalogue of Wolf-Rayet
   stars, a GCVS name, in that order. A NAME can hold one
   ("NAME * iot UMa BC");
2. the designation that the system gives;
3. the HD number, else the HIP number, of the row, else of its system;
4. a SIMBAD NAME, the shortest of several. It is not an IAU name, so it comes
   after the designations;
5. a designation in a cluster, the shortest of several, where the main
   identifier is from a survey (SURVEYS);
6. SIMBAD's main identifier.
A name has no NAME prefix and no object-type prefix (V*, **, EM*, Cl*), as
on Wikipedia ("Westerlund 1 W 26", "HV 2700"). In some acronyms the type is
the whole acronym ("C* 2905", "GR* 20B"). Such an identifier keeps it. A row
with a Gaia DR3 id gives no name when only such a main identifier or one from
a survey is left. The Gaia row then names the star.

Licence: ODbL. Acknowledge "the SIMBAD database, CDS, Strasbourg Astronomical
Observatory, France" and cite Wenger et al. 2000, A&AS 143, 9.
"""

import csv
import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pyarrow as pa

from space_map_data.download.providers.stars import simbad_stars
from space_map_data.extrasolar import sky
from space_map_data.extrasolar.engine import Source
from space_map_data.extrasolar.exoplanets.simbad import CLASSES, PULSAR
from space_map_data.extrasolar.match import PositionMatcher
from space_map_data.extrasolar.sources.gaia import EPOCH as GAIA_EPOCH
from space_map_data.extrasolar.sources.hipparcos import (
    claim_lists,
    g_estimate,
    to_gaia_epoch,
)

logger = logging.getLogger(__name__)

# Most rows link by their Gaia DR3 id. The others are stars that Gaia did not
# measure or that SIMBAD gives no Gaia id. A star without an optical
# magnitude is most often one that Gaia cannot see, so a match needs the
# magnitudes to agree. A GCVS star is seen in the optical: without a
# magnitude it matches within NEAR_ARCSEC, where a chance neighbour is rare.
NEAR_ARCSEC = 0.3
MATCHER = PositionMatcher(
    n_sigma=5.0,
    near_sigma=0.0,
    near_arcsec=NEAR_ARCSEC,
    min_error=0.3,
    reach=0.1,
    max_mag_diff=1.0,
    mag_sigma=0.3,
)
# The match kind of a row with no optical magnitude and no GCVS name. It
# keeps the row from a Gaia star, whose kind is "star".
UNSEEN = "unseen star"
# The list is a selection of SIMBAD, so a claim of an unlisted oid names no
# other listed object.
SIMBAD = Source(
    name="simbad",
    catalogue="simbad",
    release="oid",
    home=1,
    matcher=MATCHER,
    kind="star",
    subset=True,
)
SIMBAD_HIP = Source(
    name="simbad-hip", catalogue="simbad", release="oid", home=1, kind="star"
)
GAIA_DR3, HIP, HD = ("gaia", "dr3"), ("hip", "2007"), ("hd", "1949")

EPOCH = 2000.0
# Arcsec, for a position without an error.
DEFAULT_ERROR = 1.0
# Levels of SIMBAD's hierarchy that the rows look through.
MAX_DEPTH = 5
# Arcsec from a Hipparcos star beyond which a row does not claim its number.
# A rough position of 1997 can be 2′ off, and it has no proper motion.
MAX_HIP_OFFSET = 300.0
# A component below a Gaia point with a magnitude less than this much fainter
# adds to the light of that point, so it is not a point of its own.
MAX_INSIDE_MAG = 3.0
# Arcsec. One Hipparcos entry holds the components of a pair closer than
# this, and a system hands its numbers only to a component this close.
HIP_PAIR_LIMIT = 10.0
# A designation that names a component of another object.
_COMPONENT = re.compile(r"(?P<base>.+?) (?P<letter>[A-H][a-z]?)")
_BAYER_INDEX = re.compile(
    r"(?P<head>\* [a-z]{2}[a-z.])(?P<index>\d\d)(?P<tail> [A-Z][A-Za-z]{2}.*)"
)
# The class of a SIMBAD type, where it says more than "star". Pulsars are
# left out because the Gaia source near a pulsar is its companion.
OTYPE_CLASSES = {otype: name for otype, name in CLASSES.items() if name != PULSAR}
# Table columns from the columns of basic.csv and fluxes.csv. An error is the
# major axis of SIMBAD's error ellipse.
FLOAT_COLUMNS = {
    "ra_error": "coo_err_maj",
    "dec_error": "coo_err_maj",
    "parallax": "plx_value",
    "parallax_error": "plx_err",
    "pmra_error": "pm_err_maj",
    "pmdec_error": "pm_err_maj",
    "simbad_b_mag": "B",
    "simbad_v_mag": "V",
    "simbad_g_mag": "G",
}

GREEK = {
    "alf": "Alpha",
    "bet": "Beta",
    "gam": "Gamma",
    "del": "Delta",
    "eps": "Epsilon",
    "zet": "Zeta",
    "eta": "Eta",
    "tet": "Theta",
    "iot": "Iota",
    "kap": "Kappa",
    "lam": "Lambda",
    "mu.": "Mu",
    "nu.": "Nu",
    "ksi": "Xi",
    "omi": "Omicron",
    "pi.": "Pi",
    "rho": "Rho",
    "sig": "Sigma",
    "tau": "Tau",
    "ups": "Upsilon",
    "phi": "Phi",
    "chi": "Chi",
    "psi": "Psi",
    "ome": "Omega",
}
# The IAU genitives, in ASCII as the XHIP designations spell them.
GENITIVE = {
    "And": "Andromedae",
    "Ant": "Antliae",
    "Aps": "Apodis",
    "Aqr": "Aquarii",
    "Aql": "Aquilae",
    "Ara": "Arae",
    "Ari": "Arietis",
    "Aur": "Aurigae",
    "Boo": "Bootis",
    "Cae": "Caeli",
    "Cam": "Camelopardalis",
    "Cnc": "Cancri",
    "CVn": "Canum Venaticorum",
    "CMa": "Canis Majoris",
    "CMi": "Canis Minoris",
    "Cap": "Capricorni",
    "Car": "Carinae",
    "Cas": "Cassiopeiae",
    "Cen": "Centauri",
    "Cep": "Cephei",
    "Cet": "Ceti",
    "Cha": "Chamaeleontis",
    "Cir": "Circini",
    "Col": "Columbae",
    "Com": "Comae Berenices",
    "CrA": "Coronae Australis",
    "CrB": "Coronae Borealis",
    "Crv": "Corvi",
    "Crt": "Crateris",
    "Cru": "Crucis",
    "Cyg": "Cygni",
    "Del": "Delphini",
    "Dor": "Doradus",
    "Dra": "Draconis",
    "Equ": "Equulei",
    "Eri": "Eridani",
    "For": "Fornacis",
    "Gem": "Geminorum",
    "Gru": "Gruis",
    "Her": "Herculis",
    "Hor": "Horologii",
    "Hya": "Hydrae",
    "Hyi": "Hydri",
    "Ind": "Indi",
    "Lac": "Lacertae",
    "Leo": "Leonis",
    "LMi": "Leonis Minoris",
    "Lep": "Leporis",
    "Lib": "Librae",
    "Lup": "Lupi",
    "Lyn": "Lyncis",
    "Lyr": "Lyrae",
    "Men": "Mensae",
    "Mic": "Microscopii",
    "Mon": "Monocerotis",
    "Mus": "Muscae",
    "Nor": "Normae",
    "Oct": "Octantis",
    "Oph": "Ophiuchi",
    "Ori": "Orionis",
    "Pav": "Pavonis",
    "Peg": "Pegasi",
    "Per": "Persei",
    "Phe": "Phoenicis",
    "Pic": "Pictoris",
    "Psc": "Piscium",
    "PsA": "Piscis Austrini",
    "Pup": "Puppis",
    "Pyx": "Pyxidis",
    "Ret": "Reticuli",
    "Sge": "Sagittae",
    "Sgr": "Sagittarii",
    "Sco": "Scorpii",
    "Scl": "Sculptoris",
    "Sct": "Scuti",
    "Ser": "Serpentis",
    "Sex": "Sextantis",
    "Tau": "Tauri",
    "Tel": "Telescopii",
    "Tri": "Trianguli",
    "TrA": "Trianguli Australis",
    "Tuc": "Tucanae",
    "UMa": "Ursae Majoris",
    "UMi": "Ursae Minoris",
    "Vel": "Velorum",
    "Vir": "Virginis",
    "Vol": "Volantis",
    "Vul": "Vulpeculae",
}

_CONSTELLATION = r"(?P<con>[A-Z][A-Za-z]{2})(?: (?P<part>[A-Z]{1,2}[a-z]?\d?))?"
_BAYER = re.compile(r"\* (?P<letter>[a-z]{2}[a-z.])(?P<index>\d\d)? " + _CONSTELLATION)
_FLAMSTEED = re.compile(r"\* (?P<number>\d+) " + _CONSTELLATION)
_LATIN = re.compile(r"\* (?P<letter>[A-Za-z])(?P<index>\d\d)? " + _CONSTELLATION)
_GCVS = re.compile(r"V\* (?P<star>[A-Z]{1,2}|V\d{3,5}) " + _CONSTELLATION)
_GCVS_GREEK = re.compile(
    r"V\* (?P<letter>[a-z]{2}[a-z.])(?P<index>\d\d)? " + _CONSTELLATION
)
_NUMBER = {
    kind: re.compile(rf"{prefix} (\d+)")
    for kind, prefix in (("gaia", "Gaia DR3"), ("hip", "HIP"), ("hd", "HD"))
}
_HD_NAME = re.compile(r"HD \d+[A-Z]{0,2}")
_HIP_NAME = re.compile(r"HIP \d+[A-Z]{0,2}")
_WR_NAME = re.compile(r"WR \d+[a-z]*")
_SIMBAD_NAME = "NAME "
_CLUSTER_MEMBER = "Cl* "
# The object-type prefix of a SIMBAD identifier, as "V* ", "** " or "EM* ".
_TYPE_PREFIX = re.compile(r"[A-Za-z0-9]*\*+ ")
# Main identifiers that a designation in a cluster replaces.
SURVEYS = (
    "2MASS ",
    "Gaia DR",
    "TYC ",
    "UCAC",
    "WISE",
    "AllWISE ",
    "IRAS ",
    "OGLE ",
    "ASAS ",
    "ATO ",
    "CXOU ",
)


def normal(identifier: str) -> str:
    """A SIMBAD identifier with single spaces: SIMBAD pads its numbers."""
    return " ".join(identifier.split())


def _index(match: re.Match) -> str:
    return str(int(match["index"])) if match["index"] else ""


def _greek(match: re.Match) -> str | None:
    letter = GREEK.get(match["letter"])
    return None if letter is None else letter + _index(match)


# Each kind of designation, best first, with the first word of its spelling.
_KINDS = (
    (_BAYER, _greek),
    (_FLAMSTEED, lambda match: match["number"]),
    (_LATIN, lambda match: match["letter"] + _index(match)),
    (_GCVS_GREEK, _greek),
    (_GCVS, lambda match: match["star"]),
)
# The rank in _KINDS of the first GCVS kind.
_GCVS_RANK = 3


def _spelling(text: str) -> tuple[int, str] | None:
    """The rank and spelling of a traditional designation, else None."""
    for rank, (pattern, first_of) in enumerate(_KINDS):
        match = pattern.fullmatch(text)
        first = match and first_of(match)
        genitive = match and GENITIVE.get(match["con"])
        if first and genitive:
            return rank, " ".join(p for p in (first, genitive, match["part"]) if p)
    return None


def designation(identifiers: list[str], most: int = len(_KINDS)) -> str | None:
    """The best traditional designation of a star, spelled as XHIP's are.

    A Greek Bayer letter wins over a Flamsteed number, a Flamsteed number over
    a Latin Bayer letter, and all of them over a GCVS name. `most` limits the
    kinds to the first ones.
    """
    found = [found for text in identifiers if (found := _spelling(normal(text)))]
    found = [item for item in found if item[0] < most]
    return min(found)[1] if found else None


def _shortest(texts: list[str]) -> str:
    return min(texts, key=lambda text: (len(text), text))


def _plain(text: str) -> str | None:
    """`text` without the NAME and object-type prefixes. None when the prefix
    is the whole catalogue acronym, as in "C* 2905" or "GR* 20B"."""
    text = text.removeprefix(_SIMBAD_NAME)
    if prefix := _TYPE_PREFIX.match(text):
        text = text[prefix.end() :]
        if not text[:1].isalpha():
            return None
    return text


def _designated(identifiers: list[str]) -> str | None:
    """A Bayer or Flamsteed designation, a WR number or a GCVS name, in that
    order. A SIMBAD NAME can hold a designation."""
    texts = [normal(text).removeprefix(_SIMBAD_NAME) for text in identifiers]
    if name := designation(texts, most=_GCVS_RANK):
        return name
    if found := sorted(text for text in texts if _WR_NAME.fullmatch(text)):
        return found[0]
    return designation(texts)


def _numbered(texts: list[str]) -> str | None:
    """An HD number, else a HIP number. A SIMBAD NAME can hold one."""
    texts = [text.removeprefix(_SIMBAD_NAME) for text in texts]
    for pattern in (_HD_NAME, _HIP_NAME):
        if found := sorted(text for text in texts if pattern.fullmatch(text)):
            return found[0]
    return None


def star_name(
    identifiers: list[str], main_id: str, given: dict[str, str] | None = None
) -> str | None:
    """The name of a row in the order of the module docstring, else None when
    the Gaia row names the star. `given` is what `SimbadList.handed` gives the
    row."""
    given = given or {}
    texts = [normal(identifier) for identifier in identifiers]
    numbers = [
        f"{kind.upper()} {given[kind]}" for kind in ("hd", "hip") if kind in given
    ]
    if name := (
        _designated(texts)
        or given.get("designation")
        or _numbered(texts)
        or _numbered(numbers)
    ):
        return name
    main = normal(main_id)
    names = [t for t in texts if t.startswith(_SIMBAD_NAME) and _plain(t)]
    members = [t for t in texts if t.startswith(_CLUSTER_MEMBER) and _plain(t)]
    if main.startswith(_SIMBAD_NAME) and (plain := _plain(main)):
        return plain
    if names:
        return _plain(_shortest(names))
    weak = main.startswith(SURVEYS) or _plain(main) is None
    if weak and members:
        return _plain(_shortest(members))
    gaia = {m[1] for t in texts if (m := _NUMBER["gaia"].fullmatch(t))}
    if weak and len(gaia) == 1:
        return None
    return _plain(main) or main.removeprefix(_SIMBAD_NAME)


@dataclass
class SimbadObject:
    oid: int
    main_id: str
    ra: float | None
    dec: float | None
    identifiers: list[str] = field(default_factory=list)
    gaia: str | None = None
    hip: str | None = None
    hd: str | None = None
    v: float | None = None
    row: dict = field(default_factory=dict)


def _float(text: str) -> float | None:
    return float(text) if text.strip() else None


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def _number(oid: int, kind: str, texts: list[str]) -> str | None:
    """The one plain number of a catalogue in `texts`, else None."""
    found = sorted({m[1] for t in texts if (m := _NUMBER[kind].fullmatch(t))})
    if len(found) > 1:
        logger.warning(
            "SIMBAD %d has the %s numbers %s; it uses none", oid, kind, found
        )
        return None
    return found[0] if found else None


@dataclass
class SimbadList:
    """The objects of the simbad_stars download and the links between them."""

    objects: dict[int, SimbadObject]
    children: dict[int, list[int]]
    iau: dict[str, int]
    parents: dict[int, list[int]] = field(init=False)
    # The components inside a Hipparcos point (`hold`), with the row that
    # holds their light. They are not rows.
    inside: dict[int, int] = field(init=False, default_factory=dict)

    @classmethod
    def read(cls, directory: Path = simbad_stars.OUT_DIR) -> SimbadList:
        objects: dict[int, SimbadObject] = {}
        for row in _rows(directory / simbad_stars.BASIC_FILE):
            oid = int(row["oid"])
            objects[oid] = SimbadObject(
                oid, row["main_id"], _float(row["ra"]), _float(row["dec"]), row=row
            )
        for row in _rows(directory / simbad_stars.IDENT_FILE):
            objects[int(row["oidref"])].identifiers.append(normal(row["id"]))
        for row in _rows(directory / simbad_stars.FLUXES_FILE):
            found = objects[int(row["oidref"])]
            found.row |= {"B": row["B"], "V": row["V"], "G": row["G"]}
            found.v = _float(row["V"])
        for oid, found in objects.items():
            found.gaia = _number(oid, "gaia", found.identifiers)
            found.hip = _number(oid, "hip", found.identifiers)
            found.hd = _number(oid, "hd", found.identifiers)
        children: dict[int, list[int]] = defaultdict(list)
        for row in _rows(directory / simbad_stars.LINKS_FILE):
            child, parent = int(row["child"]), int(row["parent"])
            if child != parent and child in objects and parent in objects:
                children[parent].append(child)
        iau = {
            row["name"]: int(row["oid"])
            for row in _rows(directory / simbad_stars.IAU_FILE)
            if row["oid"] and int(row["oid"]) in objects
        }
        return cls(objects, dict(children), iau)

    def __post_init__(self) -> None:
        self.children = {k: list(v) for k, v in self.children.items()}
        linked = {child for children in self.children.values() for child in children}
        by_main = {found.main_id: oid for oid, found in self.objects.items()}
        found: dict[int, list[tuple[int, bool]]] = defaultdict(list)
        for oid in sorted(self.objects):
            if oid in linked:
                continue
            for base, primary in _bases(self.objects[oid].main_id):
                parent = by_main.get(base)
                if parent is not None and parent != oid:
                    found[parent].append((oid, primary))
                    break
        # Without its primary listed, the object is the primary star itself:
        # "* alf CMa" is Sirius A beside "* alf CMa B".
        added = 0
        for parent, components in sorted(found.items()):
            if any(primary for _, primary in components):
                self.children.setdefault(parent, []).extend(c for c, _ in components)
                added += len(components)
        if added:
            logger.info("SIMBAD: %d components linked by their designation", added)
        self.parents = defaultdict(list)
        for parent, children in self.children.items():
            for child in children:
                self.parents[child].append(parent)

    def gaia_point(self, oid: int, depth: int = 0) -> int | None:
        """The nearest object above `oid` with a Gaia DR3 id."""
        if depth > MAX_DEPTH:
            return None
        for parent in sorted(self.parents.get(oid, [])):
            if self.objects[parent].gaia is not None:
                return parent
            if (found := self.gaia_point(parent, depth + 1)) is not None:
                return found
        return None

    def is_row(self, oid: int) -> bool:
        if self.objects[oid].gaia is not None:
            return True
        if oid in self.children or oid in self.inside:
            return False
        point = self.gaia_point(oid)
        return point is None or not self._inside(oid, point)

    def _inside(self, oid: int, point: int) -> bool:
        """Whether the light of a component adds to that of its Gaia point."""
        mag, point_mag = self._brightness(oid), self._brightness(point)
        return bool(np.isfinite(mag) and mag - point_mag < MAX_INSIDE_MAG)

    def primary(self, oid: int, depth: int = 0) -> int | None:
        """The row that stands for `oid`: itself, the point that holds it, or
        the brightest component of a system."""
        if self.is_row(oid):
            return oid
        if oid in self.inside:
            return self.inside[oid]
        if (point := self.gaia_point(oid)) is not None:
            return point
        if depth > MAX_DEPTH:
            return None
        rows = [
            found
            for child in self.children.get(oid, [])
            if (found := self.primary(child, depth + 1)) is not None
        ]
        if not rows:
            return None
        return min(rows, key=lambda r: (self._brightness(r), r))

    def rows_of(self, oid: int, depth: int = 0) -> list[int]:
        """The rows that stand for the components of `oid`."""
        if self.is_row(oid):
            return [oid]
        if oid in self.inside:
            return [self.inside[oid]]
        if (point := self.gaia_point(oid)) is not None:
            return [point]
        if depth > MAX_DEPTH:
            return []
        found = [
            row
            for child in self.children.get(oid, [])
            for row in self.rows_of(child, depth + 1)
        ]
        return sorted(set(found))

    def hold(self, hip_mags: dict[str, float]) -> None:
        """Find the components inside a Hipparcos point.

        `hip_mags` gives the G estimate of each Hipparcos star. A system with
        a HIP number and no Gaia DR3 id hands the number to its primary row.
        Each other component without a Gaia DR3 id or a HIP number is inside
        that point when it is within HIP_PAIR_LIMIT of the system and its
        light adds to the star's.
        """
        inside: dict[int, int] = {}
        for oid in sorted(self.children):
            system = self.objects[oid]
            mag = hip_mags.get(system.hip or "")
            if system.gaia is not None or mag is None:
                continue
            primary = self.primary(oid)
            if primary is None:
                continue
            for row in self.rows_of(oid):
                found = self.objects[row]
                if row == primary or found.gaia or found.hip:
                    continue
                apart = _apart(system, found)
                if (
                    apart is not None
                    and apart <= HIP_PAIR_LIMIT
                    and self._brightness(row) - mag < MAX_INSIDE_MAG
                ):
                    inside[row] = primary
        self.inside = inside
        logger.info("SIMBAD: %d components inside a Hipparcos point", len(inside))

    def _brightness(self, oid: int) -> float:
        """G, else V, else infinity."""
        found = self.objects[oid]
        for value in (_float(found.row.get("G", "")), found.v):
            if value is not None:
                return value
        return np.inf

    def handed(self) -> dict[int, dict[str, str]]:
        """The HIP and HD numbers and the designation (spelled out) that
        systems give to their primary row, when the row has none of its own."""
        given: dict[int, dict[str, str]] = defaultdict(dict)
        for oid in sorted(self.objects):
            if self.is_row(oid) or oid not in self.children:
                continue
            system = self.objects[oid]
            primary = self.primary(oid)
            if primary is None:
                continue
            target = self.objects[primary]
            # A component far from the system is not the star of its numbers.
            apart = _apart(system, target)
            if apart is not None and apart > HIP_PAIR_LIMIT:
                continue
            for kind in ("hip", "hd"):
                number = getattr(system, kind)
                if number and not getattr(target, kind) and kind not in given[primary]:
                    given[primary][kind] = number
            # A system with a HIP or HD number of its own, where its primary
            # has another, is itself a catalogued star ("* a Lup" is HIP 71500,
            # its component HIP 71502), so the designation is that star's.
            apart = any(
                (number := getattr(system, kind))
                and getattr(target, kind) not in (None, number)
                for kind in ("hip", "hd")
            )
            # A system of several points keeps its designation: it names
            # the system node.
            name = _designated(system.identifiers)
            if (
                name
                and not apart
                and len(self.rows_of(oid)) == 1
                and not _designated(target.identifiers)
                and "designation" not in given[primary]
            ):
                given[primary]["designation"] = name
        return dict(given)


def _apart(first: SimbadObject, second: SimbadObject) -> float | None:
    """Arcsec between two objects at J2000, None when one has no position."""
    if None in (first.ra, first.dec, second.ra, second.dec):
        return None
    assert first.ra is not None and first.dec is not None
    assert second.ra is not None and second.dec is not None
    return float(sky.separation(first.ra, first.dec, second.ra, second.dec))


def _bases(main_id: str) -> list[tuple[str, bool]]:
    """The main identifiers of the systems that a designation names it a
    component of, and whether it is their primary: "* alf Gem Aa" of
    "* alf Gem A", then of "* alf Gem"; "* alf01 Cru" of "* alf Cru"."""
    if found := _COMPONENT.fullmatch(main_id):
        base, letter = found["base"], found["letter"]
        primary = letter[0] == "A"
        if len(letter) > 1:
            return [(f"{base} {letter[0]}", letter[1] == "a"), (base, primary)]
        return [(base, primary)]
    if found := _BAYER_INDEX.fullmatch(main_id):
        return [(found["head"] + found["tail"], found["index"] == "01")]
    return []


def _floats(values: list[str | None]) -> np.ndarray:
    return np.array(
        [np.nan if v is None or not str(v).strip() else float(v) for v in values],
        np.float64,
    )


def engine_rows(
    stars: SimbadList,
    hipparcos_hd: set[str],
    best: dict[str, str],
    hip_positions: dict[str, tuple[float, float]],
) -> tuple[pa.Table, pa.Table]:
    """The pass rows of SIMBAD and of SIMBAD_HIP.

    `hipparcos_hd` are the HD numbers of the Hipparcos stars. `best` gives the
    Gaia DR3 best neighbour of a HIP number, and `hip_positions` the position
    of a Hipparcos star as its pass rows have it.
    """
    handed = stars.handed()
    picked = [
        found
        for oid, found in sorted(stars.objects.items())
        if stars.is_row(oid) and found.ra is not None and found.dec is not None
    ]
    systems = sum(1 for oid in stars.children if not stars.is_row(oid))
    inside = sum(
        1
        for oid in stars.objects
        if oid not in stars.children and not stars.is_row(oid)
    )
    logger.info(
        "SIMBAD: %d objects, %d rows, %d systems, %d components inside a Gaia or"
        " Hipparcos point, %d rows take numbers of a system",
        len(stars.objects),
        len(picked),
        systems,
        inside,
        len(handed),
    )

    def column(name: str) -> np.ndarray:
        return _floats([found.row.get(name) for found in picked])

    ra, dec = column("ra"), column("dec")
    pmra, pmdec = column("pmra"), column("pmdec")
    ra_now, dec_now = to_gaia_epoch(ra, dec, pmra, pmdec, EPOCH)

    named_gaia = {found.gaia for found in picked if found.gaia}
    claims, hip_claims, names = [], [], []
    dropped = Counter()
    for at, found in enumerate(picked):
        given = handed.get(found.oid, {})
        hip = found.hip or given.get("hip")
        hd = found.hd or given.get("hd")
        row_claims = []
        if found.gaia:
            row_claims.append((*GAIA_DR3, found.gaia))
        neighbour = best.get(hip or "")
        if (
            hip
            and neighbour not in (None, found.gaia)
            and (found.gaia or neighbour in named_gaia)
        ):
            dropped["best neighbour"] += 1
            hip = None
        if hip and hip in hip_positions:
            apart = sky.separation(ra_now[at], dec_now[at], *hip_positions[hip])
            if apart > MAX_HIP_OFFSET:
                logger.info(
                    "SIMBAD %d is %.0f″ from HIP %s: no claim", found.oid, apart, hip
                )
                dropped["position"] += 1
                hip = None
        hip_claims.append([(*HIP, hip)] if hip and found.gaia else [])
        if hip and not found.gaia:
            row_claims.append((*HIP, hip))
        if hd and hd not in hipparcos_hd:
            row_claims.append((*HD, hd))
        claims.append(row_claims)
        names.append(star_name(found.identifiers, found.main_id, given))
    logger.info("SIMBAD: HIP claims left out: %s", dict(dropped))
    # mas at J2000, grown by the proper-motion error over the epochs.
    years = GAIA_EPOCH - EPOCH
    error = np.hypot(column("coo_err_maj"), years * np.nan_to_num(column("pm_err_maj")))
    error = np.where(np.isfinite(error), error / 1000, DEFAULT_ERROR)
    mag = column("G")
    estimate = g_estimate(
        column("V"), column("B") - column("V"), np.full(ra.size, np.nan)
    )
    mag = np.where(np.isfinite(mag), mag, estimate)
    variable = [
        any(text.startswith("V* ") for text in found.identifiers) for found in picked
    ]
    kind = np.where(np.isfinite(mag) | np.array(variable, bool), "star", UNSEEN)

    n = len(picked)
    rows = pa.table(
        {
            "catalogue_id": pa.array([str(found.oid) for found in picked], pa.string()),
            "mint": pa.array(np.ones(n, bool)),
            "match_ra": pa.array(ra_now),
            "match_dec": pa.array(dec_now),
            "match_pmra": pa.array(pmra, pa.float32(), from_pandas=True),
            "match_pmdec": pa.array(pmdec, pa.float32(), from_pandas=True),
            "match_mag": pa.array(mag, pa.float32(), from_pandas=True),
            "match_error": pa.array(error, pa.float32()),
            "match_kind": pa.array(kind, pa.string()),
            "claims": claim_lists(claims),
            "ra": pa.array(ra),
            "dec": pa.array(dec),
            "pmra": pa.array(pmra, pa.float32(), from_pandas=True),
            "pmdec": pa.array(pmdec, pa.float32(), from_pandas=True),
            "epoch": pa.array(np.full(n, EPOCH, np.float32)),
            **{
                name: pa.array(column(source), pa.float32(), from_pandas=True)
                for name, source in FLOAT_COLUMNS.items()
            },
            "simbad_sp_type": pa.array(
                [found.row.get("sp_type") or None for found in picked], pa.string()
            ),
            "simbad_otype": pa.array(
                [found.row["otype"] for found in picked], pa.string()
            ),
            "name": pa.array(names, pa.string()),
            "class": pa.array(
                [OTYPE_CLASSES.get(found.row["otype"], "star") for found in picked],
                pa.string(),
            ),
        }
    )
    second = pa.array([bool(found) for found in hip_claims])
    hip_rows = rows.select(["catalogue_id", "mint", "match_ra", "match_dec"])
    hip_rows = hip_rows.append_column("claims", claim_lists(hip_claims)).filter(second)
    return rows, hip_rows


def disputed_hip(stars: SimbadList, best: dict[str, str]) -> frozenset[int]:
    """The HIP numbers whose Gaia best neighbour SIMBAD gives to another star.

    The row that takes a HIP number is the row with that number, or the row
    that its system hands it to. A number is disputed when that row has
    another Gaia DR3 id, or when SIMBAD gives the best neighbour to another
    listed object. A number that no row takes keeps its best neighbour.
    Where they disagree, the source of SIMBAD has the magnitude of the
    Hipparcos star in most cases. A system's best neighbour is often its
    fainter component, and the primary's light would then take the
    companion's Gaia id, name and SIMBAD row. So such a Hipparcos star goes
    by position and magnitude.
    """
    handed = stars.handed()
    holder = {found.gaia: oid for oid, found in stars.objects.items() if found.gaia}
    taker: dict[str, int] = {}
    for oid in sorted(stars.objects):
        found = stars.objects[oid]
        hip = found.hip or handed.get(oid, {}).get("hip")
        if hip and stars.is_row(oid):
            taker.setdefault(hip, oid)
    disputed = set()
    companions = 0
    for hip, source in best.items():
        row = taker.get(hip)
        own = stars.objects[row].gaia if row is not None else None
        if own is not None and source != own:
            disputed.add(int(hip))
        elif row is not None and source in holder and holder[source] != row:
            disputed.add(int(hip))
            companions += 1
    logger.info(
        "SIMBAD: %d HIP numbers lose their best neighbour, %d of them to the"
        " SIMBAD star that has it",
        len(disputed),
        companions,
    )
    return frozenset(disputed)


def handed_neighbours(stars: SimbadList, best: dict[str, str]) -> dict[int, int]:
    """The Gaia DR3 source of each HIP number that has no best neighbour and
    that a system hands to its primary row with a Gaia DR3 id.

    The Hipparcos star of a system is the primary's light. With no best
    neighbour it would go by position, and a companion's Gaia source can be
    the nearer one.
    """
    handed = stars.handed()
    paired = set(best.values())
    found: dict[int, int] = {}
    for oid in sorted(handed):
        hip, gaia = handed[oid].get("hip"), stars.objects[oid].gaia
        if hip and gaia and hip not in best and gaia not in paired:
            found.setdefault(int(hip), int(gaia))
    logger.info("SIMBAD: %d HIP numbers take the Gaia id of their primary", len(found))
    return found


class IauRow(NamedTuple):
    """The SIMBAD row of an IAU name's object.

    `own` is true when the object is a point of its own. `hip` is the HIP
    number of the row, its own or that of its system.
    """

    oid: str
    ra: float
    dec: float
    own: bool
    hip: str | None
    gaia: str | None = None


def iau_rows(stars: SimbadList, rows: pa.Table) -> dict[str, IauRow]:
    """The row of each IAU name's object, with its position at J2016.0."""
    at = {oid: i for i, oid in enumerate(rows["catalogue_id"].to_pylist())}
    ra, dec = rows["match_ra"].to_pylist(), rows["match_dec"].to_pylist()
    handed = stars.handed()
    found = {}
    for name, oid in sorted(stars.iau.items()):
        primary = stars.primary(oid)
        if primary is None or str(primary) not in at:
            logger.info("%s: SIMBAD %d stands for no row", name, oid)
            continue
        i = at[str(primary)]
        row = stars.objects[primary]
        hip = row.hip or handed.get(primary, {}).get("hip")
        found[name] = IauRow(str(primary), ra[i], dec[i], primary == oid, hip, row.gaia)
    return found
