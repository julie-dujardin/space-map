"""Object entries of the extrasolar objects with a Wikidata item or a value
from a paper: stars, and planets with an item.

They live in the object bundles, under `x-<id>` like the `/x/<id>` pages and
`x-<host>-b-<n>` like the `/x/<host>/b/<n>` ones, so these pages read their
text as a body page does. They hold metadata only: names, descriptions,
references and discovery dates from Wikidata, Wikipedia extracts, Commons
images, and the works that the literature table cites for a value. The record
tiles and the planet files of the extrasolar export hold the values, under
their own terms.

The registry's Metadata rows say which stars have an entry (`object`), and
give their English name, QID and literature key. A planet has an entry when
its planets table row has a Wikidata QID among its cross ids.
"""

import gzip
import logging
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import orjson
import pyarrow.parquet as pq

from space_map_data.constants.providers import BASE_LOCALE, LANGUAGES
from space_map_data.constants.stars.literature import DISTANCES, REFERENCES, StarKey
from space_map_data.export.extrasolar.planets import read_planets
from space_map_data.export.images import collect_star_images
from space_map_data.export.in_place import refresh_versions
from space_map_data.export.objects.wikidata_claims import (
    STAR_ENTITY_REF_CLAIMS,
    STAR_GLOBAL_CLAIMS,
    extract_claims,
    make_body_entityref,
    resolve_entity_ref,
)
from space_map_data.export.objects.wikipedia import (
    WikipediaSummary,
    load_wikipedia_summaries_for_qid,
)
from space_map_data.export.objects.writer import ChunkObjectData, hash_bucket
from space_map_data.export.sidecar_io import write_atomic
from space_map_data.export.wikidata import (
    WikidataEntity,
    WikidataEntityCache,
    active_statements,
)
from space_map_data.extrasolar.exoplanets.join import designation_key
from space_map_data.extrasolar.exoplanets.table import IAU_NAMES
from space_map_data.extrasolar.exoplanets.wikidata import planet_qid
from space_map_data.extrasolar.registry import NoRegistry, Registry
from space_map_data.extrasolar.sources.literature import LITERATURE, key_of
from space_map_data.extrasolar.sources.wikidata import WIKIDATA, usable_name
from space_map_data.extrasolar.tables import METADATA
from space_map_data.utils.paths import EXPORT_DIR, REGISTRY_ROOT

logger = logging.getLogger(__name__)

PREFIX = "x-"
TYPE = "star"
PLANET_TYPE = "exoplanet"
# The id of a planet's entry, as its scene id.
PLANET_ID = re.compile(r"^x-\d+-b-\d+$")
# The prefixes of SIMBAD's identifiers that Wikidata copies into some aliases:
# "NAME Proxima Centauri b", "* 51 Peg b", "V* V645 Cen".
_SIMBAD_PREFIX = re.compile(r"^(NAME|V\*|\*\*|\*|Cl\*) +")

# Spectral and luminosity classes. A star type that is one of them, or a
# direct subclass of one, restates a catalogue value, so the entry leaves it
# out.
SPECTRAL_CLASSES = frozenset(
    {
        "Q1222876",  # O-type star
        "Q14745279",  # B-type star
        "Q14745284",  # A-type star
        "Q995268",  # F-type star
        "Q1007122",  # G-type star
        "Q1103085",  # K-type star
        "Q1161161",  # M-type star
        "Q244393",  # dwarf star
        "Q6220",  # subdwarf star
        "Q6227",  # subgiant
        "Q5875",  # giant star
        "Q50081",  # red giant
        "Q3929897",  # red giant branch
        "Q50089",  # asymptotic giant branch
        "Q5881",  # bright giant
        "Q193599",  # supergiant
        "Q231982",  # hypergiant
    }
)


@dataclass(frozen=True)
class StarObject:
    id: int
    name: str
    # None for a star with no Wikidata item.
    qid: str | None = None
    # The key of the star in the literature table.
    literature: StarKey | None = None


@dataclass(frozen=True)
class PlanetObject:
    host: int
    number: int
    # The planet's name in its planets table row.
    name: str
    qid: str
    # Its designation and the other names its catalogues give it.
    designations: tuple[str, ...] = ()
    letter: str | None = None
    iau_named: bool = False

    @property
    def obj_id(self) -> str:
        return f"{PREFIX}{self.host}-b-{self.number}"


class _Page(NamedTuple):
    """The page of a star or a planet: its entry id, its global name and its
    names by language where they differ."""

    obj_id: str
    name: str
    names: dict[str, str]


class _Read(NamedTuple):
    """What the entries of a star keep of its entity."""

    claims: dict
    descriptions: dict[str, str]
    aliases: dict[str, list[str]]
    sitelinks: int | None


def _read_part(path: Path) -> list[StarObject]:
    rows = pq.read_table(
        path, columns=["id", "name", "cross_ids"], filters=[("object", "=", True)]
    )
    out = []
    for id_, name, cross_ids in zip(
        rows["id"].to_pylist(), rows["name"].to_pylist(), rows["cross_ids"].to_pylist()
    ):
        ids = defaultdict(list)
        for x in cross_ids:
            ids[x["catalogue"]].append(x["catalogue_id"])
        qids, keys = ids[WIKIDATA.catalogue], ids[LITERATURE.catalogue]
        if len(qids) > 1 or len(keys) > 1 or not (qids or keys):
            raise ValueError(
                f"{path}: ID {id_} has the Wikidata items {qids} and the"
                f" literature keys {keys}"
            )
        out.append(
            StarObject(
                id_,
                name,
                qids[0] if qids else None,
                key_of(keys[0]) if keys else None,
            )
        )
    return out


def _star_objects(registry: Registry) -> list[StarObject]:
    directory = registry.table_dir(METADATA.slug)
    paths = [] if directory is None else sorted(directory.glob("*.parquet"))
    with ThreadPoolExecutor(8) as pool:
        parts = list(pool.map(_read_part, paths))
    return [star for part in parts for star in part]


def _planet_objects(registry: Registry) -> list[PlanetObject]:
    table = read_planets(registry)
    if table is None:
        return []
    columns = [
        "host",
        "number",
        "name",
        "name_source",
        "designation",
        "letter",
        "aliases",
        "cross_ids",
    ]
    out = []
    for row in table.select(columns).to_pylist():
        qid = planet_qid(row["cross_ids"])
        if qid is None:
            continue
        names = (row["designation"], *(row["aliases"] or ()))
        out.append(
            PlanetObject(
                row["host"],
                row["number"],
                row["name"],
                qid,
                tuple(dict.fromkeys(n for n in names if n)),
                row["letter"],
                row["name_source"] == IAU_NAMES,
            )
        )
    return out


def read_extrasolar_objects(
    root: Path = REGISTRY_ROOT,
) -> tuple[list[StarObject], list[PlanetObject]]:
    """The stars and the planets with an entry, from one version of the
    registry: the Metadata table and the planets table."""
    with Registry(root).reader() as registry:
        return _star_objects(registry), _planet_objects(registry)


def available_extrasolar_objects(
    root: Path = REGISTRY_ROOT,
) -> tuple[list[StarObject], list[PlanetObject]]:
    """The stars and the planets with an entry, or none on a host without
    the registry.

    Raises RegistryBusy while an ingest holds the registry, so that no export
    loses its star and planet pages.
    """
    try:
        return read_extrasolar_objects(root)
    except NoRegistry as error:
        logger.warning("No star or planet entries: %s", error)
        return [], []


def _page_name(entity: WikidataEntity | None, lang: str) -> str | None:
    """The name the star's page takes in ``lang`` when it differs from the
    global one: a label that repeats the English one, or a catalogue number,
    leaves the global name in place."""
    if entity is None or lang == "en":
        return None
    labels = entity["labels"]
    name = usable_name(labels.get(lang))
    return name if name and name != (labels.get("en") or labels.get("mul")) else None


# Gliese numbers go by `GJ`, `Gl` or `Gliese`.
_GLIESE = re.compile(r"^(gliese|gl)(?=\d)")


def _same_designation(name: str) -> str:
    return _GLIESE.sub("gj", designation_key(name))


def _planet_page_name(
    entity: WikidataEntity | None, lang: str, planet: PlanetObject
) -> str | None:
    """The name the planet's page takes in ``lang``, as a star's would, but
    only a name that ends in the planet's letter and is not one of its
    designations spelled another way ("Kepler-34b"). Another label names its
    star ("Lalande 21185" for GJ 411 b) or is a nickname. A planet with an IAU
    name keeps it: the labels in most languages are its designation."""
    if planet.iau_named or not planet.letter:
        return None
    name = _page_name(entity, lang)
    if name is None or not name.rstrip().endswith(planet.letter):
        return None
    own = {_same_designation(n) for n in (planet.name, *planet.designations)}
    return None if _same_designation(name) in own else name


def _restates_spectral_class(qid: str, entities: WikidataEntityCache) -> bool:
    if qid in SPECTRAL_CLASSES:
        return True
    entity = entities.get_referenced(qid)
    if entity is None:
        return False
    parents = {
        value["id"]
        for statement in active_statements(entity["claims"], "P279")
        if isinstance(
            value := statement["mainsnak"].get("datavalue", {}).get("value"), dict
        )
    }
    return not parents.isdisjoint(SPECTRAL_CLASSES)


def _ref(
    qid: str, lang: str, entities: WikidataEntityCache, pages: Mapping[str, _Page]
) -> dict | None:
    """The entity reference to ``qid``. A star with an entry links to its page,
    under the name that page takes."""
    page = pages.get(qid)
    if page is None:
        ref = resolve_entity_ref(qid, lang, entities)
        return ref.to_dict() if ref else None
    return make_body_entityref(page.obj_id, page.names.get(lang) or page.name).to_dict()


def _claims(qid: str, entity: WikidataEntity, entities: WikidataEntityCache) -> dict:
    claims = extract_claims(
        entity["claims"],
        qid,
        entities,
        global_claims=STAR_GLOBAL_CLAIMS,
        entity_ref_claims=STAR_ENTITY_REF_CLAIMS,
        route_temperature=False,
    )
    types = [
        qid
        for qid in claims.pop("instance_of", ())
        if not _restates_spectral_class(qid, entities)
    ]
    if types:
        claims["instance_of"] = types
    return claims


def _aliases(names: list[str]) -> list[str]:
    """The aliases without SIMBAD's prefixes, each once."""
    return list(dict.fromkeys(_SIMBAD_PREFIX.sub("", name) for name in names))


def _read(
    qid: str,
    entity: WikidataEntity | None,
    sitelinks: int | None,
    entities: WikidataEntityCache,
) -> _Read:
    if entity is None:
        return _Read({}, {}, {}, sitelinks)
    return _Read(
        _claims(qid, entity, entities),
        {
            lang: text
            for lang in LANGUAGES
            if (text := entity["descriptions"].get(lang))
        },
        {
            lang: _aliases(names)
            for lang in LANGUAGES
            if (names := entity["aliases"].get(lang))
        },
        sitelinks,
    )


def _localized(
    qid: str,
    read: _Read,
    summary: WikipediaSummary | None,
    lang: str,
    entities: WikidataEntityCache,
    pages: Mapping[str, _Page],
    page: _Page,
) -> dict:
    data: dict = {}
    if name := page.names.get(lang):
        data["name"] = name
    if desc := read.descriptions.get(lang):
        data["description"] = desc
    if aliases := read.aliases.get(lang):
        data["aliases"] = aliases
    claims = read.claims
    for claim in STAR_ENTITY_REF_CLAIMS:
        value = claims.get(claim.key)
        if value is None:
            continue
        qids = value if claim.multiple else [value]
        refs = [
            ref
            for other in qids
            if other != qid and (ref := _ref(other, lang, entities, pages))
        ]
        if refs:
            data[claim.key] = refs if claim.multiple else refs[0]
    if summary:
        data["wikipedia"] = summary.to_dict()
    return data


def star_references(star: StarObject) -> dict[str, list[dict]]:
    """The works that the literature table cites for the values of the star,
    by column group."""
    distance = DISTANCES.get(star.literature) if star.literature else None
    if distance is None:
        return {}
    return {"distance": [REFERENCES[distance.reference]._asdict()]}


def has_description(localized: dict | None) -> bool:
    """Whether a localized entry has a Wikipedia extract."""
    return bool(((localized or {}).get("wikipedia") or {}).get("extract"))


def _global(
    obj_id: str,
    name: str,
    object_type: str,
    qid: str | None,
    read: _Read,
    references: dict[str, list[dict]] | None = None,
) -> dict:
    data: dict = {"id": obj_id, "type": object_type, "name": name}
    if qid:
        data["cross_refs"] = {"wikidata_qid": qid}
    if read.sitelinks:
        data["sitelinks_count"] = read.sitelinks
    if qid and (images := collect_star_images(qid)):
        data["images"] = images
    claims = read.claims
    wikidata = {c.key: claims[c.key] for c in STAR_GLOBAL_CLAIMS if c.key in claims}
    if wikidata:
        data["wikidata"] = wikidata
    if references:
        data["references"] = references
    return data


def _log_entries(
    kind: str,
    ids: Sequence[str],
    global_data: Mapping[str, dict],
    localized: Mapping[str, Mapping[str, dict]],
) -> None:
    entries = [global_data[obj_id] for obj_id in ids]
    logger.info(
        "%s entries: %d, with images: %d, with references: %d, described: %d,"
        " localized: %s",
        kind,
        len(entries),
        sum("images" in entry for entry in entries),
        sum("references" in entry for entry in entries),
        sum(has_description(localized[BASE_LOCALE].get(obj_id)) for obj_id in ids),
        ", ".join(
            f"{lang}={sum(obj_id in localized[lang] for obj_id in ids)}"
            for lang in LANGUAGES
        ),
    )


def star_entries(
    stars: Sequence[StarObject],
    entities: WikidataEntityCache,
    planets: Sequence[PlanetObject] = (),
) -> tuple[dict[str, dict], dict[str, dict[str, dict]]]:
    """The global entries and the localized ones by language, of the stars
    and the planets."""
    # References to an object with an entry link to its page, so every page is
    # known before the first entry. A star's page takes the references to an
    # item that a star and a planet both hold.
    # Keyed by QID.
    pages: dict[str, _Page] = {}
    # Keyed by entry id.
    own_pages: dict[str, _Page] = {}
    reads: dict[str, _Read] = {}
    global_data: dict[str, dict] = {}
    missing = 0

    def read(obj_id: str, qid: str, name: str, planet: PlanetObject | None) -> None:
        nonlocal missing
        found = entities.get_star_entity(qid)
        entity = found.entity if found else None
        missing += entity is None
        names = {
            lang: page_name
            for lang in LANGUAGES
            if (
                page_name := _planet_page_name(entity, lang, planet)
                if planet
                else _page_name(entity, lang)
            )
        }
        page = _Page(obj_id, name, names)
        own_pages[obj_id] = page
        pages.setdefault(qid, page)
        reads[obj_id] = _read(qid, entity, found.sitelinks if found else None, entities)

    for star in stars:
        obj_id = f"{PREFIX}{star.id}"
        if star.qid is None:
            reads[obj_id] = _Read({}, {}, {}, None)
        else:
            read(obj_id, star.qid, star.name, None)
        global_data[obj_id] = _global(
            obj_id, star.name, TYPE, star.qid, reads[obj_id], star_references(star)
        )
    shared = sum(planet.qid in pages for planet in planets)
    for planet in planets:
        read(planet.obj_id, planet.qid, planet.name, planet)
        global_data[planet.obj_id] = _global(
            planet.obj_id, planet.name, PLANET_TYPE, planet.qid, reads[planet.obj_id]
        )
    if missing:
        logger.warning("%d star and planet items have no downloaded entity", missing)
    if shared:
        logger.info("%d planet items are star items too", shared)

    localized: dict[str, dict[str, dict]] = {lang: {} for lang in LANGUAGES}
    qids = [(f"{PREFIX}{star.id}", star.qid) for star in stars if star.qid] + [
        (planet.obj_id, planet.qid) for planet in planets
    ]
    for obj_id, qid in qids:
        summaries = load_wikipedia_summaries_for_qid(qid)
        for lang in LANGUAGES:
            block = _localized(
                qid,
                reads[obj_id],
                summaries.get(lang),
                lang,
                entities,
                pages,
                own_pages[obj_id],
            )
            if block:
                localized[lang][obj_id] = block
    _log_entries(
        "Star", [f"{PREFIX}{star.id}" for star in stars], global_data, localized
    )
    if planets:
        _log_entries(
            "Planet", [planet.obj_id for planet in planets], global_data, localized
        )
    return global_data, localized


def inject_star_objects(
    data: ChunkObjectData,
    entities: WikidataEntityCache,
    stars: Sequence[StarObject],
    planets: Sequence[PlanetObject],
) -> None:
    """Fold the entries of ``stars`` and ``planets`` into the object-bundle
    accumulators."""
    global_data, localized = star_entries(stars, entities, planets)
    data.global_data.update(global_data)
    for lang, entries in localized.items():
        data.localized_data[lang].update(entries)


def replace_bundle_entries(
    directory: Path, n_buckets: int, prefix: str, entries: Mapping[str, dict]
) -> int:
    """Make the entries whose id starts with ``prefix`` in the hashed bundles of
    ``directory`` exactly ``entries``. Returns how many bundle files changed."""
    if entries and not n_buckets:
        raise ValueError(f"{directory} has no bundles to hold {len(entries)} entries")
    by_bucket: dict[int, dict[str, dict]] = defaultdict(dict)
    for obj_id, entry in entries.items():
        by_bucket[hash_bucket(obj_id, n_buckets)][obj_id] = entry
    rewritten = 0
    for bucket in range(n_buckets):
        path = directory / f"{bucket}.json.gz"
        bundle = (
            orjson.loads(gzip.decompress(path.read_bytes())) if path.exists() else {}
        )
        new = {
            key: value for key, value in bundle.items() if not key.startswith(prefix)
        }
        new.update(by_bucket.get(bucket, {}))
        if new != bundle:
            write_atomic(path, gzip.compress(orjson.dumps(new), mtime=0))
            rewritten += 1
    return rewritten


def export_star_objects_only(out_dir: Path = EXPORT_DIR / "v1") -> None:
    """`space-map-export --only star-objects`: the star and planet entries of
    the object bundles, in place. The other entries and the bucket counts
    stay."""
    stars, planets = read_extrasolar_objects()
    global_data, localized = star_entries(stars, WikidataEntityCache(), planets)
    counts = orjson.loads((out_dir / "metadata.json").read_bytes())["object_bundles"]
    tiers: Mapping[str, Mapping[str, dict]] = {"global": global_data, **localized}
    changed: dict[str, int] = defaultdict(int)
    for tier, entries in tiers.items():
        directory = out_dir / "objects" / ("__global__" if tier == "global" else tier)
        changed[tier] = replace_bundle_entries(directory, counts[tier], PREFIX, entries)
    if any(changed.values()):
        refresh_versions(out_dir, "objects")
    logger.info("Star and planet entries rewrote bundle files: %s", dict(changed))
