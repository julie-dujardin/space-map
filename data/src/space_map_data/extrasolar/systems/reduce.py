"""One source's trees as groups of points and the interiors of points.

Each node of a tree takes the best of its candidate objects. Then, from the
leaves up, a subtree either sits inside one point, or spans several points
and is a group:
- Two siblings that reach one object are one point when the object's data
  cannot split them (`resolves`). Else the shared id is a cross-match error:
  the object goes to the sibling whose magnitude is nearer to the object's,
  and the other takes its next candidate. When that sibling leaves the tree,
  the object goes back to the other.
- A SIMBAD component with no astrometry of its own, whose light a sibling's
  point holds, is inside that point: the builder makes its row an entry.
- An id of a group that one of its members also reaches is the light of that
  member, not the group's. A group's own point beside its members stays a
  member, and its event gives its kind (`groups`).
- A member that reaches no object is an entry. It is inside its sibling's
  point when that point cannot split it, else an entry of the group.

Each member is tested against its primary. A group stands for its main star.
The main star is the first point down the tree and gives the group its
position.
- A member leaves when its parallax and its primary's clearly disagree
  (`parallaxes_disagree`). An orbit pair is exempt, and so is a point that
  holds several stars in the tree or has a Gaia DR3 orbit, because a close
  orbit can throw off the parallax.
- A member that the source lists as unverified stays only when it and its
  primary pass El-Badry's test of a bound pair (`same_distance`). It also
  stays when it reaches its primary's point and the source gives their
  separation. It stays too when it reaches no object and its primary's point
  cannot split them. A chance alignment that close is rare. A dubious member
  never stays. When it reaches its primary's point and the point
  splits them, the shared id is still a cross-match error. A member that
  fails waits for another source to agree.
- A member that leaves keeps its inner system as a system of its own.

A point that holds two or more members gets an interior: its members as
entries. A group gets the set of its points.
"""

import logging
import math
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
import pyarrow as pa

from space_map_data.extrasolar.sky import separation as sky_separation
from space_map_data.extrasolar.sources.simbad import MAX_INSIDE_MAG
from space_map_data.extrasolar.systems.groups import GROUP_OBJECT, group_kind
from space_map_data.extrasolar.systems.nodes import (
    ASTROMETRIC_ORBIT,
    ECLIPSING,
    SPECTROSCOPIC_ORBIT,
    UNVERIFIED,
    VISUAL_ORBIT,
)
from space_map_data.extrasolar.systems.resolve import (
    GAIA_ASTROMETRY,
    HIPPARCOS_ASTROMETRY,
    HOW,
    OWN_ASTROMETRY,
    Fact,
    Facts,
)

logger = logging.getLogger(__name__)

# Gaia DR3 splits two stars at this separation in arcsec and more, plus
# GAIA_SEPARATION_PER_MAG for each magnitude of contrast.
GAIA_MIN_SEPARATION = 0.4
GAIA_SEPARATION_PER_MAG = 0.25
# Hipparcos gives one entry to a pair closer than this, in arcsec, when the
# companion is less than HIPPARCOS_MAX_CONTRAST mag fainter.
HIPPARCOS_SEPARATION = 10.0
HIPPARCOS_MAX_CONTRAST = 4.0
# The bound-pair test of El-Badry, Rix & Heintz 2021 (MNRAS 506, 2269),
# section 2, eqs. 1-6, with raw errors. ϖ is the brighter star's parallax.
MIN_PARALLAX_SNR = 5.0
MAX_PARALLAX_ERROR = 2.0
# Eq. 1: θ/arcsec ≤ 206.265 · ϖ/mas, a projected separation of 1 pc.
PARSEC_SEPARATION = 206.265
# Eq. 2: parallaxes within 3σ, or 6σ at 4″ and closer.
CLOSE_SEPARATION = 4.0
WIDE_SIGMA, CLOSE_SIGMA = 3.0, 6.0
# Eqs. 3-6: motions apart by at most 0.44 · ϖ^1.5 · θ^-0.5 mas/yr plus 2σ.
ORBIT_MOTION = 0.44
MOTION_SIGMA = 2.0
# Parallaxes clearly disagree beyond 5σ, or 6σ at CLOSE_SEPARATION and
# closer, and by more than VETO_SHARE of the larger one.
VETO_WIDE_SIGMA, VETO_CLOSE_SIGMA = 5.0, 6.0
VETO_SHARE = 0.1
# How a member is known when it has an orbit about its primary.
ORBITS = frozenset({VISUAL_ORBIT, SPECTROSCOPIC_ORBIT, ASTROMETRIC_ORBIT, ECLIPSING})

POINT, GROUP, ENTRY = "point", "group", "entry"


def resolves(
    astrometry: str | None, separation: float | None, contrast: float | None
) -> bool | None:
    """Whether the data of a point split two stars, None when unknown.

    A point whose position is not Gaia's or Hipparcos's is one star.
    """
    if separation is None or not math.isfinite(separation):
        return None
    contrast = (
        abs(contrast) if contrast is not None and math.isfinite(contrast) else 0.0
    )
    if astrometry in GAIA_ASTROMETRY:
        limit = GAIA_MIN_SEPARATION + GAIA_SEPARATION_PER_MAG * contrast
        return separation >= limit
    if astrometry in HIPPARCOS_ASTROMETRY:
        return separation >= HIPPARCOS_SEPARATION or contrast > HIPPARCOS_MAX_CONTRAST
    return True


def same_distance(first: Fact, second: Fact) -> bool:
    """Whether two points pass El-Badry's test of a bound pair."""
    for fact in (first, second):
        if not 0 < fact.parallax_error < MAX_PARALLAX_ERROR:
            return False
        if not fact.parallax / fact.parallax_error > MIN_PARALLAX_SNR:
            return False
    bright = second if second.mag < first.mag else first
    separation = float(sky_separation(first.ra, first.dec, second.ra, second.dec))
    if not 0 < separation <= PARSEC_SEPARATION * bright.parallax:
        return False
    sigma = CLOSE_SIGMA if separation <= CLOSE_SEPARATION else WIDE_SIGMA
    errors = math.hypot(first.parallax_error, second.parallax_error)
    if not abs(first.parallax - second.parallax) < sigma * errors:
        return False
    ra, dec = first.pmra - second.pmra, first.pmdec - second.pmdec
    apart = math.hypot(ra, dec)
    orbit = ORBIT_MOTION * bright.parallax**1.5 / math.sqrt(separation)
    if apart <= orbit:
        return True
    error = (
        math.sqrt(
            (first.pmra_error**2 + second.pmra_error**2) * ra**2
            + (first.pmdec_error**2 + second.pmdec_error**2) * dec**2
        )
        / apart
    )
    return apart <= orbit + MOTION_SIGMA * error


def parallaxes_disagree(
    parallax: np.ndarray,
    error: np.ndarray,
    other: np.ndarray,
    other_error: np.ndarray,
    separation: np.ndarray,
) -> np.ndarray:
    """Whether two measured parallaxes, each over 5σ, clearly disagree."""
    with np.errstate(invalid="ignore"):
        measured = (error > 0) & (other_error > 0)
        measured &= (parallax > MIN_PARALLAX_SNR * error) & (
            other > MIN_PARALLAX_SNR * other_error
        )
        gap = np.abs(parallax - other)
        sigma = np.where(
            separation <= CLOSE_SEPARATION, VETO_CLOSE_SIGMA, VETO_WIDE_SIGMA
        )
        wide = gap > sigma * np.hypot(error, other_error)
        return measured & wide & (gap > VETO_SHARE * np.maximum(parallax, other))


def disagree(first: Fact, second: Fact) -> bool:
    """Whether the own astrometry of two points puts them at two distances."""
    if first.astrometry not in OWN_ASTROMETRY:
        return False
    if second.astrometry not in OWN_ASTROMETRY:
        return False
    separation = float(sky_separation(first.ra, first.dec, second.ra, second.dec))
    return bool(
        parallaxes_disagree(
            np.asarray(first.parallax),
            np.asarray(first.parallax_error),
            np.asarray(second.parallax),
            np.asarray(second.parallax_error),
            np.asarray(separation),
        )
    )


def simbad_only(fact: Fact | None) -> bool:
    """A point whose only astrometry is SIMBAD's position."""
    return (
        fact is not None
        and fact.astrometry == "simbad"
        and not math.isfinite(fact.parallax)
    )


@dataclass
class Member:
    kind: str
    # POINT: the point; GROUP: the index of the group.
    key: int = 0
    group: int = -1
    # The global value row of the member's node.
    value: int = -1
    # ENTRY: the label of the pair inside the group that holds it.
    inner: str | None = None


@dataclass
class Group:
    source: str
    rank: int
    system: str
    # The global value row of the group's node.
    value: int
    keys: frozenset[int]
    members: list[Member]


@dataclass
class Interior:
    key: int
    source: str
    rank: int
    system: str
    # The global value rows of its members, and the label of the inner pair
    # that holds each one.
    entries: list[tuple[int, str | None]]


@dataclass
class Absorbed:
    key: int
    into: int
    source: str
    evidence: str


@dataclass
class Tentative:
    """A pair that waits for another source to agree."""

    source: str
    system: str
    keys: frozenset[int]
    evidence: str


@dataclass
class Reduced:
    groups: list[Group] = field(default_factory=list)
    interiors: list[Interior] = field(default_factory=list)
    absorbed: list[Absorbed] = field(default_factory=list)
    tentative: list[Tentative] = field(default_factory=list)
    # (kind, source, text)
    events: list[tuple[str, str, str]] = field(default_factory=list)
    counts: Counter = field(default_factory=Counter)


@dataclass(eq=False)
class _Part:
    node: int
    key: int = 0
    # The rows of the members inside the point, or of the loose members.
    leaves: list[int] = field(default_factory=list)
    # A group: its index in the records that hold it, and its objects.
    group: int = -1
    group_keys: frozenset[int] = frozenset()
    # A group: its first point down the tree.
    first_point: int = 0

    @property
    def main(self) -> int:
        """The point of the part's position, 0 for loose members."""
        return self.key or self.first_point

    @property
    def loose(self) -> bool:
        return not self.key and self.group < 0

    @property
    def held(self) -> frozenset[int]:
        """The objects of the part."""
        return frozenset({self.key}) if self.key else self.group_keys


@dataclass
class _Error:
    """A shared id that splits the siblings that reach it."""

    key: int
    keeper: int
    losers: list[int]
    text: str
    back: bool = False


def _extend(out: Reduced, more: Reduced) -> int:
    """Add the records of `more` to `out`. Gives the shift of the group
    indices of `more`."""
    shift = len(out.groups)
    for group in more.groups:
        for member in group.members:
            if member.kind == GROUP:
                member.group += shift
    out.groups += more.groups
    out.interiors += more.interiors
    out.absorbed += more.absorbed
    out.tentative += more.tentative
    out.events += more.events
    out.counts.update(more.counts)
    return shift


class TreeReducer:
    """Reduces the trees of one source.

    `candidates` holds the (key, rank) candidates of each row, best first.
    `offset` turns a row of the source into a global value row. `orbits` are
    the points that have a Gaia DR3 orbit.
    """

    def __init__(
        self,
        table: pa.Table,
        rank: int,
        candidates: list[list[tuple[int, int]]],
        facts: Facts,
        offset: int,
        out: Reduced,
        dropped: frozenset[int] = frozenset(),
        orbits: frozenset[int] = frozenset(),
    ) -> None:
        self.source = table["source"][0].as_py() if table.num_rows else ""
        self.rank = rank
        self.facts = facts
        self.offset = offset
        self.out = out
        self.dropped = dropped
        # The points that hold several stars, in this tree or by a Gaia orbit.
        self.several = set(orbits)
        self.candidates = candidates
        self.system = table["system"].to_pylist()
        self.label = table["label"].to_pylist()
        self.parent = table["parent"].to_numpy()
        self.separation = table["separation"].to_pylist()
        self.evidence = table["evidence"].to_pylist()
        self.known = table["known"].to_pylist()
        v = table["v_mag"].to_pylist()
        g = table["g_mag"].to_pylist()
        self.mag = [b if b is not None else a for a, b in zip(v, g)]
        self.children: list[list[int]] = [[] for _ in range(table.num_rows)]
        for row, parent in enumerate(self.parent.tolist()):
            if parent >= 0:
                self.children[parent].append(row)

    def run(self) -> None:
        for root in np.flatnonzero(self.parent < 0).tolist():
            part = self.part(root, frozenset(), self.out)
            self._close(part, root, self.out)

    def _event(self, kind: str, text: str, out: Reduced) -> None:
        out.events.append((kind, self.source, text))
        out.counts[f"{self.source}: {kind}"] += 1

    def _name(self, row: int) -> str:
        return f"{self.source} {self.system[row]} {self.label[row]}"

    # Choosing a node's object

    def _choose(self, row: int, exclude: frozenset[int], out: Reduced) -> int:
        found = [
            (key, rank)
            for key, rank in self.candidates[row]
            if key not in exclude and key not in self.dropped
        ]
        if not found:
            return 0
        if len(found) > 1:
            keys = [key for key, _ in found]
            facts = [self.facts.get(key) for key in keys]
            # A SIMBAD component inside the light of a point of another id.
            for at, fact in enumerate(facts):
                if not simbad_only(fact):
                    continue
                for other, holder in zip(keys, facts):
                    if other != keys[at] and self._holds(holder, fact):
                        self._absorb(keys[at], other, holder, fact, out)
                        return other
            self._event(
                "ids reach two objects",
                f"{self._name(row)}: {keys[0]} ({HOW[found[0][1]]}) over"
                f" {keys[1]} ({HOW[found[1][1]]})",
                out,
            )
        if not self.children[row]:
            out.counts[f"{self.source}: members {HOW[found[0][1]]}"] += 1
        return found[0][0]

    def _holds(self, holder: Fact | None, inside: Fact | None) -> bool:
        """Whether the point `holder` holds the light of `inside`."""
        if holder is None or inside is None or holder.astrometry is None:
            return False
        if holder.astrometry not in GAIA_ASTROMETRY | HIPPARCOS_ASTROMETRY:
            return False
        contrast = inside.mag - holder.mag
        if not math.isfinite(contrast) or contrast >= MAX_INSIDE_MAG:
            return False
        apart = float(sky_separation(holder.ra, holder.dec, inside.ra, inside.dec))
        return resolves(holder.astrometry, apart, contrast) is False

    def _absorb(
        self,
        key: int,
        into: int,
        holder: Fact | None,
        inside: Fact | None,
        out: Reduced,
    ) -> None:
        assert holder is not None and inside is not None
        apart = float(sky_separation(holder.ra, holder.dec, inside.ra, inside.dec))
        evidence = (
            f"{apart:.1f}″ from {into} ({holder.astrometry}),"
            f" {inside.mag - holder.mag:+.1f} mag"
        )
        out.absorbed.append(Absorbed(key, into, self.source, evidence))

    # Parts

    def part(self, row: int, exclude: frozenset[int], out: Reduced) -> _Part:
        """The part of the subtree of `row`. Its records go to `out`."""
        own = self._choose(row, exclude, out)
        kids = self.children[row]
        if not kids:
            if not own:
                out.counts[f"{self.source}: members with no object"] += 1
            return _Part(row, own, [row])
        parts = self._children(row, exclude, out)
        parts = self._inside(parts, out)
        parts, own = self._own(row, own, parts, out)
        keys = {p.key for p in parts if p.key}
        groups = [p for p in parts if p.group >= 0]
        if not groups and not keys:
            if own:
                return _Part(row, own, [leaf for p in parts for leaf in p.leaves])
            return _Part(row, 0, [leaf for p in parts for leaf in p.leaves])
        if not groups and len(keys) == 1:
            (key,) = keys
            point = next(p for p in parts if p.key)
            apart = [p for p in parts if p.loose and self._split(point, p, parts[0])]
            if not apart:
                return _Part(row, key, [leaf for p in parts for leaf in p.leaves])
            inside = [p for p in parts if p not in apart]
            merged = _Part(point.node, key, [leaf for p in inside for leaf in p.leaves])
            parts = [merged, *apart]
        return self._group(row, parts, out)

    def _apart(self, first: _Part, second: _Part, primary: _Part) -> float | None:
        """The separation of two members of a group, from the source."""
        if first is primary:
            return self.separation[second.node]
        if second is primary:
            return self.separation[first.node]
        known = [
            s
            for s in (self.separation[first.node], self.separation[second.node])
            if s is not None
        ]
        return max(known) if known else None

    def _split(self, point: _Part, loose: _Part, primary: _Part) -> bool | None:
        """Whether the point's data split a loose member from it, None when
        unknown."""
        fact = self.facts.get(point.key)
        if fact is None:
            return None
        contrast = None
        if self.mag[loose.node] is not None and math.isfinite(fact.mag):
            contrast = self.mag[loose.node] - fact.mag
        apart = self._apart(point, loose, primary)
        return resolves(fact.astrometry, apart, contrast)

    def _tested(self, row: int, parts: list[_Part], out: Reduced) -> list[_Part]:
        """The members that stay beside the primary `parts[0]`."""
        primary = parts[0]
        first = self.facts.get(primary.main)
        kept = [primary]
        for part in parts[1:]:
            evidence = self.evidence[part.node]
            if part.key and part.key == primary.key:
                separation = self.separation[part.node]
                measured = separation is not None and math.isfinite(separation)
                if (
                    evidence is None
                    or (evidence == UNVERIFIED and measured)
                    or self._shared(row, [primary, part])[1]
                ):
                    # `_shared` merges them or finds the cross-match error.
                    kept.append(part)
                else:
                    name = f"{self.source}: {evidence} members on the primary's point"
                    out.counts[name] += 1
                continue
            if (
                part.loose
                and primary.key
                and evidence == UNVERIFIED
                and self._split(primary, part, primary) is False
            ):
                # `part` puts it inside the point.
                out.counts[
                    f"{self.source}: unverified members inside the primary's point"
                ] += 1
                kept.append(part)
                continue
            second = self.facts.get(part.main)
            pair = None if first is None or second is None else (first, second)
            if pair and self._vetoed(primary, part, *pair, out):
                self._leave(part, out)
                continue
            if evidence is None:
                kept.append(part)
                continue
            if evidence == UNVERIFIED and pair and same_distance(*pair):
                out.counts[f"{self.source}: unverified members kept by parallax"] += 1
                if primary.group >= 0:
                    name = f"{self.source}: unverified members of a group kept"
                    out.counts[name] += 1
                kept.append(part)
                continue
            out.counts[f"{self.source}: {evidence} members left for agreement"] += 1
            if part.held and primary.held:
                out.tentative.append(
                    Tentative(
                        self.source,
                        self.system[row],
                        primary.held | part.held,
                        evidence,
                    )
                )
            self._leave(part, out)
        return kept

    def _vetoed(
        self, primary: _Part, part: _Part, first: Fact, second: Fact, out: Reduced
    ) -> bool:
        """Whether the parallaxes of a member and its primary disagree."""
        if set(self.known[part.node] or ()) & ORBITS:
            return False
        if self._holds_several(primary) or self._holds_several(part):
            return False
        if not disagree(first, second):
            return False
        evidence = self.evidence[part.node] or "physical"
        out.counts[f"{self.source}: {evidence} members that the parallaxes veto"] += 1
        self._event(
            "parallaxes disagree",
            f"{self._name(part.node)}: {second.key} {second.parallax:.3f}"
            f" ± {second.parallax_error:.3f} mas, primary {self.label[primary.node]}"
            f" {first.key} {first.parallax:.3f} ± {first.parallax_error:.3f} mas,"
            f" {evidence}",
            out,
        )
        return True

    def _holds_several(self, part: _Part) -> bool:
        if part.key and len(part.leaves) > 1:
            return True
        return part.main in self.several

    def _leave(self, part: _Part, out: Reduced) -> None:
        """Keep the inner system of a member that leaves as a system of its own.

        A group's records stay in any case.
        """
        if part.key and len(part.leaves) > 1:
            self._close(part, part.node, out)
        elif part.group < 0:
            return
        out.counts[f"{self.source}: inner systems of members that left"] += 1

    def _children(self, row: int, exclude: frozenset[int], out: Reduced) -> list[_Part]:
        """The parts of the children of `row`.

        The checks of the unverified members and of the shared ids depend on
        the objects of the children, and a lost id changes these objects. So
        the children pass again until no id is shared, and only the last pass
        gives records. An id goes back from a keeper that leaves the tree, so
        that its object keeps a member. The loop ends, because each error
        excludes one more id for a child, and a keeper that leaves excludes
        its id from then on.
        """
        kids = self.children[row]
        # The part of a child depends only on the ids that it excludes.
        reduced: dict[tuple[int, frozenset[int]], tuple[_Part, Reduced]] = {}
        lost: dict[int, frozenset[int]] = {}
        errors: list[_Error] = []
        while True:
            done = []
            for kid in kids:
                at = (kid, exclude | lost.get(kid, frozenset()))
                if at not in reduced:
                    records = Reduced()
                    reduced[at] = (self.part(kid, at[1], records), records)
                done.append(reduced[at])
            checked = Reduced()
            parts = self._tested(row, [part for part, _ in done], checked)
            if self._give_back(errors, parts, lost):
                continue
            parts, error = self._shared(row, parts)
            if error is None:
                break
            errors.append(error)
            for loser in error.losers:
                lost[loser] = lost.get(loser, frozenset()) | {error.key}
        shift = {part.node: _extend(out, records) for part, records in done}
        _extend(out, checked)
        for part in parts:
            if part.group >= 0:
                part.group += shift[part.node]
        for error in errors:
            self._event("cross-match error", error.text, out)
            if error.back:
                out.counts[
                    f"{self.source}: shared ids back from a member that left"
                ] += 1
        return parts

    def _give_back(
        self, errors: list[_Error], parts: list[_Part], lost: dict[int, frozenset[int]]
    ) -> bool:
        """Give the id of each keeper that is not in `parts` back to the
        children that lost it. Gives whether any id went back."""
        kept = {part.node for part in parts}
        back = False
        for error in errors:
            if error.back or error.keeper in kept:
                continue
            error.back = back = True
            lost[error.keeper] = lost.get(error.keeper, frozenset()) | {error.key}
            for loser in error.losers:
                lost[loser] -= {error.key}
            error.text += (
                f"; {self.label[error.keeper]} leaves the tree, so it goes back to "
                + ", ".join(self.label[loser] or "?" for loser in error.losers)
            )
        return back

    def _shared(
        self, row: int, parts: list[_Part]
    ) -> tuple[list[_Part], _Error | None]:
        """Merge the siblings that reach one object that cannot split them.

        The first object that splits them is a cross-match error.
        """
        for _ in range(len(parts)):
            by_key: dict[int, list[_Part]] = {}
            for part in parts:
                if part.key:
                    by_key.setdefault(part.key, []).append(part)
            shared = [(key, ps) for key, ps in by_key.items() if len(ps) > 1]
            if not shared:
                return parts, None
            key, same = shared[0]
            fact = self.facts.get(key)
            primary = parts[0]
            apart = [self.separation[p.node] for p in same if p is not primary]
            known = [a for a in apart if a is not None]
            distance = max(known) if known else None
            first_mag, second_mag = self.mag[same[0].node], self.mag[same[1].node]
            contrast = None
            if first_mag is not None and second_mag is not None:
                contrast = second_mag - first_mag
            split = resolves(fact.astrometry if fact else None, distance, contrast)
            if not split:
                merged = _Part(
                    same[0].node, key, [leaf for p in same for leaf in p.leaves]
                )
                parts = [
                    merged if p is same[0] else p for p in parts if p not in same[1:]
                ]
                continue
            target = fact.mag if fact is not None else math.nan
            keep = min(
                same,
                key=lambda p: (
                    abs(self.mag[p.node] - target)
                    if self.mag[p.node] is not None and math.isfinite(target)
                    else math.inf
                ),
            )
            text = (
                f"{self.source} {self.system[row]}: "
                + ", ".join(self.label[p.node] or "?" for p in same)
                + f" reach {key} ({fact.astrometry if fact else None}),"
                f" {distance}″ apart; it stays with {self.label[keep.node]}"
            )
            losers = [p.node for p in same if p is not keep]
            return parts, _Error(key, keep.node, losers, text)
        return parts, None

    def _inside(self, parts: list[_Part], out: Reduced) -> list[_Part]:
        """Merge a SIMBAD component into the sibling point that holds its light."""
        points = [p for p in parts if p.key]
        for part in points:
            fact = self.facts.get(part.key)
            if not simbad_only(fact):
                continue
            holders = [
                other
                for other in points
                if other.key != part.key
                and self._holds(self.facts.get(other.key), fact)
            ]
            if not holders:
                continue
            holder = holders[0]
            self._absorb(part.key, holder.key, self.facts.get(holder.key), fact, out)
            holder.leaves = holder.leaves + part.leaves
            parts = [p for p in parts if p is not part]
            points = [p for p in points if p is not part]
        return parts

    def _own(
        self, row: int, own: int, parts: list[_Part], out: Reduced
    ) -> tuple[list[_Part], int]:
        if not own:
            return parts, 0
        held = frozenset().union(*(p.held for p in parts))
        if not held:
            return parts, own
        if own in held:
            self._event(
                "group id held by a member",
                f"{self._name(row)}: {own} is also a member's object",
                out,
            )
            return parts, 0
        merged = self._inside([*parts, _Part(row, own, [])], out)
        if any(p.key == own for p in merged):
            others = sorted(
                frozenset().union(*(p.held for p in merged if p.key != own))
            )
            kind, evidence = group_kind(
                self.facts.get(own), [self.facts.get(key) for key in others]
            )
            self._event(
                f"{GROUP_OBJECT}: {kind}",
                f"{self._name(row)}: {own} is a point of its own beside"
                f" {sorted(held)}; {evidence}",
                out,
            )
        return merged, 0

    def _close(self, part: _Part, top: int, out: Reduced) -> None:
        """Record the interior of a point part."""
        if part.key and len(part.leaves) > 1:
            self.several.add(part.key)
            entries = []
            for leaf in part.leaves:
                parent = int(self.parent[leaf])
                inner = self.label[parent] if parent >= 0 and parent != top else None
                entries.append((self.offset + leaf, inner))
            out.interiors.append(
                Interior(part.key, self.source, self.rank, self.system[top], entries)
            )

    def _group(self, row: int, parts: list[_Part], out: Reduced) -> _Part:
        members = []
        keys: set[int] = set()
        first_point = next((p.main for p in parts if p.main), 0)
        for part in parts:
            if part.group >= 0:
                members.append(
                    Member(GROUP, group=part.group, value=self.offset + part.node)
                )
            elif part.key:
                self._close(part, part.node, out)
                members.append(
                    Member(POINT, key=part.key, value=self.offset + part.node)
                )
            else:
                for leaf in part.leaves:
                    parent = int(self.parent[leaf])
                    inner = self.label[parent] if parent != row else None
                    members.append(Member(ENTRY, value=self.offset + leaf, inner=inner))
            keys |= part.held
        out.groups.append(
            Group(
                self.source,
                self.rank,
                self.system[row],
                self.offset + row,
                frozenset(keys),
                members,
            )
        )
        return _Part(row, 0, [], len(out.groups) - 1, frozenset(keys), first_point)
