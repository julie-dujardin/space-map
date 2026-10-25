"""The IAU NameExoWorlds names of planets and of their host stars.

A planet name goes to the joined planet that any catalogue row names with
the same designation. Designations compare without spaces and punctuation,
without case but for the final component and planet letters, with a Greek
letter as its three-letter abbreviation and a constellation genitive as its
IAU abbreviation. A designation in brackets after another, as in "Ain b
(epsilon Tauri b)", is a second try.

A star name goes to the star of the planets named in the same row. A star
whose planets are not found goes by its own designation. A star name that the
IAU star-name list (WGSN) also has is left to the pass of that list when that
pass claims the same star, so each name has one route.
"""

import json
import logging
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from space_map_data.download.providers.exoplanets import name_exo_worlds
from space_map_data.extrasolar.exoplanets.catalogues import GREEK, reduced
from space_map_data.extrasolar.exoplanets.hosts import Identity, Stars
from space_map_data.extrasolar.exoplanets.join import Joined

logger = logging.getLogger(__name__)

NAMES_FILE = name_exo_worlds.OUT_DIR / name_exo_worlds.NAMES_FILE
SOURCE = "iau-nameexoworlds"

# The genitives of the IAU constellations that NameExoWorlds designations use,
# with their abbreviations.
GENITIVES = {
    "andromedae": "and",
    "aquarii": "aqr",
    "aquilae": "aql",
    "arae": "ara",
    "arietis": "ari",
    "aurigae": "aur",
    "bootis": "boo",
    "cancri": "cnc",
    "canis majoris": "cma",
    "canis minoris": "cmi",
    "cassiopeiae": "cas",
    "ceti": "cet",
    "cephei": "cep",
    "comae berenices": "com",
    "coronae borealis": "crb",
    "corvi": "crv",
    "cygni": "cyg",
    "delphini": "del",
    "draconis": "dra",
    "eridani": "eri",
    "geminorum": "gem",
    "herculis": "her",
    "hydrae": "hya",
    "leonis": "leo",
    "leonis minoris": "lmi",
    "librae": "lib",
    "lyrae": "lyr",
    "ophiuchi": "oph",
    "pegasi": "peg",
    "persei": "per",
    "piscis austrini": "psa",
    "piscium": "psc",
    "sagittarii": "sgr",
    "scorpii": "sco",
    "serpentis": "ser",
    "tauri": "tau",
    "ursae majoris": "uma",
    "ursae minoris": "umi",
    "virginis": "vir",
}
_GENITIVE = re.compile(
    r"\b(" + "|".join(sorted(GENITIVES, key=len, reverse=True)) + r")\b"
)
_GREEK = re.compile(r"\b(" + "|".join(GREEK) + r")\b")
_BRACKETS = re.compile(r"^(.*?)\s*\((.+)\)\s*$")
# The final words of one or two letters: component and planet letters.
_FINAL_LETTERS = re.compile(
    r"(?<=[^A-Za-z])(?:[A-Za-z]{1,2}(?![A-Za-z])[^A-Za-z0-9]*)+$"
)
_NOT_LETTER = re.compile(r"[^A-Za-z]")


@dataclass(frozen=True)
class ExoWorld:
    edition: int
    row: int
    kind: str
    designation: str
    name: str


def key(designation: str) -> str:
    """A designation reduced for comparison.

    Case does not count, but for the final component and planet letters:
    `B` is a star or an old planet name, `b` a planet, `AB` a pair, `Ab` or
    `A b` a component of A or its planet. A final word of three letters or
    more, such as a genitive, has no such letters, so "upsilon Andromedae"
    and "ups And" give one key.
    """
    text = designation.strip()
    lowered = _GENITIVE.sub(lambda m: GENITIVES[m[1]], text.lower())
    found = reduced(_GREEK.sub(lambda m: GREEK[m[1]], lowered))
    final = _FINAL_LETTERS.search(text)
    letters = _NOT_LETTER.sub("", final[0]) if final else ""
    # A Greek letter at the end changes its spelling, as "xi" to "ksi".
    if letters and found.endswith(letters.lower()):
        return found[: -len(letters)] + letters
    return found


def tries(designation: str) -> list[str]:
    """The keys to try for a designation, the bracketed one second."""
    found = _BRACKETS.match(designation)
    texts = [found[1], found[2]] if found else [designation]
    return [key(text) for text in texts if text.strip()]


def read_names(path: Path = NAMES_FILE) -> list[list[ExoWorld]]:
    """The names, one list per row of the IAU tables."""
    rows: dict[tuple[int, int], list[ExoWorld]] = defaultdict(list)
    for entry in json.loads(path.read_text()):
        world = ExoWorld(
            entry["edition"],
            entry["row"],
            entry["kind"],
            entry["designation"],
            entry["name"],
        )
        rows[(world.edition, world.row)].append(world)
    return [rows[at] for at in sorted(rows)]


def _folded(name: str) -> str:
    """A name without case and accents."""
    return (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    )


@dataclass(frozen=True)
class WgsnName:
    """An IAU WGSN name, with the ids of the star that its pass claims."""

    name: str
    designation: str
    hip: int | None = None
    oid: str | None = None
    gaia_dr3: int | None = None

    def claims(self, identity: Identity) -> bool:
        return any(
            mine is not None and mine == theirs
            for mine, theirs in (
                (self.hip, identity.hip),
                (self.oid, identity.oid),
                (self.gaia_dr3, identity.gaia_dr3),
            )
        )


class _Wgsn:
    """The WGSN names by folded name and by designation key. The two lists
    spell some names and designations differently."""

    def __init__(self, wgsn: Iterable[WgsnName]) -> None:
        self.by_name: dict[str, list[WgsnName]] = defaultdict(list)
        self.by_key: dict[str, list[WgsnName]] = defaultdict(list)
        for entry in wgsn:
            self.by_name[_folded(entry.name)].append(entry)
            for k in tries(entry.designation):
                if k:
                    self.by_key[k].append(entry)

    def claims(self, world: ExoWorld, identity: Identity) -> bool:
        """Whether the WGSN pass claims the star of `identity` under this name."""
        found = [
            *self.by_name.get(_folded(world.name), ()),
            *(e for k in tries(world.designation) for e in self.by_key.get(k, ())),
        ]
        return any(entry.claims(identity) for entry in found)


@dataclass
class Named:
    # Joined planet index → IAU name.
    planets: dict[int, str]
    # Identity index → IAU star name.
    stars: dict[int, str]
    unplaced: list[str]
    # Star names that the IAU WGSN pass gives.
    wgsn: list[str] = field(default_factory=list)


def place_names(
    systems: list[list[ExoWorld]],
    planets: list[Joined],
    stars: Stars,
    star_of: dict[int, int],
    wgsn: Iterable[WgsnName] = (),
) -> Named:
    """Give the names to the joined planets and to their stars.

    `star_of` maps a joined planet index to the identity of its star. `wgsn`
    gives the names of the IAU WGSN pass.
    """
    listed = _Wgsn(wgsn)
    by_key: dict[str, set[int]] = defaultdict(set)
    for at, joined in enumerate(planets):
        for row in joined.rows.values():
            for name in row.names:
                by_key[key(name)].add(at)
    by_star: dict[str, set[int]] = defaultdict(set)
    for identity in stars.identities:
        for star in identity.members.values():
            for name in star.names:
                by_star[key(name)].add(identity.index)

    named = Named({}, {}, [])
    for system in systems:
        found_stars: set[int] = set()
        for world in system:
            if world.kind != "planet":
                continue
            hits = next(
                (by_key[k] for k in tries(world.designation) if len(by_key[k]) == 1),
                set(),
            )
            if not hits:
                named.unplaced.append(f"{world.name} ({world.designation})")
                continue
            at = next(iter(hits))
            named.planets[at] = world.name
            if at in star_of:
                found_stars.add(star_of[at])
        for world in system:
            if world.kind != "star":
                continue
            if len(found_stars) != 1:
                found_stars = next(
                    (
                        by_star[k]
                        for k in tries(world.designation)
                        if len(by_star[k]) == 1
                    ),
                    set(),
                )
            if len(found_stars) == 1:
                at = next(iter(found_stars))
                if listed.claims(world, stars.identities[at]):
                    named.wgsn.append(world.name)
                else:
                    named.stars[at] = world.name
            else:
                named.unplaced.append(f"{world.name} ({world.designation})")
    for text in named.unplaced:
        logger.info("NameExoWorlds name not placed: %s", text)
    return named
