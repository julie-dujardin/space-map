"""Read DeepL translations produced by the download phase, and define the
context metadata used to translate them.

The downloader (``download.providers.deepl``) writes translations under
``DEEPL_DIR/{lang}.json`` as a nested mapping
``{context_label: {english_source: translation}}``. The context label comes
from the message key's prefix (see ``PREFIX_TO_CONTEXT`` below) and is
passed to DeepL as its ``context`` parameter, which lets the engine
disambiguate domain-specific terms (orbital classes named ``Amor`` are not
``Love``, ``undocumented`` is "not catalogued" not "without papers", etc.).

When the prefix dictionaries change, the cache key changes and stale
entries are simply ignored; deleting ``DEEPL_DIR`` forces a clean
retranslation.
"""

import logging
import re
from pathlib import Path
from typing import TypedDict

import orjson

from space_map_data.utils.paths import SOURCES_METADATA_DIR

logger = logging.getLogger(__name__)

DEEPL_DIR = SOURCES_METADATA_DIR / "deepl"

# Domain context for the DeepL `context` parameter. Plain-English sentences
# describing the UI surface the strings appear on. DeepL uses these as
# conditioning; they are not translated and not billed.
_BASE = (
    "User interface labels for an interactive astronomy and spacecraft map "
    "showing planets, moons, asteroids, comets, satellites, spacecraft, and "
    "their orbital characteristics. Output is shown in compact UI controls."
)
CONTEXTS: dict[str, str] = {
    "default": _BASE,
    "type": (
        _BASE + " The string is an object type label (alongside others such as "
        "'asteroid', 'planet', 'moon', 'comet', 'spacecraft', 'debris', "
        "'barycenter', 'Lagrange point'). 'undocumented' here means "
        "'not catalogued', never refers to immigration status."
    ),
    "category": (
        _BASE + " The string names a category of artificial satellite "
        "(communications, navigation, weather, military, etc.)."
    ),
    "ops_status": (
        _BASE + " The string is an operational status of an artificial satellite, "
        "such as operational, non-operational, decayed (orbit decay, "
        "re-entered atmosphere), backup, spare, extended mission."
    ),
    "object_type": (
        _BASE + " The string is a SATCAT object type: payload, rocket body, or "
        "debris (i.e., space debris fragments)."
    ),
    "orbit_class": (
        _BASE + " The string is a NEO or asteroid orbital class. Many are proper "
        "nouns of asteroid groups derived from a representative member "
        "(Amor, Apollo, Aten, Atira, Hilda, etc.) — keep them untranslated "
        "if there is no established target-language form. Otherwise the "
        "string is a descriptive class name like 'Main-belt', "
        "'Mars-crossing', 'Trans-Neptunian'."
    ),
    "method": (
        _BASE + " The string is the name of an orbit-propagation algorithm "
        "(SGP4, Kepler, Chebyshev). Algorithm names should usually stay in "
        "their canonical English form."
    ),
    "tooltip": (
        _BASE + " The string is the descriptive body of a tooltip — a short "
        "explanatory sentence shown when the user hovers a UI element. "
        "Aim for natural, complete sentences in the target language."
    ),
    "settings": (
        _BASE + " The string is a label in a user-preferences panel "
        "(language, theme, clock format, date format, etc.)."
    ),
    "attribution": (
        _BASE + " The string appears in a 'Data sources' / credits panel that "
        "attributes the underlying scientific data."
    ),
    "credits": (
        _BASE + " The string appears on the credits page acknowledging data and "
        "imagery providers."
    ),
    "time": (
        _BASE + " The string is a time-control label (play, pause, speed, "
        "now, pick a date, etc.)."
    ),
    "image": (
        _BASE + " The string is an image-viewer control label "
        "(view, open, previous, next, etc.)."
    ),
    "source": (
        _BASE + " The string names a scientific data provider (JPL, IAU, NASA, "
        "ESA, CelesTrak, etc.) or attribution chain. Keep agency names "
        "in their canonical form."
    ),
    "spectral_type": (
        _BASE + " The string refers to an asteroid spectral-type taxonomy "
        "(SMASSII, Tholen)."
    ),
    "out_of_range": (
        _BASE + " The string is a status banner shown when the requested time is "
        "outside the dataset's coverage."
    ),
}

# Order matters: longest prefix wins so 'object_type_' resolves before 'object'.
# Keys that don't match any prefix fall back to 'default'.
PREFIX_TO_CONTEXT: tuple[tuple[str, str], ...] = (
    ("orbit_class_", "orbit_class"),
    ("ops_status_", "ops_status"),
    ("object_type_", "object_type"),
    ("attribution_", "attribution"),
    ("spectral_type_", "spectral_type"),
    ("out_of_range_", "out_of_range"),
    ("tooltip_", "tooltip"),
    ("settings_", "settings"),
    ("category_", "category"),
    ("credits_", "credits"),
    ("source_", "source"),
    ("method_", "method"),
    ("image_", "image"),
    ("type_", "type"),
    ("time_", "time"),
)


def context_label_for_key(key: str) -> str:
    """Return the ``CONTEXTS`` key for *key* (e.g. ``'orbit_class_AMO'`` → ``'orbit_class'``)."""
    for prefix, label in PREFIX_TO_CONTEXT:
        if key.startswith(prefix):
            return label
    return "default"


# --- Plural / variant handling ------------------------------------------------
#
# Paraglide's @inlang/plugin-message-format@4 represents pluralized messages as
# a JSON list of variant objects:
#
#     [
#       {
#         "declarations": ["input count", "local countPlural = count: plural"],
#         "selectors": ["countPlural"],
#         "match": {
#           "countPlural=one":   "Cleared {count} pinned object",
#           "countPlural=other": "Cleared {count} pinned objects"
#         }
#       }
#     ]
#
# Plain string values stay strings. Both shapes flow through the same DeepL
# pipeline below — variants get expanded into one translation job per *target*
# CLDR plural category, with the selector placeholder substituted by a
# representative number so DeepL produces correctly-inflected output.


class VariantBlock(TypedDict, total=False):
    declarations: list[str]
    selectors: list[str]
    match: dict[str, str]


MessageValue = str | list[VariantBlock]

# CLDR plural categories per locale, ordered as Paraglide expects.
# Sources beyond two-form locales use the full set; we omit `many` from
# French (rare, only used for compact notation like millions) to keep the
# message files lean.
LOCALE_PLURAL_CATEGORIES: dict[str, tuple[str, ...]] = {
    "en": ("one", "other"),
    "fr": ("one", "other"),
    "ja": ("other",),
    "zh": ("other",),
    "ar": ("zero", "one", "two", "few", "many", "other"),
    "ru": ("one", "few", "many", "other"),
}

# Representative integers shown to DeepL per plural category. They nudge the
# engine toward the right inflection (``2 объекта`` vs ``5 объектов``) and
# are replaced back with the original ``{placeholder}`` once translated.
CATEGORY_REPRESENTATIVE_COUNT: dict[str, str] = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "few": "3",
    "many": "5",
    "other": "5",
}

# Categories whose count is effectively a single fixed integer at runtime
# (``zero`` → 0, ``one`` → 1, ``two`` → 2). For these we leave the literal
# representative number in the translated text instead of restoring the
# ``{count}`` placeholder — the placeholder would only ever interpolate the
# same value anyway, and the literal reads more naturally.
#
# Edge case: French CLDR matches ``one`` for both 0 and 1; if a real-world
# message can fire with count=0 in fr, author its source so this is OK
# (the toast we have today only fires for count ≥ 1).
FIXED_COUNT_CATEGORIES: frozenset[str] = frozenset({"zero", "one", "two"})

_PLACEHOLDER_RE = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")
# `local countPlural = count: plural` → captures `count`.
_LOCAL_PLURAL_DECL_RE = re.compile(r"^\s*local\s+\w+\s*=\s*(\w+)\s*:\s*plural\s*$")
# Numeric stand-ins for non-selector placeholders. Far enough from any literal
# number in our messages (max is 2000 — Wikidata property ID).
_STANDIN_BASE = 99000


def parse_message_value(
    value: MessageValue,
) -> tuple[str | None, str | None, dict[str | None, str], VariantBlock | None]:
    """Decompose an en.json value into translatable parts.

    Returns ``(selector_var, selector_local, source_by_category, raw_variant)``:
    - ``selector_var``: the *input* placeholder driving the plural selector
      (e.g. ``count``), or ``None`` for plain strings.
    - ``selector_local``: the local variable name used in match keys
      (e.g. ``countPlural``), or ``None`` for plain strings.
    - ``source_by_category``: ``{category: text}`` mapping. For plain strings
      this is ``{None: text}``; for variants, one entry per CLDR category
      defined in the en.json variant block.
    - ``raw_variant``: the original variant block (used for re-emitting the
      target locale with the same declarations/selectors), or ``None``.
    """
    if isinstance(value, str):
        return None, None, {None: value}, None
    if not value or not isinstance(value, list):
        return None, None, {}, None
    variant = value[0]
    selector_var: str | None = None
    for decl in variant.get("declarations", []):
        m = _LOCAL_PLURAL_DECL_RE.match(decl)
        if m:
            selector_var = m.group(1)
            break
    selectors = variant.get("selectors", [])
    selector_local = selectors[0] if selectors else None
    source_by_cat: dict[str | None, str] = {}
    for match_key, text in variant.get("match", {}).items():
        # match_key like "countPlural=one"
        if "=" in match_key:
            cat = match_key.rsplit("=", 1)[1]
            source_by_cat[cat] = text
    return selector_var, selector_local, source_by_cat, variant


def substitute_placeholders(
    text: str,
    *,
    selector_var: str | None = None,
    selector_value: str | None = None,
    restore_selector: bool = True,
) -> tuple[str, dict[str, str]]:
    """Replace ``{placeholders}`` with stand-ins suitable for DeepL.

    When ``selector_var`` is set, ``{selector_var}`` is replaced with
    ``selector_value`` — typically a small representative number for a plural
    category. Other placeholders get distinct high-range stand-ins.

    If ``restore_selector`` is False, the selector stand-in is *not* added
    to the inverse map, so the literal value stays in the output after
    restoration. Used for fixed-count categories (``zero``/``one``/``two``)
    where the placeholder would only ever interpolate the same number.

    Returns ``(substituted_text, inverse)``: ``inverse`` maps each stand-in
    back to its original ``{placeholder}`` for restoration.
    """
    name_to_standin: dict[str, str] = {}
    inverse: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        var_name = token[1:-1]
        if (
            selector_var is not None
            and selector_value is not None
            and var_name == selector_var
        ):
            if restore_selector:
                inverse[selector_value] = token
            return selector_value
        if token not in name_to_standin:
            name_to_standin[token] = str(_STANDIN_BASE + len(name_to_standin) + 1)
            inverse[name_to_standin[token]] = token
        return name_to_standin[token]

    return _PLACEHOLDER_RE.sub(replace, text), inverse


def restore_placeholders(text: str, inverse: dict[str, str]) -> str:
    """Reverse a ``substitute_placeholders`` pass."""
    # Replace longest stand-ins first to avoid prefix collisions (e.g. ``2`` vs ``22``).
    for standin, placeholder in sorted(
        inverse.items(), key=lambda kv: len(kv[0]), reverse=True
    ):
        text = text.replace(standin, placeholder)
    return text


def _source_category_for_target(target_cat: str) -> str:
    """Choose the English variant category to feed DeepL when generating *target_cat*.

    English only declares ``one`` and ``other``, so we map every non-``one``
    target category to ``other``.
    """
    return "one" if target_cat == "one" else "other"


def expand_for_target(
    value: MessageValue,
    target_lang: str,
) -> list[tuple[str | None, str, dict[str, str]]]:
    """Enumerate translation jobs for *value* under *target_lang*.

    Each tuple is ``(target_category, substituted_source, inverse)`` where:
    - ``target_category`` is the CLDR plural category to emit in the target
      locale (e.g. ``"few"``), or ``None`` for plain non-variant values.
    - ``substituted_source`` is the text to send to DeepL (also the cache key).
    - ``inverse`` restores placeholders on the response.
    """
    selector_var, _selector_local, source_by_cat, _raw = parse_message_value(value)
    jobs: list[tuple[str | None, str, dict[str, str]]] = []
    if selector_var is None:
        text = source_by_cat.get(None, "")
        if not text:
            return jobs
        substituted, inverse = substitute_placeholders(text)
        jobs.append((None, substituted, inverse))
        return jobs

    target_cats = LOCALE_PLURAL_CATEGORIES.get(target_lang, ("other",))
    for target_cat in target_cats:
        en_cat = _source_category_for_target(target_cat)
        en_text = source_by_cat.get(en_cat) or source_by_cat.get("other")
        if not en_text:
            continue
        rep = CATEGORY_REPRESENTATIVE_COUNT.get(target_cat, "5")
        substituted, inverse = substitute_placeholders(
            en_text,
            selector_var=selector_var,
            selector_value=rep,
            restore_selector=target_cat not in FIXED_COUNT_CATEGORIES,
        )
        jobs.append((target_cat, substituted, inverse))
    return jobs


def _cache_file(target_lang: str) -> Path:
    return DEEPL_DIR / f"{target_lang}.json"


def load_translations(target_lang: str) -> dict[str, dict[str, str]]:
    """Return ``{context_label: {substituted_source: translation}}`` for *target_lang*.

    Empty dict if the downloader hasn't run yet or the file is unreadable.
    A legacy flat ``{source: translation}`` file (pre-context split) is
    lifted into the ``'default'`` bucket so it still serves as a fallback.
    """
    f = _cache_file(target_lang)
    if not f.exists():
        return {}
    try:
        data = orjson.loads(f.read_bytes())
    except orjson.JSONDecodeError:
        logger.warning("Corrupt DeepL translation file at %s, ignoring", f)
        return {}
    if data and not any(isinstance(v, dict) for v in data.values()):
        return {"default": data}
    return data


def _bucket_get(
    translations: dict[str, dict[str, str]],
    label: str,
    substituted: str,
) -> str | None:
    bucket = translations.get(label)
    if bucket and substituted in bucket:
        return bucket[substituted]
    fallback = translations.get("default")
    if fallback and substituted in fallback and label != "default":
        return fallback[substituted]
    return None


def lookup_translation(
    translations: dict[str, dict[str, str]],
    key: str,
    value: MessageValue,
    target_lang: str,
) -> MessageValue | None:
    """Return the translated value for *key* in *target_lang*, or ``None`` if missing.

    Plain string in → plain string out. Variant in → variant array out, with
    one ``match`` entry per CLDR category required by *target_lang*. If *any*
    variant translation is missing from the cache, returns ``None`` so the
    caller can fall back to a prior translation.
    """
    label = context_label_for_key(key)
    selector_var, selector_local, _source_by_cat, raw_variant = parse_message_value(
        value
    )
    jobs = expand_for_target(value, target_lang)
    if not jobs:
        return None

    if selector_var is None:
        _target_cat, substituted, inverse = jobs[0]
        translation = _bucket_get(translations, label, substituted)
        if translation is None:
            return None
        return restore_placeholders(translation, inverse)

    assert raw_variant is not None and selector_local is not None
    placeholder_token = "{" + selector_var + "}"
    match: dict[str, str] = {}
    for target_cat, substituted, inverse in jobs:
        translation = _bucket_get(translations, label, substituted)
        if translation is None:
            return None
        restored = restore_placeholders(translation, inverse)
        # For categories with a single fixed count value (zero/one/two), drop
        # the selector placeholder back to its representative number — the
        # placeholder would interpolate to the same number anyway and the
        # literal reads more naturally ("1 objet" beats "{count} objet" when
        # the count is always 1).
        if target_cat in FIXED_COUNT_CATEGORIES:
            rep = CATEGORY_REPRESENTATIVE_COUNT[target_cat]
            restored = restored.replace(placeholder_token, rep)
        match[f"{selector_local}={target_cat}"] = restored
    return [
        {
            "declarations": list(raw_variant.get("declarations", [])),
            "selectors": list(raw_variant.get("selectors", [])),
            "match": match,
        }
    ]
