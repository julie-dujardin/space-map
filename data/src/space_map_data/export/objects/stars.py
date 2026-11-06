"""Object entries of the extrasolar objects with a Wikidata item or a value
from a paper: stars and star systems, and planets with an item.

They live in the object bundles, under `x-<id>` like the `/x/<id>` pages and
`x-<host>-b-<n>` like the `/x/<host>/b/<n>` ones, so these pages read their
text as a body page does. They hold metadata only: names, descriptions,
references and discovery dates from Wikidata, Wikipedia extracts, Commons
images, and the works that the literature table cites for a value. A planet
with a map also has its texture keys (`TextureLayers.entry_blocks`). The
record tiles and the planet files of the extrasolar export hold the values,
under their own terms.

The registry's Metadata rows say which stars and systems have an entry
(`object`), and give their English name, class, QID and literature key. A
node of a star system, a resolved system or a point that holds several stars,
takes its class as its type, as a planet host does in search. A planet has an
entry when its planets table row has a Wikidata QID among its cross ids.
"""

import gzip
import logging
import re
import unicodedata
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import orjson
import pyarrow.parquet as pq

from space_map_data.constants.providers import BASE_LOCALE, LANGUAGES
from space_map_data.constants.stars.literature import (
    DISTANCES,
    RADII,
    REFERENCES,
    StarKey,
)
from space_map_data.export.extrasolar.planets import read_planets
from space_map_data.export.images import collect_star_images
from space_map_data.export.in_place import refresh_versions
from space_map_data.export.names import (
    CataloguePlanet,
    Names,
    PlanetHost,
    is_latin,
    page_aliases,
    planet_names,
    repeated_letters,
    same_designation,
    star_label,
    star_names,
    unlisted_host,
)
from space_map_data.export.objects.wikidata_claims import (
    STAR_ENTITY_REF_CLAIMS,
    STAR_GLOBAL_CLAIMS,
    attach_sky_constellation_group_link,
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
from space_map_data.export.systems import TextureLayers
from space_map_data.export.wikidata import (
    WikidataEntity,
    WikidataEntityCache,
    active_statements,
)
from space_map_data.extrasolar.exoplanets.wikidata import planet_qid
from space_map_data.extrasolar.registry import NoRegistry, Registry
from space_map_data.extrasolar.sources.literature import LITERATURE, key_of
from space_map_data.extrasolar.sources.names import IAU_WGSN
from space_map_data.extrasolar.sources.wikidata import WIKIDATA
from space_map_data.extrasolar.systems.assemble import NODE_CLASSES
from space_map_data.extrasolar.tables import METADATA
from space_map_data.utils.paths import EXPORT_DIR, EXTRASOLAR_DIR, REGISTRY_ROOT

logger = logging.getLogger(__name__)

PREFIX = "x-"
TYPE = "star"
PLANET_TYPE = "exoplanet"
# The type of the entry of a star system node, by its class.
SYSTEM_TYPES = {cls: cls.replace(" ", "_") for cls in NODE_CLASSES}
# The id of a planet's entry, as its scene id, with its host's page id and ID.
PLANET_ID = re.compile(r"^(?P<host_id>x-(?P<host>\d+))-b-\d+$")
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


def planet_id(host: int, number: int) -> str:
    """The page id of planet ``number`` of ``host`` (`PLANET_ID`)."""
    return f"{PREFIX}{host}-b-{number}"


@dataclass(frozen=True)
class StarObject:
    id: int
    name: str
    # None for a star with no Wikidata item.
    qid: str | None = None
    # The key of the star in the literature table.
    literature: StarKey | None = None
    # The entry's type: a star, or the class of a node of a star system.
    object_type: str = TYPE
    # True when its name is the IAU proper name.
    iau_named: bool = False

    @property
    def obj_id(self) -> str:
        return f"{PREFIX}{self.id}"


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
    # True when a catalogue calls it unconfirmed.
    controversial: bool = False
    # True when another planet of its host, with an entry or without one, has
    # its letter.
    letter_repeated: bool = False
    # The Metadata name of its host in the served files, which names the
    # host's page when the host has no entry, and whether it is an IAU name.
    host_name: str | None = None
    host_iau_named: bool = False

    @property
    def obj_id(self) -> str:
        return planet_id(self.host, self.number)

    @property
    def host_id(self) -> str:
        return f"{PREFIX}{self.host}"


class _Page(NamedTuple):
    """The page of a star or a planet: its entry id and its names."""

    obj_id: str
    names: Names


class _Read(NamedTuple):
    """What the entries of a star keep of its entity."""

    claims: dict
    descriptions: dict[str, str]
    aliases: dict[str, list[str]]
    sitelinks: int | None


def _read_part(path: Path) -> list[StarObject]:
    rows = pq.read_table(
        path,
        columns=["id", "name", "name_source", "class", "cross_ids"],
        filters=[("object", "=", True)],
    )
    out = []
    for id_, name, name_source, cls, cross_ids in zip(
        rows["id"].to_pylist(),
        rows["name"].to_pylist(),
        rows["name_source"].to_pylist(),
        rows["class"].to_pylist(),
        rows["cross_ids"].to_pylist(),
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
                SYSTEM_TYPES.get(cls, TYPE),
                name_source == IAU_WGSN.name,
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
        "status",
    ]
    rows = table.select(columns).to_pylist()
    repeated = repeated_letters(rows)
    return [planet for row in rows if (planet := planet_object(row, repeated))]


def planet_object(
    row: Mapping, repeated: Collection[tuple[int, str]]
) -> PlanetObject | None:
    """The entry of a planets table row, None without an item. ``repeated`` is
    the `repeated_letters` of the whole table."""
    qid = planet_qid(row["cross_ids"])
    if qid is None:
        return None
    names = (row["designation"], *(row["aliases"] or ()))
    catalogue = CataloguePlanet.of(row, repeated)
    return PlanetObject(
        row["host"],
        row["number"],
        catalogue.name,
        qid,
        tuple(dict.fromkeys(n for n in names if n)),
        catalogue.letter,
        catalogue.iau_named,
        catalogue.controversial,
        catalogue.letter_repeated,
    )


def _star_entity(
    entities: WikidataEntityCache, qid: str | None
) -> WikidataEntity | None:
    found = entities.get_star_entity(qid)
    return found.entity if found else None


def planet_host_pages(
    registry: Registry, entities: WikidataEntityCache
) -> dict[int, Names]:
    """The names of the stars with an entry that host a planet or key a
    planet system, by ID, for the planet files of the extrasolar export."""
    table = read_planets(registry)
    if table is None:
        return {}
    keys = set(table["host"].to_pylist()) | set(table["system"].to_pylist())
    return {
        star.id: star_names(star, _star_entity(entities, star.qid))
        for star in _star_objects(registry)
        if star.id in keys
    }


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


def _name_keys(names: Iterable[str]) -> set[str]:
    """How names compare: as written without case, accents, spaces or
    punctuation ("Kererū", "Kereru"; "MOA-2011-BLG-322LB", "MOA-2011-BLG-322L
    b"), and, in Latin script, as designations ("BD−10°3166 b", "BD-10 3166
    b"). A designation keeps only Latin letters and digits, so in another
    script it is a fragment: "كليبر 102 بي" (Kepler-102 b) would be "102", as
    its star is."""
    keys = set()
    for name in names:
        folded = unicodedata.normalize("NFKD", name.casefold()).replace("æ", "ae")
        keys.add("".join(c for c in folded if c.isalnum()))
        if is_latin(name) and (key := same_designation(name).casefold()):
            keys.add(key)
    return keys


def _planet_nickname(
    entity: WikidataEntity | None,
    lang: str,
    planet: PlanetObject,
    star_names: set[str],
    page: Names,
) -> str | None:
    """A label in ``lang`` that is neither a name of the planet's page, one of
    its designations nor a name of its star: a nickname ("Osiris") or a name
    in another script, which the entry keeps as an alias. A label never names
    the page (`names.planet_names`)."""
    name = star_label(entity, lang)
    if name is None:
        return None
    own = (planet.name, *planet.designations, page.name, *page.langs.values())
    # A designation without the planet's letter names its star: "TrES-2".
    star = [
        n[: -len(planet.letter)]
        for n in own
        if planet.letter and n.endswith(planet.letter)
    ]
    others = star_names | _name_keys(own) | _name_keys(star)
    return None if _name_keys([name]) & others else name


def _star_names(name: str, entity: WikidataEntity | None) -> set[str]:
    """The names of a star in every language, as they compare."""
    names = [name]
    if entity is not None:
        names += entity["labels"].values()
        names += (n for aliases in entity["aliases"].values() for n in aliases)
    return _name_keys(n for n in names if n)


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
    qid: str,
    lang: str,
    entities: WikidataEntityCache,
    pages: Mapping[str, _Page],
    homes: Mapping[str, dict],
) -> dict | None:
    """The entity reference to ``qid``. A star with an entry links to its page,
    under the name that page takes."""
    page = pages.get(qid)
    if page is None:
        ref = resolve_entity_ref(qid, lang, entities)
        if ref is None:
            return None
        attach_sky_constellation_group_link(ref, qid, lang, homes)
        return ref.to_dict()
    return make_body_entityref(page.obj_id, page.names.get(lang)).to_dict()


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


def _read(
    qid: str,
    entity: WikidataEntity | None,
    sitelinks: int | None,
    entities: WikidataEntityCache,
    names: Names,
    nicknames: Mapping[str, str] = {},
) -> _Read:
    """What the entries keep of ``entity``. The aliases in each language are
    the names that the page's name replaces, the nickname, then the Wikidata
    aliases without SIMBAD's prefixes."""
    if entity is None:
        return _Read({}, {}, {}, sitelinks)
    aliases = {
        lang: page_aliases(
            names,
            lang,
            [
                *([nickname] if (nickname := nicknames.get(lang)) else ()),
                *(_SIMBAD_PREFIX.sub("", a) for a in entity["aliases"].get(lang, ())),
            ],
        )
        for lang in LANGUAGES
    }
    return _Read(
        _claims(qid, entity, entities),
        {
            lang: text
            for lang in LANGUAGES
            if (text := entity["descriptions"].get(lang))
        },
        {lang: found for lang, found in aliases.items() if found},
        sitelinks,
    )


def _localized(
    qid: str,
    read: _Read,
    summary: WikipediaSummary | None,
    lang: str,
    entities: WikidataEntityCache,
    pages: Mapping[str, _Page],
    homes: Mapping[str, dict],
    page: _Page,
) -> dict:
    data: dict = {}
    # The app falls back to the global name, which is the `name` of the
    # Metadata row of a star and of the system file record of a planet.
    if (name := page.names.get(lang)) != page.names.name:
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
            if other != qid and (ref := _ref(other, lang, entities, pages, homes))
        ]
        if refs:
            data[claim.key] = refs if claim.multiple else refs[0]
    if summary:
        data["wikipedia"] = summary.to_dict()
    return data


def star_references(star: StarObject) -> dict[str, list[dict]]:
    """The works that the literature table cites for the values of the star,
    by column group."""
    if star.literature is None:
        return {}
    cited = {"distance": DISTANCES.get(star.literature)}
    cited["paper_radius"] = RADII.get(star.literature)
    return {
        group: [REFERENCES[value.reference]._asdict()]
        for group, value in cited.items()
        if value is not None
    }


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
    homes: Mapping[str, dict] | None = None,
    textures: TextureLayers | None = None,
) -> tuple[dict[str, dict], dict[str, dict[str, dict]]]:
    """The global entries and the localized ones by language, of the stars
    and the planets. `homes` gives the page of a constellation that a star
    lies in, by group slug, and `textures` the maps of the planets."""
    # References to an object with an entry link to its page, so every page is
    # known before the first entry. A star's page takes the references to an
    # item that a star and a planet both hold.
    homes = homes or {}
    # Keyed by QID.
    pages: dict[str, _Page] = {}
    # Keyed by entry id.
    own_pages: dict[str, _Page] = {}
    reads: dict[str, _Read] = {}
    global_data: dict[str, dict] = {}
    missing = 0

    # Keyed by entry id.
    name_keys: dict[str, set[str]] = {}
    star_pages: dict[str, PlanetHost] = {}

    def read(obj_id: str, qid: str, record: StarObject | PlanetObject) -> None:
        nonlocal missing
        found = entities.get_star_entity(qid)
        entity = found.entity if found else None
        missing += entity is None
        nicknames = {}
        if isinstance(record, StarObject):
            names = star_names(record, entity)
            name_keys[obj_id] = _star_names(record.name, entity)
            star_pages[obj_id] = PlanetHost(names, record.iau_named)
        else:
            names = planet_names(
                record, star_pages.get(record.host_id) or unlisted_host(record)
            )
            host = name_keys.get(record.host_id, set())
            nicknames = {
                lang: nickname
                for lang in LANGUAGES
                if (nickname := _planet_nickname(entity, lang, record, host, names))
            }
        page = _Page(obj_id, names)
        own_pages[obj_id] = page
        pages.setdefault(qid, page)
        reads[obj_id] = _read(
            qid,
            entity,
            found.sitelinks if found else None,
            entities,
            names,
            nicknames,
        )

    for star in stars:
        obj_id = f"{PREFIX}{star.id}"
        if star.qid is None:
            reads[obj_id] = _Read({}, {}, {}, None)
            name_keys[obj_id] = _star_names(star.name, None)
            star_pages[obj_id] = PlanetHost(star_names(star, None), star.iau_named)
        else:
            read(obj_id, star.qid, star)
        global_data[obj_id] = _global(
            obj_id,
            star.name,
            star.object_type,
            star.qid,
            reads[obj_id],
            star_references(star),
        )
    shared = sum(planet.qid in pages for planet in planets)
    for planet in planets:
        read(planet.obj_id, planet.qid, planet)
        global_data[planet.obj_id] = _global(
            planet.obj_id,
            own_pages[planet.obj_id].names.name,
            PLANET_TYPE,
            planet.qid,
            reads[planet.obj_id],
        ) | (textures.entry_blocks(planet.obj_id) if textures else {})
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
                homes,
                own_pages[obj_id],
            )
            if block:
                localized[lang][obj_id] = block
    star_ids = [f"{PREFIX}{star.id}" for star in stars if star.object_type == TYPE]
    node_ids = [f"{PREFIX}{star.id}" for star in stars if star.object_type != TYPE]
    _log_entries("Star", star_ids, global_data, localized)
    if node_ids:
        _log_entries("Star system", node_ids, global_data, localized)
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
    textures: TextureLayers,
) -> None:
    """Fold the entries of ``stars`` and ``planets`` into the object-bundle
    accumulators."""
    # The group export imports this module.
    from space_map_data.export.groups.sky_pages import home_figures

    global_data, localized = star_entries(
        stars, entities, planets, home_figures(), textures
    )
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


def export_star_objects_only(
    out_dir: Path = EXPORT_DIR / "v1", extrasolar_dir: Path = EXTRASOLAR_DIR
) -> None:
    """`space-map-export --only star-objects`: the star and planet entries of
    the object bundles, in place. The other entries and the bucket counts
    stay. As in a full export, only a planet that ``extrasolar_dir`` serves
    has an entry."""
    # The sitemap imports this module.
    from space_map_data.export.groups.sky_pages import home_figures
    from space_map_data.export.sitemap import available_planet_pages

    stars, planets = read_extrasolar_objects()
    planets = available_planet_pages(extrasolar_dir).served(planets)
    global_data, localized = star_entries(
        stars,
        WikidataEntityCache(),
        planets,
        home_figures(extrasolar_dir),
        TextureLayers.load(out_dir),
    )
    counts = orjson.loads((out_dir / "metadata.json").read_bytes())["object_bundles"]
    tiers: Mapping[str, Mapping[str, dict]] = {"global": global_data, **localized}
    changed: dict[str, int] = defaultdict(int)
    for tier, entries in tiers.items():
        directory = out_dir / "objects" / ("__global__" if tier == "global" else tier)
        changed[tier] = replace_bundle_entries(directory, counts[tier], PREFIX, entries)
    if any(changed.values()):
        refresh_versions(out_dir, "objects")
    logger.info("Star and planet entries rewrote bundle files: %s", dict(changed))
