"""The groups of all sources merged into one tree per system.

A group is a set of points. The sets that share a point are one system. Within
a system, the sets go in source order, and a set stays when it nests with
every set before it: it holds the other, or the other holds it. So a level
that one source lacks and another has stays (ε Lyr AB+CD of the MSC over
El-Badry's AB and CD). A set that crosses an earlier one is a conflict: it is
left out and logged with the set it crosses. A set that joins two systems
that earlier sets made is a merge, and is logged with both.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import pairwise

import numpy as np

logger = logging.getLogger(__name__)


def components(size: int, first: np.ndarray, second: np.ndarray) -> np.ndarray:
    """The component of each of `size` items that the edges link, as the
    lowest item of the component."""
    parent = np.arange(size, dtype=np.int64)

    def roots(items: np.ndarray) -> np.ndarray:
        while True:
            up = parent[items]
            if np.array_equal(up, items):
                return items
            items = up

    while first.size:
        a, b = roots(first), roots(second)
        apart = a != b
        if not apart.any():
            break
        low, high = np.minimum(a[apart], b[apart]), np.maximum(a[apart], b[apart])
        np.minimum.at(parent, high, low)
        while True:
            jumped = parent[parent]
            if np.array_equal(jumped, parent):
                break
            parent = jumped
        first, second = first[apart], second[apart]
    return roots(np.arange(size, dtype=np.int64))


@dataclass
class SetTable:
    """The sets of all sources, as arrays over the sets."""

    rank: np.ndarray
    # The (source, system) of each set as one number.
    tree: np.ndarray
    # The keys of set s are keys[start[s]:start[s + 1]].
    start: np.ndarray
    keys: np.ndarray
    names: list[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        return self.rank.size

    def of(self, s: int) -> frozenset[int]:
        return frozenset(self.keys[self.start[s] : self.start[s + 1]].tolist())


@dataclass
class Merged:
    # Over the sets: whether a set stays, and its system (-1 when not).
    accepted: np.ndarray
    system: np.ndarray
    # (kind, text) of each conflict and merge.
    events: list[tuple[str, str]]


def merge(sets: SetTable) -> Merged:
    n = sets.size
    if not n:
        return Merged(np.zeros(0, bool), np.zeros(0, np.int64), [])
    counts = np.diff(sets.start)
    owner = np.repeat(np.arange(n), counts)
    unique, key_index = np.unique(sets.keys, return_inverse=True)
    firsts = key_index[sets.start[:-1][counts > 0]]
    first_of_set = np.full(n, -1, np.int64)
    first_of_set[counts > 0] = firsts
    edge_first = first_of_set[owner]
    component = components(unique.size, edge_first, key_index)
    set_component = np.where(
        first_of_set >= 0, component[np.maximum(first_of_set, 0)], -1
    )

    accepted = np.zeros(n, bool)
    system = np.full(n, -1, np.int64)
    events: list[tuple[str, str]] = []
    order = np.lexsort((np.arange(n), set_component))
    sorted_component = set_component[order]
    bounds = np.flatnonzero(
        np.r_[True, sorted_component[1:] != sorted_component[:-1], True]
    )
    for low, high in pairwise(bounds):
        members = order[low:high]
        if sorted_component[low] < 0:
            continue
        if members.size == 1:
            accepted[members] = True
            system[members] = sorted_component[low]
            continue
        _merge_one(sets, members, unique, accepted, system, events)
    logger.info(
        "systems merge: %d sets, %d kept, %d events",
        n,
        int(accepted.sum()),
        len(events),
    )
    return Merged(accepted, system, events)


def _merge_one(
    sets: SetTable,
    members: np.ndarray,
    unique: np.ndarray,
    accepted: np.ndarray,
    system: np.ndarray,
    events: list[tuple[str, str]],
) -> None:
    keyed = {int(s): sets.of(int(s)) for s in members.tolist()}
    order = sorted(keyed, key=lambda s: (sets.rank[s], sets.tree[s], -len(keyed[s]), s))
    by_key: dict[int, list[int]] = defaultdict(list)
    # A union-find over the kept sets, with the keys of each root.
    parent: dict[int, int] = {}
    held: dict[int, set[int]] = {}

    def find(s: int) -> int:
        while parent[s] != s:
            parent[s] = parent[parent[s]]
            s = parent[s]
        return s

    for s in order:
        mine = keyed[s]
        touching = {t for key in mine for t in by_key[key]}
        crossing = [
            t for t in sorted(touching) if not (mine <= keyed[t] or keyed[t] <= mine)
        ]
        if crossing:
            t = crossing[0]
            events.append(
                (
                    "conflict",
                    (
                        f"{sets.names[s]} crosses {sets.names[t]}: shares"
                        f" {sorted(mine & keyed[t])}, left out"
                    ),
                )
            )
            continue
        accepted[s] = True
        parent[s] = s
        held[s] = set(mine)
        roots = sorted({find(t) for t in touching})
        systems = [r for r in roots if len(held[r]) > 1]
        if len(systems) > 1:
            events.append(
                (
                    "merge",
                    f"{sets.names[s]} joins "
                    + " and ".join(sets.names[r] for r in systems),
                )
            )
        for r in roots:
            parent[r] = s
            held[s] |= held.pop(r)
        for key in mine:
            by_key[key].append(s)
    for s in keyed:
        if accepted[s]:
            system[s] = int(np.searchsorted(unique, min(held[find(s)])))
