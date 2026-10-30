"""The names of objects: one rule for each kind of object.

The page of an object takes its names from here. Every list, stat card, chart
and map that names the object does too. A rule gives the global name, which
is the English one, the name in each language that has one of its own, and
the aliases that keep a replaced name findable.

The Wikidata label comes first. A rule that puts another source first gives
its reason at the rule.

`ObjectNames` gives the names of an object from its page id. Use it where only
the id is known.
"""

import re
import threading
import unicodedata
from collections import Counter
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field, replace
from functools import cache
from typing import TYPE_CHECKING, NamedTuple

import orjson
from sqlalchemy.orm import Session, joinedload

from space_map_data.constants.earth_sats.featured import EARTH_ID
from space_map_data.constants.object_names import NAME_ENTITIES
from space_map_data.constants.providers import BASE_LOCALE, LANGUAGES
from space_map_data.export.wikidata import (
    WikidataEntity,
    WikidataEntityCache,
    clean_label,
    entity_label,
)
from space_map_data.extrasolar.exoplanets.catalogues import CONTROVERSIAL
from space_map_data.extrasolar.exoplanets.join import designation_key
from space_map_data.extrasolar.exoplanets.table import IAU_NAMES
from space_map_data.extrasolar.sources.names import IAU_WGSN
from space_map_data.extrasolar.sources.wikidata import usable_name
from space_map_data.models.feature import Feature
from space_map_data.models.object import Object, ObjectType
from space_map_data.utils.designations import (
    format_provisional_designation,
    is_iau_named,
)
from space_map_data.utils.manual_overlay import (
    manual_object_labels,
    read_manual_objects,
)
from space_map_data.utils.paths import MESSAGES_DIR

if TYPE_CHECKING:
    from space_map_data.export.objects.stars import PlanetObject, StarObject


@dataclass(frozen=True)
class Names:
    """The global name of an object and its names by language."""

    name: str
    # The name in each language that has one of its own. It can be the same
    # as the global name.
    langs: Mapping[str, str] = field(default_factory=dict)
    # By language, the names that the name in that language replaces. A
    # reader who knows only one of them can still find the object.
    aliases: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def get(self, lang: str) -> str:
        """The name in ``lang``."""
        return self.langs.get(lang) or self.name

    def overrides(self) -> dict[str, str]:
        """The names by language that differ from the global name."""
        return {lang: name for lang, name in self.langs.items() if name != self.name}


def overrides_in(named: Mapping[str, Names], lang: str) -> dict[str, str]:
    """The names in ``lang`` that differ from the global ones, by key."""
    return {
        key: name
        for key, names in named.items()
        if (name := names.get(lang)) != names.name
    }


def by_language(named: Mapping[str, Names]) -> dict[str, dict[str, str]]:
    """The names that differ from the global ones, by language, then by key. A
    language with none is left out."""
    return {lang: found for lang in LANGUAGES if (found := overrides_in(named, lang))}


def entity_names(entity: WikidataEntity | None, fallback: str) -> Names:
    """The labels of a Wikidata item, else ``fallback``."""
    return Names(
        entity_label(entity, BASE_LOCALE) or fallback,
        {lang: label for lang in LANGUAGES if (label := entity_label(entity, lang))},
    )


def own_name(obj: Object) -> str:
    """The catalogue name of an object. A moon with no IAU name has its
    designation in the IAU form ("S/2019 S 37")."""
    if obj.object_type == ObjectType.moon and not is_iau_named(
        obj.name, obj.provisional_designation
    ):
        designation = format_provisional_designation(
            obj.provisional_designation or obj.name
        )
        if designation:
            return designation
    return clean_label(obj.name) if obj.name else obj.id


def resolve_wikidata_qid(obj: Object) -> str | None:
    """The Wikidata item that describes ``obj``, or None.

    An Earth satellite with no item of its own takes the item of its SATCAT
    row. A probe never does. A capsule, a lander and the craft that carried
    them share the NORAD number of their launch, so the row names one of them
    at most. A probe takes its item from the registry only.
    """
    if obj.wikidata_qid:
        return obj.wikidata_qid
    if obj.probe_id is not None or obj.norad_cat_id is None or not obj.satcat:
        return None
    return obj.satcat.wikidata_qid


def _without_disambiguators(obj: Object, names: Names) -> Names:
    """``names`` with labels that have no disambiguator ("エリス (準惑星)" is
    "エリス"). The parentheses of a comet or of a global name stay: they hold
    a discoverer or a designation ("C/1997 J2 (Meunier-Dupouy)", "99677
    (2002 JC15)"), which is the only difference between some objects."""
    if obj.object_type == ObjectType.comet or "(" in names.name:
        return names
    langs = {
        # Some labels are page titles: "أزور_(قمر_اصطناعي)".
        lang: without_disambiguator(label).rstrip("_")
        for lang, label in names.langs.items()
    }
    return replace(names, langs=langs)


def object_names(
    obj: Object, entities: WikidataEntityCache, item: WikidataEntity | None = None
) -> Names:
    """The names of a catalogue object: the labels of its Wikidata item, else
    its catalogue name. ``item`` is the item of ``obj`` where the caller has
    read it already.

    A moon with no IAU name has its designation in every language. Its item's
    label is a description ("Moon of 38628 Huya") or a designation that can
    disagree with the DB. For the same reason, a moon's label that is a
    designation ("S/2009 (317) 1" for Olympias) gives way to the IAU name.
    """
    is_moon = obj.object_type == ObjectType.moon
    if is_moon and not is_iau_named(obj.name, obj.provisional_designation):
        return Names(own_name(obj))
    # The registry files some probes under the item of their mission.
    # NAME_ENTITIES gives the item of the craft, so NAIF -76 is "Curiosity",
    # not "Mars Science Laboratory".
    named_by = entities.get_referenced(NAME_ENTITIES.get(obj.id))
    item = named_by or item or entities.get_entity(resolve_wikidata_qid(obj))
    if not is_moon:
        return _without_disambiguators(obj, entity_names(item, own_name(obj)))

    def name(lang: str) -> str | None:
        label = entity_label(item, lang)
        return label if is_iau_named(label, obj.provisional_designation) else None

    return _without_disambiguators(
        obj,
        Names(
            name(BASE_LOCALE) or own_name(obj),
            {lang: label for lang in LANGUAGES if (label := name(lang))},
        ),
    )


# The planet of each planetary system barycenter: NAIF X99 for NAIF X.
SYSTEM_PRIMARIES = {f"naif-{n}": f"naif-{n}99" for n in range(1, 10)}


@cache
def system_titles() -> dict[str, tuple[str, str]]:
    """The app's title of a planetary system and of the Earth–Moon system, by
    language. They come from the app's messages, so the tier-B fingerprint
    stamps them."""
    titles = {}
    for lang in LANGUAGES:
        messages = orjson.loads((MESSAGES_DIR / f"{lang}.json").read_bytes())
        titles[lang] = (
            messages["planetary_system_title"],
            messages["planetary_system_title_earth_moon"],
        )
    return titles


def system_names(primary_id: str, primary: Names) -> Names:
    """The names of a planetary system barycenter. Its page is the page of the
    whole system, so it takes the name of its planet: "Jupiter system"."""

    def title(lang: str) -> str:
        system, earth_moon = system_titles()[lang]
        if primary_id == EARTH_ID:
            return earth_moon
        return system.replace("{primary}", primary.get(lang))

    return Names(title(BASE_LOCALE), {lang: title(lang) for lang in LANGUAGES})


def manual_names(entry: Mapping) -> Names:
    """The names of a hand-authored object: its Wikidata labels, else the
    name in its entry."""
    qid = entry.get("wikidata_qid")
    labels = manual_object_labels(qid) if qid else {}
    return Names(labels.get(BASE_LOCALE) or entry.get("name") or entry["id"], labels)


def is_latin(name: str) -> bool:
    """Whether every letter of ``name`` is a Latin letter."""
    return all(unicodedata.name(c, "").startswith("LATIN") for c in name if c.isalpha())


# The Unicode scripts of each language of the site that has no Latin script.
# The other languages are written in the Latin alphabet.
_SCRIPTS = {
    "ja": ("CJK", "HIRAGANA", "KATAKANA"),
    "zh": ("CJK",),
    "ru": ("CYRILLIC",),
    "ar": ("ARABIC",),
    "he": ("HEBREW",),
}


# A Latin letter, also a full-width one ("Ａ").
_LATIN = ("LATIN", "FULLWIDTH LATIN")


def in_own_script(name: str, lang: str) -> bool:
    """Whether ``lang`` has no Latin script and ``name`` is written in its
    script. Such a name can hold Latin letters too ("メスティングA",
    "Liberalia 山"), but not those of a third script, such as a Greek Bayer
    letter."""
    scripts = _SCRIPTS.get(lang)
    if not scripts:
        return False
    letters = [unicodedata.name(c, "") for c in name if c.isalpha()]
    return any(letter.startswith(scripts) for letter in letters) and all(
        letter.startswith((*scripts, *_LATIN)) for letter in letters
    )


# The disambiguator of a Wikipedia-style label: "Tycho (Mondkrater)",
# "Saffar (Exoplanet)". Japanese and Chinese labels can use full-width
# parentheses: "ティコ（クレーター）".
_DISAMBIGUATOR = re.compile(r"\s*[(（][^()（）]*[)）]$")


def without_disambiguator(label: str) -> str:
    """``label`` without a trailing disambiguator in parentheses."""
    return _DISAMBIGUATOR.sub("", label) or label


def _name_key(name: str) -> str:
    """How two names compare: a name with a disambiguator or in another case
    is the same name."""
    return without_disambiguator(name).casefold()


def replaced_labels(
    name: str, labels: Mapping[str, str | None]
) -> dict[str, tuple[str, ...]]:
    """The labels that ``name`` replaces in the languages written in the Latin
    alphabet, without a disambiguator, as aliases by language."""
    return {
        lang: (without_disambiguator(label),)
        for lang in LANGUAGES
        if lang not in _SCRIPTS
        and (label := labels.get(lang))
        and _name_key(label) != _name_key(name)
    }


def page_aliases(names: Names, lang: str, others: Iterable[str] = ()) -> list[str]:
    """The aliases of a page in ``lang``: the names that its name replaces,
    then ``others``. Each comes once, and the page's name never does, as it
    is shown already."""
    seen = {_name_key(names.get(lang))}
    out = []
    for alias in (*names.aliases.get(lang, ()), *others):
        if (key := _name_key(alias)) not in seen:
            seen.add(key)
            out.append(alias)
    return out


def mission_names(item: WikidataEntity | None, primary: Names) -> Names:
    """The names of a mission page: the labels of its Wikidata item, else the
    names of its primary craft."""
    return entity_names(item, primary.name) if item else primary


def feature_names(feature: Feature, entities: WikidataEntityCache) -> Names:
    """The names of a surface feature.

    The IAU names planetary surface features, so its name comes first in every
    language written in the Latin alphabet, in the IAU's own spelling. The IAU
    gives each name in that alphabet only, so in a language with another
    script, a Wikidata label in that script takes its place. A label that the
    IAU name replaces stays as an alias. A label loses its disambiguator
    ("エイトケン (クレーター)"), because the page already tells what the
    feature is.
    """
    item = entities.get_feature_entity(feature.wikidata_qid)
    labels = item["labels"] if item else {}
    name = feature.unicode_name or feature.name
    return Names(
        name,
        {
            lang: label
            for lang in LANGUAGES
            if (label := without_disambiguator(labels.get(lang) or ""))
            and in_own_script(label, lang)
        },
        replaced_labels(name, labels),
    )


def feature_aliases(names: Names, lang: str, others: Iterable[str] = ()) -> list[str]:
    """The aliases of a surface feature in ``lang``, as `page_aliases` gives
    them, without disambiguators. An alias that contains the name in ``lang``
    as whole words ("Cratere Tycho" for "Tycho") is dropped, as it adds
    nothing that a search for the name does not find."""
    name = re.compile(rf"(?<!\w){re.escape(names.get(lang).strip().casefold())}(?!\w)")
    return [
        alias
        for alias in page_aliases(names, lang, map(without_disambiguator, others))
        if not name.search(alias.casefold())
    ]


def star_label(entity: WikidataEntity | None, lang: str) -> str | None:
    """The Wikidata label of a star or a planet in ``lang`` as a name, without
    its disambiguator ("Capella (étoile)"). None for a label that repeats the
    English one or is no name, such as a catalogue number."""
    if entity is None:
        return None
    labels = entity["labels"]
    name = usable_name(labels.get(lang))
    if not name or name == (labels.get("en") or labels.get("mul")):
        return None
    return without_disambiguator(name)


def star_names(star: StarObject, entity: WikidataEntity | None) -> Names:
    """The names of a star or a star system.

    The global name is the one of its Metadata row, which the registry picks.
    The other languages take the Wikidata label. A star with an IAU name keeps
    it, because the IAU names the stars. The IAU gives each name in the Latin
    alphabet only. So in a language with another script, a label in that
    script takes its place. A label that the IAU name replaces stays as an
    alias.
    """
    labels = entity["labels"] if entity is not None else {}
    return Names(
        star.name,
        {
            lang: label
            for lang in LANGUAGES
            if (label := star_label(entity, lang))
            and (not star.iau_named or in_own_script(label, lang))
        },
        replaced_labels(
            star.name, {lang: usable_name(labels.get(lang)) for lang in LANGUAGES}
        )
        if star.iau_named
        else {},
    )


# Gliese numbers go by `GJ`, `Gl` or `Gliese`.
_GLIESE = re.compile(r"^(gliese|gl)(?=\d)")


def same_designation(name: str) -> str:
    """A planet or star designation as two spellings of it compare."""
    return _GLIESE.sub("gj", designation_key(name))


class CataloguePlanet(NamedTuple):
    """A planet as its row in the planets table names it."""

    # An IAU name or a designation.
    name: str
    letter: str | None
    iau_named: bool
    # True when a catalogue calls it unconfirmed.
    controversial: bool
    # True when another planet of its host has its letter.
    letter_repeated: bool

    @classmethod
    def of(cls, row: Mapping, repeated: Collection[tuple[int, str]]) -> CataloguePlanet:
        """The planet of a planets table row. ``repeated`` is the
        `repeated_letters` of the whole table."""
        return cls(
            row["name"],
            row["letter"],
            row["name_source"] == IAU_NAMES,
            row["status"] == CONTROVERSIAL,
            (row["host"], row["letter"]) in repeated,
        )


def repeated_letters(rows: Iterable[Mapping]) -> frozenset[tuple[int, str]]:
    """The (host, letter) pairs that more than one planets table row has. Give
    it every row of a host, also the rows that keep another name, because a
    letter beside such a planet is repeated too."""
    found = Counter((row["host"], row["letter"]) for row in rows if row["letter"])
    return frozenset(key for key, count in found.items() if count > 1)


class PlanetHost(NamedTuple):
    """The page of a planet's host star or star system."""

    names: Names
    # True when its name is the IAU proper name of the star.
    iau_named: bool = False


def served_host(record: Mapping, entry: Names | None = None) -> PlanetHost | None:
    """The page of a host from its Metadata row or its system file record.
    ``entry`` names a host with an entry, else the Metadata name does. None
    when neither names it."""
    if entry is None and record["name"] is None:
        return None
    return PlanetHost(
        entry or Names(record["name"]), record["name_source"] == IAU_WGSN.name
    )


def unlisted_host(planet: PlanetObject) -> PlanetHost | None:
    """The page of a planet's host that has no entry. None when the served
    files do not give it."""
    if planet.host_name is None:
        return None
    return PlanetHost(Names(planet.host_name), planet.host_iau_named)


def planet_prefix(host: PlanetHost) -> Names | None:
    """The names that a planet named after its host takes before its letter:
    the names of its host's page, also for a host with an IAU name ("Titawin
    e"). None keeps the catalogue name of the planet."""
    return host.names


def planet_names(
    planet: CataloguePlanet | PlanetObject, host: PlanetHost | None
) -> Names:
    """The names of a planet, from the page of its host. The first rule that
    applies gives them:

    1. An IAU name stays in every language, also on a controversial planet,
       because the IAU names the planets of NameExoWorlds.
    2. A controversial planet keeps its catalogue name in every language. The
       name is the claim of that catalogue, and the planet has no agreed
       letter. Its form after its host stays as an alias, so that a search
       for "Tau Ceti e" finds "tau Cet e".
    3. A planet whose letter another planet of its host has keeps its
       catalogue name in every language, because a page name points to one
       page.
    4. Any other planet takes the name of its host's page and its letter
       (`planet_prefix`), so that it reads as its star does in each language
       ("Proxima Centauri b"). Its catalogue name stays as an alias. With no
       letter or no host name, it keeps its catalogue name.

    Every planet takes its names here: the system files, the object entries
    and the lists.
    """
    prefix = planet_prefix(host) if host is not None else None
    if planet.iau_named or planet.letter_repeated or not planet.letter or not prefix:
        return Names(planet.name)
    name = f"{prefix.name} {planet.letter}"
    langs = {lang: f"{label} {planet.letter}" for lang, label in prefix.langs.items()}
    if planet.controversial:
        return Names(
            planet.name,
            {},
            {
                lang: (alias,)
                for lang in LANGUAGES
                if (alias := langs.get(lang, name)) != planet.name
                and not _one_designation(alias, planet.name)
            },
        )
    return Names(
        name,
        langs,
        {
            lang: (planet.name,)
            for lang in LANGUAGES
            if not _one_designation(langs.get(lang, name), planet.name)
        },
    )


def _one_designation(a: str, b: str) -> bool:
    """Whether ``a`` and ``b`` are one designation spelled two ways."""
    return is_latin(a) and is_latin(b) and same_designation(a) == same_designation(b)


_MANUAL_PREFIX = "extra-"


class ObjectNames:
    """The names of objects by their page id.

    A catalogue object is read from ``session`` on first use. A star or a
    planet is one of ``stars`` or ``planets``. A planet is named after its
    host, so its host's entry must be in ``stars``. A barycenter takes the
    names of its planet, read at construction.

    Lookups by id use ``session``, so they run on one thread. `of` names an
    object in hand and is safe on any thread.
    """

    def __init__(
        self,
        entities: WikidataEntityCache,
        session: Session,
        stars: Iterable[StarObject] = (),
        planets: Iterable[PlanetObject] = (),
    ) -> None:
        self.entities = entities
        self._session = session
        self._stars = {star.obj_id: star for star in stars}
        self._planets = {planet.obj_id: planet for planet in planets}
        self._manual: dict[str, dict] | None = None
        self._cache: dict[str, Names] = {}
        self._lock = threading.Lock()
        planets_found = {
            obj.id: obj
            for obj in session.query(Object).filter(
                Object.id.in_(SYSTEM_PRIMARIES.values())
            )
        }
        self._systems = {
            bary_id: system_names(planet_id, object_names(found, entities))
            for bary_id, planet_id in SYSTEM_PRIMARIES.items()
            if (found := planets_found.get(planet_id)) is not None
        }

    def of(self, obj: Object, item: WikidataEntity | None = None) -> Names:
        """The names of a catalogue object. ``item`` is its Wikidata item
        where the caller has read it already."""
        return self._systems.get(obj.id) or object_names(obj, self.entities, item)

    def star(self, star: StarObject) -> Names:
        """The names of a star or a star system with an entry."""
        return star_names(star, self.entities.get_listed_star(star.qid))

    def planet(self, planet: PlanetObject) -> Names:
        """The names of a planet with an entry."""
        host = self._stars.get(planet.host_id)
        return planet_names(
            planet,
            PlanetHost(self.star(host), host.iau_named)
            if host is not None
            else unlisted_host(planet),
        )

    def object(self, obj_id: str) -> Names:
        """The names of the object whose page id is ``obj_id``.

        Raises KeyError for an id with no object.
        """
        found = self.find(obj_id)
        if found is None:
            raise KeyError(obj_id)
        return found

    def find(self, obj_id: str) -> Names | None:
        """The names of the object whose page id is ``obj_id``, None for an id
        with no object."""
        with self._lock:
            if obj_id in self._cache:
                return self._cache[obj_id]
        found = self._lookup(obj_id)
        if found is not None:
            with self._lock:
                self._cache[obj_id] = found
        return found

    def objects(self, obj_ids: Iterable[str]) -> dict[str, Names]:
        """The names of many catalogue objects by page id, read in one query.
        An id with no object is left out."""
        wanted = set(obj_ids)
        with self._lock:
            found = {
                obj_id: self._cache[obj_id] for obj_id in wanted & self._cache.keys()
            }
        rows = (
            self._session.query(Object)
            .options(joinedload(Object.satcat))
            .filter(Object.id.in_(wanted - found.keys()))
        )
        read = {obj.id: self.of(obj) for obj in rows}
        with self._lock:
            self._cache.update(read)
        return found | read

    def mission(self, qid: str, primary: Names) -> Names:
        """The names of the mission page of Wikidata item ``qid``, whose
        primary craft has the names ``primary``."""
        return mission_names(self.entities.get_referenced(qid), primary)

    def probe(self, entry: Mapping) -> Names:
        """The names of a probe of the registry. A probe with no object has no
        page: the labels of its registry item name it, else its registry name."""
        obj_id = f"probe-{entry['probe_id']}"
        return self.find(obj_id) or entity_names(
            self.entities.get_entity(entry.get("wikidata_qid")),
            entry.get("name") or obj_id,
        )

    def _lookup(self, obj_id: str) -> Names | None:
        if (star := self._stars.get(obj_id)) is not None:
            return self.star(star)
        if (planet := self._planets.get(obj_id)) is not None:
            return self.planet(planet)
        if obj_id.startswith(_MANUAL_PREFIX):
            if self._manual is None:
                self._manual = {entry["id"]: entry for entry in read_manual_objects()}
            entry = self._manual.get(obj_id)
            return manual_names(entry) if entry is not None else None
        obj = self._session.get(Object, obj_id)
        return self.of(obj) if obj is not None else None
