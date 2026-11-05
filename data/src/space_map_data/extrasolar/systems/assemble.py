"""The nodes, members and decisions of the merged systems.

A node is a point that holds two or more stars, or a resolved system: a set
of points that no point holds. A resolved system's members are its inner
systems, its points that hold one star, and its entries. Its class is
"binary star" for two stars and "multiple star" for three or more. Its
position is that of its primary member, the first in the order of its first
source, down to a point.

The decisions for the ingest:
- an entry that is a star of its system already leaves, so each star is
  listed once: an entry, of a node or inside a point, that is another point,
  or an entry of a node with the WDS component id of an entry inside a
  point, as the WDS and the MSC can give one star inside the point and
  beside it, unless their separations make it two stars. A node left with
  one member is that member;
- a composite spectral type of a point that holds one star moves to its
  system, and the point takes its own type from the trees, else none;
- the points of a system of two or more points share a distance (`distance`);
- a circumbinary planet's host is the point that holds both stars, else the
  pair's node;
- the names of a resolved system: SIMBAD's name of the system object, then
  the WDS designation. A Wikidata label goes first when the ingest finds an
  item about the system through the lookup ids.
"""

import logging
import math
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from space_map_data.constants.stars.families import COMPOSITE_SPECTRAL_TYPE
from space_map_data.extrasolar.sources.simbad import designation, normal
from space_map_data.extrasolar.systems.distance import (
    shared_distances,
)
from space_map_data.extrasolar.systems.merge import Merged
from space_map_data.extrasolar.systems.nodes import (
    EL_BADRY,
    EL_BADRY_PAIR,
    GAIA_DR3,
    GAIA_ORBITS,
    INTERIOR_SOURCES,
    MSC_ID,
    PARALLAX,
    PLANETS,
    PROPER_MOTION,
    SIMBAD,
    SIMBAD_OID,
    SYSTEM_CATALOGUES,
    WDS,
    WDS_ID,
    id_lists,
)
from space_map_data.extrasolar.systems.prepare import (
    VALUE_BLOCK,
    Inputs,
    Prepared,
    close_interiors,
    evidence_interiors,
    offset,
)
from space_map_data.extrasolar.systems.reduce import (
    ENTRY,
    GROUP,
    POINT,
    Interior,
)
from space_map_data.extrasolar.systems.resolve import GAIA_ASTROMETRY, Fact
from space_map_data.extrasolar.systems.simbad import LETTER
from space_map_data.extrasolar.tables import CROSS_ID

logger = logging.getLogger(__name__)

BINARY, MULTIPLE = "binary star", "multiple star"
NODE_CLASSES = (BINARY, MULTIPLE)
# An entry is a point of its system when they agree, measured from the
# entry's primary. Each test is a tier, and the best tier wins, then the
# smaller separation residual, then the smaller magnitude residual:
# 0. The separation agrees within SAME_SEPARATION arcsec or SAME_SHARE of the
#    entry's, and the position angle within SAME_ANGLE deg.
# 1. The same, with the angle turned by 180 deg. The catalogues can swap the
#    two stars of a pair.
# 2. The separation agrees within ORBIT_SHARE of the larger separation, at
#    least SAME_SEPARATION and at most ORBIT_SEPARATION arcsec, and the
#    magnitude within SAME_MAG. An orbit moves a pair between the epochs of
#    two catalogues, by an amount that scales with the separation.
# 3. The same, where both positions are from Gaia and the angle disagrees.
#    The magnitude must agree within GAIA_MAG, and no other point of the
#    system can be at that separation.
SAME_SEPARATION = 0.15
SAME_SHARE = 0.2
SAME_ANGLE = 10.0
ORBIT_SHARE = 0.5
ORBIT_SEPARATION = 2.0
SAME_MAG = 1.0
GAIA_MAG = 0.5
STAR, SYSTEM = "star", "system"
# An entry with an ID: a star with no point of its own (`drawn`).
HELD = "held star"

VALUES = pa.schema(
    [
        ("source", pa.string()),
        ("label", pa.string()),
        ("spectral_type", pa.string()),
        ("v_mag", pa.float32()),
        ("g_mag", pa.float32()),
        ("mass", pa.float32()),
        ("separation", pa.float64()),
        ("position_angle", pa.float32()),
        ("period", pa.float64()),
        ("eccentricity", pa.float32()),
        ("semi_major_axis", pa.float32()),
        ("known", pa.list_(pa.string())),
        ("ids", pa.list_(CROSS_ID)),
    ]
)
NODES = pa.schema(
    [
        ("node", pa.int64()),
        # The point's object, 0 for a resolved system (a new System ID).
        ("key", pa.int64()),
        ("parent", pa.int64()),
        ("root", pa.int64()),
        ("depth", pa.int16()),
        ("point", pa.bool_()),
        ("stars", pa.int32()),
        ("class", pa.string()),
        ("primary", pa.int64()),
        # J2016.0 ICRS of the primary point, and the node's distance in pc.
        ("ra", pa.float64()),
        ("dec", pa.float64()),
        ("distance", pa.float64()),
        ("label", pa.string()),
        ("catalogue_ids", pa.list_(CROSS_ID)),
        ("sources", pa.list_(pa.string())),
        ("spectral_type", pa.string()),
        # A point: the source of its interior.
        ("evidence", pa.string()),
    ]
)
MEMBERS = pa.schema(
    [
        ("node", pa.int64()),
        ("kind", pa.string()),
        ("key", pa.int64()),
        ("member", pa.int64()),
        ("letter", pa.string()),
        ("inner", pa.string()),
        *VALUES,
    ]
)
POINTS = pa.schema(
    [
        ("key", pa.int64()),
        # Its node when it holds two or more stars, else 0.
        ("node", pa.int64()),
        ("parent", pa.int64()),
        ("root", pa.int64()),
        ("stars", pa.int32()),
        ("spectral_type_before", pa.string()),
        ("spectral_type", pa.string()),
        ("spectral_type_moved", pa.bool_()),
        ("name", pa.string()),
    ]
)
ABSORBED = pa.schema(
    [
        ("key", pa.int64()),
        ("into", pa.int64()),
        ("source", pa.string()),
        ("evidence", pa.string()),
    ]
)
HOSTS = pa.schema(
    [
        ("host", pa.int64()),
        ("number", pa.uint16()),
        ("designation", pa.string()),
        ("node", pa.int64()),
        # The point that holds the pair, else 0 for a resolved pair.
        ("key", pa.int64()),
    ]
)
OVERLAPS = pa.schema(
    [
        ("key", pa.int64()),
        # The row of `Inputs.planets`.
        ("record", pa.int64()),
        ("designation", pa.string()),
        ("host", pa.int64()),
        ("class", pa.string()),
        ("mass", pa.float64()),
        ("period", pa.float64()),
        ("name", pa.string()),
        # What happens to the star (`prepare.Overlap`).
        ("outcome", pa.string()),
    ]
)
NAMES = pa.schema(
    [
        ("node", pa.int64()),
        ("rank", pa.int16()),
        ("source", pa.string()),
        ("name", pa.string()),
        # Ids through which a Wikidata item can be about the system.
        ("lookup", pa.list_(CROSS_ID)),
    ]
)
EVENTS = pa.schema(
    [("kind", pa.string()), ("source", pa.string()), ("text", pa.string())]
)


@dataclass
class Systems:
    nodes: pa.Table
    members: pa.Table
    points: pa.Table
    absorbed: pa.Table
    distances: pa.Table
    hosts: pa.Table
    overlaps: pa.Table
    names: pa.Table
    events: pa.Table
    counts: Counter
    # The object of each Gaia DR3 orbit of `Inputs.orbits`. It is 0 for none,
    # and for an orbit of a planet or a companion under 13 MJ: no pair's.
    orbit_keys: np.ndarray = field(default_factory=lambda: np.zeros(0, np.int64))
    # The component ids that name a star of the MSC and another of the WDS.
    two_stars: frozenset[str] = frozenset()


@dataclass
class _Node:
    keys: frozenset[int]
    attesting: list[int]
    parent: _Node | None = None
    children: list[_Node] = field(default_factory=list)
    number: int = 0
    # (kind, key, child, value, inner) in member order.
    members: list[tuple[str, int, _Node | None, int, str | None]] = field(
        default_factory=list
    )
    stars: int = 0
    primary: int = 0


class _Listed:
    """The points that each source lists in each system, by source rank."""

    def __init__(self, keys: np.ndarray, systems: np.ndarray, ranks: np.ndarray):
        order = np.lexsort((ranks, systems))
        self.keys, self.systems = keys[order], systems[order]
        self.ranks = ranks[order]

    def of(self, system: int) -> dict[int, set[int]]:
        low, high = np.searchsorted(self.systems, [system, system + 1]).tolist()
        found: dict[int, set[int]] = defaultdict(set)
        for key, rank in zip(
            self.keys[low:high].tolist(), self.ranks[low:high].tolist()
        ):
            found[rank].add(key)
        return found


class Assembler:
    def __init__(self, prepared: Prepared, merged: Merged, inputs: Inputs) -> None:
        self.p = prepared
        self.merged = merged
        self.inputs = inputs
        self.facts = prepared.facts
        self.groups = prepared.reduced.groups
        self.trees = prepared.tables
        self.el_block = len(self.trees) * VALUE_BLOCK
        self.orbit_block = self.el_block + VALUE_BLOCK
        self.events: list[tuple[str, str, str]] = list(prepared.reduced.events)
        self.events += [(kind, "merge", text) for kind, text in merged.events]
        self.counts = prepared.counts
        self._columns: dict[int, dict[str, list]] = {}
        # The entries that leave each kept interior, with the point each is.
        self.left_out: dict[int, list[tuple[int, int]]] = {}

    # Values of members

    def _tree_column(self, table: int, name: str) -> list:
        cache = self._columns.setdefault(table, {})
        if name not in cache:
            cache[name] = self.trees[table][name].to_pylist()
        return cache[name]

    def value(self, ref: int, name: str):
        if ref < 0:
            return None
        if ref < self.el_block:
            return self._tree_column(ref // VALUE_BLOCK, name)[ref % VALUE_BLOCK]
        return None

    def values(self, refs: np.ndarray) -> pa.Table:
        """The VALUES rows of these refs."""
        refs = np.asarray(refs, np.int64)
        parts = []
        index = np.arange(refs.size)
        order_parts = []
        tree = (refs >= 0) & (refs < self.el_block)
        for table in range(len(self.trees)):
            pick = tree & (refs // VALUE_BLOCK == table)
            if not pick.any():
                continue
            rows = refs[pick] % VALUE_BLOCK
            source = self.trees[table].take(pa.array(rows))
            parts.append(source.select([n for n in VALUES.names]).cast(VALUES))
            order_parts.append(index[pick])
        for block, table, maker in (
            (self.el_block, self.p.el_badry, _el_badry_values),
            (self.orbit_block, self.p.orbits, _orbit_values),
        ):
            pick = (refs >= block) & (refs < block + VALUE_BLOCK)
            if pick.any() and table is not None:
                local = refs[pick] - block
                parts.append(maker(table, local // 2, local % 2))
                order_parts.append(index[pick])
        none = refs < 0
        if none.any():
            parts.append(
                pa.table(
                    {f.name: pa.nulls(int(none.sum()), f.type) for f in VALUES},
                    schema=VALUES,
                )
            )
            order_parts.append(index[none])
        if not parts:
            return VALUES.empty_table()
        joined = pa.concat_tables(parts)
        order = np.argsort(np.concatenate(order_parts), kind="stable")
        return joined.take(pa.array(order))

    # Interiors

    def interiors(self) -> dict[int, Interior | int]:
        """The chosen interior of each point: an Interior, or an orbit row.

        An interior of unverified members comes after the others, then the
        source rank decides.
        """
        chosen: dict[int, tuple[tuple[bool, int], Interior | int]] = {}
        for interior in self.p.reduced.interiors:
            order = (interior.unverified, interior.rank)
            best = chosen.get(interior.key)
            if best is None or order < best[0]:
                chosen[interior.key] = (order, interior)
        order = (False, INTERIOR_SOURCES.index(GAIA_ORBITS))
        kept = np.flatnonzero(self.p.orbit_kept)
        for row, key in zip(kept.tolist(), self.p.orbit_keys[kept].tolist()):
            best = chosen.get(key)
            if best is None or order < best[0]:
                chosen[key] = (order, row)
        given: Counter[str] = Counter()
        for interior in self.p.reduced.interiors:
            unverified, rank = chosen[interior.key][0]
            if interior.unverified and not unverified and rank > interior.rank:
                given[interior.source] += 1
        for source, value in given.items():
            self.counts[f"{source}: interiors of unverified members that give way"] = (
                value
            )
        counts = Counter(INTERIOR_SOURCES[rank] for (_, rank), _ in chosen.values())
        for source, value in counts.items():
            self.counts[f"points holding several stars, by {source}"] = value
        for _, item in chosen.values():
            for ref, point in self.left_out.get(id(item), ()):
                self._log_point(ref, point)
        return {key: item for key, (_, item) in chosen.items()}

    def _circumbinary(self, in_systems: np.ndarray) -> list[Interior]:
        """Two stars for the host of a circumbinary planet that is in no tree
        and holds no interior: the planet orbits a pair inside that point."""
        planets = self.inputs.planets
        if planets is None:
            return []
        circling = pc.equal(planets["binary_type"], "P-type").fill_null(False)
        hosts = set(planets.filter(circling)["host"].to_pylist()) - {None, 0}
        have = evidence_interiors(self.p)
        alone = sorted(hosts - have - set(np.unique(in_systems).tolist()))
        rank = INTERIOR_SOURCES.index(PLANETS)
        self.counts[
            f"{PLANETS}: points that hold the pair of a circumbinary planet"
        ] = len(alone)
        return [
            Interior(
                key, PLANETS, rank, "circumbinary planet", [(-1, None), (-1, None)]
            )
            for key in alone
        ]

    def entry_count(self, item: Interior | int) -> int:
        return 2 if isinstance(item, int) else len(item.entries)

    def _known_interiors(self, system_of: dict[int, int], listed: _Listed) -> None:
        """Leave out the entries of each interior that are another point of
        its system. An interior with one entry left goes, so its point takes
        its next interior, if any.

        `system_of` gives the system of each point in one.
        """
        kept = []
        for item in self.p.reduced.interiors:
            system = system_of.get(item.key)
            if system is None:
                kept.append(item)
                continue
            ranks = listed.of(system)
            # A point that the interior's source lists is another star.
            others = sorted(
                set().union(*ranks.values()) - ranks[item.rank] - {item.key}
            )
            found = [
                (e, self._same_point(e[0], item.key, others)) for e in item.entries
            ]
            entries = [e for e, point in found if not point]
            if len(entries) > 1:
                item = replace(item, entries=entries)
                self.left_out[id(item)] = [(e[0], p) for e, p in found if p]
                kept.append(item)
            elif len(entries) < len(item.entries):
                self.counts["interiors of one star once an entry leaves"] += 1
            else:
                kept.append(item)
        self.p.reduced.interiors = kept

    # Systems

    def run(self) -> Systems:
        accepted = np.flatnonzero(self.merged.accepted)
        system = self.merged.system[accepted]
        order = np.lexsort((accepted, system))
        accepted, system = accepted[order], system[order]
        bounds = np.flatnonzero(np.r_[True, system[1:] != system[:-1], True])
        if not accepted.size:
            bounds = np.zeros(1, np.int64)
        origin = self.p.origin
        sizes = np.diff(bounds)
        firsts = accepted[bounds[:-1]]
        single = (sizes == 1) & (origin[firsts] < 0)
        lone_sets = firsts[single]
        python_systems = [
            (int(system[low]), accepted[low:high].tolist())
            for low, high, alone in zip(bounds[:-1], bounds[1:], single)
            if not alone
        ]
        # The keys of each system, for the close-pair rule.
        set_owner = np.repeat(np.arange(self.p.sets.size), np.diff(self.p.sets.start))
        member_system = np.full(self.p.sets.size, -1, np.int64)
        member_system[accepted] = system
        key_system = member_system[set_owner]
        in_system = key_system >= 0
        sys_keys = self.p.sets.keys[in_system]
        sys_ids = key_system[in_system]
        listed = _Listed(sys_keys, sys_ids, self.p.sets.rank[set_owner][in_system])
        held = np.array([item.key for item in self.p.reduced.interiors], np.int64)
        hit = np.isin(sys_keys, held)
        self._known_interiors(
            dict(zip(sys_keys[hit].tolist(), sys_ids[hit].tolist())), listed
        )
        close = np.array(sorted(self.p.close), np.int64)
        system_of: dict[int, int] = {}
        if close.size:
            hit = np.isin(sys_keys, close)
            system_of = dict(zip(sys_keys[hit].tolist(), sys_ids[hit].tolist()))
        wanted = set(system_of.values())
        points_of: dict[int, list[int]] = defaultdict(list)
        if wanted:
            hit = np.isin(sys_ids, list(wanted))
            for key, sid in zip(sys_keys[hit].tolist(), sys_ids[hit].tolist()):
                if key not in points_of[sid]:
                    points_of[sid].append(key)
        self.p.reduced.interiors += close_interiors(self.p, system_of, points_of)
        self.p.reduced.interiors += self._circumbinary(sys_keys)
        self.chosen = self.interiors()
        logger.info(
            "systems: %d interiors, %d systems of several sets, %d lone pairs",
            len(self.chosen),
            len(python_systems),
            lone_sets.size,
        )

        self.rows: list[dict] = []
        self.node_spectral: dict[int, str] = {}
        self.member_rows: dict[str, list] = defaultdict(list)
        self.point_nodes: dict[int, int] = {}
        self.next_node = 1
        for key in sorted(self.chosen):
            self.point_nodes[key] = self.next_node
            self.next_node += 1
        self.point_parent: dict[int, int] = {}
        self.point_root: dict[int, int] = {}
        self.moved: dict[int, tuple[int, str | None]] = {}
        self.names_rows: list[tuple[int, int, str, str, list]] = []
        started = time.monotonic()
        for sid, sets in python_systems:
            self._system(sets, listed.of(sid))
        logger.info("systems: trees in %.0f s", time.monotonic() - started)
        self._lone_pairs(lone_sets)
        self._point_nodes()
        systems = self._finish()
        logger.info("systems: assembled in %.0f s", time.monotonic() - started)
        return systems

    def _system(self, set_ids: list[int], listed: dict[int, set[int]]) -> None:
        """Build the system of `set_ids`. `listed` gives the points that each
        source lists in it, by source rank."""
        keyed: dict[frozenset[int], list[int]] = defaultdict(list)
        for s in set_ids:
            keyed[self.p.sets.of(s)].append(s)
        nodes = [
            _Node(keys, sorted(sets, key=lambda s: (self.p.sets.rank[s], s)))
            for keys, sets in keyed.items()
        ]
        nodes.sort(key=lambda n: (-len(n.keys), self.p.sets.rank[n.attesting[0]]))
        for at, node in enumerate(nodes):
            holders = [n for n in nodes[:at] if node.keys < n.keys]
            if holders:
                node.parent = min(holders, key=lambda n: len(n.keys))
                node.parent.children.append(node)
        roots = [n for n in nodes if n.parent is None]
        if len(roots) != 1:
            self.events.append(
                (
                    "several roots",
                    "merge",
                    f"{len(roots)} roots: {[sorted(r.keys) for r in roots]}",
                )
            )
        for root in roots:
            self._order(root, listed)
            # A root of one member, once entries leave, is that member.
            while len(root.members) == 1 and root.members[0][2] is not None:
                root = root.members[0][2]
            if len(root.members) == 1:
                self.counts["systems that are one point once entries leave"] += 1
                continue
            self._emit(root, 0, 0, 0)

    def _order(self, node: _Node, listed: dict[int, set[int]]) -> None:
        """The members of a node in the order of its first source."""
        for child in node.children:
            self._order(child, listed)
        covered: set[int] = set()
        members: list[tuple[str, int, _Node | None, int, str | None]] = []

        def child_of(key: int) -> _Node | None:
            return next((c for c in node.children if key in c.keys), None)

        def add_key(key: int, value: int) -> None:
            child = child_of(key)
            if child is not None and len(child.members) == 1:
                # A node that holds one member is that member, all of it.
                if key not in covered:
                    members.append(child.members[0])
                covered.update(child.keys)
            elif child is not None:
                if not any(m[2] is child for m in members):
                    members.append(
                        (SYSTEM, 0, child, self._value_of(node, child), None)
                    )
                covered.update(child.keys)
            elif key not in covered:
                members.append((POINT, key, None, value, None))
                covered.add(key)

        top = node.attesting[0]
        origin = int(self.p.origin[top])
        if origin >= 0:
            group = self.groups[origin]
            for member in group.members:
                if member.kind == POINT:
                    add_key(member.key, member.value)
                elif member.kind == GROUP:
                    for key in self._points_of(member.group):
                        add_key(key, member.value)
                else:
                    members.append((ENTRY, 0, None, member.value, member.inner))
        else:
            pair = -1 - origin
            first, second = self.p.el_badry_keys
            for side, key in ((0, first[pair]), (1, second[pair])):
                ref = self.el_block + 2 * pair + side
                if key:
                    add_key(int(key), ref)
                else:
                    members.append((ENTRY, 0, None, ref, None))
        # Nested groups of one tree with one point set are one node here.
        for other in node.attesting[1:]:
            at = int(self.p.origin[other])
            if at < 0 or self.p.sets.tree[other] != self.p.sets.tree[top]:
                continue
            for member in self.groups[at].members:
                if member.kind == ENTRY and all(m[3] != member.value for m in members):
                    members.append((ENTRY, 0, None, member.value, member.inner))
        rest = sorted(
            (k for k in node.keys if k not in covered),
            key=lambda k: (self._mag(k), k),
        )
        for key in rest:
            add_key(key, self._point_value(node, key))
        node.members = self._known_entries(node, members, listed)

    def _points_of(self, group: int) -> list[int]:
        """The points of a group in its source's order, so its primary is first."""
        points = []
        for member in self.groups[group].members:
            if member.kind == POINT:
                points.append(member.key)
            elif member.kind == GROUP:
                points += self._points_of(member.group)
        return points

    def _known_entries(
        self,
        node: _Node,
        members: list[tuple[str, int, _Node | None, int, str | None]],
        listed: dict[int, set[int]],
    ) -> list[tuple[str, int, _Node | None, int, str | None]]:
        """Leave out the entries that are a star of the system already: a
        point of the system, or a star inside a point that has the same WDS
        component id ("03257+0551 A" of the WDS and of the MSC), unless that
        id names two stars. A point that the entry's source lists is another
        star."""
        top = node
        while top.parent is not None:
            top = top.parent
        inside = self._inside(top.keys)
        primary = _first_point(members)
        kept = []
        for member in members:
            if member[0] != ENTRY:
                kept.append(member)
                continue
            texts = sorted(self._components(member[3]) - self.p.reduced.two_stars)
            point = next((inside[text] for text in texts if text in inside), 0)
            if point:
                self._log_inside(member[3], point)
                continue
            source = self.value(member[3], "source")
            if primary and source is not None:
                own = listed[INTERIOR_SOURCES.index(source)]
                others = sorted(top.keys - own - {primary})
                if self._is_point(member[3], primary, others):
                    continue
            kept.append(member)
        return kept

    def _components(self, ref: int) -> set[str]:
        """The WDS and MSC component ids of a member."""
        return {
            item["catalogue_id"]
            for item in self.value(ref, "ids") or []
            if (item["catalogue"], item["release"]) in (WDS_ID, MSC_ID)
        }

    def _inside(self, keys: frozenset[int]) -> dict[str, int]:
        """The point of each component id of an entry inside one of these
        points."""
        found: dict[str, int] = {}
        for key in sorted(keys):
            item = self.chosen.get(key)
            if isinstance(item, Interior):
                for ref, _ in item.entries:
                    for text in self._components(ref):
                        found.setdefault(text, key)
        return found

    def _log_inside(self, ref: int, point: int) -> None:
        self.counts["entries that a point of the system holds"] += 1
        text = " ".join(
            str(self.value(ref, name)) for name in ("source", "system", "label")
        )
        self.events.append(("entry is in a point", "assemble", f"{text} is in {point}"))

    def _is_point(self, ref: int, primary: int, others: list[int]) -> bool:
        """Whether the entry `ref`, measured from `primary`, is one of
        `others`. Logs each one that is."""
        found = self._same_point(ref, primary, others)
        if found:
            self._log_point(ref, found)
        return bool(found)

    def _log_point(self, ref: int, point: int) -> None:
        self.counts["entries that are a point of the system"] += 1
        text = " ".join(
            str(self.value(ref, name)) for name in ("source", "system", "label")
        )
        self.events.append(("entry is a point", "assemble", f"{text} is {point}"))

    def _same_point(self, ref: int, primary: int, others: list[int]) -> int:
        """The point of `others` that the entry `ref` is, else 0. See the
        tiers at SAME_SEPARATION."""
        separation = self.value(ref, "separation")
        angle = self.value(ref, "position_angle")
        mag = self.value(ref, "g_mag")
        if mag is None:
            mag = self.value(ref, "v_mag")
        first = self.facts.get(primary)
        if not separation or first is None:
            return 0
        near = max(SAME_SEPARATION, SAME_SHARE * separation)
        found: list[tuple[int, float, float, int]] = []
        at_separation = 0
        for other in others:
            fact = self.facts.get(other)
            if fact is None:
                continue
            step = abs(fact.mag - mag) if mag is not None else math.nan
            step = step if math.isfinite(step) else math.inf
            # With no angle, only the magnitude tier is left.
            if angle is None and step > SAME_MAG:
                continue
            apart, towards = offset(first, fact)
            miss = abs(apart - separation)
            far = ORBIT_SHARE * max(apart, separation)
            far = min(ORBIT_SEPARATION, max(SAME_SEPARATION, far))
            if not miss <= max(near, far):
                continue
            at_separation += 1
            moved = miss <= far
            tier = 2 if moved and step <= SAME_MAG else None
            if angle is not None:
                turn = abs(towards - angle) % 360
                turn = min(turn, 360 - turn)
                if turn <= SAME_ANGLE or 180 - turn <= SAME_ANGLE:
                    if miss <= near:
                        tier = 0 if turn <= SAME_ANGLE else 1
                elif _gaia(first) and _gaia(fact):
                    tier = 3 if moved and step <= GAIA_MAG else None
            if tier is not None:
                found.append((tier, miss, step, other))
        found = [f for f in found if f[0] < 3 or at_separation == 1]
        return min(found)[3] if found else 0

    def _mag(self, key: int) -> float:
        fact = self.facts.get(key)
        return fact.mag if fact is not None and math.isfinite(fact.mag) else math.inf

    def _point_value(self, node: _Node, key: int) -> int:
        for s in node.attesting:
            origin = int(self.p.origin[s])
            if origin >= 0:
                for member in self.groups[origin].members:
                    if member.kind == POINT and member.key == key:
                        return member.value
        return -1

    def _value_of(self, node: _Node, child: _Node) -> int:
        for s in node.attesting:
            origin = int(self.p.origin[s])
            if origin < 0:
                continue
            for member in self.groups[origin].members:
                if (
                    member.kind == GROUP
                    and self.groups[member.group].keys == child.keys
                ):
                    return member.value
        return -1

    def _emit(self, node: _Node, parent: int, root: int, depth: int) -> int:
        node.number = self.next_node
        self.next_node += 1
        root = root or node.number
        stars = 0
        for kind, key, child, value, inner in node.members:
            if kind == SYSTEM and child is not None:
                stars += self._emit(child, node.number, root, depth + 1)
            elif kind == POINT:
                item = self.chosen.get(key)
                stars += self.entry_count(item) if item is not None else 1
                self.point_parent[key] = node.number
                self.point_root[key] = root
            else:
                stars += 1
        node.stars = stars
        node.primary = _first_point(node.members)
        fact = self.facts.get(node.primary)
        catalogue_ids, sources, label = self._own_values(node)
        self.rows.append(
            {
                "node": node.number,
                "key": 0,
                "parent": parent,
                "root": root,
                "depth": depth,
                "point": False,
                "stars": stars,
                "class": MULTIPLE if stars > 2 else BINARY,
                "primary": node.primary,
                "ra": fact.ra if fact else None,
                "dec": fact.dec if fact else None,
                "distance": None,
                "label": label,
                "catalogue_ids": catalogue_ids,
                "sources": sources,
                "spectral_type": None,
                "evidence": None,
            }
        )
        for kind, key, child, value, inner in node.members:
            if kind == POINT and key in self.point_nodes:
                self._member(
                    node.number, SYSTEM, key, self.point_nodes[key], value, inner
                )
            elif kind == POINT:
                self._member(node.number, STAR, key, 0, value, inner)
            elif kind == SYSTEM and child is not None:
                self._member(node.number, SYSTEM, 0, child.number, value, inner)
            else:
                self._member(node.number, ENTRY, 0, 0, value, inner)
        self._composites(node)
        self._names(node, catalogue_ids)
        return stars

    def _own_values(self, node: _Node) -> tuple[list[dict], list[str], str | None]:
        ids: list[dict] = []
        sources: list[str] = []
        label = None
        for s in node.attesting:
            origin = int(self.p.origin[s])
            if origin >= 0:
                group = self.groups[origin]
                source = group.source
                if label is None:
                    label = self.value(group.value, "label")
                for item in self.value(group.value, "ids") or []:
                    pair = (item["catalogue"], item["release"])
                    own = pair != SIMBAD_OID or source == SIMBAD
                    if pair in SYSTEM_CATALOGUES and own and item not in ids:
                        ids.append(item)
            else:
                source = EL_BADRY
                assert self.p.el_badry is not None
                text = self.p.el_badry["system"][-1 - origin].as_py()
                ids.append(dict(zip(CROSS_ID.names, (*EL_BADRY_PAIR, text))))
            if source not in sources:
                sources.append(source)
        return ids, sources, label

    def _member(
        self, node: int, kind: str, key: int, member: int, value: int, inner: str | None
    ) -> None:
        self.member_rows["node"].append(node)
        self.member_rows["kind"].append(kind)
        self.member_rows["key"].append(key)
        self.member_rows["member"].append(member)
        self.member_rows["value"].append(value)
        self.member_rows["inner"].append(inner)

    # Decisions on a resolved node

    def _composites(self, node: _Node) -> None:
        for kind, key, _, value, _ in node.members:
            if kind != POINT or key in self.chosen:
                continue
            fact = self.facts.get(key)
            if fact is None or not fact.spectral_type:
                continue
            if not _composite(fact.spectral_type):
                continue
            own = self.value(value, "spectral_type")
            if own and _composite(own):
                own = None
            self.moved[key] = (node.number, own)
            self.node_spectral.setdefault(node.number, fact.spectral_type)

    def _names(self, node: _Node, catalogue_ids: list[dict]) -> None:
        lookup = [
            item
            for item in catalogue_ids
            if (item["catalogue"], item["release"]) in (SIMBAD_OID, WDS_ID)
        ]
        rank = 0
        index = self.inputs.simbad_index
        for item in catalogue_ids:
            pair = (item["catalogue"], item["release"])
            if pair == SIMBAD_OID and index is not None:
                found = index.stars.objects.get(int(item["catalogue_id"]))
                if found is None:
                    continue
                name = system_name(found.identifiers, found.main_id)
                if name:
                    rank += 1
                    self.names_rows.append((node.number, rank, SIMBAD, name, lookup))
        # One WDS designation: the WDS id alone when the node is the root.
        texts = sorted(
            (
                item["catalogue_id"]
                for item in catalogue_ids
                if (item["catalogue"], item["release"]) == WDS_ID
            ),
            key=lambda text: (" " in text, text),
        )
        if texts:
            wds_id, _, label = texts[0].partition(" ")
            self.names_rows.append(
                (node.number, rank + 1, WDS, f"WDS J{wds_id}{label}", lookup)
            )

    # El-Badry pairs alone in their system

    def _lone_pairs(self, sets: np.ndarray) -> None:
        if not sets.size:
            return
        pairs = -1 - self.p.origin[sets]
        first, second = self.p.el_badry_keys
        k1, k2 = first[pairs], second[pairs]
        n = pairs.size
        numbers = self.next_node + np.arange(n, dtype=np.int64)
        self.next_node += n
        mag = self.facts.column("mag", np.concatenate([k1, k2]))
        m1, m2 = mag[:n], mag[n:]
        swap = (
            (k2 != 0)
            & (k1 != 0)
            & (np.nan_to_num(m2, nan=np.inf) < np.nan_to_num(m1, nan=np.inf))
        )
        primary = np.where(swap, k2, np.where(k1 != 0, k1, k2))

        def stars(keys: np.ndarray) -> np.ndarray:
            counts = np.ones(keys.size, np.int64)
            for at, key in enumerate(keys.tolist()):
                if key in self.chosen:
                    counts[at] = self.entry_count(self.chosen[key])
            return counts

        total = stars(k1) + stars(k2)
        ra = self.facts.column("ra", primary)
        dec = self.facts.column("dec", primary)
        assert self.p.el_badry is not None
        systems = self.p.el_badry["system"].take(pa.array(pairs)).combine_chunks()
        self._lone = {
            "node": numbers,
            "stars": total,
            "primary": primary,
            "ra": ra,
            "dec": dec,
            "ids": id_lists([(EL_BADRY_PAIR, systems)], n),
        }
        refs1 = self.el_block + 2 * pairs
        refs2 = refs1 + 1
        self._lone_members = (numbers, k1, k2, refs1, refs2)
        for side in (k1, k2):
            hit = side != 0
            for key, number in zip(side[hit].tolist(), numbers[hit].tolist()):
                self.point_parent[key] = number
                self.point_root[key] = number

    # Points that hold several stars

    def _point_nodes(self) -> None:
        keys = np.array(sorted(self.point_nodes), np.int64)
        self._point_keys = keys

    def _finish(self) -> Systems:
        for row in self.rows:
            row["spectral_type"] = self.node_spectral.get(row["node"])
        tables = [pa.Table.from_pylist(self.rows, schema=NODES)]
        lone = getattr(self, "_lone", None)
        if lone is not None:
            n = lone["node"].size
            stars = lone["stars"]
            tables.append(
                pa.table(
                    {
                        "node": pa.array(lone["node"]),
                        "key": pa.array(np.zeros(n, np.int64)),
                        "parent": pa.array(np.zeros(n, np.int64)),
                        "root": pa.array(lone["node"]),
                        "depth": pa.array(np.zeros(n, np.int16)),
                        "point": pa.array(np.zeros(n, bool)),
                        "stars": pa.array(stars.astype(np.int32)),
                        "class": pa.array(np.where(stars > 2, MULTIPLE, BINARY)),
                        "primary": pa.array(lone["primary"]),
                        "ra": pa.array(lone["ra"], from_pandas=True),
                        "dec": pa.array(lone["dec"], from_pandas=True),
                        "distance": pa.nulls(n, pa.float64()),
                        "label": pa.nulls(n, pa.string()),
                        "catalogue_ids": lone["ids"],
                        "sources": pa.ListArray.from_arrays(
                            pa.array(np.arange(n + 1, dtype=np.int32)),
                            pa.array(np.full(n, EL_BADRY, object), pa.string()),
                        ),
                        "spectral_type": pa.nulls(n, pa.string()),
                        "evidence": pa.nulls(n, pa.string()),
                    },
                    schema=NODES,
                )
            )
        tables.append(self._point_table())
        nodes = pa.concat_tables(tables)
        nodes = self._depths(nodes)
        nodes = nodes.take(pc.sort_indices(nodes["node"]))
        members = self._members_table()
        points = self._points_table(nodes, members)
        shared = shared_distances(nodes, points, self.facts)
        self.counts.update(shared.counts)
        nodes = self._node_distances(nodes, shared.nodes)
        absorbed = pa.table(
            {
                "key": [a.key for a in self.p.reduced.absorbed],
                "into": [a.into for a in self.p.reduced.absorbed],
                "source": [a.source for a in self.p.reduced.absorbed],
                "evidence": [a.evidence for a in self.p.reduced.absorbed],
            },
            schema=ABSORBED,
        )
        hosts = self._hosts(nodes)
        overlaps = self._overlaps()
        names = pa.table(
            {
                name: [row[at] for row in self.names_rows]
                for at, name in enumerate(NAMES.names)
            },
            schema=NAMES,
        )
        self._tentative(points)
        events = pa.table(
            {
                name: [e[at] for e in self.events]
                for at, name in enumerate(EVENTS.names)
            },
            schema=EVENTS,
        )
        return Systems(
            nodes,
            members,
            points,
            absorbed,
            shared.distances,
            hosts,
            overlaps,
            names,
            events,
            self.counts,
            np.where(self.p.orbit_kept, self.p.orbit_keys, 0),
            frozenset(self.p.reduced.two_stars),
        )

    def _point_table(self) -> pa.Table:
        keys = self._point_keys
        n = keys.size
        numbers = np.array([self.point_nodes[k] for k in keys.tolist()], np.int64)
        stars = np.array(
            [self.entry_count(self.chosen[k]) for k in keys.tolist()], np.int32
        )
        parent = np.array(
            [self.point_parent.get(k, 0) for k in keys.tolist()], np.int64
        )
        root = np.array([self.point_root.get(k, 0) for k in keys.tolist()], np.int64)
        root = np.where(root == 0, numbers, root)
        evidence = []
        for key in keys.tolist():
            item = self.chosen[key]
            evidence.append(GAIA_ORBITS if isinstance(item, int) else item.source)
        spectral = self.facts.texts("spectral_type", keys)
        return pa.table(
            {
                "node": pa.array(numbers),
                "key": pa.array(keys),
                "parent": pa.array(parent),
                "root": pa.array(root),
                "depth": pa.array(np.zeros(n, np.int16)),
                "point": pa.array(np.ones(n, bool)),
                "stars": pa.array(stars),
                "class": pa.array(np.where(stars > 2, MULTIPLE, BINARY)),
                "primary": pa.array(keys),
                "ra": pa.array(self.facts.column("ra", keys), from_pandas=True),
                "dec": pa.array(self.facts.column("dec", keys), from_pandas=True),
                "distance": pa.nulls(n, pa.float64()),
                "label": pa.nulls(n, pa.string()),
                "catalogue_ids": pa.nulls(n, pa.list_(CROSS_ID)),
                "sources": pa.array([[e] for e in evidence], pa.list_(pa.string())),
                "spectral_type": pa.array(
                    [s if s and "+" in s else None for s in spectral], pa.string()
                ),
                "evidence": pa.array(evidence, pa.string()),
            },
            schema=NODES,
        )

    def _depths(self, nodes: pa.Table) -> pa.Table:
        """The depth of each node below its root."""
        number = nodes["node"].to_numpy()
        parent = nodes["parent"].to_numpy()
        order = np.argsort(number)
        sorted_number = number[order]
        depth = np.zeros(number.size, np.int16)
        current = parent.copy()
        for _ in range(64):
            has = current != 0
            if not has.any():
                break
            depth[has] += 1
            at = np.searchsorted(sorted_number, current[has])
            current[has] = parent[order[at]]
        return nodes.set_column(
            nodes.schema.get_field_index("depth"), "depth", pa.array(depth)
        )

    def _node_distances(self, nodes: pa.Table, shared: np.ndarray) -> pa.Table:
        """Each node's shared distance, else the distance of its primary."""
        own = self.facts.column("distance", nodes["primary"].to_numpy())
        return nodes.set_column(
            nodes.schema.get_field_index("distance"),
            "distance",
            pa.array(
                np.where(np.isfinite(shared), shared, own),
                pa.float64(),
                from_pandas=True,
            ),
        )

    def _members_table(self) -> pa.Table:
        rows = self.member_rows
        nodes = [np.array(rows["node"], np.int64)]
        kinds: list[str] = list(rows["kind"])
        keys = [np.array(rows["key"], np.int64)]
        members = [np.array(rows["member"], np.int64)]
        values = [np.array(rows["value"], np.int64)]
        inner: list[str | None] = list(rows["inner"])
        lone = getattr(self, "_lone_members", None)
        if lone is not None:
            numbers, k1, k2, refs1, refs2 = lone
            for side, refs in ((k1, refs1), (k2, refs2)):
                held = np.array(
                    [self.point_nodes.get(k, 0) for k in side.tolist()], np.int64
                )
                nodes.append(numbers)
                kinds += [
                    ENTRY if k == 0 else SYSTEM if h else STAR
                    for k, h in zip(side.tolist(), held.tolist())
                ]
                keys.append(side)
                members.append(held)
                values.append(refs)
                inner += [None] * side.size
        # The entries of the points that hold several stars.
        entry_nodes: list[int] = []
        entry_values: list[int] = []
        for point_key in self._point_keys.tolist():
            item = self.chosen[point_key]
            number = self.point_nodes[point_key]
            if isinstance(item, int):
                entry_values += [
                    self.orbit_block + 2 * item,
                    self.orbit_block + 2 * item + 1,
                ]
                inner += [None, None]
                entry_nodes += [number, number]
            else:
                entry_values += [ref for ref, _ in item.entries]
                inner += [label for _, label in item.entries]
                entry_nodes += [number] * len(item.entries)
        nodes.append(np.array(entry_nodes, np.int64))
        kinds += [ENTRY] * len(entry_nodes)
        keys.append(np.zeros(len(entry_nodes), np.int64))
        members.append(np.zeros(len(entry_nodes), np.int64))
        values.append(np.array(entry_values, np.int64))
        found = self.values(np.concatenate(values))
        labels = found["label"].combine_chunks()
        simbad = pc.equal(found["source"], SIMBAD).fill_null(False)
        letter = pc.if_else(
            simbad,
            pc.struct_field(pc.extract_regex(labels, LETTER.pattern), "letter"),
            labels,
        )
        table = pa.table(
            {
                "node": pa.array(np.concatenate(nodes)),
                "kind": pa.array(kinds, pa.string()),
                "key": pa.array(np.concatenate(keys)),
                "member": pa.array(np.concatenate(members)),
                "letter": letter,
                "inner": pa.array(inner, pa.string()),
                **{name: found[name] for name in VALUES.names},
            },
            schema=MEMBERS,
        )
        return table.take(pc.sort_indices(table["node"]))

    def _points_table(self, nodes: pa.Table, members: pa.Table) -> pa.Table:
        """One row per point in a system or holding several stars."""
        picked = pc.not_equal(members["key"], 0)
        keys = np.unique(
            np.r_[members.filter(picked)["key"].to_numpy(), self._point_keys]
        )
        node = np.array([self.point_nodes.get(k, 0) for k in keys.tolist()], np.int64)
        parent = np.array(
            [self.point_parent.get(k, 0) for k in keys.tolist()], np.int64
        )
        root = np.array([self.point_root.get(k, 0) for k in keys.tolist()], np.int64)
        root = np.where(root == 0, node, root)
        stars = np.array(
            [
                self.entry_count(self.chosen[k]) if k in self.chosen else 1
                for k in keys.tolist()
            ],
            np.int32,
        )
        spectral = self.facts.texts("spectral_type", keys)
        own, moved = [], []
        for key, value in zip(keys.tolist(), spectral):
            if key in self.moved:
                own.append(self.moved[key][1])
                moved.append(True)
            else:
                own.append(value)
                moved.append(False)
        return pa.table(
            {
                "key": pa.array(keys),
                "node": pa.array(node),
                "parent": pa.array(parent),
                "root": pa.array(root),
                "stars": pa.array(stars),
                "spectral_type_before": pa.array(spectral, pa.string()),
                "spectral_type": pa.array(own, pa.string()),
                "spectral_type_moved": pa.array(moved),
                "name": pa.array(self.facts.texts("name", keys), pa.string()),
            },
            schema=POINTS,
        )

    def _hosts(self, nodes: pa.Table) -> pa.Table:
        rows: dict[str, list] = defaultdict(list)
        planets = self.inputs.planets
        if planets is not None:
            for planet in planets.to_pylist():
                if planet["binary_type"] != "P-type":
                    continue
                host = planet["host"]
                if (
                    host in self.point_nodes
                    and self.entry_count(self.chosen[host]) >= 2
                ):
                    node, key = self.point_nodes[host], host
                elif host in self.point_parent:
                    node, key = self.point_parent[host], 0
                else:
                    self.counts["circumbinary planets with no pair in a tree"] += 1
                    continue
                for name, value in (
                    ("host", host),
                    ("number", planet["number"]),
                    ("designation", planet["designation"]),
                    ("node", node),
                    ("key", key),
                ):
                    rows[name].append(value)
        return pa.table({name: rows[name] for name in HOSTS.names}, schema=HOSTS)

    def _overlaps(self) -> pa.Table:
        rows: dict[str, list] = defaultdict(list)
        planets = self.inputs.planets
        if planets is None:
            return OVERLAPS.empty_table()
        for item in sorted(self.p.overlaps, key=lambda o: (o.key, o.record)):
            planet = planets.slice(item.record, 1).to_pylist()[0]
            fact = self.facts.get(item.key)
            rows["key"].append(item.key)
            rows["record"].append(item.record)
            rows["designation"].append(planet["designation"])
            rows["host"].append(item.host)
            rows["class"].append(planet["class"])
            rows["mass"].append(planet["mass"])
            rows["period"].append(planet["period"])
            rows["name"].append(fact.name if fact else None)
            rows["outcome"].append(item.outcome)
        return pa.table({name: rows[name] for name in OVERLAPS.names}, schema=OVERLAPS)

    def _tentative(self, points: pa.Table) -> None:
        root = dict(zip(points["key"].to_pylist(), points["root"].to_pylist()))
        for item in self.p.reduced.tentative:
            roots = {root.get(k) for k in item.keys}
            if len(roots) == 1 and None not in roots:
                self.counts[
                    f"{item.source}: {item.evidence} pairs that another source agrees with"
                ] += 1
            else:
                self.counts[f"{item.source}: {item.evidence} pairs left out"] += 1


def _composite(spectral_type: str) -> bool:
    return COMPOSITE_SPECTRAL_TYPE.search(spectral_type) is not None


def _gaia(fact: Fact) -> bool:
    return fact.astrometry in GAIA_ASTROMETRY


def _first_point(members: list[tuple[str, int, _Node | None, int, str | None]]) -> int:
    """The first point of the members, inside a system member too, else 0."""
    for kind, key, child, _, _ in members:
        if kind == POINT:
            return key
        if kind == SYSTEM and child is not None:
            return _first_point(child.members)
    return 0


def system_name(identifiers: list[str], main_id: str) -> str | None:
    """SIMBAD's name of a system object: its shortest NAME without a
    component letter, else its spelled designation."""
    names = [
        normal(text).removeprefix("NAME ")
        for text in identifiers
        if normal(text).startswith("NAME ")
    ]
    names = [n for n in names if not LETTER.search(n)]
    if names:
        return min(names, key=lambda n: (len(n), n))
    return designation(identifiers) or normal(main_id)


def _el_badry_values(pairs: pa.Table, rows: np.ndarray, sides: np.ndarray) -> pa.Table:
    n = rows.size
    take = pa.array(rows)
    g1 = pairs["g_mag1"].take(take).to_numpy(zero_copy_only=False)
    g2 = pairs["g_mag2"].take(take).to_numpy(zero_copy_only=False)
    gaia1 = pairs["gaia1"].take(take).to_numpy(zero_copy_only=False)
    gaia2 = pairs["gaia2"].take(take).to_numpy(zero_copy_only=False)
    separation = pairs["separation"].take(take).to_numpy(zero_copy_only=False)
    second = sides == 1
    ids = id_lists([(GAIA_DR3, pa.array(np.where(second, gaia2, gaia1)))], n)
    return pa.table(
        {
            "source": pa.array([EL_BADRY] * n, pa.string()),
            "label": pa.nulls(n, pa.string()),
            "spectral_type": pa.nulls(n, pa.string()),
            "v_mag": pa.nulls(n, pa.float32()),
            "g_mag": pa.array(np.where(second, g2, g1), pa.float32()),
            "mass": pa.nulls(n, pa.float32()),
            "separation": pa.array(
                np.where(second, separation, np.nan), from_pandas=True
            ),
            "position_angle": pa.nulls(n, pa.float32()),
            "period": pa.nulls(n, pa.float64()),
            "eccentricity": pa.nulls(n, pa.float32()),
            "semi_major_axis": pa.nulls(n, pa.float32()),
            "known": pa.array(
                [[PROPER_MOTION, PARALLAX] if s else None for s in second.tolist()],
                pa.list_(pa.string()),
            ),
            "ids": ids,
        },
        schema=VALUES,
    )


def _orbit_values(orbits: pa.Table, rows: np.ndarray, sides: np.ndarray) -> pa.Table:
    n = rows.size
    take = pa.array(rows)
    second = sides == 1
    m1 = orbits["mass1"].take(take).to_numpy(zero_copy_only=False)
    m2 = orbits["mass2"].take(take).to_numpy(zero_copy_only=False)
    period = orbits["period"].take(take).to_numpy(zero_copy_only=False)
    ecc = orbits["eccentricity"].take(take).to_numpy(zero_copy_only=False)
    known = orbits["known"].take(take).to_pylist()
    return pa.table(
        {
            "source": pa.array([GAIA_ORBITS] * n, pa.string()),
            "label": pa.nulls(n, pa.string()),
            "spectral_type": pa.nulls(n, pa.string()),
            "v_mag": pa.nulls(n, pa.float32()),
            "g_mag": pa.nulls(n, pa.float32()),
            "mass": pa.array(np.where(second, m2, m1), pa.float32(), from_pandas=True),
            "separation": pa.nulls(n, pa.float64()),
            "position_angle": pa.nulls(n, pa.float32()),
            "period": pa.array(np.where(second, period, np.nan), from_pandas=True),
            "eccentricity": pa.array(
                np.where(second, ecc, np.nan), pa.float32(), from_pandas=True
            ),
            "semi_major_axis": pa.nulls(n, pa.float32()),
            "known": pa.array(
                [[k] if s else None for k, s in zip(known, second.tolist())],
                pa.list_(pa.string()),
            ),
            "ids": pa.nulls(n, pa.list_(CROSS_ID)),
        },
        schema=VALUES,
    )


def assemble(prepared: Prepared, merged: Merged, inputs: Inputs) -> Systems:
    return Assembler(prepared, merged, inputs).run()
