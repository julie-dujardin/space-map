"""Object entries of the extrasolar objects with a Wikidata item or a value
from a paper.

They live in the object bundles, under `x-<id>` like the `/x/<id>` pages, so
a star page reads its text as a body page does. They hold metadata only:
names, descriptions, references and discovery dates from Wikidata, Wikipedia
extracts, Commons images, and the works that the literature table cites for
a value. The record tiles of the extrasolar export hold the values, under
their own terms.

The registry's Metadata rows say which IDs have an entry (`object`), and give
their English name, QID and literature key.
"""

import gzip
import logging
from collections import defaultdict
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import orjson
import pyarrow.parquet as pq

from space_map_data.constants.providers import BASE_LOCALE, LANGUAGES
from space_map_data.constants.stars.literature import DISTANCES, REFERENCES, StarKey
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
from space_map_data.extrasolar.registry import NoRegistry, Registry
from space_map_data.extrasolar.sources.literature import LITERATURE, key_of
from space_map_data.extrasolar.sources.wikidata import WIKIDATA, usable_name
from space_map_data.extrasolar.tables import METADATA
from space_map_data.utils.paths import EXPORT_DIR, REGISTRY_ROOT

logger = logging.getLogger(__name__)

PREFIX = "x-"
TYPE = "star"

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


class _Page(NamedTuple):
    """The page of a star: its entry id, its global name and its names by
    language where they differ."""

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


def read_star_objects(root: Path = REGISTRY_ROOT) -> list[StarObject]:
    """The IDs with an entry, from the current Metadata table."""
    with Registry(root).reader() as registry:
        directory = registry.table_dir(METADATA.slug)
        paths = [] if directory is None else sorted(directory.glob("*.parquet"))
        with ThreadPoolExecutor(8) as pool:
            parts = list(pool.map(_read_part, paths))
    return [star for part in parts for star in part]


def available_star_objects(root: Path = REGISTRY_ROOT) -> list[StarObject]:
    """The IDs with an entry, or none on a host without the registry.

    Raises RegistryBusy while an ingest holds the registry, so that no export
    loses its star pages.
    """
    try:
        return read_star_objects(root)
    except NoRegistry as error:
        logger.warning("No star entries: %s", error)
        return []


def _page_name(entity: WikidataEntity | None, lang: str) -> str | None:
    """The name the star's page takes in ``lang`` when it differs from the
    global one: a label that repeats the English one, or a catalogue number,
    leaves the global name in place."""
    if entity is None or lang == "en":
        return None
    labels = entity["labels"]
    name = usable_name(labels.get(lang))
    return name if name and name != (labels.get("en") or labels.get("mul")) else None


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
        {lang: names for lang in LANGUAGES if (names := entity["aliases"].get(lang))},
        sitelinks,
    )


def _localized(
    qid: str,
    read: _Read,
    summary: WikipediaSummary | None,
    lang: str,
    entities: WikidataEntityCache,
    pages: Mapping[str, _Page],
) -> dict:
    data: dict = {}
    if name := pages[qid].names.get(lang):
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


def _global(obj_id: str, star: StarObject, read: _Read) -> dict:
    data: dict = {"id": obj_id, "type": TYPE, "name": star.name}
    if star.qid:
        data["cross_refs"] = {"wikidata_qid": star.qid}
    if read.sitelinks:
        data["sitelinks_count"] = read.sitelinks
    if star.qid and (images := collect_star_images(star.qid)):
        data["images"] = images
    claims = read.claims
    wikidata = {c.key: claims[c.key] for c in STAR_GLOBAL_CLAIMS if c.key in claims}
    if wikidata:
        data["wikidata"] = wikidata
    if references := star_references(star):
        data["references"] = references
    return data


def star_entries(
    stars: list[StarObject], entities: WikidataEntityCache
) -> tuple[dict[str, dict], dict[str, dict[str, dict]]]:
    """The global entries and the localized ones by language."""
    # References to a star with an entry link to its page, so every page is
    # known before the first entry.
    # Keyed by QID.
    pages: dict[str, _Page] = {}
    # Keyed by ID.
    reads: dict[int, _Read] = {}
    missing = 0
    for star in stars:
        if star.qid is None:
            reads[star.id] = _Read({}, {}, {}, None)
            continue
        found = entities.get_star_entity(star.qid)
        entity = found.entity if found else None
        missing += entity is None
        names = {lang: name for lang in LANGUAGES if (name := _page_name(entity, lang))}
        pages[star.qid] = _Page(f"{PREFIX}{star.id}", star.name, names)
        reads[star.id] = _read(
            star.qid, entity, found.sitelinks if found else None, entities
        )
    if missing:
        logger.warning("%d star items have no downloaded entity", missing)

    global_data: dict[str, dict] = {}
    localized: dict[str, dict[str, dict]] = {lang: {} for lang in LANGUAGES}
    for star in stars:
        obj_id = f"{PREFIX}{star.id}"
        read = reads[star.id]
        global_data[obj_id] = _global(obj_id, star, read)
        if star.qid is None:
            continue
        summaries = load_wikipedia_summaries_for_qid(star.qid)
        for lang in LANGUAGES:
            block = _localized(
                star.qid, read, summaries.get(lang), lang, entities, pages
            )
            if block:
                localized[lang][obj_id] = block
    logger.info(
        "Star entries: %d, with images: %d, with references: %d, described: %d,"
        " localized: %s",
        len(global_data),
        sum("images" in entry for entry in global_data.values()),
        sum("references" in entry for entry in global_data.values()),
        sum(has_description(entry) for entry in localized[BASE_LOCALE].values()),
        ", ".join(f"{lang}={len(localized[lang])}" for lang in LANGUAGES),
    )
    return global_data, localized


def inject_star_objects(
    data: ChunkObjectData, entities: WikidataEntityCache, stars: list[StarObject]
) -> None:
    """Fold the entries of ``stars`` into the object-bundle accumulators."""
    global_data, localized = star_entries(stars, entities)
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
    """`space-map-export --only star-objects`: the star entries of the object
    bundles, in place. The other entries and the bucket counts stay."""
    global_data, localized = star_entries(read_star_objects(), WikidataEntityCache())
    counts = orjson.loads((out_dir / "metadata.json").read_bytes())["object_bundles"]
    tiers: Mapping[str, Mapping[str, dict]] = {"global": global_data, **localized}
    changed: dict[str, int] = defaultdict(int)
    for tier, entries in tiers.items():
        directory = out_dir / "objects" / ("__global__" if tier == "global" else tier)
        changed[tier] = replace_bundle_entries(directory, counts[tier], PREFIX, entries)
    if any(changed.values()):
        refresh_versions(out_dir, "objects")
    logger.info("Star entries rewrote bundle files: %s", dict(changed))
