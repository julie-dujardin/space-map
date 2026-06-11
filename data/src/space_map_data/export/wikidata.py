"""Wikidata entity loading, types, and name resolution."""

import orjson
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import TypedDict

from space_map_data.models.object import Object
from space_map_data.utils.paths import SOURCES_METADATA_DIR

logger = logging.getLogger(__name__)


class WikidataEntity(TypedDict):
    labels: dict[str, str]  # lang → name
    descriptions: dict[str, str]  # lang → short description
    aliases: dict[str, list[str]]  # lang → alternative names
    claims: dict  # raw claims from entity JSON
    sitelinks: dict[str, str]  # lang → Wikipedia article title


def load_json_dir(directory: Path, glob: str = "Q*.json") -> Iterator[tuple[str, dict]]:
    """Yield (stem, parsed_json) for each JSON file matching *glob* in *directory*.

    Skips files that fail to parse and logs an error for each.
    """
    if not directory.exists():
        return
    for path in directory.glob(glob):
        try:
            data = orjson.loads(path.read_bytes())
        except (orjson.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load %s: %s", path, exc)
            continue
        yield path.stem, data


class WikidataEntityCache:
    """On-demand Wikidata entity loader.

    Units are preloaded eagerly (143 files). Entities and referenced entries
    are loaded from disk on first access and memoized — claim resolution asks
    for the same referenced QIDs once per object per language, so uncached
    re-reads dominated export profiles.
    """

    def __init__(self) -> None:
        wikidata_dir = SOURCES_METADATA_DIR / "wikidata"
        self._entities_dir = wikidata_dir / "objects"
        self._nomenclature_dir = wikidata_dir / "nomenclature"
        self._referenced_dir = wikidata_dir / "referenced"
        self._units: dict[str, WikidataEntity] = {}
        self._properties: dict[str, WikidataEntity] = {}
        self._feature_types: dict[str, WikidataEntity] = {}
        # Benign under threads: a race just loads the same file twice.
        self._loaded: dict[tuple[str, str], WikidataEntity | None] = {}

        if not any(
            d.exists()
            for d in (
                self._entities_dir,
                self._nomenclature_dir,
                self._referenced_dir,
                wikidata_dir / "units",
            )
        ):
            logger.info("No wikidata entities found, labels will use object names only")
            return

        for qid, entity in load_json_dir(wikidata_dir / "units"):
            parsed = _parse_entity(entity)
            if parsed:
                self._units[qid] = parsed
        logger.info("Preloaded %d unit entities", len(self._units))

        for pid, entity in load_json_dir(wikidata_dir / "properties", glob="P*.json"):
            parsed = _parse_entity(entity)
            if parsed:
                self._properties[pid] = parsed
        logger.info("Preloaded %d property entities", len(self._properties))

        for qid, entity in load_json_dir(wikidata_dir / "feature_types"):
            parsed = _parse_entity(entity)
            if parsed:
                self._feature_types[qid] = parsed
        logger.info("Preloaded %d feature type entities", len(self._feature_types))

    def unit_items(self) -> dict[str, WikidataEntity]:
        """Return all preloaded unit entities as {qid: entity}."""
        return self._units

    def property_items(self) -> dict[str, WikidataEntity]:
        """Return all preloaded property entities as {pid: entity}."""
        return self._properties

    def get_feature_type(self, qid: str | None) -> WikidataEntity | None:
        """Look up an IAU feature type entity (e.g. Q2066176 for Rupes)."""
        if not qid:
            return None
        return self._feature_types.get(qid)

    def get_entity(self, qid: str | None) -> WikidataEntity | None:
        """Look up an object's own Wikidata entity (from entities/)."""
        if not qid:
            return None
        return self._load(qid, self._entities_dir)

    def get_feature_entity(self, qid: str | None) -> WikidataEntity | None:
        """Look up an IAU feature's own Wikidata entity (from nomenclature/)."""
        if not qid:
            return None
        return self._load(qid, self._nomenclature_dir)

    def get_referenced(self, qid: str | None) -> WikidataEntity | None:
        """Look up a referenced entity from claims (from referenced/ or units)."""
        if not qid:
            return None
        if qid in self._units:
            return self._units[qid]
        return self._load(qid, self._referenced_dir)

    def _load(self, qid: str, directory: Path) -> WikidataEntity | None:
        key = (directory.name, qid)
        if key in self._loaded:
            return self._loaded[key]
        path = directory / f"{qid}.json"
        if not path.exists():
            entity = None
        else:
            try:
                raw = orjson.loads(path.read_bytes())
            except (orjson.JSONDecodeError, OSError) as exc:
                raise ValueError(f"Failed to load {path}") from exc
            entity = _parse_entity(raw)
        self._loaded[key] = entity
        return entity


def _parse_entity(entity: dict) -> WikidataEntity | None:
    labels = _extract_lang_values(entity.get("labels", {}))
    descriptions = _extract_lang_values(entity.get("descriptions", {}))
    aliases = _extract_lang_aliases(entity.get("aliases", {}))
    claims = entity.get("claims", {})
    sitelinks = _extract_sitelinks(entity.get("sitelinks", {}))
    if not (labels or descriptions or aliases or claims):
        return None
    return WikidataEntity(
        labels=labels,
        descriptions=descriptions,
        aliases=aliases,
        claims=claims,
        sitelinks=sitelinks,
    )


def resolve_name(
    obj: Object,
    lang: str,
    wd: WikidataEntity | None,
) -> str | None:
    """Resolve the best available name for an object in a given language."""
    if wd:
        labels = wd["labels"]
        if lang in labels:
            return labels[lang]
        if "en" in labels:
            # TODO: save an export of where/how many fallbacks to english were done
            return labels["en"]

    return obj.name


def _extract_lang_values(data: dict) -> dict[str, str]:
    """Extract {lang: value} from Wikidata labels/descriptions format."""
    result: dict[str, str] = {}
    for lang_code, obj in data.items():
        if isinstance(obj, dict) and "value" in obj:
            result[lang_code] = obj["value"]
        elif isinstance(obj, str):
            result[lang_code] = obj
    return result


def _extract_lang_aliases(
    data: dict[str, list[dict[str, str]]],
) -> dict[str, list[str]]:
    """Extract {lang: [alias, ...]} from Wikidata aliases format."""
    result: dict[str, list[str]] = {}
    for lang_code, alias_list in data.items():
        values = [a["value"] for a in alias_list if "value" in a]
        if values:
            result[lang_code] = values
    return result


def active_statements(claims: dict, prop: str) -> list[dict]:
    """Return non-deprecated statements for *prop*, preferring ``preferred`` rank."""
    stmts = [s for s in claims.get(prop, []) if s.get("rank") != "deprecated"]
    preferred = [s for s in stmts if s.get("rank") == "preferred"]
    return preferred if preferred else stmts


def _extract_sitelinks(data: dict) -> dict[str, str]:
    """Extract {lang: article_title} from Wikidata sitelinks."""
    result: dict[str, str] = {}
    for site_key, link in data.items():
        if site_key.endswith("wiki") and isinstance(link, dict) and "title" in link:
            lang = site_key[: -len("wiki")]
            if lang:  # skip "commonswiki" etc. where lang would be "commons"
                result[lang] = link["title"]
    return result
