"""The stars that the nodes hold, and the orbits of the pairs.

A held star is an entry of a node: a star with no point of its own, inside
the node's point or known from a catalogue only. It is a held star, with an
ID, when we draw its pair, or when a source gives it a letter or a name and we
know more of it: a name of its own (SIMBAD, the planet catalogues), a mass, a
radius, a temperature or a spectral type. A star that is only a letter stays
an entry: a magnitude or a separation earns no ID. An entry whose only values
are the masses of its Gaia orbit stays an entry too, and its pair keeps the
masses. Each value comes from the first source that has it: a paper, OEC, the
entry's tree source, then the masses of its Gaia orbit. Its letter is the
source's. A held star of a pair with no letter takes A when it is the
heavier star, else B, and the other letter when the other member has A or B.

The catalogues do not share letters, so a letter stays with one member of a
system, an entry too: a star before a node, then the earlier tree source
(`_letter_order`). The other member gives it up. A held star keeps its claim,
which reads the source's letter.

A pair is a node of two members. Its orbit is that of its second member
about its first (`elements`). The orbit sources reach a pair so:
- msc, orb6: the WDS id and the secondary's letters, which a member holds
  as its WDS or MSC id `<WDS id> <letters>` (an ORB6 orbit with no
  components is of A and B); else a pair whose members have
  the letters of the two sides, found by the primary's id or by the node's
  own WDS or MSC id;
- sbx: the same with its WDS alias and its component letters, else its
  Gaia DR3, HIP and HD ids, which name the point that holds the pair;
- literature and Gaia DR3: the point that holds the pair;
- oec: the OEC ids of the binary's stars on the members, else the point
  of one of its stars.
The MSC and the WDS share ids, and their separations tell whether an id names
one star (`Systems.two_stars`). An id of two stars reads the source's own
catalogue: the MSC its MSC id, ORB6 and SBX their WDS id. A member holds the
ids of its tree source only, so either catalogue reaches a star that an id
names. When it stands in both trees, the MSC's member comes first, as in the
trees, unless only the WDS's is in a pair.

A brown dwarf's pair has no point, so an orbit that names its host reaches the
pair only at the period of the record: the host can have a companion that we
do not see.

A point of three stars of two sides, as Aa and Ab1, Ab2, is the pair of its
lone star and the first star of the other side (`_outer_pairs`). Gaia DR3 sees
that outer pair of a close triple. The inner pair has no node of its own, so an
orbit at its period stays off, unless a paper gives it: then the point is the
inner pair, as papers win. The third star takes no value of the pair.

An orbit whose secondary is the node's first member is turned round, unless
the other member is not its primary: the MSC calls a pair by the letter of its
first star, as A,B for A and BC, so the orbit goes on the pair above. Through
a point, the letters of the orbit's stars and of the members tell this, and
the stars of a paper or of OEC go to the members by them. With no letters
that agree, the orbit's primary is the first member.

Each element comes from the first orbit that has it: papers, the MSC, ORB6,
SBX, OEC, then Gaia DR3, and inside a source the orbit with the most
elements first. A measured e or ω goes before an assumed one. A node that
may be either node is settled by an orbit whose ω is fixed: when the two ω
are more than 90° apart, Ω and ω turn by 180°. An assumed ω, on either side,
settles nothing. The mass ratio comes from the papers' masses, then the K1
and K2 of the MSC and SBX, then the Gaia DR3 masses, then OEC's, then the
MSC's two masses of the pair (sys.tsv).

An orbit is drawn when it has P, a, i and, unless it is circular, ω. a in
arcsec takes the node's distance, else Kepler's third law gives it from the
total mass of the papers, Gaia DR3 or OEC; the MSC's masses give only the
barycentre. A circular orbit with no ω takes CIRCULAR_OMEGA, and an orbit with
no epoch has its periastron at J2000, each named in `assumed`. With no Ω the
node is assumed at the commit, as the planets' node (`assumed_node`).
"""

import logging
import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from space_map_data.extrasolar import frame
from space_map_data.extrasolar.exoplanets.catalogues import OEC
from space_map_data.extrasolar.exoplanets.table import default_node
from space_map_data.extrasolar.sources.gaia_orbits import ASTROMETRIC
from space_map_data.extrasolar.sources.simbad import star_name
from space_map_data.extrasolar.systems.assemble import ENTRY, SYSTEM, Systems
from space_map_data.extrasolar.systems.elements import (
    Elements,
    catalogue_elements,
    gaia_elements,
)
from space_map_data.extrasolar.systems.nodes import (
    GAIA_DR3,
    GAIA_ORBITS,
    HD,
    HIP,
    MSC_ID,
    PLANETS,
    SIMBAD,
    TREE_SOURCES,
    WDS,
    WDS_ID,
)
from space_map_data.extrasolar.systems.orbits import (
    LITERATURE,
    MSC,
    OEC_STAR,
    ORB6,
    ORBIT_SOURCES,
    SBX,
)
from space_map_data.extrasolar.systems.prepare import MEMBER, Inputs, same_period
from space_map_data.extrasolar.systems.resolve import Resolver
from space_map_data.extrasolar.tables import REFERENCE, SYSTEM_STAR

logger = logging.getLogger(__name__)

# Papers first, Gaia DR3 last.
DRAW_SOURCES = (*ORBIT_SOURCES, GAIA_ORBITS)
# What gives a pair's mass ratio, first to last: two masses of a source, or
# the K1 and K2 of its orbits.
MASSES, VELOCITIES = "masses", "velocities"
MASS_RATIO_SOURCES = (
    (LITERATURE, MASSES),
    (MSC, VELOCITIES),
    (SBX, VELOCITIES),
    (GAIA_ORBITS, MASSES),
    (OEC, MASSES),
    (MSC, MASSES),
)
TOTAL_MASS_SOURCES = (LITERATURE, GAIA_ORBITS, OEC)
# The tree sources whose letter is a component label as it stands ("Aab").
LETTER_SOURCES = frozenset({WDS, MSC})
PAIR_LETTERS = ("A", "B")
BARYCENTRE, PRIMARY = "barycentre", "primary"
# The tags of the two stars of a Gaia DR3 orbit.
GAIA_SIDES = ("primary", "secondary")
ASSUMED_PHASE = "assumed"
ELEMENTS = (
    "period",
    "semi_major_axis",
    "eccentricity",
    "inclination",
    "node",
    "arg_periastron",
    "epoch",
)
STAR_VALUES = ("mass", "radius", "teff", "spectral_type")
# A component letter of the WDS and the MSC, and one at the end of a name,
# after a space or a number ("HD 27028A").
COMPONENT = re.compile(r"^[A-Z][a-z]?\d?$")
NAME_LETTER = re.compile(r"(?:\s|(?<=\d))(?P<letter>[A-Z][a-z]?\d?)$")
# The ids of an SBX system that name a point.
SBX_KEYS = (GAIA_DR3, HIP, HD)
JULIAN_YEAR = 365.25

PAIR_ORBITS = pa.schema(
    [
        ("number", pa.int64()),
        ("ra", pa.float64()),
        ("dec", pa.float64()),
        ("period", pa.float64()),
        ("semi_major_axis", pa.float64()),
        ("semi_major_axis_arcsec", pa.float64()),
        ("eccentricity", pa.float64()),
        ("inclination", pa.float64()),
        ("node", pa.float64()),
        ("node_ascending", pa.bool_()),
        ("arg_periastron", pa.float64()),
        ("epoch", pa.float64()),
        ("mean_anomaly", pa.float64()),
        ("phase", pa.string()),
        ("barycentre", pa.float64()),
        ("mass_ratio_source", pa.string()),
        *((f"{name}_source", pa.string()) for name in ELEMENTS),
        ("assumed", pa.list_(pa.string())),
        ("computed", pa.list_(pa.string())),
        ("references", pa.list_(REFERENCE)),
    ]
)
HELD_STARS = pa.schema(
    [
        # The row of the entry in `Systems.members`, and its node.
        ("member", pa.int64()),
        ("number", pa.int64()),
        # Names the star in its node, for its claim (`_tag`). Null when
        # nothing of its own names it.
        ("tag", pa.string()),
        ("letter", pa.string()),
        # True when the letter is A or B of its pair, not a source's.
        ("pair_letter", pa.bool_()),
        # The name that SIMBAD or a planet catalogue gives the star.
        ("own_name", pa.string()),
        *((f.name, f.type) for f in SYSTEM_STAR),
    ]
)


@dataclass
class Drawn:
    held: pa.Table
    orbits: pa.Table
    counts: Counter = field(default_factory=Counter)


@dataclass
class _Pair:
    first: int
    second: int
    orbits: list[Elements] = field(default_factory=list)
    # The two stars of a paper or of OEC, first member first: source →
    # (first, second), each with the keys of STAR_VALUES, `label` and
    # `spectral_type_reference`.
    stars: dict[str, tuple[dict, dict]] = field(default_factory=dict)
    reference: str | None = None
    # The MSC's two masses of the pair, first member first, and their codes.
    msc_masses: tuple[float, float] | None = None
    msc_codes: str | None = None


def _angle(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _order(item: Elements) -> tuple:
    return (
        DRAW_SOURCES.index(item.source),
        -item.drawn_elements(),
        item.grade or 99,
        item.row,
    )


def _star(row: dict) -> dict:
    return {
        name: row[name] for name in (*STAR_VALUES, "label", "spectral_type_reference")
    }


def _two(stars: list[dict]) -> tuple[dict, dict]:
    """The first two stars of a binary."""
    found = [_star(s) for s in stars[:2]]
    found += [{}] * (2 - len(found))
    return found[0], found[1]


def _letter(text: str | None) -> str | None:
    """The component letter of a label, or of a name that ends in one."""
    if not text:
        return None
    if COMPONENT.match(text):
        return text
    found = NAME_LETTER.search(text)
    return found["letter"] if found else None


def _source_letter(entry: dict, labels: Iterable[str | None] = ()) -> str | None:
    """The component letter that a source gives a member: one at the end of
    one of `labels` or of its own letter or label, else its letter as the WDS
    or the MSC gives it ("Aab", "S17")."""
    texts = [*labels, entry["letter"], entry["label"]]
    found = next((letter for text in texts if (letter := _letter(text))), None)
    if found is None and entry["source"] in LETTER_SOURCES:
        found = entry["letter"]
    return found


def _letter_order(entry: dict, row: int) -> tuple[bool, int, int]:
    """Which member of a system keeps a letter that several have, lowest
    first. A node's letter is that of its main star, so a star goes first.
    Then the order is the tree sources, then the members."""
    source = entry["source"]
    rank = TREE_SOURCES.index(source) if source in TREE_SOURCES else len(TREE_SOURCES)
    return entry["kind"] == SYSTEM, rank, row


def without_letters(members: pa.Table, rows: set[int]) -> pa.Table:
    """`members` with no letter on `rows`. `inner` goes too, and a `label`
    that only repeats the letter, because a client reads them as the letter."""
    keep = np.ones(members.num_rows, bool)
    keep[list(rows)] = False
    mask = pa.array(keep)
    only_letter = pc.equal(members["label"], members["letter"]).fill_null(False)
    kept = {
        "letter": mask,
        "inner": mask,
        "label": pc.or_(mask, pc.invert(only_letter)),
    }
    for name, stays in kept.items():
        column = pc.if_else(stays, members[name], pa.scalar(None, pa.string()))
        members = members.set_column(members.schema.get_field_index(name), name, column)
    return members


def _tag(entry: dict, letter: str | None) -> str | None:
    """What names a held star in its node, the same in each ingest: its own
    letter or label, else its side of its Gaia DR3 orbit, else the letter of
    a paper or of OEC (`letter`). None when nothing does: its place among
    the members can change."""
    if entry["letter"] or entry["label"]:
        return entry["letter"] or entry["label"]
    if entry["source"] == GAIA_ORBITS:
        # Only the companion has the kind of the orbit (`assemble`).
        return GAIA_SIDES[entry["known"] is not None]
    return letter


def _own_name(entry: dict) -> str | None:
    """The name that SIMBAD or a planet catalogue gives an entry, spelled as
    the name of a star."""
    label = entry["label"]
    if not label:
        return None
    if entry["source"] == SIMBAD:
        return star_name([label], label)
    return label if entry["source"] == PLANETS else None


def _missing(values: dict) -> str | None:
    """The first element that the orbit needs and lacks."""
    if not values["period"] or values["period"] <= 0:
        return "period"
    if values["semi_major_axis"] is None:
        return "semi-major axis"
    if values["inclination"] is None:
        return "inclination"
    e = values["eccentricity"]
    if e is None or not 0 <= e < 1:
        return "eccentricity in [0, 1)"
    if values["arg_periastron"] is None:
        return "argument of periastron"
    return None


class Drawer:
    """Matches the orbit sources to the pairs of `systems` and draws them."""

    def __init__(self, systems: Systems, inputs: Inputs, resolver: Resolver) -> None:
        self.systems = systems
        self.inputs = inputs
        self.resolver = resolver
        self.counts: Counter = Counter()
        nodes = systems.nodes.take(pc.sort_indices(systems.nodes["node"]))
        self.number = nodes["node"].to_numpy()
        self.parent = nodes["parent"].fill_null(0).to_numpy()
        self.root = nodes["root"].to_numpy()
        self.ra = nodes["ra"].fill_null(np.nan).to_numpy()
        self.dec = nodes["dec"].fill_null(np.nan).to_numpy()
        self.distance = nodes["distance"].fill_null(np.nan).to_numpy()
        self.member_node = systems.members["node"].to_numpy()
        starts = np.searchsorted(self.member_node, self.number)
        ends = np.searchsorted(self.member_node, self.number, "right")
        two = np.flatnonzero(ends - starts == 2)
        self.pairs = {
            int(self.number[at]): _Pair(int(starts[at]), int(starts[at] + 1))
            for at in two.tolist()
        }
        keys = nodes["key"].to_numpy()
        self.point_node = {
            int(key): int(number)
            for key, number in zip(keys[two].tolist(), self.number[two].tolist())
            if key
        }
        # The periods of the records of each pair of a host and its brown dwarf.
        self.record_periods: dict[int, list[float]] = {}
        self.point_node = self._host_pairs() | self.point_node
        # The points of three stars with their outer pair, and the letters of
        # the side that their second member stands for.
        self.outer: set[int] = set()
        self.sides: dict[int, str] = {}
        # The member rows and the period of the inner pair of these points.
        self.inner_pairs: dict[int, tuple[int, int]] = {}
        self.inner_periods: dict[int, float] = {}
        self._outer_pairs(keys, starts, ends)
        # The points that hold three or more stars.
        self.other_points = set(keys[keys != 0].tolist()) - set(self.point_node)
        self.msc_members = self._member_ids((MSC_ID,))
        self.wds_members = self._member_ids((WDS_ID,))
        self.by_node = self._node_ids(nodes)
        self.by_oec = self._member_ids((OEC_STAR,))
        self.oec_of = {row: name for name, row in self.by_oec.items()}
        self.oec_stars: dict[str, dict] = {}
        # The member rows that give up their letter.
        self.repeated: set[int] = set()
        stars = inputs.catalogue_stars
        if stars is not None:
            for star in stars.filter(pc.equal(stars["source"], OEC)).to_pylist():
                if star["label"]:
                    self.oec_stars.setdefault(star["label"], _star(star))

    def _host_pairs(self) -> dict[int, int]:
        """The pair of each host whose brown dwarf is its partner. An orbit
        that names the host can be of that pair (`_of_pair`)."""
        overlaps = self.systems.overlaps
        records: dict[int, list[dict]] = defaultdict(list)
        for item in overlaps.filter(pc.equal(overlaps["outcome"], MEMBER)).to_pylist():
            records[item["key"]].append(item)
        keys = self.systems.members["key"].to_numpy()
        found: dict[int, int] = {}
        for row in np.flatnonzero(np.isin(keys, list(records))).tolist():
            number = int(self.member_node[row])
            pair = self.pairs.get(number)
            if pair is None:
                continue
            for item in records[int(keys[row])]:
                if item["host"] in (keys[pair.first], keys[pair.second]):
                    found[item["host"]] = number
                    periods = self.record_periods.setdefault(number, [])
                    if item["period"]:
                        periods.append(item["period"])
        return found

    def _outer_pairs(
        self, keys: np.ndarray, starts: np.ndarray, ends: np.ndarray
    ) -> None:
        """Give each point of three stars of two sides its outer pair."""
        three = np.flatnonzero((ends - starts == 3) & (keys != 0))
        rows = pa.array(np.repeat(starts[three], 3) + np.tile([0, 1, 2], three.size))
        members = self.systems.members.select(["inner", "period"]).take(rows)
        inner = members["inner"].to_pylist()
        period = members["period"].to_pylist()
        for index, at in enumerate(three.tolist()):
            first, second, third = inner[3 * index : 3 * index + 3]
            if first is None and second is not None and second == third:
                other = 1
            elif third is None and first is not None and first == second:
                other = 2
            else:
                continue
            number = int(self.number[at])
            start = int(starts[at])
            self.pairs[number] = _Pair(start, start + other)
            self.point_node[int(keys[at])] = number
            self.outer.add(number)
            self.inner_pairs[number] = (start + 2 - other, start + 3 - other)
            if other == 1:
                self.sides[number] = second
            if (found := period[3 * index + 3 - other]) is not None:
                self.inner_periods[number] = found

    def _member_ids(self, catalogues: tuple[tuple[str, str], ...]) -> dict[str, int]:
        """The member row of each id of these catalogues on a member."""
        ids = self.systems.members["ids"].combine_chunks()
        flat = pc.list_flatten(ids)
        hit = pa.array(np.zeros(len(flat), bool))
        for catalogue, release in catalogues:
            hit = pc.or_(
                hit,
                pc.and_(
                    pc.equal(flat.field("catalogue"), catalogue),
                    pc.equal(flat.field("release"), release),
                ),
            )
        hit = hit.fill_null(False)
        texts = flat.field("catalogue_id").filter(hit).to_pylist()
        rows = pc.list_parent_indices(ids).filter(hit).to_pylist()
        found: dict[str, int] = {}
        for text, row in zip(texts, rows):
            if found.setdefault(text, row) != row:
                self.counts["member ids that two members hold"] += 1
        return found

    def _node_ids(self, nodes: pa.Table) -> dict[str, int]:
        """The node of each of its WDS and MSC ids."""
        ids = nodes["catalogue_ids"].combine_chunks()
        flat = pc.list_flatten(ids)
        hit = pc.or_(
            pc.equal(flat.field("catalogue"), WDS_ID[0]),
            pc.equal(flat.field("catalogue"), MSC_ID[0]),
        ).fill_null(False)
        texts = flat.field("catalogue_id").filter(hit).to_pylist()
        rows = pc.list_parent_indices(ids).filter(hit).to_numpy()
        found: dict[str, int] = {}
        for text, number in zip(texts, self.number[rows].tolist()):
            found.setdefault(text, number)
        return found

    def _letters(self, row: int) -> str | None:
        members = self.systems.members
        return _letter(members["letter"][row].as_py() or members["label"][row].as_py())

    # Matching

    def _add(self, number: int, item: Elements, flipped: bool) -> None:
        self.pairs[number].orbits.append(item.flipped() if flipped else item)
        self.counts[f"{item.source}: orbits on a pair"] += 1

    def _component(self, source: str, text: str) -> int | None:
        """The member row with the component id `text`, for an orbit source.
        An id of two stars reads its own catalogue. An id of one star takes
        the MSC's member, unless only the WDS's is in a pair."""
        msc, wds = self.msc_members.get(text), self.wds_members.get(text)
        if text in self.systems.two_stars:
            return msc if source == MSC else wds
        if msc is None or (wds is not None and self.member_node[msc] not in self.pairs):
            return wds
        return msc

    def _by_component(self, source: str, text: str) -> tuple[int, int] | None:
        """The node of the member that has the id `text`, and its row."""
        row = self._component(source, text)
        return None if row is None else (int(self.member_node[row]), row)

    def _by_letters(
        self, source: str, wds: str, primary: str | None, secondary: str
    ) -> tuple[int, bool] | None:
        """A pair whose members have the letters of the two sides, reached by
        the primary's id or by the node's own id, and whether its first
        member is the secondary. A letter of two stars tells nothing."""
        if not primary or f"{wds} {secondary}" in self.systems.two_stars:
            return None
        numbers = []
        row = self._component(source, f"{wds} {primary}")
        if row is not None:
            numbers.append(int(self.member_node[row]))
        for text in (f"{wds} {primary}{secondary}", wds):
            if (number := self.by_node.get(text)) is not None:
                numbers.append(number)
        for number in numbers:
            pair = self.pairs.get(number)
            if pair is None:
                continue
            side = self.sides.get(number) or self._letters(pair.second)
            found = (self._letters(pair.first), side)
            if found in ((primary, secondary), (secondary, primary)):
                return number, found[0] == secondary
        return None

    def _heads_another_pair(self, pair: _Pair, row: int, primary: str | None) -> bool:
        """Whether the member `row`, an orbit's secondary, is the first star
        of a pair with a star that is not the orbit's primary. The other
        member can be a pair, as CD."""
        members = self.systems.members
        other = members["letter"][pair.second].as_py() or self._letters(pair.second)
        if row != pair.first or not primary or not other:
            return False
        return not (other.startswith(primary) or primary.startswith(other))

    def _pair_above(self, number: int) -> tuple[int, bool] | None:
        """The pair that holds the node `number`, and whether that node is its
        first member."""
        above = int(self.parent[np.searchsorted(self.number, number)])
        pair = self.pairs.get(above)
        if pair is None:
            return None
        return above, self.systems.members["member"][pair.first].as_py() == number

    def _secondary_pair(
        self, number: int, pair: _Pair, row: int, primary: str | None, what: str
    ) -> tuple[int, bool] | None:
        """The pair of an orbit whose secondary is the member `row` of `pair`,
        the node `number`, or the pair above when that member heads another
        pair, and whether its first member is the secondary. None with no
        pair above. `what` names the count."""
        if not self._heads_another_pair(pair, row, primary):
            return number, row == pair.first
        self.counts[f"{what} of a star that heads a pair"] += 1
        return self._pair_above(number)

    def _on_component(
        self, item: Elements, text: str, primary: str | None = None
    ) -> bool:
        """Put the orbit on the pair whose member has the id `text`, or on the
        pair above when that member heads another pair. False when no such
        pair is there."""
        hit = self._by_component(item.source, text)
        if hit is None:
            return False
        number, row = hit
        pair = self.pairs.get(number)
        if pair is None or row not in (pair.first, pair.second):
            self.counts[f"{item.source}: orbits of a node that is no pair"] += 1
            return True
        found = self._secondary_pair(
            number, pair, row, primary, f"{item.source}: orbits"
        )
        if found is None:
            return False
        self._add(found[0], item, found[1])
        return True

    def _on_letters(
        self, item: Elements, wds: str, primary: str | None, secondary: str
    ) -> bool:
        """Put the orbit on a pair whose members have the letters of its two
        sides."""
        found = self._by_letters(item.source, wds, primary, secondary)
        if found is None:
            return False
        self._add(found[0], item, found[1])
        self.counts[f"{item.source}: orbits on a pair by its letters"] += 1
        return True

    def _points(
        self, wanted: list[tuple[int, tuple[str, str], str]]
    ) -> tuple[dict[int, int], set[int]]:
        """The pair of the point of each (index, catalogue, id), by index, and
        the indexes whose point holds more than two stars."""
        by_catalogue: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)
        for index, catalogue, text in wanted:
            by_catalogue[catalogue].append((index, text))
        found: dict[int, int] = {}
        larger: set[int] = set()
        for catalogue, items in sorted(by_catalogue.items()):
            texts = pa.array([text for _, text in items], pa.string())
            keys = self.resolver.keys(*catalogue, texts)
            for (index, _), key in zip(items, keys.tolist()):
                number = self.point_node.get(int(key))
                if number is not None:
                    found.setdefault(index, number)
                elif key in self.other_points:
                    larger.add(index)
        return found, larger

    def _of_pair(self, number: int, item: Elements) -> bool:
        """Whether an orbit that names a point is of its pair. The pair of a
        host and its brown dwarf takes only the orbit of the record's period.
        A point of three stars takes the orbit of its inner pair from a paper
        only, and then no other."""
        period = item.period
        assert period is not None
        inner = self.inner_periods.get(number)
        if inner is not None and same_period(period, inner):
            if item.source != LITERATURE:
                self.counts[f"{item.source}: orbits of an inner pair"] += 1
                return False
            self.pairs[number] = _Pair(*self.inner_pairs[number])
            self.record_periods[number] = [inner]
            self.outer.discard(number)
            self.sides.pop(number, None)
            del self.inner_periods[number]
        periods = self.record_periods.get(number)
        if periods is None:
            return True
        if any(same_period(period, found) for found in periods):
            return True
        self.counts[f"{item.source}: orbits of a host at another period"] += 1
        return False

    def match_catalogues(self) -> None:
        table = self.inputs.catalogue_orbits
        if table is None:
            return
        rows = table.to_pylist()
        stars: dict[tuple[str, str | None], list[dict]] = defaultdict(list)
        if self.inputs.catalogue_stars is not None:
            for star in self.inputs.catalogue_stars.to_pylist():
                stars[(star["source"], star["system"])].append(star)
        wanted: list[tuple[int, tuple[str, str], str]] = []
        items: dict[int, Elements] = {}
        for at, row in enumerate(rows):
            item = catalogue_elements(row)
            source = row["source"]
            if item is None:
                self.counts[f"{source}: orbits with no period"] += 1
                continue
            items[at] = item
            before = len(wanted)
            ids = [
                ((i["catalogue"], i["release"]), i["catalogue_id"])
                for i in row["ids"] or []
            ]
            wds = [text for pair, text in ids if pair == WDS_ID]
            primary, letters = row["primary"], row["secondary"]
            if source == ORB6 and not row["pair"]:
                # As in the WDS, no components name the only pair, A and B.
                primary, letters = "A", "B"
            if source not in (MSC, ORB6, SBX):
                letters = None
            text = f"{wds[0]} {letters}" if wds else ""
            if letters and wds and self._on_component(item, text, primary):
                continue
            if letters and wds and self._on_letters(item, wds[0], primary, letters):
                continue
            if source == SBX:
                wanted += [(at, pair, text) for pair, text in ids if pair in SBX_KEYS]
            elif source == LITERATURE:
                wanted += [(at, pair, text) for pair, text in ids]
            elif source == OEC:
                binary = [
                    s
                    for s in stars[(OEC, row["system"])]
                    if s["designation"] == row["designation"]
                ]
                if self._oec_members(item, binary):
                    continue
                wanted += [(at, OEC_STAR, s["label"]) for s in binary if s["label"]]
            if len(wanted) == before:
                self.counts[f"{source}: orbits of pairs in no tree"] += 1
        found, larger = self._points(wanted)
        for at in sorted({index for index, _, _ in wanted}):
            item = items[at]
            number = found.get(at)
            if number is None:
                where = "a node that is no pair" if at in larger else "pairs in no tree"
                self.counts[f"{item.source}: orbits of {where}"] += 1
                continue
            if not self._of_pair(number, item):
                continue
            pair, row = self.pairs[number], rows[at]
            two = _two(
                [
                    s
                    for s in stars[(item.source, row["system"])]
                    if s["designation"] == row["designation"]
                ]
            )
            labels = (row["primary"], row["secondary"])
            if item.source == OEC:
                labels = (two[0].get("label"), two[1].get("label"))
            turned = self._turned(pair, labels)
            self._add(number, item, turned)
            if turned:
                two = (two[1], two[0])
                self.counts[f"{item.source}: orbits turned by the letters"] += 1
            if item.source == LITERATURE:
                pair.stars[LITERATURE] = two
                pair.reference = row["reference"]
            elif item.source == OEC:
                pair.stars.setdefault(OEC, two)

    def _turned(self, pair: _Pair, labels: tuple[str | None, str | None]) -> bool:
        """Whether the secondary of an orbit whose two stars have these
        labels is the pair's first member, by their letters. With no letters
        that agree, its primary is the first member."""
        first, second = self._letters(pair.first), self._letters(pair.second)
        primary, secondary = (_letter(label) for label in labels)
        return (secondary is not None and secondary == first) or (
            primary is not None and primary == second
        )

    def _oec_members(self, item: Elements, binary: list[dict]) -> bool:
        """Put an OEC binary on the pair whose members are its two stars."""
        rows = [self.by_oec.get(s["label"]) for s in binary if s["label"]]
        if len(binary) != 2 or len(rows) != 2 or None in rows:
            return False
        first, second = rows
        assert first is not None
        number = int(self.member_node[first])
        pair = self.pairs.get(number)
        if pair is None or {first, second} != {pair.first, pair.second}:
            return False
        flipped = first == pair.second
        self._add(number, item, flipped)
        stars = _two(binary)
        pair.stars[OEC] = (stars[1], stars[0]) if flipped else stars
        return True

    def match_msc_masses(self) -> None:
        """Put the MSC's two masses of each pair on the pair, as its orbits
        reach it."""
        table = self.inputs.catalogue_stars
        if table is None:
            return
        by_row: dict[int, list[dict]] = defaultdict(list)
        for star in table.filter(pc.equal(table["source"], MSC)).to_pylist():
            by_row[star["row"]].append(star)
        for first, second in by_row.values():
            wds, primary, secondary = (
                first["system"],
                first["primary"],
                first["secondary"],
            )
            hit = self._by_component(MSC, f"{wds} {secondary}")
            if hit is None:
                found = self._by_letters(MSC, wds, primary, secondary)
                if found is None:
                    self.counts["msc: masses of pairs in no tree"] += 1
                    continue
            else:
                number, row = hit
                pair = self.pairs.get(number)
                if pair is None or row not in (pair.first, pair.second):
                    self.counts["msc: masses of a node that is no pair"] += 1
                    continue
                found = self._secondary_pair(number, pair, row, primary, "msc: masses")
                if found is None:
                    continue
            number, flipped = found
            pair = self.pairs[number]
            if pair.msc_masses is not None:
                continue
            stars = (second, first) if flipped else (first, second)
            pair.msc_masses = (stars[0]["mass"], stars[1]["mass"])
            pair.msc_codes = "/".join(s["mass_method"] or "-" for s in stars)
            self.counts["msc: masses on a pair"] += 1

    def match_gaia(self) -> None:
        table = self.inputs.orbit_elements
        keys = self.systems.orbit_keys
        if table is None or not keys.size:
            return
        at = np.flatnonzero(np.isin(keys, np.array(list(self.point_node), np.int64)))
        rows = table.take(pa.array(at)).to_pylist()
        for index, key, row in zip(at.tolist(), keys[at].tolist(), rows):
            item = gaia_elements(row, index)
            if item is None or not self._of_pair(self.point_node[int(key)], item):
                continue
            self._add(self.point_node[int(key)], item, False)
            if row["nss_solution_type"] in ASTROMETRIC:
                case = "a relative orbit" if item.a_au else "a photocentre only"
                self.counts[f"Gaia DR3 astrometric orbits on a pair: {case}"] += 1

    # Orbits

    def orbit(self, number: int, pair: _Pair) -> dict | None:
        """The PAIR_ORBITS row of a pair, None when it cannot be drawn."""
        items = sorted(pair.orbits, key=_order)
        at = int(np.searchsorted(self.number, number))
        if not (math.isfinite(self.ra[at]) and math.isfinite(self.dec[at])):
            self.counts["pairs with orbits and no position"] += 1
            return None
        distance = float(self.distance[at])
        chosen: dict[str, Elements] = {}

        def first(name: str, measured: bool = False) -> Elements | None:
            return next(
                (
                    i
                    for i in items
                    if getattr(i, name) is not None
                    and not (measured and name in i.assumed)
                ),
                None,
            )

        for name in ("period", "inclination", "node", "epoch"):
            if (hit := first(name)) is not None:
                chosen[name] = hit
        for name in ("eccentricity", "arg_periastron"):
            if (hit := first(name, measured=True) or first(name)) is not None:
                chosen[name] = hit
        values = {
            name: getattr(chosen[name], name) if name in chosen else None
            for name in ELEMENTS
        }
        assumed = [
            name
            for name in ("eccentricity", "arg_periastron")
            if name in chosen and name in chosen[name].assumed
        ]
        if values["eccentricity"] and "arg_periastron" in assumed:
            # A circular orbit's ω, which the measured e makes no ω.
            values["arg_periastron"] = None
        arcsec = None
        for item in items:
            a = item.a_au
            if a is None and item.a_arcsec is not None and distance > 0:
                a, arcsec = item.a_arcsec * distance, item.a_arcsec
            if a is not None:
                values["semi_major_axis"] = a
                chosen["semi_major_axis"] = item
                break
        ratio, ratio_from, total, total_source = self._masses(pair, items)
        computed = []
        if values["semi_major_axis"] is None and total and values["period"]:
            years = values["period"] / JULIAN_YEAR
            values["semi_major_axis"] = (total * years * years) ** (1 / 3)
            computed.append("semi_major_axis")
        reason = _missing(values)
        if reason:
            self.counts[f"pairs with orbits and no {reason}"] += 1
            return None
        node = chosen.get("node")
        ascending = node is not None and node.node_ascending
        fixed = next((i for i in items if i.omega_fixed), None)
        own = None
        if node is not None and "arg_periastron" not in node.assumed:
            own = node.arg_periastron
        if node is not None and not ascending and fixed and own is not None:
            assert fixed.arg_periastron is not None and values["node"] is not None
            # The node's own ω goes with it: far from the fixed ω, both turn.
            if _angle(fixed.arg_periastron, own) > 90:
                values["node"] = (values["node"] + 180) % 360
                if chosen["arg_periastron"] is node:
                    values["arg_periastron"] = (own + 180) % 360
                self.counts["nodes turned by an orbit with a fixed ω"] += 1
            else:
                self.counts["nodes kept by an orbit with a fixed ω"] += 1
            ascending = True
        epoch = chosen.get("epoch")
        if epoch is None:
            values["epoch"], anomaly, phase = frame.J2000, 0.0, ASSUMED_PHASE
            assumed.append("epoch")
        else:
            anomaly, phase = epoch.mean_anomaly, epoch.phase
        if node is None:
            assumed.append("node")
        sources = {
            f"{name}_source": chosen[name].source if name in chosen else None
            for name in ELEMENTS
        }
        if computed:
            sources["semi_major_axis_source"] = total_source
        used = {item.source: item for item in chosen.values()}
        references = [
            {"source": source, "reference": used[source].reference}
            for source in DRAW_SOURCES
            if source in used and used[source].reference
        ]
        self.counts[f"pairs drawn, period from {chosen['period'].source}"] += 1
        if ratio_from is not None:
            self.counts[f"pairs drawn, mass ratio from {' '.join(ratio_from)}"] += 1
            if ratio_from == (MSC, MASSES):
                self.counts[f"pairs drawn, MSC mass codes {pair.msc_codes}"] += 1
        return {
            "number": number,
            "ra": float(self.ra[at]),
            "dec": float(self.dec[at]),
            **values,
            "semi_major_axis_arcsec": arcsec,
            "node_ascending": ascending,
            "mean_anomaly": anomaly,
            "phase": phase,
            "barycentre": ratio,
            "mass_ratio_source": None if ratio_from is None else ratio_from[0],
            **sources,
            "assumed": sorted(assumed),
            "computed": computed,
            "references": references,
        }

    def _two_masses(
        self, pair: _Pair, items: list[Elements], source: str
    ) -> tuple[float, float] | None:
        """The masses of the pair's two stars that `source` gives, first
        member first."""
        found: tuple | None = None
        if source == GAIA_ORBITS:
            hit = next(
                (i for i in items if i.source == source and i.mass1 and i.mass2),
                None,
            )
            found = None if hit is None else (hit.mass1, hit.mass2)
        elif source == MSC:
            found = pair.msc_masses
        elif source in pair.stars:
            found = tuple(star.get("mass") for star in pair.stars[source])
        if found is None:
            return None
        m1, m2 = found
        return (m1, m2) if m1 and m2 and m1 > 0 and m2 > 0 else None

    def _masses(
        self, pair: _Pair, items: list[Elements]
    ) -> tuple[float | None, tuple[str, str] | None, float | None, str | None]:
        """The barycentre's share of the separation and what gave it (an
        item of MASS_RATIO_SOURCES), and the total mass with its source."""
        ratio = ratio_from = None
        for name, kind in MASS_RATIO_SOURCES:
            if kind == VELOCITIES:
                k = next(
                    ((i.k1, i.k2) for i in items if i.source == name and i.k1 and i.k2),
                    None,
                )
                share = None if k is None else k[0] / (k[0] + k[1])
            else:
                masses = self._two_masses(pair, items, name)
                share = None if masses is None else masses[1] / sum(masses)
            if share is not None:
                ratio, ratio_from = share, (name, kind)
                break
        total = total_source = None
        for name in TOTAL_MASS_SOURCES:
            if (masses := self._two_masses(pair, items, name)) is not None:
                total, total_source = sum(masses), name
                break
        return ratio, ratio_from, total, total_source

    # Held stars

    def held(self, drawn: Iterable[int] = ()) -> pa.Table:
        """The held stars: the entries of the pairs with these node numbers,
        which are drawn, and the entries that a source names and that we know
        more of."""
        in_drawn = {
            row
            for number in drawn
            for row in (self.pairs[number].first, self.pairs[number].second)
        }
        members = self.systems.members
        kinds = members["kind"].to_numpy(zero_copy_only=False)
        rows = np.flatnonzero(kinds == ENTRY)
        part = members.take(pa.array(rows)).select(
            [
                "node",
                "letter",
                "label",
                "source",
                "mass",
                "spectral_type",
                "known",
                "v_mag",
                "g_mag",
            ]
        )
        gaia = self._gaia_masses()
        out: dict[str, list] = defaultdict(list)
        # The letters of the entries with no ID, which a page lists too.
        lines: dict[int, str | None] = {}
        for row, entry in zip(rows.tolist(), part.to_pylist()):
            values = self._values(row, entry, gaia)
            named = values["letter"] is not None or bool(entry["label"])
            known = any(values[name] is not None for name in STAR_VALUES)
            if not named and row not in in_drawn:
                self.counts["entries that no source names, in no drawn pair"] += 1
                if known:
                    self.counts[
                        "entries that no source names, in no drawn pair, with values"
                    ] += 1
                continue
            own = _own_name(entry)
            if row not in in_drawn and not (known or own):
                self.counts[
                    f"entries that are only a letter, of {entry['source']}"
                ] += 1
                lines[row] = values["letter"]
                continue
            tag = _tag(entry, values["letter"])
            if tag is None:
                self.counts["held stars that nothing of their own names"] += 1
            out["member"].append(row)
            out["number"].append(entry["node"])
            out["tag"].append(tag)
            out["pair_letter"].append(False)
            out["own_name"].append(own)
            for name, value in values.items():
                out[name].append(value)
            self.counts[f"held stars of {entry['source'] or 'no source'} entries"] += 1
            self.counts[
                "held stars that a source names"
                if named
                else "held stars that no source names, of drawn pairs"
            ] += 1
            if row in in_drawn:
                self.counts["held stars of drawn pairs"] += 1
            for source in {values[f"{n}_source"] for n in STAR_VALUES} - {
                None,
                entry["source"],
            }:
                self.counts[f"held stars with values from {source}"] += 1
        self.repeated = self._repeated_letters(
            lines | dict(zip(out["member"], out["letter"]))
        )
        for i, row in enumerate(out["member"]):
            if row in self.repeated:
                out["letter"][i] = None
        self._pair_letters(out)
        return pa.table(
            {name: out[name] for name in HELD_STARS.names}, schema=HELD_STARS
        )

    def _repeated_letters(self, letters: dict[int, str | None]) -> set[int]:
        """The member rows whose letter another member of their system keeps
        (`_letter_order`). `letters` gives those of the entries."""
        members = self.systems.members
        kinds = members["kind"].to_numpy(zero_copy_only=False)
        lettered = members["letter"].is_valid().to_numpy(zero_copy_only=False)
        rows = np.flatnonzero(lettered & (kinds != ENTRY))
        part = members.take(pa.array(rows)).select(["letter", "label", "source"])
        letters |= zip(rows.tolist(), map(_source_letter, part.to_pylist()))
        given = {row: text for row, text in letters.items() if text}
        rows = np.array(list(given), np.int64)
        part = members.take(pa.array(rows)).select(["node", "kind", "source"])
        holders: defaultdict[tuple[int, str], list] = defaultdict(list)
        for row, entry in zip(rows.tolist(), part.to_pylist()):
            root = self.root[np.searchsorted(self.number, entry["node"])]
            holders[int(root), given[row]].append(
                (_letter_order(entry, row), row, entry["kind"])
            )
        repeated: set[int] = set()
        for found in holders.values():
            for _, row, kind in sorted(found)[1:]:
                repeated.add(row)
                self.counts[f"letters given up by {kind} members"] += 1
        logger.info("systems: %d members give up a letter", len(repeated))
        return repeated

    def _pair_letters(self, out: dict[str, list]) -> None:
        """A or B for each held star of a pair with no letter: A for the
        heavier star, else for the first member, and the other letter when
        the other member has A or B."""
        at = {row: i for i, row in enumerate(out["member"])}
        given = list(out["letter"])
        members = self.systems.members
        for i, (row, number) in enumerate(zip(out["member"], out["number"])):
            pair = self.pairs.get(number)
            if (
                given[i] is not None
                or pair is None
                or row not in (pair.first, pair.second)
            ):
                continue
            other = pair.second if row == pair.first else pair.first
            if other in at:
                theirs, their_mass = given[at[other]], out["mass"][at[other]]
            else:
                entry = members.slice(other, 1).to_pylist()[0]
                their_mass = entry["mass"]
                theirs = None if other in self.repeated else _source_letter(entry)
            mine = out["mass"][i]
            if theirs in PAIR_LETTERS:
                letter = PAIR_LETTERS[1 - PAIR_LETTERS.index(theirs)]
            elif mine is not None and their_mass is not None and mine != their_mass:
                letter = PAIR_LETTERS[0 if mine > their_mass else 1]
            else:
                letter = PAIR_LETTERS[0 if row == pair.first else 1]
            out["letter"][i] = letter
            out["pair_letter"][i] = True
            self.counts["held stars with a letter of their pair"] += 1

    def _gaia_masses(self) -> dict[int, float]:
        """The Gaia DR3 mass of each member of a pair with a Gaia orbit."""
        found: dict[int, float] = {}
        for number, pair in self.pairs.items():
            hit = next((i for i in pair.orbits if i.source == GAIA_ORBITS), None)
            if hit is None or number in self.outer:
                continue
            for row, mass in ((pair.first, hit.mass1), (pair.second, hit.mass2)):
                if mass is not None:
                    found[row] = mass
        return found

    def _values(self, row: int, entry: dict, gaia: dict[int, float]) -> dict:
        """The SYSTEM_STAR values of an entry, and its letter."""
        pair = self.pairs.get(entry["node"])
        given: list[tuple[str, dict]] = []
        stands_for_one = pair is not None and entry["node"] not in self.outer
        if stands_for_one and row in (pair.first, pair.second):
            side = 0 if row == pair.first else 1
            given += [
                (source, pair.stars[source][side])
                for source in (LITERATURE, OEC)
                if source in pair.stars
            ]
        own = self.oec_stars.get(self.oec_of.get(row, ""))
        if own is not None and all(source != OEC for source, _ in given):
            given.append((OEC, own))
        tree = {"mass": entry["mass"], "spectral_type": entry["spectral_type"]}
        given.append((entry["source"], tree))
        if row in gaia and entry["source"] != GAIA_ORBITS:
            given.append((GAIA_ORBITS, {"mass": gaia[row]}))
        values: dict = {}
        for name in STAR_VALUES:
            hit = next(
                ((v[name], s) for s, v in given if v.get(name) is not None), None
            )
            values[name], values[f"{name}_source"] = hit or (None, None)
        works = []
        if pair is not None:
            paper = dict(given).get(LITERATURE, {})
            works = [
                paper["spectral_type_reference"]
                if name == "spectral_type"
                else pair.reference
                for name in STAR_VALUES
                if values[f"{name}_source"] == LITERATURE
            ]
        values["references"] = [
            {"source": LITERATURE, "reference": work}
            for work in dict.fromkeys(works)
            if work
        ]
        values["letter"] = _source_letter(entry, [v.get("label") for _, v in given])
        values["v_mag"], values["g_mag"] = entry["v_mag"], entry["g_mag"]
        return values


def draw(systems: Systems, inputs: Inputs, resolver: Resolver) -> Drawn:
    """The held stars and the orbits of the pairs of `systems`. The repeated
    letters leave `systems.members`, after the orbits have used them."""
    drawer = Drawer(systems, inputs, resolver)
    drawer.counts["pairs"] = len(drawer.pairs)
    drawer.match_catalogues()
    drawer.match_msc_masses()
    drawer.match_gaia()
    rows = []
    for number, pair in sorted(drawer.pairs.items()):
        if pair.orbits:
            drawer.counts["pairs with orbits"] += 1
            if (found := drawer.orbit(number, pair)) is not None:
                rows.append(found)
    orbits = pa.Table.from_pylist(rows, schema=PAIR_ORBITS)
    held = drawer.held(orbits["number"].to_pylist())
    systems.members = without_letters(systems.members, drawer.repeated)
    counts = drawer.counts
    centred = orbits["barycentre"].is_valid().to_numpy(zero_copy_only=False)
    counts["pairs drawn about their barycentre"] = int(centred.sum())
    counts["pairs drawn about their primary"] = int((~centred).sum())
    counts["pairs drawn with an assumed node"] = sum(
        "node" in assumed for assumed in orbits["assumed"].to_pylist()
    )
    logger.info(
        "systems: %d held stars, %d pairs drawn", held.num_rows, orbits.num_rows
    )
    return Drawn(held, orbits, counts)


def assumed_node(root: int) -> float:
    """The node of a pair that has none: the planets' assumed node of its
    system, so a circumbinary planet and its pair share it."""
    return default_node(root)


def scene(row: dict, node: float) -> dict:
    """The SYSTEM_ORBIT value of a PAIR_ORBITS row, with its node."""
    direction = frame.direction(row["ra"], row["dec"])
    i, om, w = frame.ecliptic_angles(
        direction, row["inclination"], node, row["arg_periastron"]
    )
    n = 360.0 / row["period"]
    ratio = row["barycentre"]
    return {
        "a": row["semi_major_axis"],
        "e": row["eccentricity"],
        "i": i,
        "om": om,
        "w": w,
        "ma": row["mean_anomaly"],
        "n": n,
        "epoch": row["epoch"],
        "phase": row["phase"],
        **{
            name: row[name]
            for name in (
                "period",
                "semi_major_axis",
                "semi_major_axis_arcsec",
                "eccentricity",
                "inclination",
                "node_ascending",
                "arg_periastron",
                "mass_ratio_source",
                *(f"{name}_source" for name in ELEMENTS),
                "assumed",
                "computed",
                "references",
            )
        },
        "node": node,
        "periastron_time": row["epoch"] - row["mean_anomaly"] / n,
        "barycentre": 0.0 if ratio is None else ratio,
        "centre": PRIMARY if ratio is None else BARYCENTRE,
    }
