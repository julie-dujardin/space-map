"""The steps of the builder before the assembly.

1. Each node of a tree source takes its candidate objects (`resolve`). An MSC
   component with no candidate takes the object of the WDS component of its
   WDS id at its place, whatever their letters, as MSC and WDS can letter one
   star differently. A WDS component with no candidate takes the object of
   the MSC component of the same WDS id and letter, and the other way round,
   when their separations agree. Separations that disagree make them two
   stars (`Reduced.two_stars`). A component that still has none goes to
   `Resolver.match` by position. It never takes the object of a node above
   it, or of another node of its WDS system near it. A candidate far from
   the place of its WDS id is a wrong id, and goes (`place_guard`).
2. A planet record that is also a star of a star catalogue stays a record of
   its host. Under the IAU's line its object leaves every tree, and no other
   record brings it back. A brown dwarf is a member of its system too
   (`Overlap`): its star takes the component of the MSC and the WDS that lies
   where it lies from its host, and the record and the star link each other.
3. Each source's trees become groups of points and interiors (`reduce`). El-
   Badry's pairs become groups of two points, and the parallax veto and the
   star-cluster test of the trees apply to them too: shared motion is all
   that links such a pair, and in a cluster every member has it. A close pair
   can throw off the astrometry of a point, so the veto skips a point with a
   Gaia orbit, a SIMBAD close type or an interior. The Gaia orbits become
   interiors of two stars. A Gaia orbit whose companion is a planet is no
   interior.
4. A SIMBAD component inside the light of another point joins that point,
   in every source.
5. A brown dwarf that no tree places joins the outermost group of its host,
   or its host joins its own and goes first. With no group, the two make one.
6. The groups merge into one tree per system (`merge`).
7. Each point takes the interior of its first source. A point that SIMBAD
   types as a close pair, with no interior and no companion in its system
   near enough to explain the type, holds two stars.
"""

import logging
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from space_map_data.extrasolar.exoplanets.iau import BROWN_DWARF
from space_map_data.extrasolar.sky import position_angle
from space_map_data.extrasolar.sky import separation as sky_separation
from space_map_data.extrasolar.sources.hipparcos import to_gaia_epoch
from space_map_data.extrasolar.systems.merge import SetTable
from space_map_data.extrasolar.systems.nodes import (
    EL_BADRY,
    GAIA_DR3,
    GAIA_ORBITS,
    INTERIOR_SOURCES,
    MSC,
    MSC_ID,
    PLANETS,
    PROPER_MOTION,
    SIMBAD,
    SIMBAD_OID,
    SIMBAD_TYPE,
    WDS,
    WDS_ID,
)
from space_map_data.extrasolar.systems.parallax import (
    IN_CLUSTER,
    cluster_text,
    disagree,
    one_cluster,
    parallaxes_disagree,
    unbound,
)
from space_map_data.extrasolar.systems.reduce import (
    POINT,
    UNBOUND,
    Group,
    Interior,
    Member,
    Reduced,
    TreeReducer,
)
from space_map_data.extrasolar.systems.resolve import (
    LETTER,
    MATCH,
    OWN_ASTROMETRY,
    POSITION,
    Fact,
    Facts,
    Resolver,
    candidates,
    flatten_ids,
    resolve_ids,
)
from space_map_data.extrasolar.systems.simbad import (
    NON_STELLAR,
    SimbadIndex,
    non_stellar_parents,
)
from space_map_data.extrasolar.systems.wds import WDS_MATCHER, WdsCatalogue

logger = logging.getLogger(__name__)

# SIMBAD types that only a close pair shows, with the projected separation
# in AU up to which a companion of its own point can be the cause. An
# eclipsing, ellipsoidal or interacting pair is never split.
CLOSE_TYPES = {
    "SB*": 100.0,
    "EB*": 0.0,
    "El*": 0.0,
    "RS*": 0.0,
    "CV*": 0.0,
    "No*": 0.0,
    "XB*": 0.0,
    "LXB": 0.0,
    "HXB": 0.0,
    "Sy*": 0.0,
}
# 13 Jupiter masses in solar masses: a lighter companion is a planet.
PLANET_MASS = 13 * 9.547919e-4
PERIOD_TOLERANCE = 0.05
# Arcsec, for the position of a WDS component.
WDS_POSITION_ERROR = 1.0
VALUE_BLOCK = 1 << 40
# The largest ratio between an MSC separation and the WDS measures of its
# letter. An orbit moves a pair, and the MSC can give the semi-major axis.
MOVING_RATIO = 5.0
# The same for a pair that the MSC knows only by proper motion. Such a pair
# shows no orbital motion.
FIXED_RATIO = 1.5
# Arcsec within which an MSC and a WDS component of one WDS id are one star, at
# most half the way to the next object.
PLACE_ARCSEC = 1.5
ID_OFF = "id off its WDS id"
# Arcsec. A candidate is wrong when it is this far from the place of its WDS
# id, past the widest separation above it, AND from the row's own place. The
# id alone lost Capella H, whose measure sits on a node above it. The row
# alone is wrong because WDS places can be rough.
ID_ARCSEC = 600.0
OWN_PLACE_ARCSEC = 60.0
# From J2000 to Gaia's J2016.
YEARS_TO_GAIA = 16.0
_WDS_ID = re.compile(r"(\d\d)(\d\d\d)([+-])(\d\d)(\d\d)")


@dataclass
class Inputs:
    """The sources, each in its normal form; a missing source is None."""

    msc: pa.Table | None = None
    simbad: pa.Table | None = None
    simbad_index: SimbadIndex | None = None
    planet_systems: pa.Table | None = None
    wds: WdsCatalogue | None = None
    # The pairs that the MSC refutes: (WDS id, primary, secondary).
    refuted: frozenset[tuple[str, str, str]] = frozenset()
    el_badry: pa.Table | None = None
    orbits: pa.Table | None = None
    # PLANETS_INPUT rows.
    planets: pa.Table | None = None
    # The members of the star clusters: `source_id`, `cluster`.
    clusters: pa.Table | None = None
    # For the orbits of the pairs only (`drawn`): the elements of the Gaia
    # orbits (GAIA_ELEMENTS), one row per row of `orbits`, and the orbit
    # sources in their normal form (ORBITS and COMPONENTS).
    orbit_elements: pa.Table | None = None
    catalogue_orbits: pa.Table | None = None
    catalogue_stars: pa.Table | None = None


# What happens to the star of a planet record.
LEAVES, MEMBER, APART = "leaves the trees", "member", "at another distance"
HOST_LEFT = "its host left the trees"


@dataclass
class Overlap:
    """A planet record that is also a star other than its host."""

    # The row of `Inputs.planets`.
    record: int
    host: int
    key: int
    outcome: str


def _rank(source: str) -> int:
    return INTERIOR_SOURCES.index(source)


def _ids_by_row(table: pa.Table, kind: tuple[str, str]) -> dict[int, str]:
    rows, catalogue, release, value = flatten_ids(table)
    picked = pc.and_(pc.equal(catalogue, kind[0]), pc.equal(release, kind[1]))
    picked = picked.fill_null(False).to_numpy(zero_copy_only=False)
    return dict(zip(rows[picked].tolist(), value.filter(pa.array(picked)).to_pylist()))


def separations_agree(
    separation: float | None,
    measures: tuple[float | None, float | None],
    known: list[str] | None,
) -> bool | None:
    """Whether an MSC component and a WDS component of one letter can be one
    star, from the MSC separation and the first and last WDS measures. None
    when a side has no separation.

    The WDS gives -1 for no measure and 0 for a pair too close to measure.
    """
    wds = [value for value in measures if value is not None and value > 0]
    if not separation or not wds:
        return None
    ratio = FIXED_RATIO if known == [PROPER_MOTION] else MOVING_RATIO
    return min(wds) / ratio <= separation <= max(wds) * ratio


def letter_links(
    msc: pa.Table | None,
    wds: pa.Table | None,
    found: dict[str, list[list[tuple[int, int]]]],
    reduced: Reduced,
    placed: frozenset[int] = frozenset(),
) -> dict[tuple[str, str, str], tuple[int, int]]:
    """Links between the MSC and WDS components of one WDS id and letter.

    The two catalogues do not share letters, so a link needs the separations
    to agree (`separations_agree`). A component with no separation links by
    the letter alone. Each takes the other's best candidate as a candidate of
    its own, below its own ids. A WDS component lends none when its Gaia id is
    on another letter of its WDS id too. Ids whose separations disagree go in
    `reduced.two_stars`, also with no candidate to lend. An MSC row of `placed`
    has its object from `place_links`.
    """
    links: dict[tuple[str, str, str], tuple[int, int]] = {}
    if msc is None or wds is None:
        return links
    msc_ids = _ids_by_row(msc, MSC_ID)
    wds_ids = _ids_by_row(wds, WDS_ID)
    gaia = _ids_by_row(wds, GAIA_DR3)
    systems = wds["system"].to_pylist()
    repeated = Counter((systems[row], value) for row, value in gaia.items())
    msc_by = {text: row for row, text in msc_ids.items()}
    msc_separation = msc["separation"].to_pylist()
    msc_known = msc["known"].to_pylist()
    last = wds["separation"].to_pylist()
    first = wds["first_separation"].to_pylist()
    for row, text in wds_ids.items():
        other = msc_by.get(text)
        if other is None or other in placed:
            continue
        measures = (first[row], last[row])
        agree = separations_agree(msc_separation[other], measures, msc_known[other])
        if agree is False:
            reduced.two_stars.add(text)
            reduced.counts[f"{WDS}: letter links that the separations refute"] += 1
            apart = f'MSC {msc_separation[other]}", WDS {first[row]}" to {last[row]}"'
            reduced.events.append(("letters of two stars", WDS, f"{text}: {apart}"))
            continue
        mine, theirs = found[WDS][row], found[MSC][other]
        # A Gaia id on several letters is the light of a close pair.
        source = gaia.get(row)
        shared = source is not None and repeated[(systems[row], source)] > 1
        lent = bool(mine) and not shared
        if not theirs and not lent:
            continue
        if agree is None:
            reduced.counts[f"{WDS}: letter links with no separation to test"] += 1
        if theirs:
            links[(*WDS_ID, text)] = (theirs[0][0], LETTER)
        if lent:
            links[(*MSC_ID, msc_ids[other])] = (mine[0][0], LETTER)
    return links


def place_links(
    msc: pa.Table,
    wds: pa.Table,
    found: dict[str, list[list[tuple[int, int]]]],
    reduced: Reduced,
) -> tuple[dict[tuple[str, str, str], tuple[int, int]], frozenset[int]]:
    """An MSC component with no object takes the object of the WDS component
    of its WDS id at its place, whatever the letters. Gives the links and the
    rows of the MSC that they place."""
    links: dict[tuple[str, str, str], tuple[int, int]] = {}
    placed = set()
    msc_ids = _ids_by_row(msc, MSC_ID)
    by_system: dict[str, list[int]] = defaultdict(list)
    for row, text in enumerate(wds["system"].to_pylist()):
        if found[WDS][row]:
            by_system[text.split(" ")[0]].append(row)
    ra = wds["ra"].fill_null(np.nan).to_numpy()
    dec = wds["dec"].fill_null(np.nan).to_numpy()
    msc_ra = msc["ra"].fill_null(np.nan).to_numpy()
    msc_dec = msc["dec"].fill_null(np.nan).to_numpy()
    systems = msc["system"].to_pylist()
    for row, text in msc_ids.items():
        if found[MSC][row] or not np.isfinite(msc_ra[row]):
            continue
        rows = np.array(by_system.get(systems[row], []), np.int64)
        rows = rows[np.isfinite(ra[rows])] if rows.size else rows
        if not rows.size:
            continue
        apart = np.atleast_1d(
            sky_separation(msc_ra[row], msc_dec[row], ra[rows], dec[rows])
        )
        order = np.argsort(apart)
        key = found[WDS][int(rows[order[0]])][0][0]
        others = [
            float(apart[at])
            for at in order[1:]
            if found[WDS][int(rows[at])][0][0] != key
        ]
        limit = min(PLACE_ARCSEC, others[0] / 2) if others else PLACE_ARCSEC
        if apart[order[0]] > limit:
            continue
        links[(*MSC_ID, text)] = (key, LETTER)
        placed.add(row)
        reduced.counts[f"{MSC}: members by place"] += 1
    return links, frozenset(placed)


def id_place(text: str) -> tuple[float, float] | None:
    """The J2000 place in degrees that a WDS id gives."""
    found = _WDS_ID.match(text)
    if found is None:
        return None
    hours, minutes, sign, degrees, arcmin = found.groups()
    dec = int(degrees) + int(arcmin) / 60
    return (int(hours) + int(minutes) / 600) * 15, -dec if sign == "-" else dec


def place_guard(
    table: pa.Table,
    found: list[list[tuple[int, int]]],
    facts: Facts,
    reduced: Reduced,
) -> None:
    """Drop the candidates of a source's rows that are far from their WDS id
    and from the row's own place. The id holds where a row's place is rough."""
    source = table["source"][0].as_py()
    separation = table["separation"].fill_null(0).to_numpy()
    parent = table["parent"].to_numpy()
    ra = table["ra"].fill_null(np.nan).to_numpy()
    dec = table["dec"].fill_null(np.nan).to_numpy()
    systems = table["system"].to_pylist()
    labels = table["label"].to_pylist()
    for row, items in enumerate(found):
        place = id_place(systems[row]) if items else None
        if place is None:
            continue
        # A wide member's measure can sit on a node above it.
        reach = 0.0
        at = row
        while at >= 0:
            reach = max(reach, float(separation[at]))
            at = int(parent[at])
        kept = []
        for key, rank in items:
            fact = facts.get(key)
            if fact is None or not math.isfinite(fact.ra):
                kept.append((key, rank))
                continue
            motion = 0.0
            if math.isfinite(fact.pmra) and math.isfinite(fact.pmdec):
                motion = math.hypot(fact.pmra, fact.pmdec) * YEARS_TO_GAIA / 1000
            apart = float(sky_separation(*place, fact.ra, fact.dec))
            own = np.inf
            if np.isfinite(ra[row]):
                own = float(sky_separation(ra[row], dec[row], fact.ra, fact.dec))
            if apart - reach - motion > ID_ARCSEC and own - motion > OWN_PLACE_ARCSEC:
                reduced.counts[f"{source}: {ID_OFF}"] += 1
                reduced.events.append(
                    (
                        ID_OFF,
                        source,
                        f"{systems[row]} {labels[row]}: {key} is {apart:.0f}″ off",
                    )
                )
            else:
                kept.append((key, rank))
        found[row] = kept


def match_rows(
    table: pa.Table, found: list[list[tuple[int, int]]], kind: tuple[str, str]
) -> pa.Table:
    """The MATCH rows of the leaves of `table` that have no candidate. `kind`
    is the id that links a row back to its node.

    A component never takes the object of a node above it, or of another
    node of its WDS system within its match radius. That object is the point
    of its pair, or the other star of the pair.
    """
    parent = table["parent"].to_numpy()
    leaf = np.ones(table.num_rows, bool)
    leaf[parent[parent >= 0]] = False
    free = np.array([not items for items in found], bool) & leaf
    free &= table["ra"].is_valid().to_numpy(zero_copy_only=False)
    free &= table["epoch"].is_valid().to_numpy(zero_copy_only=False)
    rows = table.filter(pa.array(free))
    exclude = _taken(table, found, np.flatnonzero(free))
    ids = _ids_by_row(rows, kind)
    floats = {
        name: rows[name].cast(pa.float64()).fill_null(np.nan).to_numpy()
        for name in ("ra", "dec", "pmra", "pmdec", "epoch", "v_mag", "g_mag")
    }
    ra, dec = to_gaia_epoch(
        floats["ra"], floats["dec"], floats["pmra"], floats["pmdec"], floats["epoch"]
    )
    mag = np.where(np.isfinite(floats["g_mag"]), floats["g_mag"], floats["v_mag"])
    n = rows.num_rows
    return pa.table(
        {
            "catalogue_id": pa.array([ids.get(i) for i in range(n)], pa.string()),
            "mint": pa.array(np.zeros(n, bool)),
            "match_ra": pa.array(ra),
            "match_dec": pa.array(dec),
            "match_pmra": pa.array(floats["pmra"], pa.float32(), from_pandas=True),
            "match_pmdec": pa.array(floats["pmdec"], pa.float32(), from_pandas=True),
            "match_mag": pa.array(mag, pa.float32(), from_pandas=True),
            "match_error": pa.array(np.full(n, WDS_POSITION_ERROR, np.float32)),
            "match_exclude": pa.array(exclude, pa.list_(pa.int64())),
        },
        schema=MATCH,
    )


def _taken(
    table: pa.Table, found: list[list[tuple[int, int]]], rows: np.ndarray
) -> list[list[int] | None]:
    """For each of `rows`, the candidates of the nodes above it and of the
    other nodes of its WDS system within its match radius."""
    parent = table["parent"].to_numpy()
    ra = table["ra"].fill_null(np.nan).to_numpy()
    dec = table["dec"].fill_null(np.nan).to_numpy()
    radius = float(WDS_MATCHER.radius(np.array([WDS_POSITION_ERROR]), np.zeros(1))[0])
    held: dict[str, list[int]] = defaultdict(list)
    wds_ids = [text.split(" ")[0] for text in table["system"].to_pylist()]
    for row, (wds_id, items) in enumerate(zip(wds_ids, found)):
        if items:
            held[wds_id].append(row)
    out: list[list[int] | None] = []
    for row in rows.tolist():
        above = set()
        at = int(parent[row])
        while at >= 0:
            above.add(at)
            at = int(parent[at])
        others = held[wds_ids[row]]
        apart = sky_separation(ra[row], dec[row], ra[others], dec[others])
        near = [
            o for o, d in zip(others, np.atleast_1d(apart)) if o in above or d <= radius
        ]
        out.append(sorted({key for o in near for key, _ in found[o]}) or None)
    return out


def pair_keys(pairs: pa.Table, resolver: Resolver) -> tuple[np.ndarray, np.ndarray]:
    """The objects of the two stars of each pair, 0 where none."""
    given = [pairs[f"key{side}"].fill_null(0).to_numpy() for side in "12"]
    gaia = [pairs[f"gaia{side}"].combine_chunks() for side in "12"]
    wanted = [
        g.is_valid().to_numpy(zero_copy_only=False) & (k == 0)
        for g, k in zip(gaia, given)
    ]
    values = [g.filter(pa.array(w)).cast(pa.string()) for g, w in zip(gaia, wanted)]
    unique = pc.unique(pa.concat_arrays(values))
    found = resolver.keys(*GAIA_DR3, unique) if len(unique) else np.zeros(0, np.int64)
    out = []
    for keys, mask, value in zip(given, wanted, values):
        keys = keys.copy()
        if mask.any():
            keys[mask] = found[pc.index_in(value, value_set=unique).to_numpy()]
        out.append(keys)
    return out[0], out[1]


def cluster_keys(
    clusters: pa.Table | None, resolver: Resolver, facts: Facts
) -> dict[int, frozenset[str]]:
    """The star clusters of each object of `facts`."""
    if clusters is None or not clusters.num_rows:
        return {}
    ids = clusters["source_id"].combine_chunks().cast(pa.string())
    keys = resolver.keys(*GAIA_DR3, ids)
    held = facts.at(keys) >= 0
    found: dict[int, set[str]] = defaultdict(set)
    names = clusters["cluster"].filter(pa.array(held)).to_pylist()
    for key, name in zip(keys[held].tolist(), names):
        found[key].add(name)
    return {key: frozenset(names) for key, names in found.items()}


def planet_overlaps(planets: pa.Table | None, resolver: Resolver) -> list[Overlap]:
    """The planet records that are also a star other than their host, once per
    record and star. A record under the IAU's line leaves the trees."""
    if planets is None or not planets.num_rows:
        return []
    rows, catalogue, release, value = flatten_ids(planets, "star_ids")
    ids = list(zip(catalogue.to_pylist(), release.to_pylist(), value.to_pylist()))
    wanted: dict[tuple[str, str], set[str]] = defaultdict(set)
    for c, r, v in ids:
        wanted[(c, r)].add(v)
    keys = resolve_ids(resolver, wanted)
    hosts = planets["host"].to_pylist()
    classes = planets["class"].to_pylist()
    found: dict[tuple[int, int], Overlap] = {}
    for row, item in zip(rows.tolist(), ids):
        key = keys.get(item)
        if key and key != hosts[row]:
            member = classes[row] == BROWN_DWARF and hosts[row]
            outcome = MEMBER if member else LEAVES
            found.setdefault((row, key), Overlap(row, hosts[row], key, outcome))
    return list(found.values())


def _leaving(overlaps: list[Overlap], reduced: Reduced) -> frozenset[int]:
    """The stars that leave the trees. No record brings one back: a star that
    leaves is no member, and a host that leaves has no members."""
    dropped = frozenset(item.key for item in overlaps if item.outcome == LEAVES)
    for item in overlaps:
        if item.outcome != MEMBER or not dropped & {item.key, item.host}:
            continue
        item.outcome = LEAVES if item.key in dropped else HOST_LEFT
        reduced.counts[f"{PLANETS}: brown dwarfs out with a star that leaves"] += 1
        reduced.events.append(
            (
                "brown dwarf out with a star that leaves",
                PLANETS,
                f"{item.key} of {item.host}: {item.outcome}",
            )
        )
    return dropped


def _keep_near(
    overlaps: list[Overlap], facts: Facts, close: frozenset[int], reduced: Reduced
) -> None:
    """Parallaxes that clearly disagree show a wrong id: such a star stays as
    it is, out of its record's system and with no link. A point of `close` can
    hold a close pair, which throws off its astrometry."""
    for item in overlaps:
        host, star = facts.get(item.host), facts.get(item.key)
        if item.outcome != MEMBER or host is None or star is None:
            continue
        if disagree(host, star) and not close & {item.host, item.key}:
            item.outcome = APART
            reduced.counts[f"{PLANETS}: brown dwarfs at another distance"] += 1
            reduced.events.append(
                (
                    "brown dwarf at another distance",
                    PLANETS,
                    (
                        f"{star.key} {star.parallax:.3f}"
                        f" ± {star.parallax_error:.3f} mas, host {host.key}"
                        f" {host.parallax:.3f} ± {host.parallax_error:.3f} mas"
                    ),
                )
            )


def _places_apart(
    apart: float, towards: float, separation: np.ndarray, angle: np.ndarray
) -> np.ndarray:
    """Arcsec between a place and each of `separation` and `angle`, all from
    one star. The catalogues can swap the two stars of a pair, and with no
    angle only the separations compare."""
    turn = np.abs(np.cos(np.radians(angle - towards)))
    found = apart**2 + separation**2 - 2 * apart * separation * turn
    return np.where(
        np.isfinite(angle), np.sqrt(np.maximum(found, 0)), np.abs(apart - separation)
    )


def _from_host(
    rows: list[int],
    parent: np.ndarray,
    found: list[list[tuple[int, int]]],
    host: int,
) -> list[int]:
    """The rows of a system that give their place from the host: their pair's
    primary holds it, or their parent is its point."""
    holds = set()
    first: dict[int, int] = {}
    for row in rows:
        first.setdefault(int(parent[row]), row)
        if any(key == host for key, _ in found[row]):
            while row >= 0 and row not in holds:
                holds.add(row)
                row = int(parent[row])
    return [
        row
        for row in rows
        if parent[row] >= 0
        and (
            first[int(parent[row])] in holds
            or any(key == host for key, _ in found[int(parent[row])])
        )
    ]


def member_links(
    table: pa.Table,
    kind: tuple[str, str],
    found: list[list[tuple[int, int]]],
    overlaps: list[Overlap],
    facts: Facts,
    reduced: Reduced,
) -> dict[tuple[str, str, str], tuple[int, int]]:
    """The component that each brown dwarf is: the row of a system of its host
    with no object at or below it that lies nearest, within the match radius.

    A row gives its place from its primary, which holds up for a star that
    moves, as a WDS companion has no proper motion. A row with no measure
    gives no place. The match reaches no star that SIMBAD lists with no
    magnitude, and the record shows that this star belongs here. A row with
    its object in the host's place takes the host down to its first child
    when that child is free, so the two are members side by side.
    """
    members = [item for item in overlaps if item.outcome == MEMBER]
    links: dict[tuple[str, str, str], tuple[int, int]] = {}
    if not members:
        return links
    of_key: dict[int, set[str]] = defaultdict(set)
    rows_of: dict[str, list[int]] = defaultdict(list)
    parent = table["parent"].to_numpy()
    held = np.zeros(table.num_rows, bool)
    for row, (text, items) in enumerate(zip(table["system"].to_pylist(), found)):
        system = text.split(" ")[0]
        rows_of[system].append(row)
        for key, _ in items:
            of_key[key].add(system)
        while items and row >= 0 and not held[row]:
            held[row] = True
            row = int(parent[row])
    ids = _ids_by_row(table, kind)
    labels = table["label"].to_pylist()
    separation = table["separation"].fill_null(np.nan).to_numpy()
    angle = table["position_angle"].cast(pa.float64()).fill_null(np.nan).to_numpy()
    radius = float(WDS_MATCHER.radius(np.array([WDS_POSITION_ERROR]), np.zeros(1))[0])
    for item in members:
        host, star = facts.get(item.host), facts.get(item.key)
        if host is None or star is None:
            continue
        apart, towards = offset(host, star)
        for system in sorted(of_key[item.host] - of_key[item.key]):
            rows = [r for r in rows_of[system] if r in ids]
            free = np.array(
                [
                    r
                    for r in _from_host(rows, parent, found, item.host)
                    if not held[r] and separation[r] > 0
                ],
                np.int64,
            )
            miss = _places_apart(apart, towards, separation[free], angle[free])
            near = np.flatnonzero(miss <= radius)
            if not near.size:
                continue
            row = int(free[near[np.argmin(miss[near])]])
            held[row] = True
            of_key[item.key].add(system)
            links[(*kind, ids[row])] = (item.key, POSITION)
            reduced.counts[f"{PLANETS}: brown dwarfs that take a component"] += 1
            reduced.events.append(
                (
                    "brown dwarf takes a component",
                    PLANETS,
                    (
                        f"{ids[row]} ({labels[row]}, {separation[row]}\u2033) is"
                        f" {item.key}, {apart:.1f}\u2033 from {item.host}, off by"
                        f" {miss[near].min():.1f}\u2033"
                    ),
                )
            )
            above = int(parent[row])
            first = next(r for r in rows if parent[r] == above)
            if not held[first] and any(key == item.host for key, _ in found[above]):
                held[first] = True
                links[(*kind, ids[first])] = (item.host, POSITION)
    return links


def _outermost(groups: list[Group]) -> Group | None:
    """The outermost of the groups of a point, in the order of `reduced.groups`,
    which `merge` keeps: a group that crosses an earlier one leaves."""
    top = None
    for group in sorted(groups, key=lambda g: g.rank):
        if top is None or group.keys >= top.keys:
            top = group
    return top


def _add_point(group: Group, key: int, partners: set[int], first: bool) -> None:
    """Add a point to a group. Its El-Badry partners join the group's set, as
    the pair would cross it and leave them out."""
    group.keys = group.keys | ({key} | partners) - {0}
    group.members.insert(0 if first else len(group.members), Member(POINT, key=key))


def _host_first(groups: list[Group], host: int, key: int) -> None:
    """A group's own point comes after its members, but a brown dwarf is not
    its system's primary."""
    for group in groups:
        keys = [m.key if m.kind == POINT else 0 for m in group.members]
        if host in keys and key in keys and keys.index(key) < keys.index(host):
            first, second = keys.index(key), keys.index(host)
            members = group.members
            members[first], members[second] = members[second], members[first]


def join_members(
    reduced: Reduced,
    overlaps: list[Overlap],
    pairs: tuple[np.ndarray, np.ndarray],
) -> None:
    """Put each brown dwarf that no tree places in the system of its host. No
    tree gives it a level, so it joins at the top: a set of its own would
    cross the sets of the system. `pairs` are the El-Badry pairs that stay."""
    members = [item for item in overlaps if item.outcome == MEMBER]
    hosts = {item.host for item in members}
    wanted = hosts | {item.key for item in members}
    groups: dict[int, list[Group]] = defaultdict(list)
    for group in reduced.groups:
        for key in group.keys & wanted:
            groups[key].append(group)
    partners: dict[int, set[int]] = defaultdict(set)
    first, second = pairs
    hit = np.isin(first, list(wanted)) | np.isin(second, list(wanted))
    for a, b in zip(first[hit].tolist(), second[hit].tolist()):
        partners[a].add(b)
        partners[b].add(a)
    for item in members:
        host, key = item.host, item.key
        top, own = _outermost(groups[host]), _outermost(groups[key])
        group = top or own
        if top is not None and key in top.keys:
            if key not in hosts:
                _host_first(groups[key], host, key)
            continue
        if group is None:
            if key in partners[host]:
                continue
            group = Group(
                PLANETS,
                _rank(PLANETS),
                f"{host}+{key}",
                -1,
                frozenset(({host, key} | partners[host] | partners[key]) - {0}),
                [Member(POINT, key=host), Member(POINT, key=key)],
            )
            reduced.groups.append(group)
            groups[host].append(group)
            groups[key].append(group)
        elif top is not None and own is not None:
            reduced.counts[f"{PLANETS}: brown dwarfs in another system"] += 1
            reduced.events.append(
                (
                    "brown dwarf in another system",
                    PLANETS,
                    (
                        f"{key} is in {own.source} {own.system}, its host {host}"
                        f" in {top.source} {top.system}"
                    ),
                )
            )
            continue
        else:
            joining = host if top is None else key
            # A brown dwarf is not its system's primary.
            first = joining == host and key not in hosts
            _add_point(group, joining, partners[joining], first)
            groups[joining].append(group)
        reduced.counts[f"{PLANETS}: brown dwarfs that join by their record"] += 1


def planet_periods(planets: pa.Table | None) -> dict[int, list[float]]:
    found: dict[int, list[float]] = defaultdict(list)
    if planets is None:
        return found
    for host, period in zip(planets["host"].to_pylist(), planets["period"].to_pylist()):
        if host and period:
            found[host].append(period)
    return found


def same_period(first: float, second: float) -> bool:
    return abs(first - second) / max(first, second) < PERIOD_TOLERANCE


def orbit_interiors(
    orbits: pa.Table,
    keys: np.ndarray,
    periods: dict[int, list[float]],
    reduced: Reduced,
) -> np.ndarray:
    """Whether each orbit makes an interior: a star and a companion that is
    not a planet. Logs the others."""
    period = orbits["period"].fill_null(np.nan).to_numpy()
    mass2 = orbits["mass2"].fill_null(np.nan).to_numpy()
    keep = keys != 0
    light = mass2 < PLANET_MASS
    planet = np.zeros(keys.size, bool)
    for at in np.flatnonzero(keep).tolist():
        for found in periods.get(int(keys[at]), []):
            if same_period(found, period[at]):
                planet[at] = True
    reduced.counts[f"{GAIA_ORBITS}: orbits of no object"] += int((~keep).sum())
    reduced.counts[f"{GAIA_ORBITS}: companions that are listed planets"] += int(
        (keep & planet).sum()
    )
    reduced.counts[f"{GAIA_ORBITS}: companions under 13 MJ"] += int(
        (keep & light & ~planet).sum()
    )
    systems = orbits["system"].to_pylist()
    for at in np.flatnonzero(keep & planet).tolist()[:20]:
        reduced.events.append(
            (
                "orbit of a planet",
                GAIA_ORBITS,
                f"{systems[at]}: period {period[at]:.1f} d is a planet of {keys[at]}",
            )
        )
    return keep & ~planet & ~light


def close_type_keys(index: SimbadIndex | None, resolver: Resolver) -> dict[int, str]:
    """The SIMBAD type of each point that SIMBAD types as a close pair."""
    if index is None:
        return {}
    oids = [
        oid
        for oid, found in index.stars.objects.items()
        if found.row.get("otype") in CLOSE_TYPES and index.stars.is_row(oid)
    ]
    keys = resolve_ids(resolver, {SIMBAD_OID: {str(oid) for oid in oids}})
    return {
        key: index.stars.objects[int(oid)].row["otype"]
        for (_, _, oid), key in keys.items()
    }


@dataclass
class Prepared:
    """What the steps before the assembly give."""

    tables: list[pa.Table]
    offsets: list[int]
    reduced: Reduced
    facts: Facts
    sets: SetTable
    # Over the sets: the tree group, or -1 - the El-Badry pair.
    origin: np.ndarray
    el_badry: pa.Table | None
    el_badry_keys: tuple[np.ndarray, np.ndarray]
    orbits: pa.Table | None
    orbit_keys: np.ndarray
    orbit_kept: np.ndarray
    close: dict[int, str]
    dropped: frozenset[int]
    overlaps: list[Overlap]
    counts: Counter


def prepare(inputs: Inputs, resolver: Resolver) -> Prepared:
    counts: Counter = Counter()
    trees: list[pa.Table] = []
    wds = None if inputs.wds is None else inputs.wds.nodes(inputs.refuted)
    for table in (inputs.msc, inputs.simbad, inputs.planet_systems, wds):
        if table is not None and table.num_rows:
            trees.append(table)
    for table in trees:
        counts[f"{table['source'][0].as_py()}: nodes"] = table.num_rows
    index = inputs.simbad_index or SimbadIndex.empty()

    overlaps = planet_overlaps(inputs.planets, resolver)

    by_source = {table["source"][0].as_py(): table for table in trees}
    found_lists, reach_lists = candidates(trees, resolver, index, {})
    found = dict(zip(by_source, found_lists))
    reach = dict(zip(by_source, reach_lists))
    reduced = Reduced()
    if inputs.simbad is not None:
        for text in non_stellar_parents(index.stars):
            reduced.counts[f"{SIMBAD}: {NON_STELLAR}"] += 1
            reduced.events.append((NON_STELLAR, SIMBAD, text))
    placed: frozenset[int] = frozenset()
    if MSC in by_source and WDS in by_source:
        links, placed = place_links(by_source[MSC], by_source[WDS], found, reduced)
        _add_links(trees, found, links)
    _add_links(
        trees,
        found,
        letter_links(by_source.get(MSC), by_source.get(WDS), found, reduced, placed),
    )
    for source, kind in ((WDS, WDS_ID), (MSC, MSC_ID)):
        if source not in by_source:
            continue
        rows = match_rows(by_source[source], found[source], kind)
        counts[f"{source}: members sent to match by position"] = rows.num_rows
        matched = resolver.match(rows, kind) if rows.num_rows else np.zeros(0, np.int64)
        positions = {
            (*kind, text): (key, POSITION)
            for text, key in zip(rows["catalogue_id"].to_pylist(), matched.tolist())
            if key and text
        }
        counts[f"{source}: members matched by position"] = len(positions)
        _add_links(trees, found, positions)

    el_keys = (np.zeros(0, np.int64), np.zeros(0, np.int64))
    if inputs.el_badry is not None:
        el_keys = pair_keys(inputs.el_badry, resolver)
    orbit_keys = np.zeros(0, np.int64)
    if inputs.orbits is not None:
        orbit_keys, _ = pair_keys(inputs.orbits, resolver)
    close = close_type_keys(inputs.simbad_index, resolver)

    wanted_keys = {k for items in found.values() for row in items for k, _ in row}
    wanted_keys |= set(close)
    wanted_keys |= {key for item in overlaps for key in (item.host, item.key)}
    if inputs.planets is not None:
        wanted_keys |= set(inputs.planets["host"].to_pylist())
    every = np.unique(
        np.concatenate(
            [
                np.array(sorted(wanted_keys - {0, None}), np.int64),
                *el_keys,
                orbit_keys,
            ]
        )
    )
    facts = Facts(resolver.facts(every[every != 0]))
    logger.info("systems: facts of %d objects", len(facts))
    # After every other lookup, so that an object's first id stays its own.
    clusters = cluster_keys(inputs.clusters, resolver, facts)
    counts["objects of the systems in a star cluster"] = len(clusters)

    for source in (MSC, WDS):
        if source in by_source:
            place_guard(by_source[source], found[source], facts, reduced)
    dropped = _leaving(overlaps, reduced)
    periods = planet_periods(inputs.planets)
    orbit_kept = np.zeros(orbit_keys.size, bool)
    if inputs.orbits is not None:
        orbit_kept = orbit_interiors(inputs.orbits, orbit_keys, periods, reduced)
        orbit_kept &= ~np.isin(orbit_keys, list(dropped))
    close_keys = np.array(sorted(close), np.int64)
    close_points = _close_pairs(orbit_keys[orbit_kept], close_keys)
    _keep_near(overlaps, facts, close_points, reduced)
    for source, kind in ((MSC, MSC_ID), (WDS, WDS_ID)):
        if source in by_source:
            table, rows = by_source[source], found[source]
            links = member_links(table, kind, rows, overlaps, facts, reduced)
            _add_links(trees, found, links)
    offsets = []
    block = 0
    for table in trees:
        source = table["source"][0].as_py()
        offsets.append(block)
        TreeReducer(
            table,
            _rank(source),
            found[source],
            facts,
            block,
            reduced,
            dropped,
            close_points,
            reach[source],
            clusters,
        ).run()
        block += VALUE_BLOCK
    remap = _absorptions(reduced)
    _apply(reduced, remap)
    el_keys = (_mapped(el_keys[0], remap), _mapped(el_keys[1], remap))
    orbit_keys = _mapped(orbit_keys, remap)
    for side in el_keys:
        side[np.isin(side, list(dropped))] = 0
    for item in overlaps:
        item.host = remap.get(item.host, item.host)
        item.key = remap.get(item.key, item.key)
    overlaps = [item for item in overlaps if item.host != item.key]
    exempt = _close_pairs(orbit_keys[orbit_kept], _mapped(close_keys, remap))
    exempt |= {interior.key for interior in reduced.interiors}
    vetoed = vetoed_pairs(facts, *el_keys, exempt)
    counts[f"{EL_BADRY}: pairs that the parallaxes veto"] = int(vetoed.sum())
    if inputs.el_badry is not None:
        _veto_events(facts, inputs.el_badry, el_keys, vetoed, reduced)
        refuted = cluster_pairs(facts, inputs.el_badry, el_keys, clusters)
        refuted &= ~vetoed
        _cluster_events(facts, inputs.el_badry, el_keys, refuted, clusters, reduced)
        counts[f"{EL_BADRY}: pairs {IN_CLUSTER}"] = int(refuted.sum())
        vetoed |= refuted
    join_members(reduced, overlaps, (el_keys[0][~vetoed], el_keys[1][~vetoed]))
    sets, origin = _set_table(reduced, inputs.el_badry, el_keys, vetoed, counts)
    counts.update(reduced.counts)
    return Prepared(
        trees,
        offsets,
        reduced,
        facts,
        sets,
        origin,
        inputs.el_badry,
        el_keys,
        inputs.orbits,
        orbit_keys,
        orbit_kept,
        close,
        dropped,
        overlaps,
        counts,
    )


def _add_links(
    trees: list[pa.Table],
    found: dict[str, list[list[tuple[int, int]]]],
    links: dict[tuple[str, str, str], tuple[int, int]],
) -> None:
    for table in trees:
        source = table["source"][0].as_py()
        rows, catalogue, release, value = flatten_ids(table)
        for row, c, r, v in zip(
            rows.tolist(), catalogue.to_pylist(), release.to_pylist(), value.to_pylist()
        ):
            link = links.get((c, r, v))
            if link and all(key != link[0] for key, _ in found[source][row]):
                found[source][row] = sorted(
                    [*found[source][row], link], key=lambda item: (item[1], item[0])
                )


def _absorptions(reduced: Reduced) -> dict[int, int]:
    """The point that each absorbed SIMBAD component joins, first source wins."""
    remap: dict[int, int] = {}
    for item in sorted(reduced.absorbed, key=lambda a: _rank(a.source)):
        if item.key in remap and remap[item.key] != item.into:
            reduced.events.append(
                (
                    "absorbed twice",
                    item.source,
                    (
                        f"{item.key} is in {remap[item.key]}; {item.source} puts it"
                        f" in {item.into}"
                    ),
                )
            )
            continue
        remap.setdefault(item.key, item.into)
    for key in list(remap):
        seen = {key}
        while remap[key] in remap and remap[key] not in seen:
            seen.add(remap[key])
            remap[key] = remap[remap[key]]
    return remap


def _mapped(keys: np.ndarray, remap: dict[int, int]) -> np.ndarray:
    if not remap or not keys.size:
        return keys
    source = np.array(sorted(remap), np.int64)
    target = np.array([remap[k] for k in source.tolist()], np.int64)
    at = np.searchsorted(source, keys)
    at = np.minimum(at, source.size - 1)
    hit = source[at] == keys
    return np.where(hit, target[at], keys)


def _apply(reduced: Reduced, remap: dict[int, int]) -> None:
    """Move the absorbed components into their points everywhere."""
    if not remap:
        return
    for group in reduced.groups:
        group.keys = frozenset(remap.get(k, k) for k in group.keys)
        seen: set[int] = set()
        members = []
        for member in group.members:
            if member.kind == POINT:
                member.key = remap.get(member.key, member.key)
                if member.key in seen:
                    continue
                seen.add(member.key)
            members.append(member)
        group.members = members
    for interior in reduced.interiors:
        interior.key = remap.get(interior.key, interior.key)
    for item in reduced.tentative:
        item.keys = frozenset(remap.get(k, k) for k in item.keys)


def _close_pairs(orbit_keys: np.ndarray, close_keys: np.ndarray) -> frozenset[int]:
    """The points that a Gaia DR3 orbit or a SIMBAD close type shows as a
    close pair."""
    return frozenset(orbit_keys.tolist()) | frozenset(close_keys.tolist())


def vetoed_pairs(
    facts: Facts, first: np.ndarray, second: np.ndarray, exempt: frozenset[int]
) -> np.ndarray:
    """Whether the parallaxes of each El-Badry pair of two objects disagree.

    A point of `exempt` can hold a close pair, which throws off its
    astrometry.
    """
    separation = sky_separation(
        facts.column("ra", first),
        facts.column("dec", first),
        facts.column("ra", second),
        facts.column("dec", second),
    )
    found = parallaxes_disagree(
        facts.column("parallax", first),
        facts.column("parallax_error", first),
        facts.column("parallax", second),
        facts.column("parallax_error", second),
        separation,
    )
    found &= (first != 0) & (second != 0) & (first != second)
    for keys in (first, second):
        found &= facts.has("astrometry", keys, OWN_ASTROMETRY)
        found &= ~np.isin(keys, sorted(exempt))
    return found


def _veto_events(
    facts: Facts,
    el_badry: pa.Table,
    el_keys: tuple[np.ndarray, np.ndarray],
    vetoed: np.ndarray,
    reduced: Reduced,
) -> None:
    systems = el_badry["system"].to_pylist()
    for at in np.flatnonzero(vetoed).tolist():
        stars = [facts.get(int(side[at])) for side in el_keys]
        text = ", ".join(
            f"{star.key} {star.parallax:.3f} ± {star.parallax_error:.3f} mas"
            for star in stars
            if star is not None
        )
        reduced.events.append(
            ("parallaxes disagree", EL_BADRY, f"{EL_BADRY} {systems[at]}: {text}")
        )


def cluster_pairs(
    facts: Facts,
    el_badry: pa.Table,
    el_keys: tuple[np.ndarray, np.ndarray],
    clusters: dict[int, frozenset[str]],
) -> np.ndarray:
    """Whether each El-Badry pair is no system: two neighbours in one star
    cluster."""
    first, second = el_keys
    found = np.zeros(el_badry.num_rows, bool)
    for at, (one, other) in enumerate(zip(first.tolist(), second.tolist())):
        if one not in clusters or other not in clusters or one == other:
            continue
        a, b = facts.get(one), facts.get(other)
        if a and b and one_cluster(clusters, a, b):
            found[at] = unbound(a, b, False, True) == IN_CLUSTER
    return found


def _cluster_events(
    facts: Facts,
    el_badry: pa.Table,
    el_keys: tuple[np.ndarray, np.ndarray],
    refuted: np.ndarray,
    clusters: dict[int, frozenset[str]],
    reduced: Reduced,
) -> None:
    systems = el_badry["system"].to_pylist()
    for at in np.flatnonzero(refuted).tolist():
        first, second = (facts.get(int(side[at])) for side in el_keys)
        assert first is not None and second is not None
        text = f"{EL_BADRY} {systems[at]}: {cluster_text(clusters, first, second)}"
        reduced.events.append((f"{UNBOUND}: {IN_CLUSTER}", EL_BADRY, text))


def _set_table(
    reduced: Reduced,
    el_badry: pa.Table | None,
    el_keys: tuple[np.ndarray, np.ndarray],
    vetoed: np.ndarray,
    counts: Counter,
) -> tuple[SetTable, np.ndarray]:
    ranks, trees, sizes, keys, names, origin = [], [], [], [], [], []
    tree_code: dict[tuple[str, str], int] = {}
    for at, group in enumerate(reduced.groups):
        code = tree_code.setdefault((group.source, group.system), len(tree_code))
        members = sorted(group.keys)
        ranks.append(_rank(group.source))
        trees.append(code)
        sizes.append(len(members))
        keys.append(np.array(members, np.int64))
        names.append(f"{group.source} {group.system}")
        origin.append(at)
    rank = np.array(ranks, np.int64)
    tree = np.array(trees, np.int64)
    size = np.array(sizes, np.int64)
    origin_array = np.array(origin, np.int64)
    flat = [np.concatenate(keys) if keys else np.zeros(0, np.int64)]
    if el_badry is not None and el_badry.num_rows:
        first, second = el_keys
        both = (first != 0) & (second != 0) & (first != second)
        one = (first != 0) ^ (second != 0)
        counts[f"{EL_BADRY}: pairs of two objects"] = int(both.sum())
        counts[f"{EL_BADRY}: pairs of one object and an entry"] = int(one.sum())
        counts[f"{EL_BADRY}: pairs of no object"] = int(
            ((first == 0) & (second == 0)).sum()
        )
        counts[f"{EL_BADRY}: pairs of one object twice"] = int(
            ((first != 0) & (first == second)).sum()
        )
        pick = np.flatnonzero((both & ~vetoed) | one)
        n = pick.size
        lone = np.where(first[pick] != 0, first[pick], second[pick])
        pair_size = np.where(both[pick], 2, 1)
        start = np.cumsum(np.r_[0, pair_size])
        pair_keys_flat = np.zeros(int(start[-1]), np.int64)
        pair_keys_flat[start[:-1]] = np.where(
            both[pick], np.minimum(first[pick], second[pick]), lone
        )
        two = both[pick]
        pair_keys_flat[start[:-1][two] + 1] = np.maximum(first[pick], second[pick])[two]
        rank = np.r_[rank, np.full(n, _rank(EL_BADRY), np.int64)]
        tree = np.r_[tree, len(tree_code) + np.arange(n, dtype=np.int64)]
        size = np.r_[size, pair_size]
        flat.append(pair_keys_flat)
        systems = el_badry["system"].take(pa.array(pick)).to_pylist()
        names += [f"{EL_BADRY} {s}" for s in systems]
        origin_array = np.r_[origin_array, -1 - pick]
    start = np.r_[0, np.cumsum(size)]
    sets = SetTable(rank, tree, start, np.concatenate(flat), names)
    return sets, origin_array


def separation_of(facts: Facts, first: int, second: int) -> float:
    a, b = facts.get(first), facts.get(second)
    if a is None or b is None:
        return math.nan
    return offset(a, b)[0]


def offset(first: Fact, second: Fact) -> tuple[float, float]:
    """The separation of `second` from `first` in arcsec, and its position
    angle in degrees."""
    return (
        float(sky_separation(first.ra, first.dec, second.ra, second.dec)),
        float(position_angle(first.ra, first.dec, second.ra, second.dec)),
    )


def evidence_interiors(prepared: Prepared) -> set[int]:
    """The points with an interior that an interior of unverified members
    gives way to."""
    have = {
        interior.key
        for interior in prepared.reduced.interiors
        if not interior.unverified
    }
    return have | set(prepared.orbit_keys[prepared.orbit_kept].tolist())


def close_interiors(
    prepared: Prepared, system_of: dict[int, int], points_of: dict[int, list[int]]
) -> list[Interior]:
    """Two stars for each close-pair point with no interior that no companion
    explains. An interior of unverified members does not count."""
    have = evidence_interiors(prepared)
    found = []
    for key, otype in sorted(prepared.close.items()):
        if key in have or key in prepared.dropped:
            continue
        reach = CLOSE_TYPES[otype]
        system = system_of.get(key)
        explained = False
        if system is not None and reach > 0:
            fact = prepared.facts.get(key)
            distance = fact.distance if fact else math.nan
            if not math.isfinite(distance) and fact and fact.parallax > 0:
                distance = 1000 / fact.parallax
            for other in points_of[system]:
                if other == key:
                    continue
                apart = separation_of(prepared.facts, key, other) * distance
                if apart <= reach:
                    explained = True
                    prepared.counts[
                        f"{SIMBAD_TYPE}: {otype} explained by a companion"
                    ] += 1
                    break
        if not explained:
            found.append(
                Interior(
                    key,
                    SIMBAD_TYPE,
                    _rank(SIMBAD_TYPE),
                    otype,
                    [(-1, None), (-1, None)],
                )
            )
    prepared.counts[f"{SIMBAD_TYPE}: points that hold a close pair"] = len(found)
    return found
