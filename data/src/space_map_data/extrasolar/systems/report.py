"""The "Systems" section of the ingest report, and the tree of one system.

REPORT_TARGETS are the systems that the report shows as trees. Each is a
star of the system by an id: a SIMBAD identifier (through the SIMBAD list)
or a catalogue id that the resolver knows.
"""

from collections import Counter
from collections.abc import Sequence

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from space_map_data.extrasolar.exoplanets.catalogues import OEC
from space_map_data.extrasolar.systems.assemble import ENTRY, Systems
from space_map_data.extrasolar.systems.nodes import INTERIOR_SOURCES, SIMBAD_OID
from space_map_data.extrasolar.systems.resolve import Resolver
from space_map_data.extrasolar.systems.simbad import SimbadIndex

SIMBAD_IDENTIFIER = ("simbad", "identifier")
REPORT_TARGETS = (
    ("α Cen", (*SIMBAD_IDENTIFIER, "* alf Cen A")),
    ("Castor", (*SIMBAD_IDENTIFIER, "* alf Gem B")),
    ("Mizar and Alcor", (*SIMBAD_IDENTIFIER, "* zet01 UMa")),
    ("Sirius", (*SIMBAD_IDENTIFIER, "* alf CMa")),
    ("Procyon", (*SIMBAD_IDENTIFIER, "* alf CMi")),
    ("Polaris", (*SIMBAD_IDENTIFIER, "* alf UMi")),
    ("Acrux", (*SIMBAD_IDENTIFIER, "* alf Cru")),
    ("Capella", (*SIMBAD_IDENTIFIER, "* alf Aur")),
    ("ε Lyr", (*SIMBAD_IDENTIFIER, "* eps01 Lyr A")),
    ("Kepler-16", (OEC, "systems", "Kepler-16 A")),
)
EXAMPLES = 20


def target_keys(index: SimbadIndex | None, resolver: Resolver) -> list[tuple[str, int]]:
    """The key of a star of each report target, 0 where none."""
    by_identifier: dict[str, int] = {}
    if index is not None:
        for oid, found in index.stars.objects.items():
            for text in (found.main_id, *found.identifiers):
                by_identifier.setdefault(" ".join(text.split()), oid)
    found = []
    for label, (catalogue, release, value) in REPORT_TARGETS:
        if (catalogue, release) == SIMBAD_IDENTIFIER:
            oid = by_identifier.get(value)
            if oid is None:
                found.append((label, 0))
                continue
            catalogue, release, value = (*SIMBAD_OID, str(oid))
        keys = resolver.keys(catalogue, release, pa.array([value], pa.string()))
        found.append((label, int(keys[0])))
    return found


def _counted(title: str, counts: Counter, indent: str = "  ") -> list[str]:
    if not counts:
        return [f"{title}: none"]
    return [f"{title}:"] + [
        f"{indent}{name}: {value:,}" for name, value in sorted(counts.items())
    ]


def report_lines(
    systems: Systems,
    targets: Sequence[tuple[str, int]] = (),
    ids: dict[str, int] | None = None,
    examples: int = EXAMPLES,
    classes: Counter | None = None,
) -> list[str]:
    """The lines of the section. `ids` holds the System IDs that the ingest
    minted, kept and retired. `classes` counts the class changes in the
    merged Metadata, such as "star → binary star". Only the ingest has them."""
    lines = ["", "Systems", ""]
    counts = systems.counts
    lines.append("per source:")
    by_source: dict[str, dict[str, int]] = {}
    for name, value in counts.items():
        source, _, what = name.partition(": ")
        if what:
            by_source.setdefault(source, {})[what] = value
    order = [s for s in INTERIOR_SOURCES if s in by_source]
    order += sorted(set(by_source) - set(order))
    for source in order:
        lines.append(
            f"  {source}: "
            + ", ".join(f"{k} {v:,}" for k, v in sorted(by_source[source].items()))
        )
    others = {name: value for name, value in counts.items() if ": " not in name}
    lines += _counted("other counts", Counter(others))
    nodes = systems.nodes
    roots = nodes.filter(pc.equal(nodes["parent"], 0))
    lines.append(
        f"systems: {roots.num_rows:,}; nodes {nodes.num_rows:,}, of which points"
        f" {int(pc.sum(nodes['point']).as_py() or 0):,} and resolved"
        f" {int(pc.sum(pc.invert(nodes['point'])).as_py() or 0):,}"
    )
    stars = Counter(_bucket(n) for n in roots["stars"].to_pylist())
    lines += _counted("systems by stars", stars)
    depth = _max_depth(nodes)
    lines += _counted("systems by depth", Counter(depth))
    points = nodes.filter(nodes["point"])
    lines += _counted(
        "points that hold several stars, by evidence",
        Counter(points["evidence"].to_pylist()),
    )
    resolved = nodes.filter(pc.invert(nodes["point"]))
    lines.append(f"new system nodes (resolved): {resolved.num_rows:,}")
    if ids:
        lines.append("  system IDs: " + ", ".join(f"{k} {v:,}" for k, v in ids.items()))
    events = systems.events
    kinds = Counter(events["kind"].to_pylist())
    lines += _counted("events", kinds)
    for kind in ("merge", "conflict", "cross-match error"):
        picked = events.filter(pc.equal(events["kind"], kind))
        for text in picked["text"].to_pylist()[:examples]:
            lines.append(f"  {kind}: {text}")
    if classes is not None:
        lines += _counted("class changes", classes)
    moved = int(pc.sum(systems.points["spectral_type_moved"]).as_py() or 0)
    lines.append(f"composite spectral types moved to their system: {moved:,}")
    lines += _name_moves(systems, examples)
    lines.append(f"placements by system distance: {systems.distances.num_rows:,}")
    for row in systems.distances.slice(0, examples).to_pylist():
        lines.append(
            f"  {row['key']} takes {row['distance']:.2f} pc from {row['donor']}"
        )
    lines.append(
        f"SIMBAD components inside another point: {systems.absorbed.num_rows:,}"
    )
    for row in systems.absorbed.slice(0, examples).to_pylist():
        lines.append(f"  {row['key']} into {row['into']}: {row['evidence']}")
    lines.append(f"circumbinary planets: {systems.hosts.num_rows:,}")
    lines.append(f"planets that are also stars: {systems.overlaps.num_rows:,}")
    for row in systems.overlaps.slice(0, examples).to_pylist():
        lines.append(
            f"  {row['designation']} ({row['class']}): star {row['key']} {row['name']}"
        )
    for label, key in targets:
        lines.append(f"{label}:")
        lines += ["  " + line for line in tree_lines(systems, key)]
    return lines


def _bucket(stars: int) -> str:
    return f"{stars}" if stars < 6 else "6+"


def _max_depth(nodes: pa.Table) -> list[int]:
    root = nodes["root"].to_numpy()
    depth = nodes["depth"].to_numpy()
    order = np.argsort(root, kind="stable")
    root, depth = root[order], depth[order]
    starts = np.flatnonzero(np.r_[True, root[1:] != root[:-1]])
    return np.maximum.reduceat(depth, starts).tolist() if root.size else []


def _name_moves(systems: Systems, examples: int) -> list[str]:
    """Components whose name is a name of their system."""
    names = systems.names
    if not names.num_rows:
        return ["name moves: none"]
    first = names.filter(pc.equal(names["rank"], 1))
    by_node = dict(zip(first["node"].to_pylist(), first["name"].to_pylist()))
    points = systems.points
    found = []
    for key, root, parent, name in zip(
        points["key"].to_pylist(),
        points["root"].to_pylist(),
        points["parent"].to_pylist(),
        points["name"].to_pylist(),
    ):
        for node in (parent, root):
            if name and by_node.get(node) == name:
                found.append(f"{name}: from {key} to node {node}")
                break
    return [f"name moves: {len(found):,}"] + [f"  {text}" for text in found[:examples]]


def tree_lines(systems: Systems, key: int) -> list[str]:
    """The tree of the system that holds `key`, one line per node and member."""
    points = systems.points
    hit = points.filter(pc.equal(points["key"], key))
    if not key or not hit.num_rows:
        return [f"{key}: in no system"]
    root = hit["root"][0].as_py()
    nodes = systems.nodes
    mine = nodes.filter(pc.equal(nodes["root"], root))
    by_node = {row["node"]: row for row in mine.to_pylist()}
    members = systems.members.filter(
        pc.is_in(systems.members["node"], value_set=mine["node"])
    )
    by_parent: dict[int, list[dict]] = {}
    for row in members.to_pylist():
        by_parent.setdefault(row["node"], []).append(row)
    keys = pa.concat_arrays(
        [mine["key"].combine_chunks(), members["key"].combine_chunks()]
    )
    named = points.filter(pc.is_in(points["key"], value_set=keys))
    names = dict(zip(named["key"].to_pylist(), named["name"].to_pylist()))
    lines: list[str] = []

    def show(node: int, depth: int) -> None:
        row = by_node[node]
        what = f"point {row['key']}" if row["point"] else "resolved"
        name = f" {names.get(row['key'])}" if row["point"] else ""
        lines.append(
            "  " * depth
            + f"[{node}] {row['class']}, {row['stars']} stars, {what}{name}"
            + f" ({', '.join(row['sources'] or [])})"
            + (f" sp {row['spectral_type']}" if row["spectral_type"] else "")
        )
        for member in by_parent.get(node, []):
            letter = member["letter"] or member["label"] or "?"
            values = _values(member)
            if member["kind"] == ENTRY:
                inner = f" in {member['inner']}" if member["inner"] else ""
                lines.append("  " * (depth + 1) + f"entry {letter}{inner}{values}")
            elif member["member"]:
                show(member["member"], depth + 1)
            else:
                lines.append(
                    "  " * (depth + 1)
                    + f"star {letter} {member['key']} {names.get(member['key'])}{values}"
                )

    show(root, 0)
    return lines


def _values(member: dict) -> str:
    parts = []
    if member["separation"] is not None:
        parts.append(f"{member['separation']:.3g}″")
    if member["period"] is not None:
        parts.append(f"P {member['period']:.4g} d")
    if member["spectral_type"]:
        parts.append(member["spectral_type"])
    if member["known"]:
        parts.append("/".join(member["known"]))
    return f" [{'; '.join(parts)}]" if parts else ""
