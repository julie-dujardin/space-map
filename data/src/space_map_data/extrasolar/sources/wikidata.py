"""The Wikidata items of stars as an ingest source.

The source is not permanent: each ingest links the items again. An item never
mints and never matches by position. It reaches an object by one claim: its
Hipparcos number, else its Gaia DR3 id, else its HD number, each only when the
item gives one value of it. One claim, because an item that lists two Gaia
sources or a whole system is no proof that they are one star. Hipparcos
first, because the Gaia id on the item of a bright star is often a duplicate
or a companion.

The classes of an item tell what it is about (`kind`). An item about a star
goes to its star, an item about a system to a node of its system (`place`),
so each object has one item at most. Readers look for that one.

Its English label (else its multilingual one) names the object unless it
is a Gaia id or a SIMBAD identifier. A label that is a catalogue number
names it only where no other source but Gaia does (`METADATA`).
"""

import logging
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
from cdshealpix import nested

from space_map_data.download.providers.stars.wikidata_stars import (
    GAIA_PIXEL_LEVEL,
    GAIA_PIXEL_SHIFT,
    StarItem,
)
from space_map_data.extrasolar import sky
from space_map_data.extrasolar.engine import IngestRun, Source
from space_map_data.extrasolar.sources.hipparcos import GAIA_DR3, HD
from space_map_data.extrasolar.sources.names import HIP
from space_map_data.extrasolar.sources.simbad import SimbadList
from space_map_data.extrasolar.tables import CATALOGUE_NUMBER, CROSS_ID
from space_map_data.utils.arrays import find_sorted

if TYPE_CHECKING:
    # The systems ingest reads the literature source, which reads this one.
    from space_map_data.extrasolar.systems.ingest import Plan

logger = logging.getLogger(__name__)

WIKIDATA = Source(
    name="wikidata", catalogue="wikidata", release="qid", home=1, permanent=False
)

# The SIMBAD prefix of a name; the rest is the name.
_SIMBAD_NAME = "NAME "
# Other SIMBAD identifiers, in SIMBAD's own short forms. They are SIMBAD's
# syntax, not a name.
_SIMBAD_IDENTIFIER = re.compile(r"^(V\*|\*\*|\*|Cl\*|\[)")
# A Gaia id is the name of last resort, and the Gaia source gives it.
_GAIA_ID = re.compile(r"^Gaia E?DR\d\s*\d")
_CATALOGUE_NUMBER = re.compile(CATALOGUE_NUMBER)


STAR, SYSTEM, MIXED, OTHER = "star", "system", "mixed", "other"
# The catalogues of a claim, in the order of `_claim`.
CLAIMS = (HIP, GAIA_DR3, HD)
# On each level of a system, the item about the smallest part wins: a star,
# then no known kind, then a star and a system, then a system. So a system
# item that loses a level can go to the level above.
_RANK = {STAR: 0, OTHER: 1, MIXED: 2, SYSTEM: 3}
# A label that ends in a component letter: "Alpha Centauri B", "Xi UMa Ba".
_COMPONENT = re.compile(r"\s[A-Z][a-z]?$")


def kind(item: StarItem) -> str:
    """STAR, SYSTEM, MIXED (classes of both) or OTHER, by the item's classes.

    A class that is a kind of star and a kind of star system, such as an
    eclipsing binary, is a star class: it describes one point that is a pair.
    """
    star = bool(item.star_classes)
    system = any(name not in item.star_classes for name in item.system_classes)
    if star and system:
        return MIXED
    if star:
        return STAR
    return SYSTEM if system else OTHER


def names_component(item: StarItem) -> bool:
    """Whether a label of the item ends in a component letter."""
    return any(
        label is not None and _COMPONENT.search(label) is not None
        for label in (item.label_en, item.label_mul)
    )


@dataclass(frozen=True)
class Reach:
    """Where the ids of one item lead. Objects and nodes are numbers of the
    caller, such as run keys and node numbers."""

    item: StarItem
    # The object that the claim reaches, and the claim's rank in CLAIMS.
    target: int
    claim: int
    # The target's node where it is a point that holds several stars.
    point: int = 0
    # The root of the target's system, 0 for a star in no system.
    root: int = 0
    # The resolved node that the claim names as a system, and its root.
    named: int = 0
    named_root: int = 0


@dataclass(frozen=True)
class Placed:
    """Where an item goes: `node` 0 keeps its target, None leaves it off."""

    qid: str
    node: int | None
    case: str


# The cases of `place`.
ON_STAR = "a star item on its star"
ON_POINT = "an item on its point of several stars"
WINS = "a: a star item wins its star over a system item"
TIE = "a: of star items, the first claim, then the most articles wins"
OUTRANKED = "a: outranked"
TO_ROOT = "b: to the root"
TO_NAMED = "b: to the node that its ids name"
COMPONENT = "b: its label names a component, so it stays on its star"
TAKEN_MIXED = "b: the node has an item, so the mixed item stays on its star"
TAKEN_SYSTEM = "b: the node has an item, so the system item is left off"
ALONE_SYSTEM = "c: a system item on a star in no system stays on it"
ALONE_MIXED = "d: a mixed item on a star in no system stays on it"
INNER = "e: on an inner pair that its ids name, below a root with no item"
CASES = (
    ON_STAR,
    ON_POINT,
    WINS,
    TIE,
    OUTRANKED,
    TO_ROOT,
    TO_NAMED,
    COMPONENT,
    TAKEN_MIXED,
    TAKEN_SYSTEM,
    ALONE_SYSTEM,
    ALONE_MIXED,
    INNER,
)


def _rank(reach: Reach) -> tuple:
    item = reach.item
    return (_RANK[kind(item)], reach.claim, -item.articles, int(item.qid[1:]))


def _about_star(reach: Reach) -> bool:
    found = kind(reach.item)
    return found == STAR or (found == OTHER and not reach.named)


def place(reaches: Iterable[Reach]) -> list[Placed]:
    """Where each item goes, by what it is about.

    The items that reach one object rank by `_rank`. A star item that wins
    stays, and so does an item of no known kind whose ids name no system.
    Every other item goes on to the node that its ids name, else to the root
    of its system. A node takes the best of the items that its ids name,
    else the best of the items from below. These items stay where they are:
    - the winner of a point of several stars; the loser goes to the root;
    - an item whose label names a component, when it wins its star;
    - on a star in no system, a mixed or system item that wins it, so the
      item of a system that we do not hold (Mira) stays until we hold it.
    An item that loses an inner node goes to the root. One that finds its
    node taken stays on its star when it is mixed and the star is free.
    """
    placed: dict[str, Placed] = {}
    on_target: dict[int, list[Reach]] = defaultdict(list)
    of: dict[str, Reach] = {}
    for reach in reaches:
        on_target[reach.target].append(reach)
        of[reach.item.qid] = reach
    own: dict[int, list[Reach]] = defaultdict(list)
    up: dict[int, list[Reach]] = defaultdict(list)
    taken: set[int] = set()

    def put(reach: Reach, node: int | None, case: str) -> None:
        placed[reach.item.qid] = Placed(reach.item.qid, node, case)
        if node == 0:
            taken.add(reach.target)

    def route(reach: Reach, won: bool) -> None:
        if reach.named:
            own[reach.named].append(reach)
        elif reach.point:
            if won:
                put(reach, 0, ON_POINT)
            elif reach.root != reach.point:
                up[reach.root].append(reach)
            else:
                put(reach, None, OUTRANKED)
        elif names_component(reach.item):
            put(reach, 0 if won else None, COMPONENT if won else OUTRANKED)
        elif reach.root:
            up[reach.root].append(reach)
        elif not won:
            put(reach, None, OUTRANKED)
        else:
            put(reach, 0, ALONE_SYSTEM if kind(reach.item) == SYSTEM else ALONE_MIXED)

    for found in on_target.values():
        found.sort(key=_rank)
        winner, *losers = found
        if _about_star(winner):
            kinds = {kind(loser.item) for loser in losers}
            if kinds & {SYSTEM, MIXED}:
                case = WINS
            elif losers:
                case = TIE
            else:
                case = ON_POINT if winner.point else ON_STAR
            put(winner, 0, case)
        else:
            route(winner, True)
        for loser in losers:
            if _about_star(loser):
                put(loser, None, OUTRANKED)
            else:
                route(loser, False)

    back: list[Reach] = []
    inner = sorted(n for n, found in own.items() if found[0].named_root != n)
    for node in inner:
        winner, *losers = sorted(own.pop(node), key=_rank)
        put(winner, node, TO_NAMED)
        for loser in losers:
            up[loser.named_root].append(loser)
    for node in sorted(own.keys() | up.keys()):
        if own.get(node):
            winner, *losers = sorted(own[node], key=_rank)
            put(winner, node, TO_NAMED)
            back += losers + up.get(node, [])
        else:
            winner, *losers = sorted(up[node], key=_rank)
            put(winner, node, TO_ROOT)
            back += losers
    for reach in sorted(back, key=_rank):
        if kind(reach.item) == SYSTEM:
            put(reach, None, TAKEN_SYSTEM)
        elif reach.target in taken:
            put(reach, None, OUTRANKED)
        else:
            put(reach, 0, TAKEN_MIXED)

    # No id names the root of these, so they stay where their ids lead.
    held = {p.node or of[p.qid].point for p in placed.values() if p.node is not None}
    for qid, found in placed.items():
        reach = of[qid]
        if found.case == ON_POINT and reach.root != reach.point:
            root = reach.root
        elif found.case == TO_NAMED and found.node != reach.named_root:
            root = reach.named_root
        else:
            continue
        if root not in held and not _about_star(reach):
            placed[qid] = Placed(qid, found.node, INNER)
    return list(placed.values())


def _designation(label: str | None) -> str | None:
    """The label without its SIMBAD prefix, or None for a Gaia id or a SIMBAD
    identifier."""
    if label is None:
        return None
    label = label.removeprefix(_SIMBAD_NAME).strip()
    if not label or _SIMBAD_IDENTIFIER.match(label) or _GAIA_ID.match(label):
        return None
    return label


def usable_name(label: str | None) -> str | None:
    """The label as a name, or None for a catalogue number, a Gaia id or a
    SIMBAD identifier."""
    name = _designation(label)
    return None if name is None or _CATALOGUE_NUMBER.match(name) else name


def label_name(item: StarItem) -> str | None:
    """The name that the item gives its star, a catalogue number included,
    or None."""
    return _designation(item.label_en or item.label_mul)


def hd_positions(hipparcos_rows: pa.Table) -> dict[str, tuple[float, float]]:
    """The J2016.0 position of each HD number that a Hipparcos row claims."""
    claims = hipparcos_rows["claims"].combine_chunks()
    flat = pc.list_flatten(claims)
    parent = pc.list_parent_indices(claims).to_numpy()
    is_hd = pc.and_(
        pc.equal(flat.field("catalogue"), HD[0]),
        pc.equal(flat.field("release"), HD[1]),
    ).to_numpy(zero_copy_only=False)
    numbers = flat.field("catalogue_id").filter(pa.array(is_hd)).to_pylist()
    rows = parent[is_hd]
    ra = hipparcos_rows["match_ra"].to_numpy()[rows]
    dec = hipparcos_rows["match_dec"].to_numpy()[rows]
    return dict(zip(numbers, zip(ra.tolist(), dec.tolist())))


def gaia_position(source_id: str) -> tuple[float, float]:
    """The centre of the source's pixel, good to a region for the claim lookup."""
    pixel = np.array([int(source_id) >> GAIA_PIXEL_SHIFT], np.uint64)
    lon, lat = nested.healpix_to_lonlat(pixel, GAIA_PIXEL_LEVEL)
    return float(lon.deg[0]), float(lat.deg[0])


def _claim(
    item: StarItem,
    hip_positions: dict[str, tuple[float, float]],
    hd_positions: dict[str, tuple[float, float]],
) -> tuple[tuple[str, str, str], tuple[float, float]] | None:
    """The one claim of the item and the position of its star."""
    if len(item.hip) == 1 and item.hip[0] in hip_positions:
        return (*HIP, item.hip[0]), hip_positions[item.hip[0]]
    if len(item.gaia_dr3) == 1:
        return (*GAIA_DR3, item.gaia_dr3[0]), gaia_position(item.gaia_dr3[0])
    if len(item.hd) == 1 and item.hd[0] in hd_positions:
        return (*HD, item.hd[0]), hd_positions[item.hd[0]]
    return None


def _keys(
    run: IngestRun, rows: pa.Table, claims: list[tuple[str, str, str]]
) -> dict[tuple[str, str, str], int]:
    """The object that each claim reaches in the run, from the regions of the
    rows and their neighbours, as the engine looks."""
    cells = sky.cells(rows["match_ra"].to_numpy(), rows["match_dec"].to_numpy())
    regions = {
        near
        for region in np.unique(sky.region_of(cells)).tolist()
        for near in (region, *sky.neighbour_regions(region))
    }
    wanted = set(claims)
    ids = pa.array(sorted({claim[2] for claim in claims}), pa.string())
    found: dict[tuple[str, str, str], int] = {}
    for region in sorted(regions):
        links = run.links(region, CLAIMS)
        links = links.filter(pc.is_in(links["catalogue_id"], value_set=ids))
        # The latest link of an id holds.
        for *claim, key in zip(
            *(links[name].to_pylist() for name in (*CROSS_ID.names, "key"))
        ):
            if tuple(claim) in wanted:
                found[(claim[0], claim[1], claim[2])] = key
    return found


def attach(
    rows: pa.Table,
    items: Iterable[StarItem],
    run: IngestRun,
    plan: Plan,
    stars: SimbadList,
) -> tuple[pa.Table, list[str]]:
    """The rows with each claim where `place` puts its item, and the lines of
    the report.

    An item that goes to a node claims the node from the node's position. An
    item that is left off has no row. An item that reaches nothing keeps its
    row, so the engine counts it.
    """
    by_qid = {item.qid: item for item in items}
    qids = rows["catalogue_id"].to_pylist()
    claims = [
        (claim[0]["catalogue"], claim[0]["release"], claim[0]["catalogue_id"])
        for claim in rows["claims"].to_pylist()
    ]
    keys = _keys(run, rows, claims)

    points = plan.systems.points
    point_order = np.argsort(points["key"].to_numpy(), kind="stable")
    point_keys = points["key"].to_numpy()[point_order]
    point_nodes = points["node"].to_numpy()[point_order]
    point_roots = points["root"].to_numpy()[point_order]
    nodes = plan.systems.nodes
    node_order = np.argsort(nodes["node"].to_numpy(), kind="stable")
    node_numbers = nodes["node"].to_numpy()[node_order]
    node_roots = nodes["root"].to_numpy()[node_order]
    # An item that claims the own HIP or HD number of a SIMBAD system object
    # names the node of that object.
    named: dict[tuple[str, str], int] = {}
    for oid in stars.children:
        node = plan.simbad_nodes.get(str(oid))
        if node is None:
            continue
        found = stars.objects[oid]
        for catalogue, number in ((HIP, found.hip), (HD, found.hd)):
            if number:
                named.setdefault((catalogue[0], number), node)

    reaches = []
    for qid, claim in zip(qids, claims):
        key = keys.get(claim)
        if key is None:
            continue
        at = int(find_sorted(point_keys, np.array([key], np.int64))[0])
        point = int(point_nodes[at]) if at >= 0 else 0
        root = int(point_roots[at]) if at >= 0 else 0
        node = named.get((claim[0], claim[2]), 0)
        node_at = int(find_sorted(node_numbers, np.array([node], np.int64))[0])
        reaches.append(
            Reach(
                by_qid[qid],
                key,
                CLAIMS.index((claim[0], claim[1])),
                point,
                root,
                node,
                int(node_roots[node_at]) if node and node_at >= 0 else 0,
            )
        )
    placed = {found.qid: found for found in place(reaches)}

    keep, moved = [], {}
    for at, qid in enumerate(qids):
        found = placed.get(qid)
        if found is None or found.node == 0:
            keep.append(at)
        elif found.node is not None:
            keep.append(at)
            moved[at] = found.node
    out = rows.take(pa.array(keep, pa.int64()))
    if moved:
        numbers = np.array([moved.get(at, 0) for at in keep], np.int64)
        index = find_sorted(plan.node_numbers, numbers)
        mask = pa.array(index < 0)
        node_claims = plan.node_claims.take(pa.array(np.maximum(index, 0)))
        offsets = pa.array(np.arange(len(keep) + 1, dtype=np.int32))
        out = out.set_column(
            out.schema.get_field_index("claims"),
            "claims",
            pc.if_else(
                mask,
                out["claims"].combine_chunks(),
                pa.ListArray.from_arrays(offsets, node_claims),
            ),
        )
        # The engine looks for a claim near the row.
        node_at = find_sorted(node_numbers, numbers)
        for name in ("ra", "dec"):
            values = nodes[name].to_numpy(zero_copy_only=False)[node_order]
            values = np.where(node_at >= 0, values[np.maximum(node_at, 0)], np.nan)
            column = f"match_{name}"
            out = out.set_column(
                out.schema.get_field_index(column),
                column,
                pa.array(np.where(np.isfinite(values), values, out[column].to_numpy())),
            )
    return out, report_lines(reaches, list(placed.values()), len(qids) - len(reaches))


def report_lines(
    reaches: list[Reach], placed: list[Placed], unreached: int, examples: int = 5
) -> list[str]:
    """The kinds of the items and the count of each case of `place`, with
    examples."""
    of = {reach.item.qid: reach.item for reach in reaches}
    kinds = Counter(kind(reach.item) for reach in reaches)
    lines = [
        "Wikidata items that reach an object: "
        + ", ".join(f"{name} {count:,}" for name, count in kinds.most_common())
        + f"; reach nothing {unreached:,}"
    ]
    by_case: dict[str, list[str]] = defaultdict(list)
    for found in placed:
        item = of[found.qid]
        by_case[found.case].append(f"{item.qid} {item.label_en or item.label_mul}")
    for case in (case for case in CASES if case in by_case):
        found = by_case[case]
        lines.append(f"  {case}: {len(found):,}")
        lines += [f"    {text}" for text in sorted(found)[:examples]]
    return lines


def engine_rows(
    items: Iterable[StarItem],
    hip_positions: dict[str, tuple[float, float]],
    hd_positions: dict[str, tuple[float, float]],
) -> pa.Table:
    """The pass rows of the items with a claim, the most articles first.

    The engine gives a star that several rows claim to the first of them.
    """
    rows = []
    unclaimed = 0
    for item in sorted(items, key=lambda i: (-i.articles, int(i.qid[1:]))):
        found = _claim(item, hip_positions, hd_positions)
        if found is None:
            unclaimed += 1
            logger.debug("%s: no single id of a star", item.qid)
            continue
        claim, (ra, dec) = found
        rows.append(
            {
                "catalogue_id": item.qid,
                "match_ra": ra,
                "match_dec": dec,
                "claims": [dict(zip(CROSS_ID.names, claim))],
                "name": label_name(item),
            }
        )
    logger.info(
        "Wikidata: %d items with a claim, %d with no single id of a star",
        len(rows),
        unclaimed,
    )
    table = pa.Table.from_pylist(
        rows,
        pa.schema(
            [
                ("catalogue_id", pa.string()),
                ("match_ra", pa.float64()),
                ("match_dec", pa.float64()),
                ("claims", pa.list_(CROSS_ID)),
                ("name", pa.string()),
            ]
        ),
    )
    return table.append_column("mint", pa.array(np.zeros(table.num_rows, bool)))
