"""The sky cultures of the extrasolar export, one JSON file per culture.

The input is the matched cultures that `space-map-ingest` writes at the end of
the extrasolar target, or with `--targets skycultures`. A culture
file holds its figures, the members that the figures and the star names point
to, and the star names. A member is a star with its ID and its position in the
frame of the render tree, or an object with no ID, kept with its reference so
that no line is cut. The position comes from `render.render_rows`, run over
the whole Point source region as the tree build runs it, so a line ends on
the rendered star. A star that the tree does not draw keeps its ID and has no
position.

A member with no ID that has a direction, a deep-sky object or a point of the
sky, has a stand-in position until the registry holds its object. `stand_in`
names the source of its distance.

All files share one directory. A Bucur culture that has the key of a
Stellarium culture, or that is a copy of one under another key, is left out,
and `select` logs why.

`STAR_SHARDS` more files give the figures of each star, so that a star's page
reads no culture file. A shard is whole: a client filters the cultures it shows.

A file is JSON in gzip. Its `token` field holds the token of the table. The
token hashes each file with 16 zeros in that field, as a container token
hashes a payload with a zero token.
"""

import gzip
import hashlib
import html
import json
import logging
import math
import re
import unicodedata
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from urllib.parse import quote

import numpy as np

from space_map_data.constants.providers import BASE_LOCALE, LANGUAGES
from space_map_data.constants.stars.constellations import (
    EQUATORIAL_CHART,
    IAU_NAMED_CULTURES,
    MISNUMBERED_FIGURES,
    MODERN_IAU_CONSTELLATIONS,
    POLISH_CONSTELLATION_NAMES,
    SKY_CONSTELLATION_SLUG_PREFIX,
    SKY_PAGE_NAME_FIXES,
    sky_constellation_pages,
    sky_figure_pages,
)
from space_map_data.constants.stars.cultures import (
    SKY_CULTURE_LABEL_PREFIXES,
    SKY_CULTURE_LABELS,
    SKY_CULTURE_NAME_FIXES,
    SKY_CULTURE_NAMES_LEFT_OUT,
    SKY_CULTURE_REGIONS,
    SKY_PAGE_LABEL_FIXES,
    UNPICKED_SKY_CULTURES,
    sky_culture_page,
)
from space_map_data.export.extrasolar import container, render
from space_map_data.export.extrasolar.container import Written
from space_map_data.export.extrasolar.skyculture_authors import AUTHORS
from space_map_data.export.names import Names
from space_map_data.export.wikidata import WikidataEntityCache, entity_label
from space_map_data.extrasolar.ids import cell_of
from space_map_data.extrasolar.registry import Registry
from space_map_data.extrasolar.sky import region_of
from space_map_data.skycultures import translations
from space_map_data.skycultures.build import COMMON_NAMES, INDEX_FILE
from space_map_data.skycultures.licences import (
    NO_DERIVATIVES,
    NO_LICENCE,
    NON_COMMERCIAL,
    OPEN,
    TK_LABELS,
    UNDECIDED,
)
from space_map_data.skycultures.translations import Catalogues
from space_map_data.utils.paths import DERIVED_SKYCULTURES_DIR

logger = logging.getLogger(__name__)

TABLE = "skycultures"
STELLARIUM = "stellarium"
# A translation is an adaptation, which a CC ND licence forbids to share; a
# culture with no licence grants nothing; Traditional Knowledge labels add terms
# of their own. These cultures keep the names they publish.
UNTRANSLATED_FLAGS = frozenset({NO_DERIVATIVES, NO_LICENCE, TK_LABELS})
# The `stand_in` of a distance that no catalogue gives. All these points sit at
# one distance, among the culture's stars: each figure of sky points keeps its
# shape from near the Sun, and no point spikes out of it from afar.
CULTURE_STARS = "culture-stars"
# Their constellations are the 88 of the IAU; a figure ID ends in the
# abbreviation and the source has no field for it. `modern_journey_to_the_west`
# has those IDs too, but it draws figures of its own over them.
IAU_CULTURES = frozenset({"modern", "modern_iau", "modern_st", "modern_chinese"})
# A Bucur culture is a copy of a Stellarium one when they share at least
# SAME_SEGMENTS of their line segments (Jaccard), and the Stellarium one has
# at least SAME_NAMES of the Bucur figure names.
SAME_SEGMENTS = 0.5
SAME_NAMES = 0.5
# The matched cultures that the export reads.
CULTURES_DIR = DERIVED_SKYCULTURES_DIR
ZERO_TOKEN = "0" * container.TOKEN_SIZE
DEGREES_PER_HOUR = 15.0
# The name fields a figure or a star name keeps.
NAME_FIELDS = ("native", "english", "pronounce", "transliteration", "IPA")
# The name fields that a label reads.
LABEL_NAME_FIELDS = ("native", "english", "pronounce")
# Few enough for a star's page to read a small part of the index.
STAR_SHARDS = 64
# What a Wikidata title adds to a name to tell it from a namesake.
TITLE_NOTE = re.compile(r"\s*\([^)]*\)$")
# Wikidata's Polish labels of constellations are article titles.
POLISH_TITLE = "Gwiazdozbiór "
# The tiers from the most open; an unknown tier is never served.
LADDER = (OPEN, NON_COMMERCIAL, "site-only")
DATASET_URLS = {
    "stellarium": "https://github.com/Stellarium/stellarium",
    "bucur": "https://github.com/doinab/constellation-lines",
}
SIMBAD = {
    "name": "SIMBAD astronomical database",
    "organisation": "CDS, Strasbourg Astronomical Observatory, France",
    "source": "https://simbad.cds.unistra.fr/simbad/",
    "license": "ODbL",
    "attribution": "This research has made use of the SIMBAD database, CDS,"
    " Strasbourg Astronomical Observatory, France.",
    "citation": "Wenger et al. 2000, A&AS 143, 9",
}
HUNT_REFFERT = {
    "name": "Cleaned open cluster catalogue (J/A+A/686/A42)",
    "organisation": "Hunt & Reffert 2024",
    "source": "https://cdsarc.cds.unistra.fr/viz-bin/cat/J/A+A/686/A42",
    "license": "CC BY-NC 3.0 IGO",
    "citation": "Hunt & Reffert 2024, A&A 686, A42",
}
# What places the deep-sky stand-ins, which a culture that draws one credits.
DEEP_SKY_CREDITS = (
    SIMBAD,
    HUNT_REFFERT,
    {
        "name": "Fundamental parameters of Galactic globular clusters",
        "organisation": "Baumgardt et al.",
        "source": "https://people.smp.uq.edu.au/HolgerBaumgardt/globular/",
        "citation": "Baumgardt & Hilker 2018, MNRAS 478, 1520; Baumgardt &"
        " Vasiliev 2021, MNRAS 505, 5957",
    },
    {
        "name": "Heraklion Extragalactic Catalogue (HECATE)",
        "organisation": "Kovlakas et al. 2021",
        "source": "https://cdsarc.cds.unistra.fr/viz-bin/cat/J/MNRAS/506/1896",
        "license": "CC BY 4.0",
        "citation": "Kovlakas et al. 2021, MNRAS 506, 1896",
    },
    {
        "name": "OpenNGC",
        "organisation": "Mattia Verga",
        "source": "https://github.com/mattiaverga/OpenNGC",
        "license": "CC BY-SA 4.0",
    },
)
CREDITS = (
    {
        "name": "Stellarium sky cultures",
        "organisation": "Stellarium",
        "source": "https://github.com/Stellarium/stellarium/tree/master/skycultures",
    },
    {
        "name": "Constellation line figures in sky cultures across the world",
        "organisation": "Doina Bucur",
        "source": "https://github.com/doinab/constellation-lines",
        "license": "CC BY-SA",
    },
    {
        "name": "Stellarium sky culture translations",
        "organisation": "Stellarium translators",
        "source": "https://github.com/Stellarium/stellarium/tree/master/po/stellarium-skycultures",
        "license": "GPL-2.0",
    },
    *({**credit, "deep_sky": True} for credit in DEEP_SKY_CREDITS),
)


def path_of(key: str) -> str:
    return f"{TABLE}/{key}.json.gz"


def star_path(shard: int | str) -> str:
    return f"{TABLE}/stars/{shard}.json.gz"


def segments(record: dict) -> set[frozenset]:
    """The line segments of a matched culture, each a pair of points."""
    found = set()
    for kind in ("constellations", "asterisms"):
        for figure in record["culture"].get(kind, []):
            for chain in figure.get("lines", []):
                points = [
                    p if isinstance(p, int) else json.dumps(p, sort_keys=True)
                    for p in chain
                ]
                found.update(frozenset(s) for s in pairwise(points) if s[0] != s[1])
    return found


def figure_names(record: dict) -> set[str]:
    """The English and native names of the figures of a matched culture."""
    found = set()
    for kind in ("constellations", "asterisms"):
        for figure in record["culture"].get(kind, []):
            names = figure.get("names") or [figure.get("common_name") or {}]
            for name in names:
                for kind in ("english", "native"):
                    if isinstance(name.get(kind), str) and name[kind].strip():
                        found.add(name[kind].strip().casefold())
    return found


def same_culture(bucur: dict, stellarium: dict) -> tuple[float, float]:
    """The share of segments the two cultures share (Jaccard), and the share
    of the Bucur figure names that the Stellarium one also has."""
    a, b = segments(bucur), segments(stellarium)
    names = figure_names(bucur)
    shared_segments = len(a & b) / len(a | b) if a | b else 0.0
    shared_names = len(names & figure_names(stellarium)) / len(names) if names else 0.0
    return shared_segments, shared_names


def select(records: list[dict]) -> tuple[list[dict], list[str]]:
    """The records to export, and why each other one is left out.

    The files share one directory, so Stellarium's culture wins a key that
    Bucur also uses, in any case. A Bucur culture that is a copy of a
    Stellarium one under another key is left out too.
    """
    stellarium = [r for r in records if r["dataset"] == STELLARIUM]
    stellarium_keys = {r["key"].casefold() for r in stellarium} | {COMMON_NAMES}
    taken = set(stellarium_keys)
    kept, left_out = list(stellarium), []
    for record in records:
        if record["dataset"] == STELLARIUM:
            continue
        name = f"{record['dataset']}/{record['key']}"
        key = record["key"].casefold()
        if key in stellarium_keys:
            left_out.append(f"{name}: Stellarium has the key {record['key']}")
            continue
        if key in taken:
            left_out.append(f"{name}: another culture has the key {record['key']}")
            continue
        copies = []
        for other in stellarium:
            shared_segments, shared_names = same_culture(record, other)
            if shared_segments >= SAME_SEGMENTS and shared_names >= SAME_NAMES:
                copies.append(
                    f"{name}: a copy of stellarium/{other['key']}, sharing"
                    f" {shared_segments:.2f} of the segments and {shared_names:.2f}"
                    " of the figure names"
                )
        if copies:
            left_out.append(copies[0])
            continue
        taken.add(key)
        kept.append(record)
    for line in left_out:
        logger.info("sky cultures: left out %s", line)
    return kept, left_out


def combined(*tiers: str) -> str:
    """The tier that every one of `tiers` allows; undecided when one is unknown."""
    if any(t not in LADDER for t in tiers):
        return UNDECIDED
    return max(tiers, key=LADDER.index)


def check(registry: Registry, cultures_dir: Path) -> str | None:
    """Why the matched cultures cannot be exported, or None.

    The IDs of the cultures are those of one registry state, so they must
    come from the ingest that the export reads.
    """
    index = cultures_dir / INDEX_FILE
    if not index.exists():
        return None
    matched = json.loads(index.read_text())["registry_ingest"]
    if matched != registry.last_ingest:
        return (
            f"the sky cultures match registry ingest {matched}, the registry is at"
            f" {registry.last_ingest}: run space-map-ingest --targets skycultures"
        )
    return None


class Members:
    """The distinct objects of one culture, in order of first use."""

    def __init__(self) -> None:
        self.entries: list[dict] = []
        self._index: dict[tuple, int] = {}

    def add(self, point: object) -> int:
        if isinstance(point, int):
            key: tuple = ("id", point)
            entry: dict = {"id": point}
        elif isinstance(point, list):
            key = ("sky", *point)
            entry = {"ra_hours": point[0], "dec": point[1]}
        elif isinstance(point, dict):
            key = ("ref", point["ref"], point["reason"])
            entry = {
                k: point[k]
                for k in ("ref", "reason", "designation", "place")
                if k in point
            }
        else:
            raise TypeError(f"not a culture point: {point!r}")
        if key not in self._index:
            self._index[key] = len(self.entries)
            self.entries.append(entry)
        return self._index[key]

    def ids(self) -> list[int]:
        return [entry["id"] for entry in self.entries if "id" in entry]


def _names(names: Iterable[dict]) -> list[dict]:
    out = []
    for name in names:
        kept = {k: name[k] for k in NAME_FIELDS if isinstance(name.get(k), str)}
        if kept:
            out.append(kept)
    return out


def iau_slug(name: str) -> str:
    """The key in `MODERN_IAU_CONSTELLATIONS` of a Latin name ("Boötes")."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return plain.casefold().replace(" ", "-")


def iau_labels(wikidata: WikidataEntityCache) -> dict[str, dict[str, str]]:
    """The name of each IAU constellation in each site language, by slug."""
    labels: dict[str, dict[str, str]] = {}
    for slug, (qid,) in MODERN_IAU_CONSTELLATIONS.items():
        entity = wikidata.get_referenced(qid)
        if entity is None:
            logger.warning("sky cultures: no Wikidata item %s for %s", qid, slug)
            continue
        found = {lang: entity_label(entity, lang) for lang in LANGUAGES}
        found["pl"] = POLISH_CONSTELLATION_NAMES[slug]
        labels[slug] = {lang: label for lang, label in found.items() if label}
    return labels


def page_labels(wikidata: WikidataEntityCache) -> dict[str, dict[str, str]]:
    """The name of each page of another culture in each site language, by slug."""
    labels: dict[str, dict[str, str]] = {}
    for slug, qid in sky_constellation_pages().items():
        if slug in MODERN_IAU_CONSTELLATIONS:
            continue
        entity = wikidata.get_referenced(qid)
        if entity is None:
            logger.warning("sky cultures: no Wikidata item %s for %s", qid, slug)
            continue
        # Not `entity_label`: its English fallback is a page title.
        found = {lang: entity["labels"].get(lang) for lang in LANGUAGES}
        found |= SKY_PAGE_NAME_FIXES.get(slug, {})
        # A page needs a base name, and `mul` is no page title.
        found[BASE_LOCALE] = found[BASE_LOCALE] or entity_label(entity, BASE_LOCALE)
        if not found[BASE_LOCALE]:
            logger.warning("sky cultures: no %s label on %s", BASE_LOCALE, qid)
            continue
        labels[slug] = {
            lang: TITLE_NOTE.sub("", label).removeprefix(POLISH_TITLE)
            for lang, label in found.items()
            if label
        }
    return labels


def sky_constellation_names(
    wikidata: WikidataEntityCache, home_labels: Mapping[str, dict[str, str]]
) -> dict[str, Names]:
    """The names of each constellation page, by group slug: its label on the
    map. A page of another culture reads the labels of its figure, in
    `home_labels` by group slug."""
    names = {
        f"{SKY_CONSTELLATION_SLUG_PREFIX}{slug}": Names(found[BASE_LOCALE], found)
        for slug, found in iau_labels(wikidata).items()
    }
    for slug, found in page_labels(wikidata).items():
        group = f"{SKY_CONSTELLATION_SLUG_PREFIX}{slug}"
        names[group] = Names(found[BASE_LOCALE], home_labels.get(group, found))
    return names


def _capitalised(value: str) -> str:
    value = value.rstrip(".")
    return value[0].upper() + value[1:]


def translated_cultures(
    records: Iterable[dict], catalogues: Catalogues
) -> dict[str, dict[str, str]]:
    """Stellarium's name of each of its cultures in each language, by key."""
    names = {}
    for record in records:
        if record["dataset"] != STELLARIUM:
            continue
        key = record["key"]
        left_out = SKY_CULTURE_NAMES_LEFT_OUT.get(key, ())
        names[key] = {
            lang: _capitalised(value)
            for lang, value in catalogues.labels(record["name"]).items()
            if lang not in left_out
        } | SKY_CULTURE_NAME_FIXES.get(key, {})
    return names


def _edition_root(slug: str, translated: Mapping[str, dict[str, str]]) -> dict:
    """The translated names of the culture that an edition of `slug` belongs to."""
    for cultures in SKY_CULTURE_REGIONS.values():
        for key, page in cultures.items():
            if page == (slug,) and key in translated:
                return translated[key]
    return {}


def culture_labels(
    key: str,
    name: str,
    wikidata: WikidataEntityCache,
    translated: Mapping[str, dict[str, str]] | None = None,
) -> dict:
    """The name of a culture in each site language that has one of its own:
    Stellarium's, and the table's or Wikidata's in a gap. A language with none,
    and English, read the dataset's `name`."""
    translated = translated or {}
    labels = dict(SKY_CULTURE_LABELS.get(key, {}))
    page = next(
        (c[key] for c in SKY_CULTURE_REGIONS.values() if c.get(key)),
        None,
    )
    entity = None
    if page is not None and key not in SKY_CULTURE_LABELS:
        entity = wikidata.get_referenced(sky_culture_page(page[0]))
        if entity is None:
            logger.warning("sky cultures: no Wikidata item for %s", page[0])
    if entity is not None and page is not None:
        slug, *edition = page
        fixes = SKY_PAGE_LABEL_FIXES.get(slug, {})
        prefixes = SKY_CULTURE_LABEL_PREFIXES.get(key)
        root = _edition_root(slug, translated) if edition else {}
        for lang in LANGUAGES:
            # Not `entity_label`: its English fallback is a page title.
            label = root.get(lang) or fixes.get(lang) or entity["labels"].get(lang)
            if lang == BASE_LOCALE or not label:
                continue
            label = TITLE_NOTE.sub("", label)
            label = label[0].upper() + label[1:]
            if prefixes is not None:
                if lang not in prefixes:
                    continue
                label = f"{prefixes[lang]} ({label})"
            labels[lang] = f"{label} ({edition[0]})" if edition else label
    labels |= translated.get(key, {})
    return {lang: label for lang, label in labels.items() if label != name}


def culture_group(key: str) -> str | None:
    """The region group of a culture, or None when the picker leaves it out."""
    for group, cultures in SKY_CULTURE_REGIONS.items():
        if key in cultures:
            return group
    if key not in UNPICKED_SKY_CULTURES:
        logger.warning("sky cultures: %s has no region, so no picker shows it", key)
    return None


@dataclass
class Naming:
    """What names the figures of a culture."""

    # The labels of each IAU constellation, by slug of the table.
    iau: Mapping[str, dict[str, str]]
    # The labels of each page of another culture, by slug.
    pages: Mapping[str, dict[str, str]] = field(default_factory=dict)
    figures: Catalogues = field(default_factory=Catalogues)


def _group_slug(slug: str) -> str:
    return f"{SKY_CONSTELLATION_SLUG_PREFIX}{slug}"


def _iau_page(key: str, kind: str, name: dict, naming: Naming) -> str | None:
    """The IAU constellation that a figure is, as a slug of the table."""
    if kind != "constellation":
        return None
    if key in IAU_CULTURES:
        slug = iau_slug(name.get("native", ""))
    elif key in IAU_NAMED_CULTURES:
        slug = iau_slug(name.get("english", "").removesuffix(EQUATORIAL_CHART))
    else:
        return None
    return slug if slug in naming.iau else None


def _translations(record: dict, name: dict, naming: Naming) -> dict:
    """Stellarium's names of a figure, by language. See `UNTRANSLATED_FLAGS`."""
    english = name.get("english")
    if (
        record["dataset"] != STELLARIUM
        or not english
        or UNTRANSLATED_FLAGS & set(record["licence"]["flags"])
    ):
        return {}
    return naming.figures.labels(english, name.get("context"))


def _figure(
    record: dict,
    figure: dict,
    kind: str,
    members: Members,
    naming: Naming,
    pages: Mapping[str, str],
) -> dict:
    names = figure.get("names") or (
        [figure["common_name"]] if "common_name" in figure else []
    )
    out: dict = {"id": figure["id"], "kind": kind, "names": _names(names)}
    out["lines"] = [
        [members.add(point) for point in chain] for chain in figure.get("lines", [])
    ]
    if "group" in figure:
        out["group"] = [members.add(point) for point in figure["group"]]
    if "IAU" in figure:
        out["iau"] = figure["IAU"]
    key, name = record["key"], names[0] if names else {}
    if key in IAU_CULTURES and kind == "constellation":
        out["iau"] = figure["id"].rsplit(" ", 1)[-1]
    if iau := _iau_page(key, kind, name, naming):
        out["page"] = _group_slug(iau)
        out["labels"] = naming.iau[iau]
    elif page := MISNUMBERED_FIGURES.get((key, name.get("english"))) or pages.get(
        figure["id"]
    ):
        out["page"] = _group_slug(page)
        found = _translations(record, name, naming)
        labels = naming.pages.get(page, {}) | found
        labels.pop(BASE_LOCALE, None)
        if labels:
            out["labels"] = labels
    else:
        # A page needs a name in each language; a label needs only to add one.
        own = {n.get("native") for n in names}
        found = _translations(record, name, naming)
        labels = {k: v for k, v in found.items() if v not in own}
        if labels:
            out["labels"] = labels
    if figure.get("is_ray_helper"):
        out["ray_helper"] = True
    return out


def layout(record: dict, naming: Naming) -> tuple[dict, Members]:
    """The file content of a matched culture, without positions."""
    culture = record["culture"]
    members = Members()
    pages = sky_figure_pages().get(record["key"], {})
    figures = [
        _figure(record, figure, kind, members, naming, pages)
        for key, kind in (
            ("constellations", "constellation"),
            ("asterisms", "asterism"),
        )
        for figure in culture.get(key, [])
    ]
    names = [
        {"member": members.add(entry["object"]), "names": _names(entry["names"])}
        for entry in culture.get("common_names", [])
    ]
    content = {
        "token": ZERO_TOKEN,
        "dataset": record["dataset"],
        "key": record["key"],
        "name": record["name"],
        "members": members.entries,
        "figures": figures,
        "names": names,
    }
    return content, members


def positions(registry: Registry, ids: Iterable[int]) -> dict[int, list[float]]:
    """The render-tree position (pc) of each ID that the tree draws.

    Each region is rendered whole, as `render.region_rows` renders it, so the
    float64 positions are the tree's.
    """
    wanted = np.unique(np.fromiter(ids, np.int64))
    found: dict[int, list[float]] = {}
    regions = region_of(cell_of(wanted))
    for region in np.unique(regions).tolist():
        rows, _ = render.render_rows(render.region_table(registry, region))
        hit = np.isin(rows["id"], wanted[regions == region])
        for id_, x, y, z in zip(
            rows["id"][hit].tolist(),
            rows["x"][hit].tolist(),
            rows["y"][hit].tolist(),
            rows["z"][hit].tolist(),
        ):
            found[id_] = [x, y, z]
    return found


def _cartesian(ra: float, dec: float, distance: float) -> list[float]:
    ra_rad, dec_rad = math.radians(ra), math.radians(dec)
    return [
        distance * math.cos(dec_rad) * math.cos(ra_rad),
        distance * math.cos(dec_rad) * math.sin(ra_rad),
        distance * math.sin(dec_rad),
    ]


def place_stand_ins(members: list[dict]) -> None:
    """Give each member with a direction and no ID its stand-in position.

    Its distance is that of its catalogue, else the median of the culture's
    stars. A culture with no star cannot give that, so such a member has no
    position.
    """
    stars = [np.linalg.norm(m["position"]) for m in members if "position" in m]
    median = float(np.median(stars)) if stars else None
    for member in members:
        place = member.pop("place", None)
        if "ra_hours" in member:
            ra, dec = member["ra_hours"] * DEGREES_PER_HOUR, member["dec"]
            distance, source = None, None
        elif place is not None:
            ra, dec = place["ra"], place["dec"]
            distance, source = place["distance"], place["source"]
        else:
            continue
        if distance is None:
            distance, source = median, CULTURE_STARS
        if distance is None:
            continue
        member["position"] = _cartesian(ra, dec, distance)
        member["stand_in"] = source


def figure_star_ids(members: list[dict], figure: dict) -> Iterator[int]:
    """The extrasolar IDs of a figure's stars in the order of its lines, then
    its group. A star on two lines comes twice."""
    points = [p for chain in figure["lines"] for p in chain]
    for point in (*points, *figure.get("group", ())):
        if "id" in members[point]:
            yield members[point]["id"]


def star_shards(contents: Iterable[dict]) -> list[dict]:
    """The shard contents: for each star, its figures by culture key."""
    shards: list[dict] = [
        {"token": ZERO_TOKEN, "stars": {}} for _ in range(STAR_SHARDS)
    ]
    for content in contents:
        for figure in content["figures"]:
            if figure.get("ray_helper"):
                continue
            entry = {
                "names": [
                    kept
                    for name in figure["names"]
                    if (kept := {k: name[k] for k in LABEL_NAME_FIELDS if k in name})
                ]
            }
            entry |= {k: figure[k] for k in ("labels", "page") if k in figure}
            for id_ in sorted(set(figure_star_ids(content["members"], figure))):
                stars = shards[id_ % STAR_SHARDS]["stars"]
                stars.setdefault(str(id_), {}).setdefault(content["key"], []).append(
                    entry
                )
    return shards


def _letters(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def authors(record: dict) -> list[str]:
    """The plain author names of a Stellarium culture that its Authors section
    still holds. Bucur's cultures credit the dataset."""
    if record["dataset"] != STELLARIUM:
        return []
    names = AUTHORS.get(record["key"])
    if names is None:
        logger.warning("%s: no author names, so its credit has none", record["key"])
        return []
    text = _letters(html.unescape(record.get("authors") or ""))
    found = [name for name in names if _letters(name) in text]
    for name in names:
        if name not in found:
            logger.warning(
                "%s: %r is not in its Authors section, so its credit leaves it out",
                record["key"],
                name,
            )
    return found


def _payload(content: dict) -> bytes:
    return (
        json.dumps(content, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode()


@dataclass
class Result:
    files: list[Written]
    entry: dict
    # Each culture left out, and why.
    left_out: list[str]


def culture_credit(record: dict) -> dict:
    """The credit of a culture, in the shape of the export's `credits`."""
    parts = [
        p["licence"]
        if p["applies_to"] == "all"
        else f"{p['licence']} ({p['applies_to']})"
        for p in record["licence"]["parts"]
    ]
    stellarium = record["dataset"] == STELLARIUM
    # A Stellarium culture is a directory, a Bucur culture one file.
    view = "tree" if stellarium else "blob"
    credit = {
        "name": record["name"],
        "organisation": "Stellarium" if stellarium else "Doina Bucur",
        "source": (
            f"{DATASET_URLS[record['dataset']]}/{view}/{record['source']['commit']}"
            f"/{quote(record['source']['path'])}"
        ),
        "license": "; ".join(parts) or "none stated",
    }
    names = authors(record)
    if names:
        credit["authors"] = names
    return credit


def _entry(
    record: dict,
    content: dict,
    path: str,
    wikidata: WikidataEntityCache,
    translated: Mapping[str, dict[str, str]],
) -> dict:
    licence = record["licence"]
    credit = culture_credit(record)
    members = content["members"]
    return {
        "dataset": record["dataset"],
        "key": record["key"],
        "name": record["name"],
        "region": record["region"],
        "subregion": record.get("subregion"),
        "group": culture_group(record["key"]),
        "labels": culture_labels(record["key"], record["name"], wikidata, translated),
        "packaged": record["packaged"],
        "fallback_to_international_names": bool(
            record["culture"].get("fallback_to_international_names")
        ),
        "file": path,
        "licence": {"parts": licence["parts"], "distribution": licence["distribution"]},
        "distribution": combined(licence["distribution"], NON_COMMERCIAL),
        "flags": licence["flags"],
        "credit": credit,
        "figures": len(content["figures"]),
        "members": len(members),
        "positioned": sum(1 for m in members if "position" in m),
        "stand_ins": sum(1 for m in members if "stand_in" in m),
        "unresolved": sum(1 for m in members if "ref" in m),
    }


def build(
    registry: Registry,
    out: Path,
    wikidata: WikidataEntityCache,
    cultures_dir: Path | None = None,
) -> Result | None:
    """Write the culture files below `out` with their token, or None with no input.

    The returned entry goes to `skycultures` in metadata.json.
    """
    cultures_dir = cultures_dir or CULTURES_DIR
    index_file = cultures_dir / INDEX_FILE
    if not index_file.exists():
        logger.warning("no matched sky cultures at %s: the export has none", index_file)
        return None
    index = json.loads(index_file.read_text())
    records, left_out = select(
        [
            json.loads((cultures_dir / entry["file"]).read_text())
            for entry in index["cultures"]
        ]
    )
    common = json.loads(
        (cultures_dir / "stellarium" / f"{COMMON_NAMES}.json").read_text()
    )

    naming = Naming(
        iau_labels(wikidata),
        page_labels(wikidata),
        translations.load(translations.FIGURES),
    )
    translated = translated_cultures(records, translations.load(translations.CULTURES))
    laid_out = [layout(record, naming) for record in (*records, common)]
    ids = {id_ for _, members in laid_out for id_ in members.ids()}
    logger.info("sky cultures: positions of %d stars", len(ids))
    found = positions(registry, ids)
    logger.info(
        "sky cultures: %d of %d stars are in the render tree", len(found), len(ids)
    )
    contents = []
    for content, members in laid_out:
        for entry in members.entries:
            if "id" in entry and entry["id"] in found:
                entry["position"] = found[entry["id"]]
        place_stand_ins(members.entries)
        contents.append(content)
    unplaced = sorted(ids - set(found))
    logger.debug("sky cultures: stars that the tree does not draw: %s", unplaced)

    paths = [path_of(c["key"]) for c in contents]
    shards = star_shards(contents)
    files = [
        *zip(paths, contents),
        *((star_path(n), shard) for n, shard in enumerate(shards)),
    ]
    digests = [hashlib.sha256(_payload(content)).digest() for _, content in files]
    token = container.token_of(
        [Written(path, digest, 0, 0) for (path, _), digest in zip(files, digests)]
    )
    written = []
    for (path, content), digest in zip(files, digests):
        content["token"] = token
        data = gzip.compress(_payload(content), compresslevel=9, mtime=0)
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        rows = len(content.get("members", content.get("stars")))
        written.append(Written(path, digest, rows, len(data)))

    cultures = [
        _entry(record, content, path, wikidata, translated)
        for record, content, path in zip(records, contents, paths)
    ]
    entry = {
        "token": token,
        "file": path_of("{key}"),
        "star_figures": star_path("{shard}"),
        "star_shards": STAR_SHARDS,
        "international_names": paths[-1],
        "international_names_distribution": combined(
            common["licence"]["distribution"], NON_COMMERCIAL
        ),
        "units": "pc",
        "commits": index["commits"],
        "cultures": cultures,
        "credits": list(CREDITS),
    }
    return Result(written, entry, left_out)
