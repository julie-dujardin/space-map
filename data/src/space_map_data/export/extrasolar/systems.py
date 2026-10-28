"""The checks of the star systems in the System table.

A node is a System row: a point that holds two or more stars, or a resolved
system. Its members are stars (points that hold one star, with no System
row), nodes, and entries, which have no ID. The export refuses when:

- an ID has two System rows;
- a member star has a System row, a member node has none or names another
  parent, or a row has a parent that is no System row or that does not list
  it;
- an ID is a member of two nodes: a node has one parent, and a star is in one
  system;
- the parents of a node lead to no root (a cycle), or to another root than
  its `root`, or its `depth` does not count the steps;
- a root has no `tree`, another node has one, or a root's tree does not hold
  exactly the nodes with that root, each with its row's parent, point, stars
  and label;
- the primary of a node is not in the node's system;
- in Metadata, a node or a member star has no live row, has another `system`
  than its root (null for the root itself) or a node lacks the System bit of
  `mask`; or an ID that no tree holds has a `system` or the System bit.

The last check runs in the Metadata tiles, which read every Metadata row
anyway. As every row of the export holds an ID that the registry has with the
status the row shows, a live Metadata row means a live ID.
"""

import math
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, fields, replace

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from space_map_data.export.extrasolar.tiles import Problems
from space_map_data.extrasolar.ids import CELL_MASK
from space_map_data.extrasolar.registry import Registry
from space_map_data.extrasolar.sky import REGION_COUNT, region_of
from space_map_data.extrasolar.systems import assemble
from space_map_data.extrasolar.tables import SYSTEM, SYSTEM_TABLE
from space_map_data.utils.arrays import find_sorted

type Runner = Callable[[Callable, list, str], list]

SYSTEM_BIT = 1 << SYSTEM_TABLE
# The member kinds, by their code in `Systems.member_kind`.
KINDS = (assemble.STAR, assemble.SYSTEM, assemble.ENTRY)
STAR, NODE, ENTRY = range(len(KINDS))
UNKNOWN_KIND = len(KINDS)


def _ids(column: pa.ChunkedArray | pa.Array) -> np.ndarray:
    """IDs with 0 for null."""
    return column.fill_null(0).to_numpy().astype(np.int64)


def _kinds(kinds: pa.Array) -> np.ndarray:
    """The code of each member kind."""
    codes = pc.index_in(kinds, value_set=pa.array(KINDS))
    return codes.fill_null(UNKNOWN_KIND).to_numpy().astype(np.uint8)


def _flat(rows: pa.Table, name: str) -> tuple[np.ndarray, pa.StructArray]:
    """The ID of the row of each entry of a list column, and the entries."""
    lists = rows[name].combine_chunks()
    lengths = pc.list_value_length(lists).fill_null(0).to_numpy()
    return np.repeat(rows["id"].to_numpy(), lengths), lists.flatten()


@dataclass(frozen=True)
class Systems:
    """The System rows of the whole sky, sorted by ID (0 for a null ID), then
    their members and their tree entries, flat."""

    id: np.ndarray
    parent: np.ndarray
    root: np.ndarray
    primary: np.ndarray
    depth: np.ndarray
    point: np.ndarray
    stars: np.ndarray
    label: np.ndarray
    has_tree: np.ndarray
    # The node that lists each member.
    member_node: np.ndarray
    member_id: np.ndarray
    # The index of each member's kind in KINDS, UNKNOWN_KIND for another.
    member_kind: np.ndarray
    # The root that holds each tree entry.
    tree_root: np.ndarray
    tree_id: np.ndarray
    tree_parent: np.ndarray
    tree_point: np.ndarray
    tree_stars: np.ndarray
    tree_label: np.ndarray

    @classmethod
    def of(cls, rows: pa.Table) -> Systems:
        """The arrays of some System rows."""
        rows = rows.take(pc.sort_indices(rows["id"]))
        member_node, members = _flat(rows, "members")
        tree_root, tree = _flat(rows, "tree")

        def flags(column) -> np.ndarray:
            return column.fill_null(False).to_numpy(zero_copy_only=False)

        def counts(column) -> np.ndarray:
            return column.fill_null(0).to_numpy().astype(np.int64)

        return cls(
            id=rows["id"].to_numpy(),
            parent=_ids(rows["parent"]),
            root=_ids(rows["root"]),
            primary=_ids(rows["primary"]),
            depth=rows["depth"].fill_null(-1).to_numpy().astype(np.int64),
            point=flags(rows["point"]),
            stars=counts(rows["stars"]),
            label=rows["label"].to_numpy(zero_copy_only=False),
            has_tree=rows["tree"].is_valid().to_numpy(zero_copy_only=False),
            member_node=member_node,
            member_id=_ids(members.field("id")),
            member_kind=_kinds(members.field("kind")),
            tree_root=tree_root,
            tree_id=_ids(tree.field("id")),
            tree_parent=_ids(tree.field("parent")),
            tree_point=flags(tree.field("point")),
            tree_stars=counts(tree.field("stars")),
            tree_label=tree.field("label").to_numpy(zero_copy_only=False),
        )

    @classmethod
    def read(cls, registry: Registry, run: Runner) -> Systems:
        """The System rows of every region."""
        jobs = [(registry, region) for region in range(REGION_COUNT)]
        parts = run(read_region, jobs, "system trees")
        parts = [part for part in parts if part is not None]
        if not parts:
            return cls.of(SYSTEM.schema.empty_table())
        whole = cls(
            *(
                np.concatenate([getattr(part, f.name) for part in parts])
                for f in fields(cls)
            )
        )
        order = np.argsort(whole.id, kind="stable")
        return replace(
            whole, **{name: getattr(whole, name)[order] for name in ROW_FIELDS}
        )

    def check(self) -> Problems:
        problems = Problems()
        ids = self.id
        doubled = np.flatnonzero(ids[1:] == ids[:-1])
        problems.add("System ID with two rows", ids[doubled], doubled.size)
        problems.update(self._check_members())
        problems.update(self._check_roots())
        problems.update(self._check_trees())
        problems.update(self._check_primaries())
        return problems

    def _check_members(self) -> Problems:
        """Members and parents agree, and no ID is a member twice."""
        problems = Problems()
        kind, member, node = self.member_kind, self.member_id, self.member_node
        unknown = kind == UNKNOWN_KIND
        problems.add("member of an unknown kind", node[unknown], int(unknown.sum()))
        entry = kind == ENTRY
        with_id = entry & (member > 0)
        problems.add("entry with an ID", node[with_id], int(with_id.sum()))
        no_id = ~entry & (member == 0)
        problems.add("star or node member with no ID", node[no_id], int(no_id.sum()))
        stars = (kind == STAR) & (find_sorted(self.id, member) >= 0)
        problems.add("member star with a System row", member[stars], int(stars.sum()))
        inner = kind == NODE
        at = find_sorted(self.id, member[inner])
        problems.add(
            "member node with no System row",
            member[inner][at < 0],
            int((at < 0).sum()),
        )
        other = (at >= 0) & (self.parent[np.maximum(at, 0)] != node[inner])
        problems.add(
            "member node whose row names another parent",
            member[inner][other],
            int(other.sum()),
        )
        listed, times = np.unique(member[~entry & (member > 0)], return_counts=True)
        twice = listed[times > 1]
        problems.add("ID that is a member of two nodes", twice, twice.size)
        has_parent = self.parent > 0
        stray = has_parent & (find_sorted(self.id, self.parent) < 0)
        problems.add("parent that is no System row", self.id[stray], int(stray.sum()))
        unlisted = has_parent & ~np.isin(self.id, member[inner])
        problems.add(
            "node that its parent does not list",
            self.id[unlisted],
            int(unlisted.sum()),
        )
        return problems

    def _check_roots(self) -> Problems:
        """No cycle; `root` is the end of the parents, `depth` the steps."""
        problems = Problems()
        ids = self.id
        parent_at = np.where(self.parent > 0, find_sorted(ids, self.parent), -1)
        top = np.where(parent_at >= 0, parent_at, np.arange(ids.size))
        # Each step doubles the parents climbed, so log2(n) + 1 steps reach a
        # root from any depth, and a node in a cycle never does.
        for _ in range(math.ceil(math.log2(max(ids.size, 2))) + 1):
            top = top[top]
        cycle = parent_at[top] >= 0
        problems.add("node in a cycle of parents", ids[cycle], int(cycle.sum()))
        wrong = ~cycle & (self.root != ids[top])
        problems.add(
            "root that is not the end of the node's parents",
            ids[wrong],
            int(wrong.sum()),
        )
        expected = np.where(parent_at >= 0, self.depth[np.maximum(parent_at, 0)] + 1, 0)
        steps = ~cycle & (self.depth != expected)
        problems.add(
            "depth that does not count the steps to the root",
            ids[steps],
            int(steps.sum()),
        )
        return problems

    def _check_trees(self) -> Problems:
        """The root's tree holds every node of its system, as its rows say."""
        problems = Problems()
        ids = self.id
        is_root = self.parent == 0
        bare = is_root & ~self.has_tree
        problems.add("root with no tree", ids[bare], int(bare.sum()))
        extra = ~is_root & self.has_tree
        problems.add("tree on a node that is not a root", ids[extra], int(extra.sum()))
        at = find_sorted(ids, self.tree_id)
        safe = np.maximum(at, 0)
        outside = (at < 0) | (self.root[safe] != self.tree_root)
        problems.add(
            "tree entry that is no node of its root",
            self.tree_id[outside],
            int(outside.sum()),
        )
        unlike = ~outside & (
            (self.parent[safe] != self.tree_parent)
            | (self.point[safe] != self.tree_point)
            | (self.stars[safe] != self.tree_stars)
            | (self.label[safe] != self.tree_label)
        )
        problems.add(
            "tree entry unlike its node's row",
            self.tree_id[unlike],
            int(unlike.sum()),
        )
        entries, times = np.unique(self.tree_id, return_counts=True)
        twice = entries[times > 1]
        problems.add("node twice in the trees", twice, twice.size)
        held = Counter(self.tree_root[~outside].tolist())
        nodes = Counter(self.root[self.root > 0].tolist())
        short = sorted(root for root, count in nodes.items() if held[root] != count)
        problems.add("root whose tree does not hold its nodes", short, len(short))
        return problems

    def _member_stars(self) -> tuple[np.ndarray, np.ndarray]:
        """Each member star with an ID, and the root of the node that lists it."""
        stars = (self.member_kind == STAR) & (self.member_id > 0)
        at = find_sorted(self.id, self.member_node[stars])
        return self.member_id[stars], self.root[np.maximum(at, 0)]

    def _check_primaries(self) -> Problems:
        """The primary is a point of the node's own system."""
        problems = Problems()
        star_ids, star_roots = self._member_stars()
        known = np.concatenate([self.id, star_ids])
        roots = np.concatenate([self.root, star_roots])
        order = np.argsort(known, kind="stable")
        at = find_sorted(known[order], self.primary)
        outside = (self.primary > 0) & (
            (at < 0) | (roots[order][np.maximum(at, 0)] != self.root)
        )
        problems.add(
            "primary outside its node's system", self.id[outside], int(outside.sum())
        )
        return problems

    def refs(self) -> Refs:
        """Every node and member star with the `system` its Metadata row must
        show: the root, or null for the root itself."""
        star_ids, star_roots = self._member_stars()
        ids = np.concatenate([self.id, star_ids])
        system = np.concatenate([np.where(self.parent > 0, self.root, 0), star_roots])
        node = np.r_[np.ones(self.id.size, bool), np.zeros(star_ids.size, bool)]
        ids, first = np.unique(ids, return_index=True)
        return Refs(ids, system[first], node[first])

    def counts(self) -> dict[str, int]:
        kind = self.member_kind
        sizes = np.unique(self.root[self.root > 0], return_counts=True)[1]
        return {
            "nodes": int(self.id.size),
            "points": int(self.point.sum()),
            "resolved": int((~self.point).sum()),
            "roots": int((self.parent == 0).sum()),
            "member stars": int((kind == STAR).sum()),
            "member nodes": int((kind == NODE).sum()),
            "entries": int((kind == ENTRY).sum()),
            "deepest": int(self.depth.max()) if self.depth.size else 0,
            "largest system": int(sizes.max()) if sizes.size else 0,
        }


# The fields of one System row; the others are of its members or tree entries.
ROW_FIELDS = (
    "id",
    "parent",
    "root",
    "primary",
    "depth",
    "point",
    "stars",
    "label",
    "has_tree",
)


# The columns that the checks read.
READ_COLUMNS = (*ROW_FIELDS[:-1], "members", "tree")


def read_region(job: tuple[Registry, int]) -> Systems | None:
    """The System rows of one region."""
    registry, region = job
    rows = registry.read_table(SYSTEM.slug, region, list(READ_COLUMNS))
    return None if rows is None or not rows.num_rows else Systems.of(rows)


@dataclass(frozen=True)
class Refs:
    """The IDs that the trees hold, sorted, with the `system` that their
    Metadata row must show (0 for null), and whether each is a node."""

    id: np.ndarray
    system: np.ndarray
    node: np.ndarray


def refs_by_unit(refs: Refs, units: list[tuple[int, ...]]) -> list[Refs]:
    """The refs of each unit, a run of regions."""
    regions = region_of(refs.id & CELL_MASK)
    order = np.argsort(regions, kind="stable")
    regions = regions[order]
    out = []
    for unit in units:
        start, end = np.searchsorted(regions, [unit[0], unit[-1] + 1])
        part = np.sort(order[start:end])
        out.append(Refs(refs.id[part], refs.system[part], refs.node[part]))
    return out


def check_metadata(refs: Refs, rows: pa.Table) -> Problems:
    """The Metadata `system` and System bit of `rows`, the Metadata rows of
    some regions, against the refs of those regions."""
    problems = Problems()
    live = rows.select(["id", "system", "mask"]).filter(rows["alias_target"].is_null())
    ids = live["id"].to_numpy()
    order = np.argsort(ids, kind="stable")
    ids = ids[order]
    system = _ids(live["system"])[order]
    mask = live["mask"].fill_null(0).to_numpy()[order]
    at = find_sorted(ids, refs.id)
    found = at >= 0
    lost = refs.id[~found]
    problems.add("node or member star with no live Metadata row", lost, lost.size)
    at, held_ids = at[found], refs.id[found]
    wrong = system[at] != refs.system[found]
    problems.add(
        "Metadata system that is not the root of the ID's tree",
        held_ids[wrong],
        int(wrong.sum()),
    )
    unmarked = refs.node[found] & (mask[at] & SYSTEM_BIT == 0)
    problems.add(
        "node without the System bit of its mask",
        held_ids[unmarked],
        int(unmarked.sum()),
    )
    held = find_sorted(refs.id, ids) >= 0
    strays = ~held & (system > 0)
    problems.add(
        "Metadata system on an ID that no tree holds", ids[strays], int(strays.sum())
    )
    nodes = find_sorted(refs.id[refs.node], ids) >= 0
    marked = ~nodes & (mask & SYSTEM_BIT > 0)
    problems.add(
        "System bit on an ID with no System row", ids[marked], int(marked.sum())
    )
    return problems
