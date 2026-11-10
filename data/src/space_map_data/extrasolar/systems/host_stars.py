"""The held star that the planets of a point orbit.

A planet catalogue lists the star that its planets orbit. When that star is
a point that holds several stars, the catalogue's values describe one of
them, so the planets and the values go to that held star. The evidence,
strongest first:
1. an id: the catalogue's star and one member share an id (a catalogue key,
   the Gaia DR3 id, the HIP number or the SIMBAD object);
2. a letter: the catalogues' names of the star end in one letter, and one
   member has it;
3. the brightest member, when the catalogue's values agree with it;
4. the point's id: the ids of the catalogue's star with a key are all the
   point's, and the point's first member dominates its light (`dominates`).

The values agree when the mass is within MASS_SHARE of the member's, or
within twice the catalogue's error, and the Teff is within TEFF_SHARE of the
member's own Teff, else of the Teff of its spectral type in the dwarf
sequence. An uncertain type ("G6?") or a type of two stars ("L2+L3.5") gives
no Teff. A value that disagrees stops the move, whatever the evidence. A
letter that the chosen member does not have, or two letters in the
catalogues' names, stop it too. An id needs the letter of the host when the
catalogues give one. The caller removes the ids that the point carries too: a
member often carries the Gaia DR3 id of its point, and such an id is evidence
for the point only. The brightest member must be brighter than each
other member by BRIGHTER_BY in a band that all of them have, and it needs one
value that agrees with it and not with the next brightest member. The chosen
member must be one that a source names, so that it can hold an ID. A planet
around both stars of a pair stays on the pair. Each other case stays on the
point, with its reason for the review.

`dominates` also marks the held star whose point's light is its own
(`drawn`): it takes the point's measured radius, and the point stands for it
where a star is sized.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

import numpy as np

from space_map_data.constants.stars.dwarf_teff import DWARF_TEFF
from space_map_data.constants.stars.families import COMPOSITE_SPECTRAL_TYPE
from space_map_data.extrasolar.families import _parse

MASS_SHARE = 0.2
TEFF_SHARE = 0.1
# The WDS and the MSC often give a component magnitude to a few tenths only.
BRIGHTER_BY = 0.5
BAND_NAMES = {"g_mag": "G", "own_v_mag": "own V", "v_mag": "V"}
# The MK marks of an uncertain type.
UNCERTAIN = ("?", ":")
LETTERS = "OBAFGKMLTY"
# The stages that the dwarf sequence describes. It is of dwarfs of solar
# metallicity, so a subdwarf, hot or cool, has no type Teff.
DWARF_STAGES = (None, "main-sequence")
BY_ID, BY_LETTER, BY_BRIGHTNESS, BY_POINT = "id", "letter", "brightest", "point id"
# The first member dominates the light of its point when each other member is
# fainter by BLEND_MAGNITUDES in the first of LIGHT_BANDS that both have, else
# below BLEND_MASS_RATIO of its mass. With neither, the light can blend.
BLEND_MAGNITUDES = 2.5
LIGHT_BANDS = ("g_mag", "v_mag")
BLEND_MASS_RATIO = 0.7


def _outshines(
    main: Mapping[str, float | None], other: Mapping[str, float | None]
) -> tuple[bool, str]:
    """Whether `main` dominates the light of `other`, and the comparison as
    text. Both have the keys of LIGHT_BANDS and `mass`. A mass that is not
    positive is unknown."""
    for band in LIGHT_BANDS:
        mine, theirs = main[band], other[band]
        if mine is not None and theirs is not None:
            delta = theirs - mine
            return delta >= BLEND_MAGNITUDES, f"Δ{BAND_NAMES[band]} {delta:.2f}"
    mine, theirs = main["mass"], other["mass"]
    if mine is not None and theirs is not None and min(mine, theirs) > 0:
        return theirs / mine <= BLEND_MASS_RATIO, f"mass ratio {theirs / mine:.2f}"
    return False, "no band or mass that both have"


def _code(letter: str, subclass: float) -> float:
    return LETTERS.index(letter) * 10 + subclass


_CODES = np.array([_code(t[0], float(t[1:])) for t, _ in DWARF_TEFF])
_TEFFS = np.array([teff for _, teff in DWARF_TEFF], float)


def type_teff(spectral_type: str | None) -> float | None:
    """The dwarf Teff of a spectral type with a subclass, else None."""
    if not spectral_type or any(mark in spectral_type for mark in UNCERTAIN):
        return None
    if COMPOSITE_SPECTRAL_TYPE.search(spectral_type):
        return None
    letter, stage, _, subclass = _parse(spectral_type.strip())
    if letter is None or letter not in LETTERS or subclass is None:
        return None
    if stage not in DWARF_STAGES:
        return None
    code = _code(letter, subclass)
    if not _CODES[0] <= code <= _CODES[-1]:
        return None
    return float(np.interp(code, _CODES, _TEFFS))


@dataclass(frozen=True)
class Member:
    """A member of the point, with the values of its sources."""

    row: int
    # A source names it, so it can be a held star.
    named: bool
    letter: str | None = None
    g_mag: float | None = None
    # The V of the star alone, as its source splits the light of a pair.
    own_v_mag: float | None = None
    v_mag: float | None = None
    mass: float | None = None
    teff: float | None = None
    spectral_type: str | None = None
    # (catalogue, release, catalogue id).
    ids: frozenset[tuple[str, str, str]] = frozenset()


@dataclass(frozen=True)
class Host:
    """The planets' star as the catalogues give it: the first value of each."""

    # The ids that the point does not carry.
    ids: frozenset[tuple[str, str, str]] = frozenset()
    # Its ids with a key are all the point's.
    of_point: bool = False
    letters: frozenset[str] = frozenset()
    teff: float | None = None
    mass: float | None = None
    mass_error: float | None = None


@dataclass(frozen=True)
class Choice:
    """The member that the planets orbit, or None with the reason."""

    row: int | None
    evidence: str
    reason: str | None = None


def _v_band(members: Sequence[Member]) -> str:
    """The V band that compares `members`. A plain V can hold the light of
    the point, so the own V of each star replaces it when a member has one."""
    return "own_v_mag" if any(m.own_v_mag is not None for m in members) else "v_mag"


def dominates(members: Sequence[Member]) -> tuple[bool, str]:
    """Whether the first of a point's `members` dominates its light, and
    the comparisons as text. V is the band of `_v_band`. When that is own V,
    the members need G or own V, because a mass does not tell then."""
    main, *others = members
    v_band = _v_band(members)

    def light(member: Member) -> dict[str, float | None]:
        v_mag = getattr(member, v_band)
        return {"g_mag": member.g_mag, "v_mag": v_mag, "mass": member.mass}

    texts = []
    for other in others:
        if v_band == "own_v_mag" and not any(
            None not in (getattr(main, band), getattr(other, band))
            for band in ("g_mag", v_band)
        ):
            return False, "no G or own V that both have"
        bright, text = _outshines(light(main), light(other))
        if not bright:
            return False, text
        texts.append(text)
    return True, ", ".join(texts)


def comparisons(host: Host, member: Member) -> dict[str, tuple[bool, str]]:
    """Each value of the host that the member has too: whether they agree,
    and the two as text."""
    found = {}
    if host.mass is not None and member.mass is not None:
        margin = max(MASS_SHARE * member.mass, 2 * (host.mass_error or 0))
        close = abs(host.mass - member.mass) <= margin
        found["mass"] = close, f"mass {host.mass:.3g} vs {member.mass:.3g}"
    if host.teff is not None:
        own, label = member.teff, "Teff"
        if own is None:
            own, label = type_teff(member.spectral_type), member.spectral_type
        if own is not None:
            close = abs(host.teff - own) <= TEFF_SHARE * own
            found["teff"] = close, f"Teff {host.teff:.0f} vs {label} {own:.0f}"
    return found


def _checked(
    host: Host, member: Member, evidence: str, detail: str, agree: list[str]
) -> Choice:
    """The move to `member` unless a value disagrees or no source names it.
    `agree` are the values that count for it."""
    disagree = [text for close, text in comparisons(host, member).values() if not close]
    if disagree:
        return Choice(None, evidence, f"{detail}, but {'; '.join(disagree)}")
    text = "; ".join([detail, *agree])
    if not member.named:
        return Choice(None, evidence, f"{text}, but no source names the member")
    return Choice(member.row, f"{evidence}: {text}")


def _agreeing(host: Host, member: Member) -> list[str]:
    return [text for close, text in comparisons(host, member).values() if close]


def _band(members: list[Member]) -> str | None:
    """The first of G and the `_v_band` that each member has. Gaia measures
    each star that it splits, so G goes first."""
    return next(
        (
            band
            for band in ("g_mag", _v_band(members))
            if all(getattr(m, band) is not None for m in members)
        ),
        None,
    )


def _brightest(host: Host, members: list[Member]) -> Choice:
    if not members:
        return Choice(None, BY_BRIGHTNESS, "the point lists no member")
    band = _band(members)
    if band is None:
        return Choice(None, BY_BRIGHTNESS, "no band that every member has")
    lit = sorted((getattr(m, band), m.row) for m in members)
    detail = f"{BAND_NAMES[band]} {lit[0][0]:.2f}"
    brightest = next(m for m in members if m.row == lit[0][1])
    mine = comparisons(host, brightest)
    agree = [text for close, text in mine.values() if close]
    if len(lit) > 1:
        detail += f", next {lit[1][0]:.2f}"
        if lit[1][0] - lit[0][0] < BRIGHTER_BY:
            return Choice(None, BY_BRIGHTNESS, f"{detail}, within {BRIGHTER_BY} mag")
        next_one = next(m for m in members if m.row == lit[1][1])
        theirs = comparisons(host, next_one)
        agree = [
            text
            for name, (close, text) in mine.items()
            if close and not theirs.get(name, (True,))[0]
        ]
    choice = _checked(host, brightest, BY_BRIGHTNESS, detail, agree)
    if choice.row is not None and not agree:
        if not mine:
            return Choice(None, BY_BRIGHTNESS, f"{detail}, but no value to compare")
        shared = "; ".join(text for _, text in mine.values())
        return Choice(
            None,
            BY_BRIGHTNESS,
            f"{detail}; {shared}, but no value that the next member fails",
        )
    return choice


def _dominant(host: Host, members: list[Member]) -> Choice:
    """The move to the first member when it dominates the point's light."""
    bright, text = dominates(members)
    if not bright:
        return Choice(None, BY_POINT, f"first member, but {text}")
    main = members[0]
    return _checked(
        host, main, BY_POINT, f"dominant member ({text})", _agreeing(host, main)
    )


def choose(host: Host, members: list[Member]) -> Choice:
    """The member that the planets of `host` orbit."""
    if len(host.letters) > 1:
        letters = ", ".join(sorted(host.letters))
        return Choice(None, BY_LETTER, f"the catalogues give letters {letters}")
    letter = next(iter(host.letters), None)
    by_id = [m for m in members if m.ids & host.ids]
    if len(by_id) > 1:
        return Choice(None, BY_ID, f"{len(by_id)} members share an id with the host")
    if by_id:
        (member,) = by_id
        catalogue, _, catalogue_id = min(member.ids & host.ids)
        detail = f"{catalogue} {catalogue_id}"
        if letter is not None and member.letter != letter:
            has = f"letter {member.letter}" if member.letter else "no letter"
            return Choice(
                None, BY_ID, f"{detail}, but letter {letter} and it has {has}"
            )
        if letter is not None:
            detail += f", letter {letter}"
        return _checked(host, member, BY_ID, detail, _agreeing(host, member))
    if letter is not None:
        by_letter = [m for m in members if m.letter == letter]
        if len(by_letter) != 1:
            found = f"{len(by_letter)} members have" if by_letter else "no member has"
            return Choice(None, BY_LETTER, f"letter {letter}, but {found} it")
        detail = f"letter {letter}"
        return _checked(
            host, by_letter[0], BY_LETTER, detail, _agreeing(host, by_letter[0])
        )
    choice = _brightest(host, members)
    if choice.row is not None or not host.of_point or not members:
        return choice
    point = _dominant(host, members)
    if point.row is not None:
        return point
    return replace(choice, reason=f"{choice.reason}; {BY_POINT}: {point.reason}")
