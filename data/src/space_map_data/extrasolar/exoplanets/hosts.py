"""Host stars: one identity per star across the catalogues, and their systems.

A star of one catalogue joins the same star of another catalogue by its Gaia
DR3 id, then its HIP number, then its SIMBAD object, then its name, and two
stars that have neither a Gaia DR3 id nor a HIP number by a position within
3″ (microlensing events and pulsars go by several names). Names compare
without the lens letter of a microlensing event (`KMT-2021-BLG-0240L`). The
Gaia DR3 id is SIMBAD's, else the catalogue's own, else the DR3 source
nearest to its Gaia DR2 id. SIMBAD comes first because a catalogue can match
an old position of a fast star to a background source.

A join is refused when it would put in one identity two Gaia DR3 ids, two HIP
numbers, or two stars of one catalogue with other component letters: `HD 1 A`
and `HD 1 B` can share an unresolved HIP number or Gaia DR3 id. A join by
position is also refused for two stars of one catalogue, or with other
component letters (OEC puts every star of a system at one position). Two names of one catalogue that share an id are one star that the
catalogue lists twice: the first stays its member, and the planets of the
other name go to the same identity.

A system is the stars that the archive or OEC puts in one system. Its key
star, the host in the URL of its planets, is the first star with planets in
OEC's order, else the star without a component letter or with `A`, else the
first by name.

Each catalogue gives one engine row per identity that hosts a planet. Every
row of an identity claims the same id: its Gaia DR3 id, else its HIP number,
else the row of the first catalogue. The first catalogue's row of an identity
without either id matches by position, or mints a literature star.
"""

import csv
import logging
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyarrow as pa

from space_map_data.download.providers.exoplanets import gaia as gaia_provider
from space_map_data.download.providers.exoplanets import names as provider_names
from space_map_data.extrasolar.exoplanets.catalogues import (
    CATALOGUES,
    GREEK,
    LENS,
    OEC,
    Catalogue,
    Star,
    reduced,
)
from space_map_data.extrasolar.exoplanets.simbad import Simbad
from space_map_data.extrasolar.exoplanets.sources import BY_NAME
from space_map_data.extrasolar.sky import separation
from space_map_data.extrasolar.sources.gaia import EPOCH as GAIA_EPOCH
from space_map_data.extrasolar.sources.hipparcos import propagate
from space_map_data.extrasolar.tables import CROSS_ID

logger = logging.getLogger(__name__)

NEIGHBOURHOOD = gaia_provider.OUT_DIR / "dr2_neighbourhood.csv"
GAIA_DR3 = ("gaia", "dr3")
HIP = ("hip", "2007")
# The kind of a row that may match by position, and of one that never does.
STAR_KIND = "star"
UNMATCHED_KIND = "planet host"
# Arcsec of a catalogue position after its proper motion.
POSITION_ERROR = 1.0
NAME_JOIN = "a name"
POSITION_JOIN = "a position"
TWIN_JOIN = "a registry twin"
# Arcsec between two stars without ids that are one star.
POSITION_RADIUS = 3.0
_COMPONENT = re.compile(r"\s*(?:\(?([A-D])\)?|([A-D])[a-z]?)$")


def read_neighbours(path: Path = NEIGHBOURHOOD) -> dict[int, int]:
    """The nearest DR3 source of each Gaia DR2 id."""
    best: dict[int, tuple[float, float, int]] = {}
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            dr2, dr3 = int(row["dr2_source_id"]), int(row["dr3_source_id"])
            rank = (
                float(row["angular_distance"] or "inf"),
                abs(float(row["magnitude_difference"] or "inf")),
                dr3,
            )
            if dr2 not in best or rank < best[dr2]:
                best[dr2] = rank
    return {dr2: rank[2] for dr2, rank in best.items()}


@dataclass
class Identity:
    """One star, with its row in each catalogue that lists it."""

    index: int
    members: dict[str, Star] = field(default_factory=dict)
    gaia_dr3: int | None = None
    hip: int | None = None
    oid: str | None = None
    # The DR3 id came from a catalogue, not from SIMBAD or DR2.
    gaia_from_catalogue: bool = False

    @property
    def first(self) -> Star:
        return next(self.members[c] for c in CATALOGUES if c in self.members)

    @property
    def name(self) -> str:
        return self.first.name

    def value(self, name: str) -> float | None:
        for catalogue in CATALOGUES:
            star = self.members.get(catalogue)
            if star is not None and name in star.values:
                return star.values[name].value
        return None


@dataclass
class Stars:
    """The identities of the stars of all catalogues."""

    identities: list[Identity]
    # (catalogue, star key) → identity index.
    of: dict[tuple[str, str], int]
    refused: list[str]
    # Ids that several identities held, and who keeps each.
    dropped_ids: list[str]
    # Stars that one catalogue lists under a second name.
    duplicates: list[str] = field(default_factory=list)
    # Catalogue Gaia DR3 ids that SIMBAD's id of the star replaces.
    overruled: list[str] = field(default_factory=list)

    def identity(self, catalogue: str, key: str | None) -> Identity | None:
        if key is None:
            return None
        at = self.of.get((catalogue, key))
        return None if at is None else self.identities[at]


@dataclass
class _Group:
    # Catalogue → the component letter of its first star in the group.
    catalogues: dict[str, str]
    gaia: set[int]
    hip: set[int]


def component_letter(name: str) -> str:
    """The component letter at the end of a star name.

    "" stands for the primary: no letter, `A`, or the lens `L`.
    """
    stripped = provider_names.without_component(name)
    letter = "" if stripped is None else name[len(stripped) :]
    letter = letter.removeprefix("L").strip(" ()")
    return "" if letter == "A" else letter


def build_stars(
    catalogues: list[Catalogue],
    simbad: Simbad,
    neighbours: dict[int, int],
    joins: Iterable[tuple[tuple[str, str], tuple[str, str]]] = (),
) -> Stars:
    """Join the stars of the catalogues into identities.

    `joins` holds pairs of (catalogue, star key) that are one star by their
    registry twin.
    """
    entries: list[tuple[str, Star, str | None, int | None, int | None, bool]] = []
    overruled: list[str] = []
    for catalogue in catalogues:
        for star in catalogue.stars.values():
            oid = simbad.star(catalogue.name, star.name)
            dr3 = star.gaia_dr3
            from_catalogue = dr3 is not None
            by_simbad = simbad.gaia_dr3.get(oid) if oid is not None else None
            if by_simbad is not None and by_simbad != dr3:
                if dr3 is not None:
                    overruled.append(
                        f"{star.name} ({catalogue.name}): Gaia DR3 {dr3},"
                        f" SIMBAD {oid} gives {by_simbad}"
                    )
                dr3, from_catalogue = by_simbad, False
            if dr3 is None:
                dr2 = star.gaia_dr2 or (simbad.gaia_dr2.get(oid) if oid else None)
                dr3 = neighbours.get(dr2) if dr2 else None
            hip = star.hip or (simbad.hip.get(oid) if oid else None)
            entries.append((catalogue.name, star, oid, dr3, hip, from_catalogue))

    parent = list(range(len(entries)))
    groups = [
        _Group(
            {e[0]: component_letter(e[1].name)},
            {e[3]} if e[3] else set(),
            {e[4]} if e[4] else set(),
        )
        for e in entries
    ]
    refused: list[str] = []

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int, why: str) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        ga, gb = groups[ra], groups[rb]
        shared = ga.catalogues.keys() & gb.catalogues.keys()
        reason = None
        # A pair and its primary are one source for a position.
        letters = {
            "" if letter == "AB" else letter
            for letter in (*ga.catalogues.values(), *gb.catalogues.values())
        }
        if shared and why == POSITION_JOIN:
            reason = "one catalogue lists both"
        elif why == POSITION_JOIN and len(letters) > 1:
            reason = "other component letters"
        elif any(ga.catalogues[c] != gb.catalogues[c] for c in shared):
            reason = "one catalogue lists both as components"
        elif ga.gaia and gb.gaia and ga.gaia != gb.gaia:
            reason = "two Gaia DR3 ids"
        elif ga.hip and gb.hip and ga.hip != gb.hip:
            reason = "two HIP numbers"
        if reason is not None:
            refused.append(
                f"{entries[a][1].name} ({entries[a][0]}) and {entries[b][1].name}"
                f" ({entries[b][0]}) share {why}, not joined: {reason}"
            )
            return
        parent[rb] = ra
        groups[ra] = _Group(
            gb.catalogues | ga.catalogues, ga.gaia | gb.gaia, ga.hip | gb.hip
        )

    order = sorted(
        range(len(entries)),
        key=lambda i: (CATALOGUES.index(entries[i][0]), entries[i][1].key),
    )
    for why, key_of in (
        ("a Gaia DR3 id", lambda e: e[3]),
        ("a HIP number", lambda e: e[4]),
        ("a SIMBAD object", lambda e: e[2]),
        (NAME_JOIN, lambda e: reduced(LENS.sub(r"\1", e[1].name))),
    ):
        buckets: dict[object, list[int]] = defaultdict(list)
        for i in order:
            key = key_of(entries[i])
            if key:
                buckets[key].append(i)
        for members in buckets.values():
            for other in members[1:]:
                union(members[0], other, why)

    def without_ids(i: int) -> bool:
        group = groups[find(i)]
        return not group.gaia and not group.hip

    for a, b in _close_pairs([entries[i][1] for i in order]):
        a, b = order[a], order[b]
        if without_ids(a) and without_ids(b):
            union(a, b, POSITION_JOIN)

    entry_of = {(e[0], e[1].key): i for i, e in enumerate(entries)}
    for a, b in joins:
        union(entry_of[a], entry_of[b], TWIN_JOIN)

    identities: list[Identity] = []
    of: dict[tuple[str, str], int] = {}
    roots: dict[int, int] = {}
    duplicates = []
    for i in order:
        root = find(i)
        if root not in roots:
            roots[root] = len(identities)
            identities.append(Identity(len(identities)))
        identity = identities[roots[root]]
        catalogue, star, oid, dr3, hip, from_catalogue = entries[i]
        of[(catalogue, star.key)] = identity.index
        if catalogue in identity.members:
            duplicates.append(
                f"{catalogue}: {star.name} is {identity.members[catalogue].name}"
            )
            continue
        identity.members[catalogue] = star
        if dr3 and (identity.gaia_dr3 is None or from_catalogue):
            identity.gaia_dr3 = dr3
            identity.gaia_from_catalogue |= from_catalogue
        identity.hip = identity.hip or hip
        identity.oid = identity.oid or oid
    dropped = _drop_shared_ids(identities)
    for text in overruled:
        logger.warning("catalogue Gaia DR3 id replaced by SIMBAD's: %s", text)
    logger.info(
        "%d stars in %d identities, %d joins refused, %d second names",
        len(entries),
        len(identities),
        len(refused),
        len(duplicates),
    )
    return Stars(identities, of, refused, dropped, duplicates, overruled)


def _close_pairs(stars: list[Star]) -> list[tuple[int, int]]:
    """Pairs of stars within POSITION_RADIUS, as indexes into `stars`."""
    at = [i for i, s in enumerate(stars) if s.ra is not None and s.dec is not None]
    dec = np.array([stars[i].dec for i in at], np.float64)
    ra = np.array([stars[i].ra for i in at], np.float64)
    order = np.argsort(dec)
    sorted_dec = dec[order]
    reach = POSITION_RADIUS / 3600
    pairs = []
    for k, i in enumerate(order):
        end = np.searchsorted(sorted_dec, dec[i] + reach, side="right")
        others = order[k + 1 : end]
        if not others.size:
            continue
        apart = separation(ra[i], dec[i], ra[others], dec[others])
        pairs += [(at[i], at[j]) for j in others[apart <= POSITION_RADIUS]]
    return sorted(pairs)


def _drop_shared_ids(identities: list[Identity]) -> list[str]:
    """Clear a Gaia DR3 id or HIP number that several identities hold.

    A DR3 id stays with the one primary star among them (no component letter
    or `A`: Gaia sees an unresolved pair as its primary), else with the one
    identity whose catalogue gives it.
    """
    dropped = []
    holders: dict[int, list[Identity]] = defaultdict(list)
    for identity in identities:
        if identity.gaia_dr3:
            holders[identity.gaia_dr3].append(identity)
    for dr3, found in holders.items():
        if len(found) < 2:
            continue
        primary = [i for i in found if component_letter(i.name) == ""]
        keeper = primary or [i for i in found if i.gaia_from_catalogue]
        if len(primary) > 1:
            keeper = [i for i in primary if i.gaia_from_catalogue]
        kept = keeper[0] if len(keeper) == 1 else None
        for identity in found:
            if identity is not kept:
                identity.gaia_dr3 = None
        dropped.append(
            f"Gaia DR3 {dr3} on {', '.join(i.name for i in found)}:"
            f" kept by {kept.name if kept else 'none'}"
        )
    holders = defaultdict(list)
    for identity in identities:
        if identity.hip:
            holders[identity.hip].append(identity)
    for hip, found in holders.items():
        if len(found) > 1:
            for identity in found:
                identity.hip = None
            dropped.append(
                f"HIP {hip} on {', '.join(i.name for i in found)}: kept by none"
            )
    for text in dropped:
        logger.warning("id on several stars: %s", text)
    return dropped


@dataclass
class Systems:
    # Identity index → system index.
    of: list[int]
    # System index → key identity index, for systems with planets.
    key: dict[int, int] = field(default_factory=dict)

    def choose_keys(self, stars: Stars, hosts: set[int]) -> None:
        """Pick the key of each system among `hosts`, the stars with planets."""
        candidates: dict[int, list[int]] = defaultdict(list)
        for index in sorted(hosts):
            candidates[self.of[index]].append(index)
        self.key = {
            system: min(members, key=lambda index: key_rank(stars, index))
            for system, members in candidates.items()
        }


def key_rank(stars: Stars, index: int) -> tuple:
    """The rank of a host as the key of its system, lowest first: the first
    star in OEC's hierarchy, else the star without a component letter or
    with `A`."""
    identity = stars.identities[index]
    oec = identity.members.get(OEC)
    return (
        oec is None,
        oec.order if oec is not None else 0,
        component_rank(identity.name),
        identity.name,
    )


def component_rank(name: str) -> int:
    """0 for no component letter or `A`, 1 for another letter."""
    found = _COMPONENT.search(name)
    letter = (found[1] or found[2]) if found else None
    return 0 if letter in (None, "A") else 1


def group_systems(stars: Stars, links: Iterable[tuple[int, int]] = ()) -> Systems:
    """Group the identities that the archive or OEC put in one system, and
    the pairs of identities in `links`."""
    parent = list(range(len(stars.identities)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    by_system: dict[tuple[str, str], list[int]] = defaultdict(list)
    for identity in stars.identities:
        for catalogue, star in identity.members.items():
            if star.system:
                by_system[(catalogue, star.system)].append(identity.index)
    for members in by_system.values():
        for other in members[1:]:
            parent[find(other)] = find(members[0])
    for a, b in links:
        parent[find(b)] = find(a)
    return Systems([find(i) for i in range(len(stars.identities))])


# Engine rows


def reference_position(identity: Identity) -> tuple[float, float] | None:
    """The J2016.0 position of the first member with one."""
    for catalogue in CATALOGUES:
        star = identity.members.get(catalogue)
        if star is None or star.ra is None or star.dec is None:
            continue
        pmra, pmdec = star.values.get("pmra"), star.values.get("pmdec")
        if pmra is None or pmdec is None or star.epoch is None:
            return star.ra, star.dec
        ra, dec = propagate(
            np.array([star.ra]),
            np.array([star.dec]),
            np.array([pmra.value]),
            np.array([pmdec.value]),
            GAIA_EPOCH - star.epoch,
        )
        return float(ra[0]), float(dec[0])
    return None


def _value(star: Star, name: str) -> float | None:
    found = star.values.get(name)
    return None if found is None else found.value


def _error(star: Star, name: str) -> float | None:
    found = star.values.get(name)
    if found is None or (found.upper is None and found.lower is None):
        return None
    return max(e for e in (found.upper, found.lower) if e is not None)


HOST_STAR_FIELDS = (
    "host_teff",
    "host_radius",
    "host_mass",
    "host_metallicity",
    "host_logg",
    "host_age",
    "host_v_mag",
    "host_g_mag",
    "host_k_mag",
)


def host_rows(
    catalogue: str,
    identities: list[Identity],
    names: dict[int, str],
    classes: dict[int, str],
    lensed: set[int],
    claims: dict[int, tuple[str, str, str]],
    long_names: dict[int, str],
) -> pa.Table:
    """The pass rows of one catalogue for these identities.

    `names` holds the IAU name of a star, `classes` its class, `lensed` the
    identities whose planets were found by microlensing, `claims` the claim
    that replaces the DR3 id or HIP number of an identity, and `long_names`
    the Hipparcos name of a star.
    """
    rows = []
    for identity in identities:
        star = identity.members.get(catalogue)
        position = reference_position(identity)
        if star is None or position is None:
            continue
        first = identity.first
        claim = claims.get(identity.index) or _claim(identity, star)
        g = _value(first, "g_mag")
        matchable = g is not None and identity.index not in lensed
        rows.append(
            {
                "catalogue_id": star.key,
                "mint": True,
                "match_ra": position[0],
                "match_dec": position[1],
                "match_mag": g,
                "match_error": POSITION_ERROR,
                "match_kind": STAR_KIND if matchable else UNMATCHED_KIND,
                "claims": [dict(zip(CROSS_ID.names, claim))] if claim else None,
                "ra": star.ra,
                "dec": star.dec,
                "ra_error": None,
                "dec_error": None,
                "parallax": _value(star, "parallax"),
                "parallax_error": _error(star, "parallax"),
                "pmra": _value(star, "pmra"),
                "pmra_error": _error(star, "pmra"),
                "pmdec": _value(star, "pmdec"),
                "pmdec_error": _error(star, "pmdec"),
                "epoch": star.epoch,
                "host_name": star.name,
                "host_distance": _value(star, "distance"),
                "host_distance_error": _error(star, "distance"),
                **{name: _value(star, name[5:]) for name in HOST_STAR_FIELDS},
                "host_spectral_type": star.spectral_type,
                "name": names.get(identity.index)
                or long_form(star.name, long_names.get(identity.index)),
                "class": classes.get(identity.index, "star"),
            }
        )
    return pa.Table.from_pylist(rows, schema=HOST_ROW_SCHEMA)


def long_form(name: str, hipparcos: str | None) -> str:
    """The Hipparcos Bayer or Flamsteed designation when `name` is only its
    short form ("sig Per" for "Sigma Persei", "14 Her" for "14 Herculis").

    The constellation abbreviation must read as letters of the genitive in
    order, which tells a slip in either name from the same star.
    """
    if not hipparcos:
        return name
    short, long = name.split(), hipparcos.split()
    if len(short) != 2 or len(long) < 2:
        return name
    letter = _LONG_LETTER.fullmatch(long[0])
    if long[0].isdigit():
        first = long[0]
    elif letter and letter[1].lower() in GREEK:
        first = GREEK[letter[1].lower()] + letter[2]
    else:
        return name
    genitive = iter(" ".join(long[1:]).lower())
    if short[0].lower() == first and all(c in genitive for c in short[1].lower()):
        return hipparcos
    return name


_LONG_LETTER = re.compile(r"([A-Z][a-z]+)(\d*)")


def _claim(identity: Identity, star: Star) -> tuple[str, str, str] | None:
    """The DR3 id, else the HIP number, else the row of the first catalogue."""
    if identity.gaia_dr3:
        return (*GAIA_DR3, str(identity.gaia_dr3))
    if identity.hip:
        return (*HIP, str(identity.hip))
    first = identity.first
    if first is star:
        return None
    source = BY_NAME[first.catalogue]
    return (source.catalogue, source.release, first.key)


HOST_ROW_SCHEMA = pa.schema(
    [
        ("catalogue_id", pa.string()),
        ("mint", pa.bool_()),
        ("match_ra", pa.float64()),
        ("match_dec", pa.float64()),
        ("match_mag", pa.float32()),
        ("match_error", pa.float32()),
        ("match_kind", pa.string()),
        ("claims", pa.list_(CROSS_ID)),
        ("ra", pa.float64()),
        ("dec", pa.float64()),
        ("ra_error", pa.float32()),
        ("dec_error", pa.float32()),
        ("parallax", pa.float32()),
        ("parallax_error", pa.float32()),
        ("pmra", pa.float32()),
        ("pmra_error", pa.float32()),
        ("pmdec", pa.float32()),
        ("pmdec_error", pa.float32()),
        ("epoch", pa.float32()),
        ("host_name", pa.string()),
        ("host_distance", pa.float32()),
        ("host_distance_error", pa.float32()),
        *((name, pa.float32()) for name in HOST_STAR_FIELDS),
        ("host_spectral_type", pa.string()),
        ("name", pa.string()),
        ("class", pa.string()),
    ]
)


def found_by(stars: Stars, catalogues: list[Catalogue], methods: set[str]) -> set[int]:
    """The identities with a planet found by one of these methods."""
    found = set()
    for catalogue in catalogues:
        for planet in catalogue.planets:
            identity = stars.identity(catalogue.name, planet.star)
            if identity is not None and planet.method in methods:
                found.add(identity.index)
    return found


def claim_counts(identities: list[Identity]) -> Counter:
    """How the identities reach the registry: Gaia DR3, HIP, or neither."""
    counts: Counter = Counter()
    for identity in identities:
        if identity.gaia_dr3:
            counts["Gaia DR3 id"] += 1
        elif identity.hip:
            counts["HIP number"] += 1
        else:
            counts["no Gaia or HIP id"] += 1
    return counts
