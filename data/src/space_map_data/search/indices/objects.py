"""Objects search index.

Source files:

    v1/objects/__global__/{bucket}.json.gz   — language-independent fields
    v1/objects/{lang}/{bucket}.json.gz       — per-language name/description/aliases

One document per object, all language variants on the same document. The
names are those of the object's page (`export.names`): `name` and
`name_{lang}`. A moon carries the names of its host too: `moon_host_name` and
`moon_host_name_{lang}`, from the bundles' `parent_name`.

Filter: skip minor asteroids that have no notable Wikidata signal. ~1.2M of
the 1.5M global entries are bare SBDB designations like "2018 XY" whose only
translation is the word "asteroid" — pure noise in a name search. Notable
ones (Ceres, Vesta, Pallas, …) carry aliases, a Wikipedia article, or a
`named_after` field and survive the cut.

The stars, star systems and planets of the extrasolar catalogue that have an
entry (`x-<id>`, `x-<host>-b-<n>`) are in the same bundles. A star or a
system is indexed when its entry in the base locale has a Wikipedia extract,
as the sitemap lists it, or when it hosts planets. A planet's document is built in `extrasolar`, which
puts the names of its entry on it.

The root `classes` of a document are its type and the class pages it is on, for
the class filter. Search has one class of asteroid: the orbit classes in
`object.groups` tell them apart. A satellite system is the document of its
barycenter, with the `moon_count` of its planet.
"""

import gzip
import json
import logging
import re
from collections.abc import Collection, Iterator
from pathlib import Path
from typing import Any

from space_map_data.constants.categories import (
    DEBRIS_SLUG,
    MOONS_SLUG,
    PROBES_SLUG,
    SATELLITE_SYSTEMS_SLUG,
    SATELLITES_SLUG,
)
from space_map_data.constants.providers import BASE_LOCALE, LANGUAGES
from space_map_data.constants.stars.families import SUN_SPECTRAL_TYPE
from space_map_data.export.groups.planet_family import PAGES as PLANET_PAGES
from space_map_data.export.groups.star_family import star_pages
from space_map_data.export.images import pick_thumbnail
from space_map_data.export.names import SYSTEM_PRIMARIES
from space_map_data.export.objects.stars import PREFIX as STAR_PREFIX
from space_map_data.export.objects.stars import has_description
from space_map_data.extrasolar.families import of_spectral_type
from space_map_data.utils.manual_overlay import read_manual_aliases

from .base import object_pk

logger = logging.getLogger(__name__)

# Object types that are always indexed regardless of whether a localized
# record exists. Everything else (the asteroid_* family) needs a translation
# to make the cut.
_ALWAYS_INDEX = frozenset(
    {
        "barycenter",
        "star",
        "binary_star",
        "multiple_star",
        "planet",
        "exoplanet",
        "dwarf_planet",
        "moon",
        "comet",
        "spacecraft",
        "debris",
        "lagrange_point",
        "undocumented",
    }
)

# The eight planets. A moon of one of these is a planetary satellite, named by
# the IAU's WGPSN; everything else orbits a minor planet — dwarf planets
# included, Pluto being minor planet 134340 — and is named by the WGSBN.
_PLANET_IDS = frozenset(f"naif-{n}99" for n in range(1, 9))
_SUN_ID = "naif-10"


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


def _load_sized_craft(export_dir: Path) -> set[str]:
    """The objects whose bundle is the craft itself, with a span to draw it at."""
    path = export_dir / "v1" / "models" / "index.json"
    if not path.exists():
        logger.warning("No model index at %s — no craft is drawable", path)
        return set()
    bundles: dict[str, dict[str, Any]] = json.loads(path.read_text())["bundles"]
    return {
        attached["id"]
        for bundle in bundles.values()
        if bundle.get("kind") != "shape_model" and bundle.get("scale_meters")
        for attached in bundle["objects"]
    }


def _load_system_moons(export_dir: Path) -> dict[str, int]:
    """The moons of each satellite system, by object ID: the Satellite Systems
    page lists the systems, the Moons page counts the moons of their planets."""
    pages: dict[str, dict[str, Any]] = {}
    for bundle in (export_dir / "v1" / "groups" / "__global__").glob("*.json.gz"):
        groups = json.loads(gzip.decompress(bundle.read_bytes()))
        for slug in (SATELLITE_SYSTEMS_SLUG, MOONS_SLUG):
            if slug in groups:
                pages[slug] = groups[slug]
    moons = pages.get(MOONS_SLUG, {}).get("moon_counts", ())
    counts = {row["primary_id"]: row["n"] for row in moons}
    systems = pages.get(SATELLITE_SYSTEMS_SLUG, {}).get("notable_members", ())
    return {member["id"]: counts[SYSTEM_PRIMARIES[member["id"]]] for member in systems}


def _search_type(otype: str) -> str:
    return "asteroid" if otype.startswith("asteroid_") else otype


def _spacecraft_category(g: dict[str, Any], otype: str) -> str | None:
    """Category slug for a tracked craft, for the search filter. Spacecraft in
    the CelesTrak (NORAD) catalog orbit Earth (`cat-satellites`); the rest are
    deep-space probes (`cat-probes`). Debris is catalogued the same way but
    belongs to `cat-debris`. None for everything else."""
    if otype == "debris":
        return DEBRIS_SLUG if g.get("celestrak") else None
    if otype != "spacecraft":
        return None
    return SATELLITES_SLUG if g.get("celestrak") else PROBES_SLUG


def _class_pages(obj_id: str, g: dict[str, Any]) -> list[str]:
    """The pages of a Solar System planet or the Sun, which no catalogue tags.
    The stars of the extrasolar catalogue get theirs in `extrasolar`."""
    if g.get("type") == "planet" and obj_id in _PLANET_IDS:
        return PLANET_PAGES.pages_of(g.get("planet_families", ()))
    if obj_id == _SUN_ID:
        return star_pages(of_spectral_type(SUN_SPECTRAL_TYPE))
    return []


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


def _radii_diameter_km(radii: dict[str, Any]) -> float | None:
    """Mean triaxial diameter (km) from SPICE PCK radii — the diameter source
    for moons/planets, which aren't in SBDB. Mirrors export/objects/moons.py."""
    vals = [
        v for v in (radii.get("a"), radii.get("b"), radii.get("c")) if v is not None
    ]
    if not vals:
        return None
    return sum(vals) / len(vals) * 2.0


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


def build_object_documents(
    export_dir: Path, keep: Collection[str] = frozenset()
) -> Iterator[dict[str, Any]]:
    """The object documents of the export. An extrasolar entry in `keep`, a
    planet host or a planet, is indexed without a description too."""
    objects_dir = export_dir / "v1" / "objects"
    global_dir = objects_dir / "__global__"
    if not global_dir.exists():
        logger.warning("No object bundles at %s — nothing to index", global_dir)
        return

    localized = _load_localized(objects_dir)
    earth_groups = _load_earth_membership(export_dir)
    sized_craft = _load_sized_craft(export_dir)
    system_moons = _load_system_moons(export_dir)
    manual_aliases = read_manual_aliases()
    global_files = sorted(global_dir.glob("*.json.gz"))
    logger.info("Streaming %d global object bundles", len(global_files))

    total_seen = 0
    total_indexed = 0
    named_moons = 0
    skipped_no_translation = 0
    skipped_stars = 0
    # Minor-planet moons carry no orbit, so their host only shows up on the
    # parent's `notable_moons`. Collected while streaming, applied at the end.
    moon_host_by_child: dict[str, str] = {}
    deferred_moons: list[dict[str, Any]] = []

    for bundle in global_files:
        entries: dict[str, dict[str, Any]] = json.loads(
            gzip.decompress(bundle.read_bytes())
        )
        for obj_id, g in entries.items():
            total_seen += 1
            otype = g.get("type", "undocumented")
            # Harvested before the skip: an unindexed asteroid still names the
            # host of its (indexed) moon.
            for child in g.get("notable_moons") or []:
                child_id = child.get("id")
                if child_id:
                    moon_host_by_child[child_id] = obj_id
            if otype not in _ALWAYS_INDEX and not _is_notable(obj_id, localized):
                skipped_no_translation += 1
                continue
            if (
                obj_id.startswith(STAR_PREFIX)
                and obj_id not in keep
                and not has_description(localized[BASE_LOCALE].get(obj_id))
            ):
                skipped_stars += 1
                continue

            sbdb = g.get("sbdb") or {}
            # Object-specific fields live under the nested `object` key; the
            # natural id rides along so the frontend can route without re-parsing
            # the URL-form primary key.
            obj: dict[str, Any] = {"id": obj_id, "type": _search_type(otype)}

            parent_id = (g.get("orbit") or {}).get("parent_id")
            if parent_id:
                # The host of a planet's moon is the planet, not the barycenter.
                obj["parent_id"] = SYSTEM_PRIMARIES.get(parent_id, parent_id)

            designations = _designations(g)
            if designations:
                obj["designations"] = designations

            if sbdb.get("neo"):
                obj["neo"] = True
            if sbdb.get("pha"):
                obj["pha"] = True
            ct = g.get("celestrak") or {}
            if ct.get("ops_status"):
                obj["ops_status"] = ct["ops_status"]
            if g.get("render_quality"):
                obj["render_quality"] = g["render_quality"]

            # Group membership — backs the "show all members" query and the search
            # filter tree. Small-body slugs from SBDB class/flags, earth-sat slugs
            # from the inverted membership index, plus the satellite/debris/probe
            # category for tracked craft. An object draws from one of these, so a
            # union is safe.
            groups = _small_body_groups(sbdb) + earth_groups.get(obj_id, [])
            spacecraft_cat = _spacecraft_category(g, otype)
            if spacecraft_cat:
                groups.append(spacecraft_cat)
            # Natural satellites back the Moons category's "show all members",
            # and drill by host body / satellite class in the filter tree.
            if otype == "moon":
                groups.append(MOONS_SLUG)
                host = obj.get("parent_id")
                if host:
                    obj["moon_host"] = host
                    obj["moon_class"] = (
                        "planetary" if host in _PLANET_IDS else "minor_planet"
                    )
                # Fallback label for the host-body filter leaves: most minor
                # planets with a moon are too obscure to be indexed themselves,
                # so their own document can't supply a name.
                if host_name := g.get("parent_name"):
                    obj["moon_host_name"] = host_name
                obj["iau_named"] = bool(g.get("iau_named"))
                if obj["iau_named"]:
                    named_moons += 1
            if groups:
                obj["groups"] = groups

            magnitude = sbdb.get("H")
            if magnitude is None:
                magnitude = (g.get("wikidata") or {}).get("absolute_magnitude")
            if isinstance(magnitude, (int, float)):
                obj["magnitude"] = magnitude
            inception = _inception(g)
            if inception is not None:
                obj["inception"] = inception

            doc: dict[str, Any] = {
                "id": object_pk(obj_id),
                "kind": "object",
                "name": g["name"],
                "object": obj,
                "classes": [obj["type"], *_class_pages(obj_id, g)],
            }
            if obj_id in system_moons:
                doc["classes"].append(SATELLITE_SYSTEMS_SLUG)
                doc["moon_count"] = system_moons[obj_id]

            # Root, shared across kinds: prominence (ranking key), size, image.
            if g.get("sitelinks_count"):
                doc["sitelinks_count"] = g["sitelinks_count"]
            if sbdb.get("diameter") is not None:
                doc["diameter_km"] = sbdb["diameter"]
            elif g.get("radii"):
                radii_diameter = _radii_diameter_km(g["radii"])
                if radii_diameter is not None:
                    doc["diameter_km"] = radii_diameter
            # A star's own size is in the extrasolar export (`extrasolar`).
            if not obj_id.startswith(STAR_PREFIX) and (
                obj_id in sized_craft or doc.get("diameter_km")
            ):
                obj["drawable"] = True
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
                if host_name := entry.get("parent_name"):
                    obj[f"moon_host_name_{lang}"] = host_name
                aliases = entry.get("aliases")
                if aliases:
                    obj[f"aliases_{lang}"] = aliases
                description = entry.get("description")
                if description:
                    doc[f"description_{lang}"] = description

            # Hand-authored extra aliases (sources/metadata/manual/aliases.json)
            # fold onto the object's existing alias terms.
            extra_aliases = manual_aliases.get(obj_id)
            if extra_aliases:
                for lang, terms in extra_aliases.items():
                    key = f"aliases_{lang}"
                    obj[key] = (obj.get(key) or []) + terms

            # A moon with no propagated orbit has no host yet — hold it until
            # every bundle's `notable_moons` has been seen.
            if otype == "moon" and "moon_host" not in obj:
                deferred_moons.append(doc)
            else:
                yield doc
            total_indexed += 1

    unhosted = 0
    for doc in deferred_moons:
        host = moon_host_by_child.get(doc["object"]["id"])
        if host:
            doc["object"]["moon_host"] = host
            doc["object"]["moon_class"] = (
                "planetary" if host in _PLANET_IDS else "minor_planet"
            )
        else:
            unhosted += 1
        yield doc
    if unhosted:
        logger.warning(
            "%d moon(s) have neither an orbit parent nor a listing on their "
            "host — no host/class facet",
            unhosted,
        )

    logger.info("Indexed %d IAU-named moons", named_moons)
    logger.info(
        "Built %d object documents (saw %d, skipped %d asteroids without"
        " translation and %d stars without a description)",
        total_indexed,
        total_seen,
        skipped_no_translation,
        skipped_stars,
    )
