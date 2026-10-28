"""The Washington Double Star Catalog as a tree source.

A WDS pair names its components by letters: AB, AC, Aa,Ab, AB,C, AB,CD. The
letters imply the tree:
- a lower-case letter is a component of its capital: Aa and Ab are in A;
- a group of capitals is one component: in AB,C the pair AB is one node and
  C is measured from it;
- the other pairs join their components from the closest pair outwards. A
  pair measured from a component of a group joins that group as one more
  member when its separation is less than NEST_RATIO times the group's own,
  else the group and the new component make a new level.

A pair is physical when its notes say so (T, V, Z), when it has an orbit (O,
C), or when both components move together (CPM_RATIO). A pair noted optical
(S, U, Y) is left out, unless a physical code says the opposite: then it is
dubious, as X marks it. A pair with no evidence either way is unverified. The
builder keeps an unverified or dubious member only where other data agree.

The Gaia DR3 source of each component comes from wds_comp_dr3.txt. Its
position is the J2000 position of the primary, offset by the last measure.
"""

import logging
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyarrow as pa

from space_map_data.download.providers.stars import wds
from space_map_data.extrasolar.systems.nodes import (
    DUBIOUS,
    GAIA_DR3,
    PARALLAX,
    PROPER_MOTION,
    UNVERIFIED,
    VISUAL,
    VISUAL_ORBIT,
    WDS,
    WDS_ID,
    NodeList,
)

logger = logging.getLogger(__name__)

EPOCH = 2000.0
# A pair moves together when the motions differ by less than this share of
# the primary's, and the primary moves at least CPM_MIN mas/yr.
CPM_RATIO = 0.2
CPM_MIN = 30.0
NEST_RATIO = 3.0
ORBIT_CODES = frozenset("OC")
# Bands other than V in the magnitudes of a pair.
OTHER_BANDS = frozenset("KRB")
OPTICAL = "optical"

_GROUP = re.compile(r"[A-Z]+")
_SUB = re.compile(r"([A-Z])[a-z]\d?")


def split_components(text: str | None) -> tuple[str, str] | None:
    """The primary and secondary labels of a pair's components.

    Null is A,B. "AB" is A and B; "Aa1,2" is Aa1 and Aa2.
    """
    if text is None:
        return "A", "B"
    if "," not in text:
        if len(text) == 2 and text.isupper():
            return text[0], text[1]
        return None
    first, second = (part.strip() for part in text.split(",", 1))
    if not first or not second:
        return None
    if second.isdigit():
        second = first.rstrip("0123456789") + second
    elif second[0].islower():
        second = first[0] + second
    return first, second


def top_letters(label: str) -> frozenset[str]:
    """The capital components that a label stands for."""
    if _GROUP.fullmatch(label):
        return frozenset(label)
    if found := _SUB.fullmatch(label):
        return frozenset(found[1])
    return frozenset([label])


def is_sub(label: str) -> bool:
    return _SUB.fullmatch(label) is not None


def evidence(
    notes: str | None,
    pm1: tuple[float | None, float | None],
    pm2: tuple[float | None, float | None],
) -> tuple[str | None, list[str]]:
    """OPTICAL, DUBIOUS, UNVERIFIED or None (physical), and how it is known."""
    codes = set(notes or "")
    known = [VISUAL]
    physical = bool(codes & wds.PHYSICAL_CODES)
    optical = bool(codes & wds.OPTICAL_CODES)
    if codes & ORBIT_CODES:
        known.append(VISUAL_ORBIT)
        physical = True
    if "V" in codes or "T" in codes:
        known.append(PROPER_MOTION)
    if "Z" in codes or "T" in codes:
        known.append(PARALLAX)
    motions = [value for value in (*pm1, *pm2) if value is not None]
    if len(motions) == 4:
        ra1, dec1, ra2, dec2 = motions
        primary = math.hypot(ra1, dec1)
        apart = math.hypot(ra1 - ra2, dec1 - dec2)
        if primary >= CPM_MIN and apart < CPM_RATIO * primary:
            physical = True
            if PROPER_MOTION not in known:
                known.append(PROPER_MOTION)
    if optical and physical:
        return DUBIOUS, known
    if optical:
        return OPTICAL, known
    if wds.DUBIOUS_CODE in codes:
        return DUBIOUS, known
    return (None if physical else UNVERIFIED), known


@dataclass(eq=False)
class _Node:
    label: str
    # The capital components below the node.
    letters: frozenset[str] = frozenset()
    children: list[_Node] = field(default_factory=list)
    # The pair that measures this node from its group's primary.
    pair: dict | None = None
    evidence: str | None = None
    known: list[str] | None = None


@dataclass
class _Cluster:
    letters: frozenset[str]
    node: _Node
    # The separation of the pair that made the node, 0 for one component.
    scale: float = 0.0


@dataclass
class WdsCatalogue:
    """The pairs and components of the WDS, by WDS id."""

    pairs: dict[str, list[dict]]
    components: dict[tuple[str, str], dict]
    counts: Counter

    @classmethod
    def read(cls, directory: Path = wds.OUT_DIR) -> WdsCatalogue:
        counts: Counter = Counter()
        rows = wds.read_pairs(directory / wds.PAIRS_FILE).to_pylist()
        components = _components(
            wds.read_components(directory / wds.GAIA_FILE).to_pylist()
        )
        overflow = _overflow(
            wds.read_components(directory / wds.COMPONENTS_FILE).to_pylist()
        )
        pairs: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            labels = split_components(row["components"])
            if labels is None:
                counts["pairs with labels that do not parse"] += 1
                logger.debug("WDS %s: components %r", row["wds_id"], row["components"])
                continue
            found, known = evidence(
                row["notes"],
                (row["pm1_ra"], row["pm1_dec"]),
                (row["pm2_ra"], row["pm2_dec"]),
            )
            counts[f"pairs {found or 'physical'}"] += 1
            if found == OPTICAL:
                continue
            separation = row["sep_last"]
            if separation is not None and separation >= wds.SEPARATION_OVERFLOW:
                key = (row["wds_id"], row["discoverer"], labels[1])
                separation = max(overflow.get(key, [separation]))
            pairs[row["wds_id"]].append(
                {
                    "primary": labels[0],
                    "secondary": labels[1],
                    "discoverer": row["discoverer"],
                    "separation": separation,
                    "position_angle": row["pa_last"],
                    "mag1": row["mag1"],
                    "mag2": row["mag2"],
                    "v_band": not set(row["notes"] or "") & OTHER_BANDS,
                    "spectral_type": row["spectral_type"],
                    "evidence": found,
                    "known": known,
                }
            )
        counts["systems"] = len(pairs)
        logger.info("WDS: %s", dict(counts))
        return cls(dict(pairs), components, counts)

    def nodes(self, refuted: frozenset[tuple[str, str, str]] | None = None) -> pa.Table:
        """The trees of the pairs that are not optical, one or more per id.

        `refuted` are the (WDS id, primary, secondary) that the MSC refutes.
        """
        out = NodeList(WDS)
        for system in sorted(self.pairs):
            self._add_system(out, system, refuted)
        logger.info("WDS: %d nodes", len(out))
        return out.table()

    def _add_system(
        self,
        out: NodeList,
        system: str,
        refuted: frozenset[tuple[str, str, str]] | None,
    ) -> None:
        pairs = self.pairs[system]
        # The values of each component: its magnitude and spectral type.
        mags: dict[str, float] = {}
        types: dict[str, str] = {}
        for pair in pairs:
            parts = (pair["spectral_type"] or "").split("+")
            for at, label in enumerate((pair["primary"], pair["secondary"])):
                mag = pair[f"mag{at + 1}"] if pair["v_band"] else None
                if mag is not None:
                    mags.setdefault(label, mag)
                if at < len(parts) and parts[at].strip():
                    types.setdefault(label, parts[at].strip())

        tops: dict[str, _Node] = {}
        subs: dict[str, _Node] = {}

        def sub_node(label: str) -> _Node:
            if label not in subs:
                subs[label] = _Node(label, top_letters(label))
                parent = label[:-1] if label[-1].isdigit() else label[0]
                holder = sub_node(parent) if is_sub(parent) else top_node(parent)
                holder.children.append(subs[label])
            return subs[label]

        def top_node(label: str) -> _Node:
            if label not in tops:
                tops[label] = _Node(label, top_letters(label))
            return tops[label]

        top_pairs = []
        refuted = refuted or frozenset()
        for pair in sorted(pairs, key=_by_evidence):
            if (system, pair["primary"], pair["secondary"]) in refuted:
                self.counts["pairs that the MSC refutes, left out"] += 1
                continue
            first, second = pair["primary"], pair["secondary"]
            if is_sub(first) and is_sub(second) and first[0] == second[0]:
                sub_node(first)
                node = sub_node(second)
                node.pair, node.evidence = pair, pair["evidence"]
                node.known = pair["known"]
            else:
                if top_letters(first) & top_letters(second):
                    self.counts["pairs inside one component, left out"] += 1
                    continue
                top_pairs.append(pair)
        clusters: dict[str, _Cluster] = {}

        def cluster(label: str) -> _Cluster:
            # Groups follow the letter order of the label; the first is the primary.
            found: dict[int, _Cluster] = {}
            for letter in sorted(top_letters(label), key=label.find):
                if letter not in clusters:
                    clusters[letter] = _Cluster(frozenset([letter]), top_node(letter))
                found.setdefault(id(clusters[letter]), clusters[letter])
            if len(found) == 1:
                return next(iter(found.values()))
            # A group label whose letters no pair has joined yet.
            letters = frozenset().union(*(c.letters for c in found.values()))
            joined = _Cluster(
                letters, _Node("", letters, [c.node for c in found.values()])
            )
            for letter in joined.letters:
                clusters[letter] = joined
            return joined

        for pair in top_pairs:
            cluster(pair["primary"])
            second = cluster(pair["secondary"])
            # The secondary's group label can hold the primary's group.
            first = cluster(pair["primary"])
            if first is second:
                continue
            separation = pair["separation"]
            second.node.pair, second.node.evidence = pair, pair["evidence"]
            second.node.known = pair["known"]
            from_group = len(top_letters(pair["primary"])) > 1
            letters = first.letters | second.letters
            # A group that pairs made. A component with an interior is no group.
            group = first.node.label == ""
            # A pair with no separation joins the group of its primary.
            near = (
                separation is None
                or first.scale == 0
                or separation < NEST_RATIO * first.scale
            )
            if not from_group and group and near:
                first.node.children.append(second.node)
                first.node.letters = letters
                merged = _Cluster(letters, first.node, first.scale)
            else:
                node = _Node("", letters, [first.node, second.node])
                merged = _Cluster(letters, node, separation or first.scale)
            for letter in merged.letters:
                clusters[letter] = merged
        roots = {id(c): c for c in clusters.values()}.values()
        trees = [c.node for c in roots]
        trees += [n for label, n in tops.items() if label not in clusters]
        for tree in sorted(trees, key=lambda n: min(n.letters)):
            if not tree.children:
                continue
            main = "A" in tree.letters
            key = system if main else f"{system} {''.join(sorted(tree.letters))}"
            self._emit(out, key, system, tree, mags, types)

    def _emit(
        self,
        out: NodeList,
        key: str,
        system: str,
        tree: _Node,
        mags: dict[str, float],
        types: dict[str, str],
    ) -> None:
        stack: list[tuple[_Node, int]] = [(tree, -1)]
        while stack:
            node, parent = stack.pop()
            label = node.label or "".join(sorted(node.letters))
            component = self.components.get((system, label), {})
            pair = node.pair or {}
            ids = []
            if component.get("source_id"):
                ids.append((*GAIA_DR3, str(component["source_id"])))
            ids.append((*WDS_ID, key if parent < 0 else f"{system} {label}"))
            number = out.add(
                key,
                parent,
                label,
                ids,
                ra=component.get("ra"),
                dec=component.get("dec"),
                epoch=EPOCH if component.get("ra") is not None else None,
                pmra=component.get("pmra"),
                pmdec=component.get("pmdec"),
                v_mag=mags.get(label),
                spectral_type=types.get(label),
                separation=pair.get("separation"),
                position_angle=pair.get("position_angle"),
                known=node.known,
                evidence=node.evidence,
            )
            stack += [(child, number) for child in reversed(node.children)]


def _by_evidence(pair: dict) -> tuple[bool, float, str, str]:
    """Physical pairs first, so that a pair with no evidence never makes a
    level that a physical pair should make; then by separation."""
    separation = pair["separation"]
    return (
        pair["evidence"] is not None,
        np.inf if separation is None else separation,
        pair["primary"],
        pair["secondary"],
    )


def _components(rows: list[dict]) -> dict[tuple[str, str], dict]:
    """One record per component: its Gaia DR3 source, position and motion.

    The position and motion are those of the row where it is the primary,
    else of its first row.
    """
    found: dict[tuple[str, str], dict] = {}
    sources: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for row in rows:
        key = (row["wds_id"], row["component"])
        if row["source_id"] is not None:
            sources[key][row["source_id"]] += 1
        if key in found and not row["primary"]:
            continue
        if key in found and found[key]["primary"]:
            continue
        side = "1" if row["primary"] else "2"
        found[key] = {
            "primary": row["primary"],
            "ra": row["ra"],
            "dec": row["dec"],
            "pmra": row[f"pm{side}_ra"],
            "pmdec": row[f"pm{side}_dec"],
        }
    for key, counter in sources.items():
        (source, _), *others = counter.most_common()
        if others:
            logger.debug("WDS %s %s: Gaia sources %s", *key, dict(counter))
        found[key]["source_id"] = source
    return found


def _overflow(rows: list[dict]) -> dict[tuple[str, str, str], list[float]]:
    """The true separations of the secondaries, for the pairs that overflow."""
    found: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row in rows:
        if not row["primary"] and row["sep"] is not None:
            key = (row["wds_id"], row["discoverer"], row["component"])
            found[key].append(row["sep"])
    return dict(found)
