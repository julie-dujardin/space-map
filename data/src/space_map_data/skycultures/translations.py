"""Stellarium's translations of its sky cultures: two gettext catalogues.

`stellarium-skycultures` holds the names of figures, and
`stellarium-skycultures-descriptions` the names of cultures. An entry is found
by its msgid and msgctxt, as Stellarium finds it, so a figure gets what its
own `context` selects. A msgid with no context serves every culture that uses
the word. The translator sees all of them, and can translate for one only, so
`WRONG_SENSE` lists the values that do not fit.

The files are untrusted data. They are only parsed, never run.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from space_map_data.constants.providers import BASE_LOCALE, LANGUAGES
from space_map_data.utils.paths import SOURCES_SKYCULTURES_DIR

logger = logging.getLogger(__name__)

PO_DIR = SOURCES_SKYCULTURES_DIR / "stellarium" / "po"
FIGURES, CULTURES = "stellarium-skycultures", "stellarium-skycultures-descriptions"
# The site's Chinese is Simplified. Its Portuguese is European, so `pt_BR` is
# not a fallback.
PO_FILES = {"zh": "zh_CN"}

_ENTRY = re.compile(r'^(msgctxt|msgid|msgstr) "(.*)"$')
_CONTINUED = re.compile(r'^"(.*)"$')
_FUZZY = re.compile(r"^#,.*\bfuzzy\b", re.MULTILINE)
_ESCAPE = re.compile(r"\\(.)")
_ESCAPES = {"n": "\n", "t": "\t"}
# Arabic entries wrap their text in left-to-right marks.
_MARKS = re.compile(r"[\u200e\u200f\u202a-\u202e]")

# Values that name something else: a translator's choice for another culture
# (zh "Net" is the Chinese mansion, also on an Egyptian net), the wrong sense of
# an English word (fr "Dipper" is the bird), or a machine's guess. Found by
# reading the figures with a page and the one-word names; English reads better.
WRONG_SENSE: dict[str, frozenset[str]] = {
    msgid: frozenset(langs.split())
    for msgid, langs in {
        "Arrow": "zh",
        "Ashes": "it",
        "Banner": "ru",
        "Bond": "ar",
        "Caribou": "pt",
        "Circlet": "ru",
        "Collarbones": "pt",
        "Crab": "fr",
        "Dipper": "fr it pl pt",
        "Dog": "fr",
        "Embrace": "fr",
        "Establishment": "it pl",
        "Flock": "ru",
        "Fly": "pt",
        "Fox": "fr",
        "Hairy Head": "pt",
        "Horn": "ar",
        "Horse": "fr",
        "Keystone": "fr",
        "Little Dipper": "es fr",
        "Magha": "ja",
        "Meat ant": "fr",
        "Net": "ja zh",
        "Prow": "pl",
        "Purva Ashadha": "ru",
        "Purva Bhadrapada": "ru",
        "Purva Phalguni": "ru",
        "Revolving Female": "pt",
        "Roofing": "ru",
        "Root": "ja zh",
        "Screen": "es pt",
        "Sea monster": "fr it",
        "Star": "ja",
        "The Backbone": "ru",
        "The Brothers": "it",
        "The Bunch": "ru",
        "The He-Goat": "de it",
        "The Herdsman": "ru",
        "The Mowers": "es fr it",
        "The Nail": "fr it",
        "The Scythe": "fr",
        "The Stargate": "fr",
        "The Twins": "de",
        "The Whale": "zh",
        "Trials": "ru",
        "Uttara Ashadha": "ru",
        "Uttara Bhadrapada": "ru",
        "Uttara Phalguni": "ru",
        "Willow": "pt",
    }.items()
}


def parse(text: str) -> dict[tuple[str | None, str], str]:
    """The translated entries of a catalogue, by msgctxt and msgid."""
    entries: dict[tuple[str | None, str], str] = {}
    for block in text.split("\n\n"):
        # A fuzzy value is a machine's guess from another msgid.
        if _FUZZY.search(block):
            continue
        fields: dict[str, str] = {}
        current = None
        for line in block.splitlines():
            if found := _ENTRY.match(line):
                current = found[1]
                fields[current] = found[2]
            elif (found := _CONTINUED.match(line)) and current:
                fields[current] += found[1]
            elif not line.startswith("#"):
                current = None
        if fields.get("msgid") and fields.get("msgstr"):
            context, msgid, value = (
                _unescape(fields[k]) if k in fields else None
                for k in ("msgctxt", "msgid", "msgstr")
            )
            if msgid and value:
                entries[context, msgid] = value
    return entries


def _unescape(text: str) -> str:
    return _ESCAPE.sub(lambda m: _ESCAPES.get(m[1], m[1]), text)


def clean(value: str) -> str:
    return _MARKS.sub("", value).strip()


@dataclass
class Catalogues:
    """One catalogue per site language; a language with no file has none."""

    by_language: dict[str, dict[tuple[str | None, str], str]] = field(
        default_factory=dict
    )

    def labels(self, msgid: str, context: str | None = None) -> dict[str, str]:
        """The value of an entry in each language that translates it."""
        out = {}
        for lang, entries in self.by_language.items():
            if (value := entries.get((context, msgid))) is None:
                continue
            value = clean(value)
            if value and value != msgid and lang not in WRONG_SENSE.get(msgid, ()):
                out[lang] = value
        return out


def catalogue_paths(domain: str, directory: Path = PO_DIR) -> dict[str, Path]:
    """The file of a catalogue by site language."""
    return {
        lang: directory / domain / f"{PO_FILES.get(lang, lang)}.po"
        for lang in LANGUAGES
        if lang != BASE_LOCALE
    }


def load(domain: str, directory: Path = PO_DIR) -> Catalogues:
    """A catalogue in each site language. With no files, it is empty."""
    catalogues = Catalogues()
    for lang, path in catalogue_paths(domain, directory).items():
        if path.exists():
            catalogues.by_language[lang] = parse(path.read_text(encoding="utf-8"))
        else:
            logger.warning("sky cultures: no %s translations at %s", lang, path)
    return catalogues
