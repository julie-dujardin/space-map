"""Object entries of the extrasolar objects with a Wikidata item.

They live in the object bundles, under `x-<id>` like the `/x/<id>` pages, so
a star page reads its text as a body page does. They hold Wikidata and
Wikipedia text only, no catalogue values: the record tiles of the extrasolar
export hold those, under their own terms.

The registry's Metadata rows say which IDs have an entry (`object`), and give
their English name and QID.
"""

import gzip
import logging
from collections import defaultdict
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import orjson
import pyarrow.parquet as pq

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.in_place import refresh_versions
from space_map_data.export.objects.wikipedia import (
    WikipediaSummary,
    load_wikipedia_summaries_for_qid,
)
from space_map_data.export.objects.writer import ChunkObjectData, hash_bucket
from space_map_data.export.sidecar_io import write_atomic
from space_map_data.export.wikidata import WikidataEntity, WikidataEntityCache
from space_map_data.extrasolar.registry import NoRegistry, Registry
from space_map_data.extrasolar.sources.wikidata import WIKIDATA, usable_name
from space_map_data.extrasolar.tables import METADATA
from space_map_data.utils.paths import EXPORT_DIR, REGISTRY_ROOT

logger = logging.getLogger(__name__)

PREFIX = "x-"
TYPE = "star"


@dataclass(frozen=True)
class StarObject:
    id: int
    name: str
    qid: str


def _read_part(path: Path) -> list[StarObject]:
    rows = pq.read_table(
        path, columns=["id", "name", "cross_ids"], filters=[("object", "=", True)]
    )
    out = []
    for id_, name, cross_ids in zip(
        rows["id"].to_pylist(), rows["name"].to_pylist(), rows["cross_ids"].to_pylist()
    ):
        qids = [
            x["catalogue_id"] for x in cross_ids if x["catalogue"] == WIKIDATA.catalogue
        ]
        if len(qids) != 1:
            raise ValueError(f"{path}: ID {id_} has the Wikidata items {qids}")
        out.append(StarObject(id_, name, qids[0]))
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


def _localized(
    entity: WikidataEntity | None, summary: WikipediaSummary | None, lang: str
) -> dict:
    data: dict = {}
    if entity is not None:
        labels = entity["labels"]
        english = labels.get("en") or labels.get("mul")
        # A label that repeats the English one, or a catalogue number, leaves
        # the global name in place: the IAU name or our designation.
        name = usable_name(labels.get(lang))
        if lang != "en" and name and name != english:
            data["name"] = name
        if desc := entity["descriptions"].get(lang):
            data["description"] = desc
        if aliases := entity["aliases"].get(lang):
            data["aliases"] = aliases
    if summary:
        data["wikipedia"] = summary.to_dict()
    return data


def star_entries(
    stars: list[StarObject], entities: WikidataEntityCache
) -> tuple[dict[str, dict], dict[str, dict[str, dict]]]:
    """The global entries and the localized ones by language."""
    global_data: dict[str, dict] = {}
    localized: dict[str, dict[str, dict]] = {lang: {} for lang in LANGUAGES}
    missing = 0
    for star in stars:
        obj_id = f"{PREFIX}{star.id}"
        global_data[obj_id] = {
            "id": obj_id,
            "type": TYPE,
            "name": star.name,
            "cross_refs": {"wikidata_qid": star.qid},
        }
        entity = entities.get_star_entity(star.qid)
        missing += entity is None
        summaries = load_wikipedia_summaries_for_qid(star.qid)
        for lang in LANGUAGES:
            if block := _localized(entity, summaries.get(lang), lang):
                localized[lang][obj_id] = block
    if missing:
        logger.warning("%d star items have no downloaded entity", missing)
    logger.info(
        "Star entries: %d, localized: %s",
        len(global_data),
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
