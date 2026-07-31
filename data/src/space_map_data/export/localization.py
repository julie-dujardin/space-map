"""Merge generated localization entries into frontend/messages/{lang}.json."""

import json
import orjson
import logging
import subprocess
from collections.abc import Callable

from space_map_data.constants.earth_sats.constellations import CONSTELLATION_SLUG_PREFIX
from space_map_data.constants.earth_sats.launch_sites import LAUNCH_SITE_BY_SLUG
from space_map_data.constants.earth_sats.organizations import (
    ORGANIZATION_BY_SLUG,
    ORGANIZATION_SLUG_PREFIX,
)
from space_map_data.constants.nomenclature.feature_types import (
    FEATURE_TYPES,
    feature_type_key,
)
from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.groups.registry import (
    LAUNCH_SITE_SLUG_PREFIX,
    GROUPS,
    GroupType,
)
from space_map_data.export.objects.wikidata_claims import PID_TO_KEY, resolve_unit
from space_map_data.export.wikidata import (
    WikidataEntity,
    WikidataEntityCache,
    active_statements,
)
from space_map_data.utils.paths import PROJECT_ROOT, SOURCES_METADATA_DIR

logger = logging.getLogger(__name__)

MESSAGES_DIR = PROJECT_ROOT / "frontend" / "messages"
BASE_LOCALE = "en"

# All prefixes managed by this module. Generated values only fill gaps:
# existing translations (hand-fixed or otherwise) always win, and keys no
# longer generated for the base locale are pruned.
#
# A hand-written key must never start with one of these: the prune claims the
# whole namespace, so an export would delete it. Pruned keys are logged by name
# for that reason — a count alone hides the mistake.
GENERATED_PREFIXES = (
    "unit_name_",
    "unit_symbol_",
    "property_name_",
    "feature_type_label_",
    "feature_type_description_",
    "group_name_",
)

_UNIT_SYMBOL_PID = "P5061"

# Units whose labels must always be exported regardless of whether they appear
# in used_units (they bypass the normal UnitConverter path).
_ALWAYS_INCLUDE_UNITS: set[str] = {
    "degree_fahrenheit",
    "degree_celsius",
    "kelvin",  # temperatures ship as bare kelvin, bypassing UnitConverter
    "astronomical_unit",  # system scale orbital elements
    "hour",  # sbdb rot_per - rotation period
    "year",  # sbdb per_y - orbital period
    "jupiter_radius",  # exoplanet radii
    "kilometre_per_second",  # orbital speed readout
}

# Units with no Wikidata entity — reuse the same label/symbol across all languages.
_UNIT_FALLBACK_LABELS: dict[str, tuple[str, str]] = {
    "magnitude": ("magnitude", "magnitude"),
}


def _unit_qids() -> set[str]:
    """Return QIDs present in the units/ download directory."""
    units_dir = SOURCES_METADATA_DIR / "wikidata" / "units"
    if not units_dir.exists():
        return set()
    return {f.stem for f in units_dir.glob("Q*.json")}


def _extract_symbol(entity: WikidataEntity, lang: str) -> str | None:
    """Extract the unit symbol (P5061), preferring *lang* then ``mul`` (multilingual) then English."""
    stmts = active_statements(entity["claims"], _UNIT_SYMBOL_PID)
    for target in (lang, "mul", "en"):
        for stmt in stmts:
            dv = stmt.get("mainsnak", {}).get("datavalue", {}).get("value", {})
            if isinstance(dv, dict) and dv.get("language") == target:
                return dv.get("text")
    return None


def _collect_unit_labels(
    wikidata_entities: WikidataEntityCache,
    used_units: set[str],
) -> dict[str, dict[str, str]]:
    """Return {lang: {key: value}} for unit name and symbol entries.

    Only includes units whose normalized key appears in *used_units*.
    """
    qids = _unit_qids()
    if not qids:
        return {}

    # Build {normalized_english_key: (qid, entity)} mapping
    units: dict[str, tuple[str, WikidataEntity]] = {}
    for qid in sorted(qids):
        entity = wikidata_entities.get_referenced(qid)
        if not entity:
            continue
        key = resolve_unit(qid, wikidata_entities)
        if key and (key in used_units or key in _ALWAYS_INCLUDE_UNITS):
            units[key] = (qid, entity)

    if not units:
        return {}

    result: dict[str, dict[str, str]] = {}
    for lang in LANGUAGES:
        labels: dict[str, str] = {}
        for key, (_qid, entity) in units.items():
            label = entity["labels"].get(lang) or entity["labels"].get("en")
            if label:
                labels[f"unit_name_{key}"] = label

            symbol = _extract_symbol(entity, lang)
            if symbol:
                labels[f"unit_symbol_{key}"] = symbol
            elif label:
                labels[f"unit_symbol_{key}"] = label

        for key, (name, symbol) in _UNIT_FALLBACK_LABELS.items():
            labels[f"unit_name_{key}"] = name
            labels[f"unit_symbol_{key}"] = symbol

        result[lang] = labels

    return result


def _collect_property_labels(
    wikidata_entities: WikidataEntityCache,
) -> dict[str, dict[str, str]]:
    """Return {lang: {key: value}} for property name entries."""
    properties = wikidata_entities.property_items()
    if not properties:
        return {}

    result: dict[str, dict[str, str]] = {}
    for lang in LANGUAGES:
        labels: dict[str, str] = {}
        for pid, entity in sorted(properties.items()):
            key = PID_TO_KEY.get(pid)
            if not key:
                continue
            label = entity["labels"].get(lang) or entity["labels"].get("en")
            if label:
                labels[f"property_name_{key}"] = label
        result[lang] = labels

    return result


def _collect_feature_type_labels(
    wikidata_entities: WikidataEntityCache,
) -> dict[str, dict[str, str]]:
    """Return {lang: {key: value}} for IAU feature type labels and descriptions.

    Keyed by the type's slug stem (``feature_type_label_crater``), which is
    also the name its ``ft-`` collection page shows — one string per type, no
    ``group_name_ft-*`` twin.

    Only emits entries for locales that actually have a Wikidata
    label/description — missing translations are left out so Paraglide's
    compile-time baseLocale fallback fills them in. Codes without a Wikidata
    QID (CL/LF/LO/ST) and any field gap in baseLocale itself are backfilled
    from ``FEATURE_TYPES`` so the baseLocale JSON always has every key.
    """
    result: dict[str, dict[str, str]] = {lang: {} for lang in LANGUAGES}
    base = result[BASE_LOCALE]

    for code, feature_type in FEATURE_TYPES.items():
        key = feature_type_key(code)
        label_key = f"feature_type_label_{key}"
        desc_key = f"feature_type_description_{key}"
        qid = feature_type.qid
        entity = wikidata_entities.get_feature_type(qid) if qid else None

        if entity:
            for lang in LANGUAGES:
                if label := entity["labels"].get(lang):
                    result[lang][label_key] = label[:1].upper() + label[1:]
                if desc := entity["descriptions"].get(lang):
                    result[lang][desc_key] = desc[:1].upper() + desc[1:]

        # Fall back to the in-repo IAU constants for the baseLocale where
        # Wikidata didn't provide a value (or had no entity at all).
        base.setdefault(label_key, feature_type.singular)
        base.setdefault(desc_key, feature_type.description)

    return result


def _collect_group_name_labels(
    wikidata_entities: WikidataEntityCache,
) -> dict[str, dict[str, str]]:
    """Return {lang: {group_name_<slug>: label}}, deduped by QID.

    Dedup-by-QID keeps a single label when groups of different types share a
    Wikidata entity (e.g. a constellation and its operator org). Country and
    orbit-class groups are skipped: countries resolve from the ISO code via
    ``Intl.DisplayNames``, and orbit classes reuse the autogenerated
    ``orbit_class_<NAME>`` keys already shipped for the body-detail view, and
    feature types reuse ``feature_type_label_<stem>``.
    """
    result: dict[str, dict[str, str]] = {lang: {} for lang in LANGUAGES}
    base = result[BASE_LOCALE]
    seen_qids: set[str] = set()

    for group in GROUPS:
        if group.type in (
            GroupType.COUNTRY,
            GroupType.ORBIT_CLASS,
            GroupType.EARTH_ORBIT_CLASS,
            GroupType.CATEGORY,
            # Feature types own `feature_type_label_<stem>`; a group_name_ twin
            # would duplicate it from a worse source (uncapitalized labels,
            # disambiguation parentheticals, raw slugs for the QID-less codes).
            GroupType.FEATURE_TYPE,
        ):
            continue
        if group.wikidata_qid and group.wikidata_qid in seen_qids:
            continue
        key = f"group_name_{group.slug}"
        if group.wikidata_qid:
            seen_qids.add(group.wikidata_qid)
            entity = wikidata_entities.get_referenced(group.wikidata_qid)
            if entity:
                for lang in LANGUAGES:
                    if label := entity["labels"].get(lang):
                        result[lang][key] = label
        base.setdefault(key, _group_fallback_name(group))

    return result


def _group_fallback_name(group) -> str:
    if group.type is GroupType.ORGANIZATION:
        org = ORGANIZATION_BY_SLUG.get(
            group.slug.removeprefix(ORGANIZATION_SLUG_PREFIX)
        )
        if org is not None:
            return org.name
    elif group.type is GroupType.LAUNCH_SITE:
        site = LAUNCH_SITE_BY_SLUG.get(group.slug.removeprefix(LAUNCH_SITE_SLUG_PREFIX))
        if site is not None:
            return site.name
    elif group.type is GroupType.CONSTELLATION:
        # No name registry; the bare slug is the fallback the frontend prettifies.
        return group.slug.removeprefix(CONSTELLATION_SLUG_PREFIX)
    return group.slug


def write_messages(
    wikidata_entities: WikidataEntityCache,
    used_units: set[str],
) -> None:
    """Collect unit + property labels and merge them into frontend message files."""
    unit_labels = _collect_unit_labels(wikidata_entities, used_units)
    property_labels = _collect_property_labels(wikidata_entities)
    feature_type_labels = _collect_feature_type_labels(wikidata_entities)
    group_name_labels = _collect_group_name_labels(wikidata_entities)

    def collect(lang: str) -> dict[str, str]:
        return {
            **unit_labels.get(lang, {}),
            **property_labels.get(lang, {}),
            **feature_type_labels.get(lang, {}),
            **group_name_labels.get(lang, {}),
        }

    _merge_all_locales(collect, GENERATED_PREFIXES)


def write_group_messages(wikidata_entities: WikidataEntityCache) -> None:
    """Fill missing ``group_name_*`` keys; leave other generated keys intact."""
    group_name_labels = _collect_group_name_labels(wikidata_entities)
    _merge_all_locales(lambda lang: group_name_labels.get(lang, {}), ("group_name_",))


def _merge_all_locales(
    collect: Callable[[str], dict[str, str]],
    prefixes: tuple[str, ...],
) -> None:
    """Merge the *prefixes* slice of generated entries into every locale file.

    Base locale always has every generated key, so it defines which keys are
    still live; anything else belongs to a removed group/unit/property. It also
    seeds the values other locales are compared against — a translation
    identical to baseLocale is dropped so Paraglide's fallback serves it instead.
    """
    live_keys = set(collect(BASE_LOCALE))
    base_values = _merge_into_file(
        BASE_LOCALE, collect(BASE_LOCALE), live_keys, prefixes
    )
    for lang in LANGUAGES:
        if lang == BASE_LOCALE:
            continue
        _merge_into_file(lang, collect(lang), live_keys, prefixes, base_values)
    _format_messages()


def _format_messages() -> None:
    """Run the frontend's prettier over the message files.

    The export writes near-prettier JSON; delegating the final shape keeps it
    byte-identical to `pnpm format` instead of re-deriving its wrap rules here.
    """
    try:
        result = subprocess.run(
            ["pnpm", "exec", "prettier", "--write", "--log-level", "warn", "*.json"],
            cwd=MESSAGES_DIR,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        logger.warning("Could not run prettier on message files (%s)", exc)
        return
    if result.returncode != 0:
        logger.warning(
            "prettier failed on message files (exit %d): %s",
            result.returncode,
            result.stderr.strip(),
        )


def _merge_into_file(
    lang: str,
    fresh: dict[str, str],
    live_keys: set[str],
    prefixes: tuple[str, ...],
    base_values: dict[str, str] | None = None,
) -> dict[str, str]:
    """Merge *fresh* generated entries into the *lang* message file.

    Existing translations win — generated values only fill gaps. *prefixes*
    scopes what this run manages: only those keys are pruned against
    *live_keys*. Generated keys outside that scope keep their values but are
    still re-sorted with the rest, so a partial run leaves the same layout a
    full one would. When *base_values* is given (non-base locales), any
    generated value identical to the base locale is omitted so Paraglide's
    compile-time fallback serves it instead. Returns the effective generated
    map for this locale.
    """
    msg_file = MESSAGES_DIR / f"{lang}.json"
    existing = orjson.loads(msg_file.read_bytes()) if msg_file.exists() else {}

    def generated_by(key: str, group: tuple[str, ...]) -> bool:
        return any(key.startswith(p) for p in group)

    manual = {
        k: v for k, v in existing.items() if not generated_by(k, GENERATED_PREFIXES)
    }
    carried = {
        k: v
        for k, v in existing.items()
        if k not in manual and not generated_by(k, prefixes)
    }
    kept = {
        k: v
        for k, v in existing.items()
        if k not in manual and k not in carried and k in live_keys
    }
    pruned = [
        k for k in existing if k not in manual and k not in carried and k not in kept
    ]

    generated = {**carried, **fresh, **kept}
    redundant = (
        {k for k, v in generated.items() if base_values.get(k) == v}
        if base_values is not None
        else set()
    )
    generated = {k: v for k, v in generated.items() if k not in redundant}
    merged = {**manual, **dict(sorted(generated.items()))}

    msg_file.write_text(
        json.dumps(merged, ensure_ascii=False, indent="\t") + "\n", encoding="utf-8"
    )
    filled = sum(1 for k in generated if k not in existing)
    logger.info(
        "Merged %d generated keys into %s "
        "(%d kept, %d filled, %d pruned%s, %d == base, %d total)",
        len(generated),
        msg_file.name,
        len(generated) - filled,
        filled,
        len(pruned),
        ": " + ", ".join(sorted(pruned)) if pruned else "",
        len(redundant),
        len(merged),
    )
    return generated
