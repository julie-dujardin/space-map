"""The planet join: the rows of the three catalogues that are one planet.

A planet of a later catalogue looks for its planet among the earlier ones
that orbit the same host (the same star identity, the same system, or a
SIMBAD parent of its star) and among those with its designation on any
star. A candidate scores:
- 2 for the same SIMBAD planet object and 2 for the same letter, when the
  two periods are within 20% or one is unknown;
- 1 for periods within 2%, 1 for the same designation, and 1 for a
  semi-major axis and a mass within 10% when neither has a period;
- when the periods differ by more than 20%: -3 for the same SIMBAD object
  with another letter (a brown dwarf that SIMBAD names like the planet); 0.5
  for the same letter and component when the periods are within a factor of
  3 or the designations are the same (a weak match); else 0.
So in a re-lettered system the planet with the same period wins over the one
with the same letter, and a weak match joins a planet only when no candidate
has its period: one catalogue then has a wrong or an old period.

Designations compare over all names of the two rows, without the lens
letter and without a primary component (`A`, `AB`), so "GJ 229 Ab" is
"GJ 229 b". Between two rows of one star, a component `AB` and one that
only repeats the planet's own star, as in exoplanet.eu's "HAT-P-44 Bc" on
its star "HAT-P-44 B", do not count.

Pairs join best score first, one-to-one, so two rows of one catalogue never
become one planet. A row that ties between candidates stays unmatched, and
so does a candidate that two rows want equally. A row whose candidate went
to a better row tries its next candidate.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from space_map_data.extrasolar.exoplanets.catalogues import (
    ARCHIVE,
    CONFIRMED,
    CONTROVERSIAL,
    EU,
    LENS,
    OEC,
    Catalogue,
    Planet,
    close,
    reduced,
)
from space_map_data.extrasolar.exoplanets.hosts import (
    Stars,
    Systems,
    component_letter,
)
from space_map_data.extrasolar.exoplanets.simbad import Simbad

KEPT_STATUS = frozenset({CONFIRMED, CONTROVERSIAL})
# Objects that orbit a planet or share its orbit are not planets of a star.
_NOT_A_PLANET = re.compile(r"\b(exomoon|exocomet|trojan)\b", re.IGNORECASE)
MOONS, OF_THE_SUN, SELF_NAMED, TWICE = (
    "moons, comets and trojans",
    "objects of the Sun",
    "named like their star",
    "listed twice",
)
LEFT_OUT = (MOONS, OF_THE_SUN, SELF_NAMED, TWICE)


def excluded(planet: Planet, catalogue: Catalogue) -> str | None:
    """Why a kept row is not a planet of a star, None when it is one.

    A row named like its own star is a free-floating object; a row of the Sun
    is an interstellar object.
    """
    if _NOT_A_PLANET.search(planet.name):
        return MOONS
    star = catalogue.stars.get(planet.star or "")
    if star is not None and reduced(star.name) == "sun":
        return OF_THE_SUN
    if star is not None and reduced(star.name) == reduced(planet.name):
        return SELF_NAMED
    return None


LETTER_TOLERANCE = 0.2
PERIOD_TOLERANCE = 0.02
# The score of a same-letter candidate with a period more than 20% off, and
# the largest ratio of the two periods for it.
WEAK = 0.5
WEAK_RATIO = 3.0
_COMPONENT = re.compile(r"(?:\s|^|\))([A-D]{1,2}|\([A-D]+\))?\s?[b-z]$")
_PRIMARY = re.compile(r"(?:(?<=\s)|(?<=\)))(?:A|AB|\(AB\))\s?(?=[b-z]$)")
# Matched pairs with periods further apart than this are listed in the report.
CHECK_TOLERANCE = 0.05
BY_OBJECT, BY_LETTER, BY_PERIOD = "SIMBAD object", "letter", "period"
BY_DESIGNATION = "designation"
# Semi-major axes and masses of one planet differ by less than this, as a
# fraction, where no catalogue gives a period.
ORBIT_TOLERANCE = 0.1


@dataclass
class Joined:
    """One planet: its row in each catalogue that lists it."""

    rows: dict[str, Planet] = field(default_factory=dict)
    # How each later catalogue's row joined.
    how: dict[str, str] = field(default_factory=dict)

    @property
    def first(self) -> Planet:
        return next(self.rows[c] for c in (ARCHIVE, EU, OEC) if c in self.rows)

    def period(self) -> float | None:
        for planet in self.rows.values():
            if "period" in planet.values:
                return planet.values["period"].value
        return None


@dataclass
class JoinResult:
    planets: list[Joined]
    # (catalogue, rule) → count.
    counts: Counter
    ambiguous: list[str]
    contested: list[str]
    # Matched pairs whose periods differ by more than CHECK_TOLERANCE.
    period_checks: list[str]
    # Unmatched planets with a sibling of the same period on a shared host.
    missed: list[str]
    # Unmatched planets with a sibling of the same letter on a shared host.
    same_letter: list[str] = field(default_factory=list)


def _value(planet: Planet, name: str) -> float | None:
    found = planet.values.get(name)
    return found.value if found is not None and found.value > 0 else None


def _period(planet: Planet) -> float | None:
    return _value(planet, "period")


@dataclass
class _Hosts:
    """The host keys of planets: their star, their system, SIMBAD parents."""

    stars: Stars
    systems: Systems
    simbad: Simbad
    # (catalogue, star key) → star name.
    star_names: dict[tuple[str, str], str] = field(default_factory=dict)

    def star_of(self, planet: Planet) -> int | None:
        identity = self.stars.identity(planet.catalogue, planet.star)
        return None if identity is None else identity.index

    def own_component(self, planet: Planet) -> str | None:
        """The planet's component when it only repeats its star's, else None."""
        found = component(planet.name)
        star = self.star_names.get((planet.catalogue, planet.star or ""))
        if found and star is not None and component_letter(star) == found:
            return found
        return None

    def designations(self, planet: Planet) -> set[str]:
        names = {_bare(name) for name in (planet.name, *planet.names)}
        own = self.own_component(planet)
        if own:
            names |= {re.sub(rf"\(?{own}\)?\s?(?=[b-z]$)", "", n) for n in names}
        return {reduced(name) for name in names}

    def keys(self, planet: Planet) -> set[tuple[str, object]]:
        identity = self.stars.identity(planet.catalogue, planet.star)
        if identity is None:
            return set()
        keys: set[tuple[str, object]] = {
            ("star", identity.index),
            ("system", self.systems.of[identity.index]),
        }
        if identity.oid:
            keys |= {("parent", oid) for oid in self.simbad.systems(identity.oid)}
        return keys


def _bare(name: str) -> str:
    return _PRIMARY.sub("", LENS.sub(r"\1", name))


def designation_key(name: str) -> str:
    """A planet designation without case, punctuation, the lens letter and a
    primary component."""
    return reduced(_bare(name))


def component(name: str) -> str:
    """The star component before a planet letter: "" for none or `A`."""
    found = _COMPONENT.search(name.strip())
    letters = (found[1] or "").strip("()") if found else ""
    return "" if letters == "A" else letters


def _score(
    base: Planet, row: Planet, same_object: bool, hosts: _Hosts
) -> tuple[float, str]:
    """The score of a candidate and the rule that carries it."""
    pb, pr = _period(base), _period(row)
    compatible = pb is None or pr is None or close(pb, pr, LETTER_TOLERANCE)
    same_letter = bool(row.letter) and row.letter == base.letter
    same_name = bool(hosts.designations(base) & hosts.designations(row))
    if not compatible:
        assert pb is not None and pr is not None
        components = [component(base.name), component(row.name)]
        if hosts.star_of(base) == hosts.star_of(row):
            # On one star, a pair's planet and one named after the star itself
            # orbit that star.
            components = [
                "" if hosts.own_component(p) or c == "AB" else c
                for p, c in zip((base, row), components)
            ]
        weak = (
            same_letter
            and components[0] == components[1]
            and (max(pb, pr) / min(pb, pr) <= WEAK_RATIO or same_name)
        )
        if weak:
            return WEAK, BY_OBJECT if same_object else BY_LETTER
        return (-3.0 if same_object else 0.0), BY_PERIOD
    score, rule = 0.0, BY_PERIOD
    if same_object:
        score += 2
        rule = BY_OBJECT
    if same_letter:
        score += 2
        if rule == BY_PERIOD:
            rule = BY_LETTER
    if close(pb, pr, PERIOD_TOLERANCE):
        score += 1
    if same_name:
        score += 1
    if pb is None and pr is None and _same_orbit(base, row):
        score += 1
    return score, rule


def _same_orbit(a: Planet, b: Planet) -> bool:
    """Whether two rows give one semi-major axis and mass, the measures of a
    planet that has no period, as a microlensing planet."""
    return all(
        close(_value(a, name), _value(b, name), ORBIT_TOLERANCE)
        for name in ("semi_major_axis", "mass")
    )


def _match(
    base: list[Joined],
    rows: list[Planet],
    hosts: _Hosts,
    simbad: Simbad,
    result: JoinResult,
) -> list[Planet]:
    """Join `rows` of one catalogue to `base`; returns the rows left over."""
    catalogue = rows[0].catalogue if rows else ""
    by_key: dict[tuple[str, object], list[int]] = defaultdict(list)
    by_object: dict[str, list[int]] = defaultdict(list)
    by_name: dict[str, list[int]] = defaultdict(list)
    for at, joined in enumerate(base):
        for planet in joined.rows.values():
            for key in hosts.keys(planet):
                by_key[key].append(at)
            oid = simbad.planet(planet.catalogue, planet.name)
            if oid:
                by_object[oid].append(at)
            by_name[designation_key(planet.name)].append(at)

    pairs: list[tuple[float, int, int, str]] = []
    for index, row in enumerate(rows):
        candidates = {at for key in hosts.keys(row) for at in by_key.get(key, ())}
        oid = simbad.planet(row.catalogue, row.name)
        same = set(by_object.get(oid, ())) if oid else set()
        # A designation names one planet, also when two catalogues put it on
        # other stars.
        named = set(by_name.get(designation_key(row.name), ())) - candidates
        for at in candidates | same | named:
            best = (0.0, BY_PERIOD)
            for planet in base[at].rows.values():
                best = max(best, _score(planet, row, at in same, hosts))
            if best[0] > 0:
                rule = BY_DESIGNATION if at in named - same else best[1]
                pairs.append((best[0], index, at, rule))

    free_rows, free_bases = set(range(len(rows))), set(range(len(base)))
    joined_rows = set()
    for level in sorted({pair[0] for pair in pairs}, reverse=True):
        wanted_by: dict[int, list[tuple[int, str]]] = defaultdict(list)
        for score, index, at, rule in pairs:
            if score == level and index in free_rows and at in free_bases:
                wanted_by[index].append((at, rule))
        wanting: dict[int, list[tuple[int, str]]] = defaultdict(list)
        for index, found in sorted(wanted_by.items()):
            if len(found) > 1:
                names = ", ".join(sorted(base[at].first.name for at, _ in found))
                result.ambiguous.append(
                    f"{catalogue} {rows[index].name}: ties between {names}"
                )
                free_rows.discard(index)
            else:
                wanting[found[0][0]].append((index, found[0][1]))
        for at, found in sorted(wanting.items()):
            free_bases.discard(at)
            if len(found) > 1:
                names = ", ".join(rows[index].name for index, _ in found)
                result.contested.append(
                    f"{base[at].first.name}: {catalogue} rows {names} want it equally"
                )
                free_rows -= {index for index, _ in found}
                continue
            index, rule = found[0]
            free_rows.discard(index)
            row = rows[index]
            base[at].rows[row.catalogue] = row
            base[at].how[row.catalogue] = rule
            result.counts[(catalogue, rule)] += 1
            joined_rows.add(index)
            other = base[at].first
            if not close(_period(other), _period(row), CHECK_TOLERANCE) and (
                _period(other) and _period(row)
            ):
                result.period_checks.append(
                    f"{row.name} ({catalogue}, {_period(row):g} d) = {other.name}"
                    f" ({other.catalogue}, {_period(other):g} d)"
                )
    return [row for index, row in enumerate(rows) if index not in joined_rows]


def _missed(
    planets: list[Joined], left: list[Planet], hosts: _Hosts
) -> tuple[list[str], list[str]]:
    """Unmatched rows with a sibling of the same period, or of the same letter,
    of another catalogue on a shared host."""
    found, letters = [], []
    by_key: dict[tuple[str, object], list[tuple[int, Planet]]] = defaultdict(list)
    joined_of: dict[int, int] = {}
    for at, joined in enumerate(planets):
        for planet in joined.rows.values():
            joined_of[id(planet)] = at
            for key in hosts.keys(planet):
                by_key[key].append((at, planet))
    for row in left:
        siblings = {
            id(p): p
            for key in hosts.keys(row)
            for at, p in by_key.get(key, ())
            if p.catalogue != row.catalogue and at != joined_of[id(row)]
        }
        same = [
            p.name
            for p in siblings.values()
            if close(_period(p), _period(row), CHECK_TOLERANCE)
        ]
        if same:
            found.append(f"{row.name} ({row.catalogue}) and {', '.join(sorted(same))}")
        lettered = sorted(
            f"{p.name} ({p.catalogue}, {_days(p)})"
            for p in siblings.values()
            if row.letter and p.letter == row.letter
        )
        if lettered:
            letters.append(
                f"{row.name} ({row.catalogue}, {_days(row)}) and {', '.join(lettered)}"
            )
    return found, letters


def _days(planet: Planet) -> str:
    period = _period(planet)
    return "no period" if period is None else f"{period:g} d"


def join_planets(
    catalogues: list[Catalogue], stars: Stars, systems: Systems, simbad: Simbad
) -> JoinResult:
    """Join the kept planets of the catalogues, in their order."""
    result = JoinResult([], Counter(), [], [], [], [])
    star_names = {
        (c.name, key): star.name for c in catalogues for key, star in c.stars.items()
    }
    hosts = _Hosts(stars, systems, simbad, star_names)
    left_over: list[Planet] = []
    for catalogue in catalogues:
        rows = [
            p for p in catalogue.planets if p.status in KEPT_STATUS and hosts.keys(p)
        ]
        kept = []
        seen: set[tuple[int, str]] = set()
        for row in rows:
            reason = excluded(row, catalogue)
            # One star's planet under a name with and without the lens letter.
            identity = stars.identity(row.catalogue, row.star)
            assert identity is not None
            name = (identity.index, reduced(LENS.sub(r"\1", row.name)))
            if reason is None and name in seen:
                reason = TWICE
            if reason is None:
                kept.append(row)
                seen.add(name)
            else:
                result.counts[(catalogue.name, reason)] += 1
        rows = kept
        result.counts[(catalogue.name, "rows")] += len(rows)
        if not result.planets:
            result.planets = [Joined({row.catalogue: row}) for row in rows]
            continue
        left = _match(result.planets, rows, hosts, simbad, result)
        result.counts[(catalogue.name, "unmatched")] += len(left)
        left_over += left
        result.planets += [Joined({row.catalogue: row}) for row in left]
    result.missed, result.same_letter = _missed(result.planets, left_over, hosts)
    return result
