"""Score and rank Commons image candidates per object.

Per-object the export wants ONE image per derivative tree, picked by quality
signals rather than discovery order. This module is the pure-data layer of
that decision: it groups direct candidates into their ``derived_from`` /
``other_versions`` connected components and scores each tree's members so
the caller can pick the best.

Scoring is lexicographic — a featured tree-only crop beats a non-assessed
direct pageimage, but among non-assessed candidates the file most language
wikis chose for THIS object wins, and globalusage breaks any remaining tie:

1. Assessment (featured > quality > valued > none)
2. Pageimage count for THIS object (langs whose pageimage[Q] == this file)
3. Globalusage entry count (saturates at the API's gulimit cap, which is
   fine — saturation already means "very popular")
4. Original discovery order, as a deterministic final tiebreaker
"""

from collections import defaultdict, deque
from dataclasses import dataclass

_ASSESSMENT_RANK = {
    "featured": 3,
    "quality": 2,
    "valued": 1,
}


@dataclass(frozen=True)
class CandidateScore:
    """Score for one image candidate; sortable lexicographically."""

    assessment: int
    pageimage_count: int
    globalusage_count: int
    discovery_order: int  # negated when used so earlier = better

    def as_tuple(self) -> tuple[int, int, int, int]:
        # Higher is better for the first three; for discovery order we want
        # the smallest index to win, so negate it.
        return (
            self.assessment,
            self.pageimage_count,
            self.globalusage_count,
            -self.discovery_order,
        )


def assessment_rank(metadata: dict) -> int:
    """Map ``imageinfo.extmetadata.Assessments.value`` to a numeric rank.

    Returns 0 when no assessment is recorded. Commons can stack multiple
    assessments in one comma-separated value (e.g. ``"featured,quality"``);
    we take the highest.
    """
    value = (
        ((metadata.get("imageinfo") or {}).get("extmetadata") or {}).get("Assessments")
        or {}
    ).get("value")
    if not isinstance(value, str):
        return 0
    return max(
        (_ASSESSMENT_RANK.get(tag.strip().lower(), 0) for tag in value.split(",")),
        default=0,
    )


def globalusage_count(metadata: dict) -> int:
    """Number of cross-wiki page references; 0 if missing."""
    return len(metadata.get("globalusage") or ())


def tree_components(
    direct_candidates: list[str],
    metadata_by_filename,
) -> list[list[str]]:
    """Group direct candidates by ``derived_from``/``other_versions`` reachability.

    Two direct candidates are in the same component iff their forward-BFS
    walks (over ``derived_from`` and ``other_versions``) reach any common
    file. This catches the case where two siblings share a parent that
    neither of them is a parent of — purely-forward walking would miss it,
    because metadata only stores child→parent edges, not parent→child.

    Components are returned in the order their first candidate appears;
    candidates within a component preserve their position in
    ``direct_candidates``.
    """
    if not direct_candidates:
        return []

    reachable = {c: _forward_reach(c, metadata_by_filename) for c in direct_candidates}

    parent: dict[str, str] = {c: c for c in direct_candidates}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, c1 in enumerate(direct_candidates):
        for c2 in direct_candidates[i + 1 :]:
            if reachable[c1] & reachable[c2]:
                parent[find(c1)] = find(c2)

    groups: dict[str, list[str]] = defaultdict(list)
    component_order: list[str] = []
    seen_roots: set[str] = set()
    for cand in direct_candidates:
        root = find(cand)
        if root not in seen_roots:
            seen_roots.add(root)
            component_order.append(root)
        groups[root].append(cand)

    return [groups[root] for root in component_order]


def best_in_tree(
    component: list[str],
    metadata_by_filename,
    pageimage_count_for: dict[str, int],
    discovery_order_of: dict[str, int],
) -> str:
    """Pick the highest-scoring file in the tree containing ``component``.

    ``component`` is a list of direct candidates known to be in the same
    tree (e.g. from :func:`tree_components`). All forward-reachable files
    from any candidate join the candidate pool; ties break lexicographically
    on ``(assessment, pageimage_count, globalusage_count, -discovery_order)``.

    Tree-only members (not in ``discovery_order_of``) score at order=∞ and
    only win on a higher assessment / pageimage count / globalusage.
    """
    members: set[str] = set()
    for cand in component:
        members |= _forward_reach(cand, metadata_by_filename)

    best_name = component[0]
    best_score: tuple[int, int, int, int] | None = None
    for name in members:
        meta = metadata_by_filename.get(name) or {}
        score = CandidateScore(
            assessment=assessment_rank(meta),
            pageimage_count=pageimage_count_for.get(name, 0),
            globalusage_count=globalusage_count(meta),
            discovery_order=discovery_order_of.get(name, 1_000_000),
        ).as_tuple()
        if best_score is None or score > best_score:
            best_score = score
            best_name = name
    return best_name


def _forward_reach(start: str, metadata_by_filename) -> set[str]:
    """All files reachable from ``start`` via ``derived_from`` / ``other_versions``."""
    seen: set[str] = set()
    queue: deque[str] = deque([start])
    while queue:
        node = queue.popleft()
        if node in seen:
            continue
        seen.add(node)
        meta = metadata_by_filename.get(node)
        if not meta:
            continue
        for related in meta.get("derived_from") or ():
            if related not in seen:
                queue.append(related)
        for related in meta.get("other_versions") or ():
            if related not in seen:
                queue.append(related)
    return seen
