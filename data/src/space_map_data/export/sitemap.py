"""Sitemap generation for the notable-object subset.

Enumerates the promoted set plus anything with a real Wikidata presence, and
writes a single ``v1/seo/sitemap.xml``. The same pages get the records of
``seo_pages.py``.

A page states its canonical link with the name the app gives it in the base
locale. Each path here carries that name, taken from the files the app reads,
so that no listed URL names another one as canonical. The names follow
``frontend/src/lib/state/page-name.ts`` and the paths ``page-href.ts``:
``/<type>/<id>/<name>`` for objects, ``/g/<slug>/<name>`` for groups,
``/<type>/<id>/f/<featureId>/<name>`` for features.
"""

import datetime
import gzip
import logging
from collections.abc import Collection
from pathlib import Path
from typing import NamedTuple
from urllib.parse import quote
from xml.sax.saxutils import escape

import orjson
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from space_map_data.constants.categories import CATEGORY_SLUG_PREFIX
from space_map_data.constants.promoted import PROMOTED_EXTRA_IDS
from space_map_data.constants.providers import BASE_LOCALE
from space_map_data.export.groups.registry import CLASS_SLUG_PREFIX
from space_map_data.export.localization import MESSAGES_DIR
from space_map_data.export.nomenclature.writer import (
    feature_label,
    renderable_feature_filter,
)
from space_map_data.export.objects.writer import hash_bucket
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.models.feature import Feature
from space_map_data.models.object import Object, ObjectType

logger = logging.getLogger(__name__)

SITE_ORIGIN = "https://spacemap.co"
SITELINKS_THRESHOLD = 5

# Sitemaps allow 50k URLs per file; the notable subset is well under, so a
# single file suffices. Split into an index above this and the frontend proxy
# will need matching chunk routes.
_MAX_URLS_PER_FILE = 45_000

# Promoted types minus barycenter (a math point, not a landing page).
_SITEMAP_TYPES = (
    ObjectType.planet,
    ObjectType.dwarf_planet,
    ObjectType.moon,
    ObjectType.star,
)

# Object id prefix → URL type segment. Inverse of urlTypeToIdPrefix in view.ts.
_PREFIX_TO_TYPE = {
    "naif": "b",
    "spkid": "s",
    "norad_satcat": "e",
    "probe": "p",
    "extra": "u",
}

# encodeURIComponent's unreserved set, so Python-built name segments byte-match
# the app's links.
_URI_SAFE = "-_.!~*'()"


def _object_path(obj_id: str) -> str | None:
    """``/<type>/<id>`` for an object id, or None if the id uses an unknown
    scheme."""
    prefix, _, numeric = obj_id.partition("-")
    letter = _PREFIX_TO_TYPE.get(prefix)
    if letter is None or not numeric:
        return None
    return f"/{letter}/{numeric}"


def _named(path: str, name: str | None) -> str:
    """*path* with its name segment. A page with no name has none."""
    return f"{path}/{quote(name, safe=_URI_SAFE)}" if name else path


class SitemapPages(NamedTuple):
    """The pages the sitemap lists: each subject with its path."""

    objects: dict[str, str]
    groups: dict[str, str]
    features: list[tuple[Feature, str]]


def bundle_entries(
    bundle_dir: Path, n_buckets: int, keys: Collection[str]
) -> dict[str, dict]:
    """The entry of each of *keys* that the bundles of *bundle_dir* have.

    Finds a bucket by the hash of the key, as the app does: the directory can
    hold files of an earlier run with more buckets.
    """
    # A tier with no entry has no bucket.
    if not n_buckets:
        return {}
    by_bucket: dict[int, list[str]] = {}
    for key in keys:
        by_bucket.setdefault(hash_bucket(key, n_buckets), []).append(key)
    entries: dict[str, dict] = {}
    for bucket, bucket_keys in by_bucket.items():
        path = bundle_dir / f"{bucket}.json.gz"
        # A bucket with no entry has no file.
        if not path.exists():
            continue
        bundle = orjson.loads(gzip.decompress(path.read_bytes()))
        for key in bucket_keys:
            if key in bundle:
                entries[key] = bundle[key]
    return entries


def _bundle_names(
    bundle_dir: Path, n_buckets: int, keys: Collection[str]
) -> dict[str, str | None]:
    """The name of each of *keys* that the bundles of *bundle_dir* have an
    entry for; None when the entry gives no name."""
    entries = bundle_entries(bundle_dir, n_buckets, keys)
    return {key: entry.get("name") or None for key, entry in entries.items()}


def _object_names(
    out_dir: Path, object_buckets: dict[str, int], ids: Collection[str]
) -> dict[str, str | None]:
    """The page name of each of *ids* that the export has. Mirror of
    ``objectPageName``: the localized name, else the catalogue's."""
    objects = out_dir / "objects"
    localized = _bundle_names(objects / BASE_LOCALE, object_buckets[BASE_LOCALE], ids)
    named = {obj_id: name for obj_id, name in localized.items() if name}
    # Each exported object has a global entry.
    rest = [obj_id for obj_id in ids if obj_id not in named]
    return named | _bundle_names(objects / "__global__", object_buckets["global"], rest)


def _notable_paths(
    session: Session, out_dir: Path, object_buckets: dict[str, int]
) -> dict[str, str]:
    """The canonical path of every notable object the export has, by id:
    promoted types, curated extras, or a Wikidata presence at or above the
    sitelink floor.

    Never a barycenter: its page takes its title from an app label.
    """
    ids = session.scalars(
        select(Object.id).where(
            Object.object_type != ObjectType.barycenter,
            or_(
                Object.object_type.in_(_SITEMAP_TYPES),
                Object.id.in_(PROMOTED_EXTRA_IDS),
                Object.sitelinks_count >= SITELINKS_THRESHOLD,
            ),
        )
    ).all()
    names = _object_names(out_dir, object_buckets, ids)
    # The catalogue has objects the export leaves out; they have no page.
    if len(names) < len(ids):
        logger.info(
            "sitemap: skipped %d objects that are not in the export",
            len(ids) - len(names),
        )
    paths: dict[str, str] = {}
    skipped = 0
    for obj_id, name in names.items():
        path = _object_path(obj_id)
        if path is None:
            skipped += 1
            continue
        paths[obj_id] = _named(path, name)
    if skipped:
        logger.warning("sitemap: skipped %d objects with unmapped id scheme", skipped)
    return paths


def _feature_paths(
    session: Session, wikidata_entities: WikidataEntityCache
) -> list[tuple[Feature, str]]:
    """Surface features at or above the sitelink floor, with their canonical
    paths.

    Most of the 16k gazetteer entries are anonymous craters with no description
    worth indexing; the Wikidata-backed ones clear the bar. Only a feature the
    gazetteer exports is listed: the page of another one answers 404.
    """
    features = session.scalars(
        select(Feature).where(
            Feature.wikidata_qid.isnot(None), *renderable_feature_filter()
        )
    ).all()
    paths: list[tuple[Feature, str]] = []
    skipped = 0
    for feature in features:
        wd = wikidata_entities.get_feature_entity(feature.wikidata_qid)
        if not wd or len(wd["sitelinks"]) < SITELINKS_THRESHOLD:
            continue
        assert feature.object_id is not None
        base = _object_path(feature.object_id)
        if base is None:
            skipped += 1
            continue
        path = _named(
            f"{base}/f/{feature.feature_id}",
            feature_label(feature, BASE_LOCALE, wikidata_entities),
        )
        paths.append((feature, path))
    if skipped:
        logger.warning("sitemap: skipped %d features with unmapped host id", skipped)
    logger.info(
        "sitemap: %d of %d Wikidata-backed features meet the %d-sitelink floor",
        len(paths),
        len(features),
        SITELINKS_THRESHOLD,
    )
    return paths


def _group_name(
    slug: str, exported: str | None, app_labels: dict[str, str]
) -> str | None:
    """Mirror of ``groupPageName``: the app has its own label for a category,
    and for an orbit class the export does not name."""
    if slug.startswith(CATEGORY_SLUG_PREFIX):
        stem = slug.removeprefix(CATEGORY_SLUG_PREFIX).replace("-", "_")
        return app_labels.get(f"category_name_{stem}")
    if exported is None and slug.startswith(CLASS_SLUG_PREFIX):
        return app_labels.get(f"orbit_class_{slug.removeprefix(CLASS_SLUG_PREFIX)}")
    return exported


def _group_paths(out_dir: Path, n_buckets: int) -> dict[str, str]:
    """The canonical path of every exported group, by slug."""
    index = out_dir / "groups" / "__index__.json"
    if not index.exists():
        logger.warning("sitemap: %s missing; no group URLs emitted", index)
        return {}
    slugs = list(orjson.loads(index.read_bytes()))
    exported = _bundle_names(out_dir / "groups" / BASE_LOCALE, n_buckets, slugs)
    app_labels = orjson.loads((MESSAGES_DIR / f"{BASE_LOCALE}.json").read_bytes())
    names = {slug: _group_name(slug, exported.get(slug), app_labels) for slug in slugs}
    unnamed = [slug for slug, name in names.items() if not name]
    if unnamed:
        # The page of such a group calls itself by a name this file cannot give.
        logger.warning(
            "sitemap: %d groups have no name: %s", len(unnamed), ", ".join(unnamed)
        )
    return {slug: _named(f"/g/{slug}", name) for slug, name in names.items()}


def _urlset(paths: list[str], lastmod: str) -> bytes:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for path in paths:
        loc = escape(f"{SITE_ORIGIN}{path}")
        lines.append(f"  <url><loc>{loc}</loc><lastmod>{lastmod}</lastmod></url>")
    lines.append("</urlset>\n")
    return "\n".join(lines).encode()


def write_sitemap(
    session: Session,
    out_dir: Path,
    wikidata_entities: WikidataEntityCache,
    object_buckets: dict[str, int],
    group_buckets: dict[str, int],
) -> SitemapPages:
    """Write ``v1/seo/sitemap.xml`` and return the pages it lists.

    Reads the object and group bundles and the group index already in
    ``out_dir``; the bucket counts are those of ``metadata.json``.
    """
    pages = SitemapPages(
        objects=_notable_paths(session, out_dir, object_buckets),
        groups=_group_paths(out_dir, group_buckets[BASE_LOCALE]),
        features=_feature_paths(session, wikidata_entities),
    )
    paths = [
        *pages.objects.values(),
        *pages.groups.values(),
        *(path for _, path in pages.features),
    ]
    if len(paths) > _MAX_URLS_PER_FILE:
        logger.warning(
            "sitemap: %d URLs exceeds single-file budget (%d) — add chunking",
            len(paths),
            _MAX_URLS_PER_FILE,
        )
    lastmod = datetime.date.today().isoformat()
    seo_dir = out_dir / "seo"
    seo_dir.mkdir(parents=True, exist_ok=True)
    (seo_dir / "sitemap.xml").write_bytes(_urlset(paths, lastmod))
    logger.info("Sitemap: %d URLs written to %s", len(paths), seo_dir / "sitemap.xml")
    return pages
