"""Print a tree-style visualization of Commons derivative graphs.

Reads ``metadata.json`` under ``DOWNLOAD_DIR/commons/images/`` and renders
each connected component of the ``derived_from`` graph as a ``tree(1)``-style
ASCII forest. A file is included if it has at least one ``derived_from``
edge or is named as a parent by another file; isolated files are skipped.

Each line is annotated with the Commons file-page URL (using the
``imageinfo.descriptionurl`` we already have on disk, falling back to a
constructed URL for parents whose metadata wasn't fetched).

Files with multiple parents legitimately appear under each parent's tree —
the underlying structure is a DAG, not a strict tree, and seeing the same
file in multiple places makes the multi-parentage visible. Cycles (which
shouldn't exist in well-formed Commons data) are short-circuited with a
``↺`` marker.

Run::

    uv run python data/scripts/derivative_tree.py
"""

import sys
from collections import defaultdict
from urllib.parse import quote

import orjson

from space_map_data.utils.commons_images import IMAGES_DIR


def main() -> int:
    parents_of: dict[str, list[str]] = {}
    children_of: dict[str, list[str]] = defaultdict(list)
    description_url: dict[str, str] = {}

    for img_dir in sorted(IMAGES_DIR.iterdir()):
        if not img_dir.is_dir():
            continue
        meta_path = img_dir / "metadata.json"
        if not meta_path.exists():
            continue
        try:
            meta = orjson.loads(meta_path.read_bytes())
        except orjson.JSONDecodeError:
            continue
        if meta.get("missing"):
            continue
        filename = meta.get("filename") or img_dir.name
        derived_from = list(meta.get("derived_from") or ())
        parents_of[filename] = derived_from
        for parent in derived_from:
            children_of[parent].append(filename)
        info = meta.get("imageinfo") or {}
        url = info.get("descriptionurl")
        if url:
            description_url[filename] = url

    # Files with at least one edge in either direction.
    in_graph: set[str] = set()
    for filename, parents in parents_of.items():
        if parents or children_of.get(filename):
            in_graph.add(filename)
            in_graph.update(parents)

    # Roots: in-graph files with no parents we know about. Files that appear
    # only as parents (never had their own metadata fetched) qualify too —
    # they sit at the top of any chain that mentions them.
    roots = sorted(f for f in in_graph if not parents_of.get(f))

    if not roots:
        print("No derivative trees found.")
        return 0

    print(
        f"# Commons derivative-of graph: {len(in_graph):,} files in {len(roots):,} trees\n"
    )
    for root in roots:
        _print_node(
            root,
            children_of,
            description_url,
            prefix="",
            is_last=True,
            is_root=True,
            seen=set(),
        )
        print()
    return 0


def _print_node(
    node: str,
    children_of: dict[str, list[str]],
    description_url: dict[str, str],
    prefix: str,
    is_last: bool,
    is_root: bool,
    seen: set[str],
) -> None:
    """Render one node and recurse into its children."""
    if is_root:
        line = node
        child_prefix = ""
    else:
        line = prefix + ("└── " if is_last else "├── ") + node
        child_prefix = prefix + ("    " if is_last else "│   ")

    url = description_url.get(node) or _commons_url(node)
    cycle_marker = "  ↺ (already shown)" if node in seen else ""
    print(f"{line}  {url}{cycle_marker}")

    if node in seen:
        return
    seen = seen | {node}

    children = sorted(set(children_of.get(node, [])))
    for i, child in enumerate(children):
        _print_node(
            child,
            children_of,
            description_url,
            prefix=child_prefix,
            is_last=(i == len(children) - 1),
            is_root=False,
            seen=seen,
        )


def _commons_url(filename: str) -> str:
    return f"https://commons.wikimedia.org/wiki/File:{quote(filename)}"


if __name__ == "__main__":
    sys.exit(main())
