"""Per-object derivative-tree dump with score components.

Walks every Object in the DB that has a Wikidata QID and prints, for each
one, the trees its direct candidates land in. Each tree member is annotated
with the three score components plus depicts/direct flags so we can
visually audit the selection rule before committing it.

Single-member trees (one direct candidate, no tree-only members reachable)
are skipped — the selection there is trivial. Only multi-member trees and
the objects that contain at least one are printed.

Score notation (higher is better, lexicographic):

    a=N  Assessment rank — 3=featured, 2=quality, 1=valued, 0=none
    pi=N Pageimage count — # language wikis using this file as the
         pageimage for THIS object
    gu=N Globalusage count — # cross-wiki page references on Commons
         (saturates at the API's gulimit cap, fine as a tiebreaker)

Flags:
    [D]  Direct candidate — file appears in P18 / P154 / a Wikipedia
         pageimage of this object
    [T]  Tree-only — reached via metadata graph from a direct candidate
    [d]  SDC P180 (depicts) lists this object's QID — would be eligible
         under a depicts-based scoring rule
    [✓]  Currently servable license (passes ``license_servable``)

Run::

    uv run python data/scripts/derivative_tree.py [--filter SUBSTR]

Output goes to stdout; pipe to less or a file.
"""

import argparse
import sys
from urllib.parse import quote

from space_map_data.ingest.providers.image_selection import _collect_candidates
from space_map_data.models.object import Object
from space_map_data.utils import image_scoring
from space_map_data.utils.commons_images import (
    read_download_metadata,
)
from space_map_data.utils.db import session_scope, get_session


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--filter",
        metavar="SUBSTR",
        default=None,
        help=(
            "Limit output to objects whose ID or name contains SUBSTR "
            "(case-insensitive). Useful when scanning the full corpus would "
            "be too noisy."
        ),
    )
    args = parser.parse_args()

    with session_scope():
        session = get_session()
        rows = (
            session.query(Object.id, Object.name, Object.wikidata_qid)
            .filter(Object.wikidata_qid.is_not(None))
            .order_by(Object.id)
            .all()
        )

    needle = args.filter.lower() if args.filter else None
    metadata_cache: dict[str, dict | None] = {}

    printed = 0
    for obj_id, name, qid in rows:
        if (
            needle
            and needle not in obj_id.lower()
            and needle not in (name or "").lower()
        ):
            continue

        direct, kind_of, pageimage_count = _collect_candidates(qid)
        if not direct:
            continue

        components = image_scoring.tree_components(
            direct, _MetadataView(metadata_cache)
        )
        # Single-image objects don't need a tree dump — the selection is
        # trivial. Only print when at least one tree has >1 member after
        # walking the metadata graph.
        components = [c for c in components if _tree_is_multi(c, metadata_cache)]
        if not components:
            continue

        _print_object(
            obj_id,
            name,
            qid,
            direct,
            kind_of,
            pageimage_count,
            components,
            metadata_cache,
        )
        printed += 1

    print(f"\n# {printed:,} objects shown", file=sys.stderr)
    return 0


def _print_object(
    obj_id, name, qid, direct, kind_of, pageimage_count, components, metadata_cache
):
    """Pretty-print one object and its tree dump."""
    print(f"{obj_id} — {name or '(unnamed)'} ({qid})")
    discovery_order = {n: i for i, n in enumerate(direct)}
    direct_set = set(direct)

    for ti, component in enumerate(components, start=1):
        members = _tree_members(component, metadata_cache)
        # Order: direct candidates first (in discovery order), then tree-only.
        direct_in_tree = sorted(
            (m for m in members if m in direct_set), key=discovery_order.__getitem__
        )
        tree_only = sorted(m for m in members if m not in direct_set)

        kind_label = ", ".join(sorted({kind_of.get(m, "?") for m in direct_in_tree}))
        print(f"  TREE {ti}  ({len(members)} members; {kind_label})")
        for name_ in direct_in_tree + tree_only:
            print(
                "    "
                + _format_member(
                    name_,
                    metadata_cache,
                    pageimage_count,
                    qid,
                    is_direct=name_ in direct_set,
                )
            )
    print()


def _format_member(
    name: str,
    metadata_cache: dict[str, dict | None],
    pageimage_count: dict[str, int],
    object_qid: str,
    *,
    is_direct: bool,
) -> str:
    meta = _meta(name, metadata_cache) or {}
    a = image_scoring.assessment_rank(meta)
    pi = pageimage_count.get(name, 0)
    gu = image_scoring.globalusage_count(meta)
    flags = "[D]" if is_direct else "[T]"
    if _depicts_qid(meta, object_qid):
        flags += "[d]"
    if meta.get("license_servable"):
        flags += "[✓]"
    url = (meta.get("imageinfo") or {}).get("descriptionurl") or _commons_url(name)
    return f"{flags:<10}  a={a} pi={pi} gu={gu:<6}  {name}  {url}"


def _tree_members(component, metadata_cache):
    """All forward-reachable filenames from any candidate in the component."""
    members: set[str] = set()
    view = _MetadataView(metadata_cache)
    for cand in component:
        members |= image_scoring._forward_reach(cand, view)
    return members


def _tree_is_multi(component, metadata_cache) -> bool:
    """True if the tree has more than one filename in it."""
    return len(_tree_members(component, metadata_cache)) > 1


def _depicts_qid(meta: dict, qid: str) -> bool:
    """True if SDC P180 (depicts) contains the given QID."""
    sdc = meta.get("sdc") or {}
    statements = sdc.get("statements") or {}
    for stmt in statements.get("P180") or ():
        v = (stmt.get("mainsnak", {}).get("datavalue", {}).get("value") or {}).get("id")
        if v == qid:
            return True
    return False


def _meta(filename, cache):
    if filename not in cache:
        cache[filename] = read_download_metadata(filename)
    return cache[filename]


class _MetadataView:
    """Lazy dict-like wrapper for :func:`read_download_metadata`."""

    def __init__(self, cache):
        self._cache = cache

    def get(self, filename):
        return _meta(filename, self._cache)


def _commons_url(filename: str) -> str:
    return f"https://commons.wikimedia.org/wiki/File:{quote(filename)}"


if __name__ == "__main__":
    sys.exit(main())
