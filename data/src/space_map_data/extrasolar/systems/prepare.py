"""The steps of the builder before the assembly.

1. Each node of a tree source takes its candidate objects (`resolve`). A WDS
   component with no candidate takes the object of the MSC component of the
   same WDS id and letter, and the other way round. A WDS component that still
   has none goes to `Resolver.match` by position.
2. A planet that is also a star of a star catalogue stays a planet: its
   object leaves every tree.
3. Each source's trees become groups of points and interiors (`reduce`). El-
   Badry's pairs become groups of two points, the Gaia orbits interiors of
   two stars. A Gaia orbit whose companion is a planet is no interior.
4. A SIMBAD component inside the light of another point joins that point,
   in every source.
5. The groups merge into one tree per system (`merge`).
6. Each point takes the interior of its first source. A point that SIMBAD
   types as a close pair, with no interior and no companion in its system
   near enough to explain the type, holds two stars.
"""

import logging
import math
from collections import Counter, defaultdict
from dataclasses import dataclass

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

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
    SIMBAD_OID,
    SIMBAD_TYPE,
    WDS,
    WDS_ID,
)
from space_map_data.extrasolar.systems.reduce import (
    POINT,
    Interior,
    Reduced,
    TreeReducer,
)
from space_map_data.extrasolar.systems.resolve import (
    LETTER,
    MATCH,
    POSITION,
    Facts,
    Resolver,
    candidates,
    flatten_ids,
    resolve_ids,
)
from space_map_data.extrasolar.systems.simbad import SimbadIndex
from space_map_data.extrasolar.systems.wds import WdsCatalogue

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


def _rank(source: str) -> int:
    return INTERIOR_SOURCES.index(source)


def _ids_by_row(table: pa.Table, kind: tuple[str, str]) -> dict[int, str]:
    rows, catalogue, release, value = flatten_ids(table)
    picked = pc.and_(pc.equal(catalogue, kind[0]), pc.equal(release, kind[1]))
    picked = picked.fill_null(False).to_numpy(zero_copy_only=False)
    return dict(zip(rows[picked].tolist(), value.filter(pa.array(picked)).to_pylist()))


def letter_links(
    msc: pa.Table | None,
    wds: pa.Table | None,
    found: dict[str, list[list[tuple[int, int]]]],
) -> dict[tuple[str, str, str], tuple[int, int]]:
    """Links between the MSC and WDS components of one WDS id and letter.

    Each takes the other's best candidate as a candidate of its own, below
    its own ids. A WDS component lends none when its Gaia id is on another
    letter of its WDS id too.
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
    for row, text in wds_ids.items():
        other = msc_by.get(text)
        if other is None:
            continue
        mine, theirs = found[WDS][row], found[MSC][other]
        if theirs:
            links[(*WDS_ID, text)] = (theirs[0][0], LETTER)
        # A Gaia id on several letters is the light of a close pair.
        source = gaia.get(row)
        shared = source is not None and repeated[(systems[row], source)] > 1
        if mine and not shared:
            links[(*MSC_ID, msc_ids[other])] = (mine[0][0], LETTER)
    return links


def match_rows(table: pa.Table, found: list[list[tuple[int, int]]]) -> pa.Table:
    """The MATCH rows of the leaves of `table` that have no candidate."""
    parent = table["parent"].to_numpy()
    leaf = np.ones(table.num_rows, bool)
    leaf[parent[parent >= 0]] = False
    free = np.array([not items for items in found], bool) & leaf
    free &= table["ra"].is_valid().to_numpy(zero_copy_only=False)
    free &= table["epoch"].is_valid().to_numpy(zero_copy_only=False)
    rows = table.filter(pa.array(free))
    ids = _ids_by_row(rows, WDS_ID)
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
        },
        schema=MATCH,
    )


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


def planet_periods(planets: pa.Table | None) -> dict[int, list[float]]:
    found: dict[int, list[float]] = defaultdict(list)
    if planets is None:
        return found
    for host, period in zip(planets["host"].to_pylist(), planets["period"].to_pylist()):
        if host and period:
            found[host].append(period)
    return found


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
            if abs(found - period[at]) / max(found, period[at]) < PERIOD_TOLERANCE:
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
    dropped: dict[int, str]
    counts: Counter


def prepare(inputs: Inputs, resolver: Resolver) -> Prepared:
    counts: Counter = Counter()
    trees: list[pa.Table] = []
    for table in (inputs.msc, inputs.simbad, inputs.planet_systems):
        if table is not None and table.num_rows:
            trees.append(table)
    if inputs.wds is not None:
        trees.append(inputs.wds.nodes(inputs.refuted))
    for table in trees:
        counts[f"{table['source'][0].as_py()}: nodes"] = table.num_rows
    index = inputs.simbad_index or SimbadIndex.empty()

    # Planets that are stars of a star catalogue leave the trees.
    dropped: dict[int, str] = {}
    if inputs.planets is not None and inputs.planets.num_rows:
        rows, catalogue, release, value = flatten_ids(inputs.planets, "star_ids")
        wanted: dict[tuple[str, str], set[str]] = defaultdict(set)
        for c, r, v in zip(
            catalogue.to_pylist(), release.to_pylist(), value.to_pylist()
        ):
            wanted[(c, r)].add(v)
        keys = resolve_ids(resolver, wanted)
        names = inputs.planets["designation"].to_pylist()
        hosts = inputs.planets["host"].to_pylist()
        for row, c, r, v in zip(
            rows.tolist(), catalogue.to_pylist(), release.to_pylist(), value.to_pylist()
        ):
            key = keys.get((c, r, v))
            if key and key != hosts[row]:
                dropped.setdefault(key, names[row])

    by_source = {table["source"][0].as_py(): table for table in trees}
    found_lists = candidates(trees, resolver, index, {})
    found = dict(zip(by_source, found_lists))
    _add_links(
        trees, found, letter_links(by_source.get(MSC), by_source.get(WDS), found)
    )
    if WDS in by_source:
        rows = match_rows(by_source[WDS], found[WDS])
        counts[f"{WDS}: members sent to match by position"] = rows.num_rows
        matched = resolver.match(rows) if rows.num_rows else np.zeros(0, np.int64)
        positions = {
            (*WDS_ID, text): (key, POSITION)
            for text, key in zip(rows["catalogue_id"].to_pylist(), matched.tolist())
            if key and text
        }
        _add_links(trees, found, positions)

    el_keys = (np.zeros(0, np.int64), np.zeros(0, np.int64))
    if inputs.el_badry is not None:
        el_keys = pair_keys(inputs.el_badry, resolver)
    orbit_keys = np.zeros(0, np.int64)
    if inputs.orbits is not None:
        orbit_keys, _ = pair_keys(inputs.orbits, resolver)
    close = close_type_keys(inputs.simbad_index, resolver)

    wanted_keys = {k for items in found.values() for row in items for k, _ in row}
    wanted_keys |= set(close) | set(dropped)
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

    reduced = Reduced()
    offsets = []
    offset = 0
    dropped_keys = frozenset(dropped)
    for table in trees:
        source = table["source"][0].as_py()
        offsets.append(offset)
        TreeReducer(
            table,
            _rank(source),
            found[source],
            facts,
            offset,
            reduced,
            dropped_keys,
        ).run()
        offset += VALUE_BLOCK
    periods = planet_periods(inputs.planets)
    orbit_kept = np.zeros(orbit_keys.size, bool)
    if inputs.orbits is not None:
        orbit_kept = orbit_interiors(inputs.orbits, orbit_keys, periods, reduced)
        orbit_kept &= ~np.isin(orbit_keys, list(dropped_keys))
    remap = _absorptions(reduced)
    _apply(reduced, remap)
    el_keys = (_mapped(el_keys[0], remap), _mapped(el_keys[1], remap))
    orbit_keys = _mapped(orbit_keys, remap)
    for side in el_keys:
        side[np.isin(side, list(dropped_keys))] = 0
    sets, origin = _set_table(reduced, inputs.el_badry, el_keys, counts)
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


def _set_table(
    reduced: Reduced,
    el_badry: pa.Table | None,
    el_keys: tuple[np.ndarray, np.ndarray],
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
        pick = np.flatnonzero(both | one)
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
    return float(sky_separation(a.ra, a.dec, b.ra, b.dec))


def close_interiors(
    prepared: Prepared, system_of: dict[int, int], points_of: dict[int, list[int]]
) -> list[Interior]:
    """Two stars for each close-pair point with no interior that no companion
    explains."""
    have = {interior.key for interior in prepared.reduced.interiors}
    have |= set(prepared.orbit_keys[prepared.orbit_kept].tolist())
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
