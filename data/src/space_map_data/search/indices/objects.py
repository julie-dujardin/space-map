"""Objects search index.

Source files:

    v1/objects/__global__/{bucket}.json.gz   — language-independent fields
    v1/objects/{lang}/{bucket}.json.gz       — per-language name/description/aliases

One document per object, all language variants on the same document.

Filter: skip minor asteroids that have no notable Wikidata signal. ~1.2M of
the 1.5M global entries are bare SBDB designations like "2018 XY" whose only
translation is the word "asteroid" — pure noise in a name search. Notable
ones (Ceres, Vesta, Pallas, …) carry aliases, a Wikipedia article, or a
`named_after` field and survive the cut.
"""

import gzip
import json
import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.images import pick_thumbnail

from .features import Index

logger = logging.getLogger(__name__)

# Object types that are always indexed regardless of whether a localized
# record exists. Everything else (the asteroid_* family) needs a translation
# to make the cut.
_ALWAYS_INDEX = frozenset(
    {
        "barycenter",
        "star",
        "planet",
        "dwarf_planet",
        "moon",
        "comet",
        "spacecraft",
        "debris",
        "lagrange_point",
        "undocumented",
    }
)

# Show "moon of Saturn", not "moon of Saturn Barycenter".
_PLANET_BY_BARYCENTER = {
    "naif-1": "naif-199",
    "naif-2": "naif-299",
    "naif-3": "naif-399",
    "naif-4": "naif-499",
    "naif-5": "naif-599",
    "naif-6": "naif-699",
    "naif-7": "naif-799",
    "naif-8": "naif-899",
    "naif-9": "naif-999",
}

# Type → ranking weight (higher = surfaces first when scores tie). Lets a
# query like "mars" prefer the planet over the dozens of probes that share
# the word.
_TYPE_PRIORITY: dict[str, int] = {
    "star": 100,
    "planet": 95,
    "dwarf_planet": 90,
    "moon": 85,
    "barycenter": 70,
    "lagrange_point": 65,
    "comet": 60,
    "spacecraft": 55,
    "asteroid": 40,
    "asteroid_inner": 40,
    "asteroid_main_belt": 40,
    "asteroid_trojan": 40,
    "asteroid_centaur": 40,
    "asteroid_tno": 40,
    "debris": 20,
    "undocumented": 10,
}


def _load_localized(
    objects_dir: Path,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Return {lang: {obj_id: localized_entry}} fully in-memory.

    Localized data is the small side (~hundreds of MB unpacked) and we need
    random access by id while streaming the global bundles. Keeping it in
    RAM avoids re-decoding each lang bundle once per global bundle.
    """
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for lang in LANGUAGES:
        lang_dir = objects_dir / lang
        if not lang_dir.exists():
            logger.warning("No %s object bundles at %s", lang, lang_dir)
            out[lang] = {}
            continue
        merged: dict[str, dict[str, Any]] = {}
        for bundle in sorted(lang_dir.glob("*.json.gz")):
            merged.update(json.loads(gzip.decompress(bundle.read_bytes())))
        logger.info("Loaded %d localized entries for %s", len(merged), lang)
        out[lang] = merged
    return out


def _is_notable(obj_id: str, localized: dict[str, dict[str, dict[str, Any]]]) -> bool:
    """Asteroid filter: keep only entries that carry a real-name signal in
    any language. `name`/`description` alone aren't enough — Wikidata fills
    those with "(123) 2001 QC44" / "asteroid" for every minor asteroid."""
    for lang in LANGUAGES:
        entry = localized[lang].get(obj_id)
        if not entry:
            continue
        if entry.get("aliases") or entry.get("named_after") or entry.get("wikipedia"):
            return True
    return False


def _designations(global_entry: dict[str, Any]) -> list[str]:
    """Cross-reference designations worth searching by — SBDB number,
    provisional designation, COSPAR id, MPC packed designation, etc."""
    out: list[str] = []
    for key in ("sbdb_primary_designation", "provisional_designation"):
        v = global_entry.get(key)
        if v:
            out.append(str(v))
    refs = global_entry.get("cross_refs") or {}
    for key in ("cospar_id", "mpc_designation", "norad_cat_id", "spkid", "naif_id"):
        v = refs.get(key)
        if v is not None:
            out.append(str(v))
    return out


def _load_earth_membership(export_dir: Path) -> dict[str, list[str]]:
    """Invert v1/membership/earth.json.gz ({slug: [ids]}) into {id: [slugs]}.

    Earth-sat group membership (constellation/operator/manufacturer/launch-site/
    country) only lives in this inverted index, so we fold it onto each doc's
    `groups` array to back the "show all members" query.
    """
    path = export_dir / "v1" / "membership" / "earth.json.gz"
    if not path.exists():
        logger.warning("No earth membership at %s — sat groups will be empty", path)
        return {}
    merged: dict[str, list[str]] = json.loads(gzip.decompress(path.read_bytes()))
    inverted: dict[str, list[str]] = {}
    for slug, ids in merged.items():
        for obj_id in ids:
            inverted.setdefault(obj_id, []).append(slug)
    logger.info(
        "Loaded earth membership: %d sats tagged across %d groups",
        len(inverted),
        len(merged),
    )
    return inverted


def _small_body_groups(sbdb: dict[str, Any]) -> list[str]:
    """Group slugs from SBDB orbit class + NEO/PHA flags. Slugs mirror
    export/groups/registry.py: `class-<OrbitClass.name>`, `flag-neo`, `flag-pha`."""
    groups: list[str] = []
    cls = sbdb.get("class")
    if cls:
        groups.append(f"class-{cls}")
    if sbdb.get("neo"):
        groups.append("flag-neo")
    if sbdb.get("pha"):
        groups.append("flag-pha")
    return groups


# Leading +/- (Wikidata times), year, then optional -MM-DD; trailing time ignored.
_DATE_RE = re.compile(r"[+-]?(\d{1,4})(?:-(\d{2})(?:-(\d{2}))?)?")


def _date_to_int(value: str) -> int | None:
    """Parse 'YYYY', 'YYYY-MM-DD' or a Wikidata '+YYYY-MM-DDT..Z' time into a
    sortable YYYYMMDD int. Missing or zero month/day default to 01."""
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    year = int(m.group(1))
    month = int(m.group(2)) if m.group(2) and m.group(2) != "00" else 1
    day = int(m.group(3)) if m.group(3) and m.group(3) != "00" else 1
    return year * 10000 + month * 100 + day


def _inception(g: dict[str, Any]) -> int | None:
    """One sortable date (YYYYMMDD): discovery for asteroids, launch for sats,
    else Wikidata launch/inception/discovery. First parseable source wins."""
    candidates: list[str] = []
    first_obs = (g.get("sbdb") or {}).get("first_obs")
    if isinstance(first_obs, str):
        candidates.append(first_obs)
    launch = (g.get("celestrak") or {}).get("launch_date")
    if isinstance(launch, str):
        candidates.append(launch)
    wd = g.get("wikidata") or {}
    for key in ("launch_date", "inception"):
        if isinstance(wd.get(key), str):
            candidates.append(wd[key])
    disc = wd.get("discovery_date")
    if isinstance(disc, list):
        candidates.extend(d for d in disc if isinstance(d, str))
    for c in candidates:
        parsed = _date_to_int(c)
        if parsed is not None:
            return parsed
    return None


def _build_object_documents(export_dir: Path) -> Iterator[dict[str, Any]]:
    objects_dir = export_dir / "v1" / "objects"
    global_dir = objects_dir / "__global__"
    if not global_dir.exists():
        logger.warning("No object bundles at %s — nothing to index", global_dir)
        return

    localized = _load_localized(objects_dir)
    earth_groups = _load_earth_membership(export_dir)
    global_files = sorted(global_dir.glob("*.json.gz"))
    logger.info("Streaming %d global object bundles", len(global_files))

    total_seen = 0
    total_indexed = 0
    skipped_no_translation = 0

    for bundle in global_files:
        entries: dict[str, dict[str, Any]] = json.loads(
            gzip.decompress(bundle.read_bytes())
        )
        for obj_id, g in entries.items():
            total_seen += 1
            otype = g.get("type", "undocumented")
            if otype not in _ALWAYS_INDEX and not _is_notable(obj_id, localized):
                skipped_no_translation += 1
                continue

            global_name = g.get("name") or obj_id
            doc: dict[str, Any] = {
                "id": obj_id,
                "name": global_name,
                "type": otype,
                "priority": _TYPE_PRIORITY.get(otype, 0),
            }

            parent_id = (g.get("orbit") or {}).get("parent_id")
            if parent_id:
                doc["parent_id"] = _PLANET_BY_BARYCENTER.get(parent_id, parent_id)

            designations = _designations(g)
            if designations:
                doc["designations"] = designations

            # Optional: NEO/PHA flags & celestrak ops_status are nice-to-have
            # facets even if we don't expose filters yet.
            sbdb = g.get("sbdb") or {}
            if sbdb.get("neo"):
                doc["neo"] = True
            if sbdb.get("pha"):
                doc["pha"] = True
            ct = g.get("celestrak") or {}
            if ct.get("ops_status"):
                doc["ops_status"] = ct["ops_status"]

            # Group membership — backs the "show all members" query. Small-body
            # slugs come from SBDB class/flags, earth-sat slugs from the inverted
            # membership index. An object is one or the other, so a union is safe.
            groups = _small_body_groups(sbdb) + earth_groups.get(obj_id, [])
            if groups:
                doc["groups"] = groups

            # Sort keys for member listings: prominence/size/brightness/date.
            if g.get("sitelinks_count"):
                doc["sitelinks_count"] = g["sitelinks_count"]
            if sbdb.get("diameter") is not None:
                doc["diameter_km"] = sbdb["diameter"]
            magnitude = sbdb.get("H")
            if magnitude is None:
                magnitude = (g.get("wikidata") or {}).get("absolute_magnitude")
            if isinstance(magnitude, (int, float)):
                doc["magnitude"] = magnitude
            inception = _inception(g)
            if inception is not None:
                doc["inception"] = inception

            thumb = pick_thumbnail(g.get("images"))
            if thumb:
                doc["thumbnail"] = thumb

            for lang in LANGUAGES:
                entry = localized[lang].get(obj_id)
                if not entry:
                    continue
                name = entry.get("name")
                if name:
                    doc[f"name_{lang}"] = name
                aliases = entry.get("aliases")
                if aliases:
                    doc[f"aliases_{lang}"] = aliases
                description = entry.get("description")
                if description:
                    doc[f"description_{lang}"] = description

            yield doc
            total_indexed += 1

    logger.info(
        "Built %d object documents (saw %d, skipped %d asteroids without translation)",
        total_indexed,
        total_seen,
        skipped_no_translation,
    )


def _objects_settings() -> dict[str, Any]:
    name_fields = ["name"] + [f"name_{lang}" for lang in LANGUAGES]
    alias_fields = [f"aliases_{lang}" for lang in LANGUAGES]
    designation_fields = ["designations"]
    description_fields = [f"description_{lang}" for lang in LANGUAGES]
    return {
        # Order matters — earlier attributes outrank later ones via the
        # "attribute" ranking rule, so name matches beat alias/designation
        # matches, and descriptions are last-resort full-text fallback.
        "searchableAttributes": (
            name_fields + alias_fields + designation_fields + description_fields
        ),
        "filterableAttributes": [
            "type",
            "parent_id",
            "neo",
            "pha",
            "ops_status",
            "groups",
        ],
        "sortableAttributes": [
            "priority",
            "sitelinks_count",
            "diameter_km",
            "magnitude",
            "inception",
        ],
        "localizedAttributes": [
            {
                "locales": [lang],
                "attributePatterns": [
                    f"name_{lang}",
                    f"aliases_{lang}",
                    f"description_{lang}",
                ],
            }
            for lang in LANGUAGES
        ],
        # Type priority tiebreaks ties — planet "Mars" wins over probe "Mars 3".
        "rankingRules": [
            "words",
            "typo",
            "proximity",
            "attribute",
            "sort",
            "exactness",
            "priority:desc",
        ],
    }


class ObjectsIndex(Index):
    def build_documents(self, export_dir: Path) -> Iterator[dict[str, Any]]:
        return _build_object_documents(export_dir)


OBJECTS_INDEX = ObjectsIndex(
    uid="objects",
    primary_key="id",
    settings=_objects_settings(),
)
