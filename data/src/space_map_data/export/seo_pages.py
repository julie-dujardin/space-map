"""SEO page records, in ``v1/seo/pages.json.gz``: one per page of the sitemap
other than the planets and their hosts.

A record holds what the SSR meta of its page reads from the bundles
(``frontend/src/lib/seo/meta.ts``), in every language, with the credit of its
card image. The site's build writes each record into its own static assets
(``frontend/scripts/seo-pages.mjs``): the Worker then reads a file of a few KB
where the bundles are buckets of a few MB, which cost most of its CPU time.
A page with no record still reads the bundles.
"""

import gzip
import logging
from collections.abc import Collection, Iterator
from pathlib import Path

import orjson
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from space_map_data.export.nomenclature.writer import feature_bucket_key, feature_label
from space_map_data.export.objects.stars import available_star_objects
from space_map_data.export.sitemap import (
    SitemapPages,
    available_planet_pages,
    bundle_entries,
    write_sitemap,
)
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.models.feature import Feature
from space_map_data.utils.paths import EXPORT_DIR

logger = logging.getLogger(__name__)

# The fields meta.ts reads, as its `Seo*` types name them: a tuple keeps those
# fields of a sub-object, or of each element of a list; None keeps the value.
type Spec = dict[str, tuple[str, ...] | None]

_OBJECT_GLOBAL: Spec = {
    "name": None,
    "type": None,
    "parent_name": None,
    "discovery_year": None,
    "sbdb": ("class", "first_obs", "diameter", "H", "spec_B", "spec_T"),
    "wikidata": ("discovery_date", "launch_date"),
    "celestrak": ("object_type", "launch_date", "orbit_center"),
    "part_of_mission": ("name",),
    "mission": ("name",),
}
_OBJECT_LOCALIZED: Spec = {"name": None, "description": None, "discoverers": ("name",)}
_GROUP_LOCALIZED: Spec = {"name": None, "description": None}
_FEATURE_GLOBAL: Spec = {"origin": None}
_FEATURE_LOCALIZED: Spec = {"description": None}

_IMAGE_FIELDS = ("file", "kind", "attr", "variants")
_CARD_KINDS = ("photo", "logo")
_CARD_TIERS = ("free", "credit")


def _pick(value: dict, fields: tuple[str, ...]) -> dict:
    return {field: value[field] for field in fields if field in value}


def _project(entry: dict, spec: Spec) -> dict:
    out: dict = {}
    for key, fields in spec.items():
        value = entry.get(key)
        if value is None:
            continue
        if fields is not None:
            value = (
                [_pick(item, fields) for item in value]
                if isinstance(value, list)
                else _pick(value, fields)
            )
        # A sub-object with none of the fields says nothing.
        if value != {}:
            out[key] = value
    return out


def _card_images(images: list[dict] | None) -> list[dict]:
    """The images ``pickOgImage`` can choose: the first of each kind and tier,
    in their order, which leaves its choice unchanged."""
    seen: set[tuple] = set()
    out: list[dict] = []
    for image in images or ():
        key = (image.get("kind"), image.get("attr"))
        if key[0] in _CARD_KINDS and key[1] in _CARD_TIERS and key not in seen:
            seen.add(key)
            out.append(_pick(image, _IMAGE_FIELDS))
    return out


def _hero(entry: dict) -> dict | None:
    """Mirror of ``heroImage``: the group's first picture, else its first
    gallery's."""
    galleries = entry.get("galleries") or [{}]
    images = entry.get("images") or galleries[0].get("images") or []
    return images[0] if images else None


def _with_images(projected: dict, images: list[dict]) -> dict:
    return {**projected, "images": images} if images else projected


class _Credits:
    """Credit metadata of ``credit`` images, as their variants embed it. The
    Worker would otherwise fetch an image to read it."""

    def __init__(self, out_dir: Path) -> None:
        self._images_dir = out_dir / "images"
        self._cache: dict[str, dict | None] = {}

    def _read(self, file: str) -> dict | None:
        if file not in self._cache:
            path = self._images_dir / file / "metadata.json.gz"
            credit: dict = {}
            if path.exists():
                meta = orjson.loads(gzip.decompress(path.read_bytes()))
                if meta.get("license"):
                    credit["license"] = _pick(meta["license"], ("name",))
                if meta.get("artist"):
                    credit["artist"] = meta["artist"]
            self._cache[file] = credit or None
        return self._cache[file]

    def of(self, images: list[dict]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for image in images:
            if image.get("attr") == "credit" and (credit := self._read(image["file"])):
                out[image["file"]] = credit
        return out


def _localized(
    bundle_root: Path,
    buckets: dict[str, int],
    langs: Collection[str],
    keys: Collection[str],
    spec: Spec,
) -> dict[str, dict[str, dict]]:
    """The projected localized entries of *keys*, by language then key."""
    return {
        lang: {
            key: _project(entry, spec)
            for key, entry in bundle_entries(
                bundle_root / lang, buckets.get(lang, 0), keys
            ).items()
        }
        for lang in langs
    }


def _by_key(localized: dict[str, dict[str, dict]], key: str) -> dict[str, dict]:
    return {lang: entries[key] for lang, entries in localized.items() if key in entries}


def _object_records(
    out_dir: Path,
    ids: Collection[str],
    buckets: dict[str, int],
    langs: Collection[str],
    credits: _Credits,
) -> Iterator[tuple[str, dict]]:
    root = out_dir / "objects"
    localized = _localized(root, buckets, langs, ids, _OBJECT_LOCALIZED)
    for obj_id, entry in bundle_entries(
        root / "__global__", buckets["global"], ids
    ).items():
        images = _card_images(entry.get("images"))
        yield (
            f"o/{obj_id}",
            {
                "global": _with_images(_project(entry, _OBJECT_GLOBAL), images),
                "localized": _by_key(localized, obj_id),
                "credits": credits.of(images),
            },
        )


def _group_records(
    out_dir: Path,
    slugs: Collection[str],
    buckets: dict[str, int],
    langs: Collection[str],
    credits: _Credits,
) -> Iterator[tuple[str, dict]]:
    root = out_dir / "groups"
    localized = _localized(root, buckets, langs, slugs, _GROUP_LOCALIZED)
    entries = bundle_entries(root / "__global__", buckets["global"], slugs)
    for slug in slugs:
        entry = entries.get(slug)
        hero = _hero(entry) if entry is not None else None
        images = [_pick(hero, _IMAGE_FIELDS)] if hero else []
        yield (
            f"g/{slug}",
            {
                "global": None if entry is None else _with_images({}, images),
                "localized": _by_key(localized, slug),
                "credits": credits.of(images),
            },
        )


def _feature_records(
    out_dir: Path,
    features: Collection[Feature],
    buckets: dict[str, int],
    langs: Collection[str],
    credits: _Credits,
    wikidata_entities: WikidataEntityCache,
) -> Iterator[tuple[str, dict]]:
    root = out_dir / "nomenclature" / "details"
    by_key: dict[str, Feature] = {}
    for feature in features:
        assert feature.object_id is not None
        by_key[feature_bucket_key(feature.object_id, feature.feature_id)] = feature
    localized = _localized(root, buckets, langs, by_key, _FEATURE_LOCALIZED)
    entries = bundle_entries(root / "__global__", buckets["global"], by_key)
    for key, feature in by_key.items():
        entry = entries.get(key)
        images = _card_images(entry.get("images")) if entry else []
        yield (
            f"f/{feature.object_id}/{feature.feature_id}",
            {
                "global": None
                if entry is None
                else _with_images(_project(entry, _FEATURE_GLOBAL), images),
                "localized": _by_key(localized, key),
                "credits": credits.of(images),
                # The line of the gazetteer's label file, which names the page.
                "names": {
                    lang: feature_label(feature, lang, wikidata_entities)
                    for lang in langs
                },
            },
        )


def write_seo_pages(
    out_dir: Path,
    pages: SitemapPages,
    wikidata_entities: WikidataEntityCache,
    object_buckets: dict[str, int],
    feature_buckets: dict[str, int],
    group_buckets: dict[str, int],
) -> None:
    """Write ``v1/seo/pages.json.gz``, keyed by the record's asset path:
    ``o/<object id>``, ``g/<slug>``, ``f/<body id>/<feature id>``.

    Reads the bundles already in ``out_dir``; the bucket counts are those of
    ``metadata.json``.
    """
    langs = [lang for lang in object_buckets if lang != "global"]
    credits = _Credits(out_dir)
    records = {
        **dict(_object_records(out_dir, pages.objects, object_buckets, langs, credits)),
        **dict(_group_records(out_dir, pages.groups, group_buckets, langs, credits)),
        **dict(
            _feature_records(
                out_dir,
                [feature for feature, _ in pages.features],
                feature_buckets,
                langs,
                credits,
                wikidata_entities,
            )
        ),
    }
    path = out_dir / "seo" / "pages.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(orjson.dumps(records)))
    logger.info(
        "SEO pages: %d records, %.1f MB written to %s",
        len(records),
        path.stat().st_size / 1e6,
        path,
    )


def export_seo_only(engine: Engine) -> None:
    """`space-map-export --only seo` — rewrites the sitemap and the page records.

    They come from the bundles, and the planet pages from the served
    extrasolar export, so a change of their rules reaches the files without
    re-running the whole export.
    """
    out_dir = EXPORT_DIR / "v1"
    metadata = orjson.loads((out_dir / "metadata.json").read_bytes())
    wikidata_entities = WikidataEntityCache()
    with Session(engine) as session:
        pages = write_sitemap(
            session,
            out_dir,
            wikidata_entities,
            metadata["object_bundles"],
            metadata["group_bundles"],
            available_star_objects(),
            available_planet_pages(),
        )
        write_seo_pages(
            out_dir,
            pages,
            wikidata_entities,
            metadata["object_bundles"],
            metadata["feature_bundles"],
            metadata["group_bundles"],
        )
