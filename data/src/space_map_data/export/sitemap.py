"""Sitemap generation for the notable-object subset.

Enumerates the promoted set, anything with a real Wikidata presence, the
stars and star systems of the extrasolar catalogue whose entry in the base
locale has a Wikipedia extract, and every planet that the extrasolar export
serves, with its host. Writes the sitemap index ``v1/seo/sitemap.xml`` and its files
``sitemap-<n>.xml``. The pages other than the planets and the hosts without
an entry get the records of ``seo_pages.py``.

A page states its canonical link with the name the app gives it in the base
locale. Each path here carries that name, taken from the files the app reads,
so that no listed URL names another one as canonical. The names follow
``frontend/src/lib/state/page-name.ts`` and the paths ``page-href.ts``:
``/<type>/<id>/<name>`` for objects, ``/g/<slug>/<name>`` for groups,
``/g/culture-<key>/f/<figure>/<name>`` for a constellation in its home culture,
``/<type>/<id>/f/<featureId>/<name>`` for features, ``/x/<host>/b/<n>/<name>``
for planets.
"""

import datetime
import gzip
import logging
from collections.abc import Collection, Iterable, Mapping
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import NamedTuple
from urllib.parse import quote
from xml.sax.saxutils import escape

import orjson
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from space_map_data.constants.categories import CATEGORY_SLUG_PREFIX
from space_map_data.constants.promoted import PROMOTED_EXTRA_IDS
from space_map_data.constants.providers import BASE_LOCALE, LANGUAGES
from space_map_data.constants.stars.constellations import SKY_CONSTELLATION_SLUG_PREFIX
from space_map_data.constants.stars.cultures import SKY_CULTURE_SLUG_PREFIX
from space_map_data.export.extrasolar.reader import ExportReader
from space_map_data.export.groups.registry import CLASS_SLUG_PREFIX
from space_map_data.export.names import (
    Names,
    ObjectNames,
    feature_names,
    served_host,
)
from space_map_data.export.nomenclature.writer import renderable_feature_filter
from space_map_data.export.objects.stars import PREFIX as STAR_PREFIX
from space_map_data.export.objects.stars import (
    PlanetObject,
    StarObject,
    has_description,
    planet_id,
)
from space_map_data.export.objects.writer import hash_bucket
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.models.feature import Feature
from space_map_data.models.object import Object, ObjectType
from space_map_data.utils.paths import EXTRASOLAR_DIR, MESSAGES_DIR

logger = logging.getLogger(__name__)

SITE_ORIGIN = "https://spacemap.co"
SITELINKS_THRESHOLD = 5

# Sitemaps allow 50k URLs per file.
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
    "x": "x",
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
    """The pages of the sitemap that get a record: each subject with its
    path, and the entry ids of the planets with an entry."""

    objects: dict[str, str]
    groups: dict[str, str]
    features: list[tuple[Feature, str]]
    planets: tuple[str, ...] = ()


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
    out_dir: Path,
    object_buckets: dict[str, int],
    ids: Collection[str],
    localized: dict[str, dict],
) -> dict[str, str | None]:
    """The page name of each of *ids* that the export has. Mirror of
    ``objectPageName``: the localized name, else the catalogue's.
    *localized* has the entries of the base locale."""
    named = {
        obj_id: name
        for obj_id in ids
        if (name := (localized.get(obj_id) or {}).get("name"))
    }
    # Each exported object has a global entry.
    rest = [obj_id for obj_id in ids if obj_id not in named]
    return named | _bundle_names(
        out_dir / "objects" / "__global__", object_buckets["global"], rest
    )


def _notable_paths(
    session: Session,
    out_dir: Path,
    object_buckets: dict[str, int],
    star_ids: Collection[str],
    hosts: Collection[str] = frozenset(),
) -> dict[str, str]:
    """The canonical path of every notable object the export has, by id:
    promoted types, curated extras, a Wikidata presence at or above the
    sitelink floor, or a star or star system of the extrasolar catalogue
    (``star_ids``) with a description or with planets (``hosts``). It has a
    description when its entry in the base locale has a Wikipedia extract: a
    crawler reads a page in the base locale.

    Never a barycenter: its page takes its title from an app label.
    """
    catalogue = session.scalars(
        select(Object.id).where(
            Object.object_type != ObjectType.barycenter,
            or_(
                Object.object_type.in_(_SITEMAP_TYPES),
                Object.id.in_(PROMOTED_EXTRA_IDS),
                Object.sitelinks_count >= SITELINKS_THRESHOLD,
            ),
        )
    ).all()
    localized = bundle_entries(
        out_dir / "objects" / BASE_LOCALE,
        object_buckets[BASE_LOCALE],
        [*catalogue, *star_ids],
    )
    described = [key for key in star_ids if has_description(localized.get(key))]
    logger.info(
        "sitemap: %d of %d star entries have a description",
        len(described),
        len(star_ids),
    )
    listed = set(described) | set(hosts)
    ids = [*catalogue, *(key for key in star_ids if key in listed)]
    names = _object_names(out_dir, object_buckets, ids, localized)
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
            feature_names(feature, wikidata_entities).name,
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


def _figure_paths(
    out_dir: Path, n_buckets: int, slugs: Collection[str]
) -> dict[str, str]:
    """The page of each constellation key: its figure in its home culture. A
    key with no such figure has no page."""
    entries = bundle_entries(out_dir / "groups" / "__global__", n_buckets, slugs)
    return {
        slug: _named(
            f"/g/{SKY_CULTURE_SLUG_PREFIX}{home['culture']}/f/{home['figure']}",
            home["name"],
        )
        for slug, entry in entries.items()
        if (home := entry.get("home_figure"))
    }


def _group_paths(out_dir: Path, n_buckets: int, n_global: int = 0) -> dict[str, str]:
    """The canonical path of every exported group, by slug."""
    index = out_dir / "groups" / "__index__.json"
    if not index.exists():
        logger.warning("sitemap: %s missing; no group URLs emitted", index)
        return {}
    keys = list(orjson.loads(index.read_bytes()))
    constellations = [s for s in keys if s.startswith(SKY_CONSTELLATION_SLUG_PREFIX)]
    slugs = [s for s in keys if not s.startswith(SKY_CONSTELLATION_SLUG_PREFIX)]
    exported = _bundle_names(out_dir / "groups" / BASE_LOCALE, n_buckets, slugs)
    app_labels = orjson.loads((MESSAGES_DIR / f"{BASE_LOCALE}.json").read_bytes())
    names = {slug: _group_name(slug, exported.get(slug), app_labels) for slug in slugs}
    unnamed = [slug for slug, name in names.items() if not name]
    if unnamed:
        # The page of such a group calls itself by a name this file cannot give.
        logger.warning(
            "sitemap: %d groups have no name: %s", len(unnamed), ", ".join(unnamed)
        )
    return {
        **{slug: _named(f"/g/{slug}", name) for slug, name in names.items()},
        **_figure_paths(out_dir, n_global, constellations),
    }


def _index(files: list[str], lastmod: str) -> bytes:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for file in files:
        loc = escape(f"{SITE_ORIGIN}/{file}")
        lines.append(
            f"  <sitemap><loc>{loc}</loc><lastmod>{lastmod}</lastmod></sitemap>"
        )
    lines.append("</sitemapindex>\n")
    return "\n".join(lines).encode()


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


class PlanetPages(NamedTuple):
    """The served planets as (host, number, name), the Metadata name of each
    host, the hosts whose name is the IAU name, and the names of each host and
    planet page in the system files, by page id."""

    planets: list[tuple[int, int, str | None]]
    hosts: dict[int, str | None]
    iau_hosts: frozenset[int] = frozenset()
    served_names: Mapping[str, Names] = MappingProxyType({})

    def stale_names(
        self,
        names: ObjectNames,
        stars: Iterable[StarObject],
        planets: Iterable[PlanetObject],
    ) -> list[str]:
        """The hosts and the planets with an entry whose names in the system
        files differ from the names that ``names`` gives them now, each as
        "page id (language): served → now". A Wikidata download or a registry
        ingest after the extrasolar export makes them differ."""
        page_ids = [
            entry.obj_id
            for entry in (*stars, *planets)
            if entry.obj_id in self.served_names
        ]
        out = []
        for page_id in page_ids:
            served, now = self.served_names[page_id], names.object(page_id)
            for lang in LANGUAGES:
                if (was := served.get(lang)) != (found := now.get(lang)):
                    out.append(f"{page_id} ({lang}): {was} → {found}")
                    break
        return out

    def served(self, objects: Iterable[PlanetObject]) -> list[PlanetObject]:
        """The planets of `objects` that have a page, each with the Metadata
        name of its host, which names a planet (`names.planet_names`)."""
        pages = {(host, number) for host, number, _ in self.planets}
        return [
            replace(
                p,
                host_name=self.hosts.get(p.host),
                host_iau_named=p.host in self.iau_hosts,
            )
            for p in objects
            if (p.host, p.number) in pages
        ]


def available_planet_pages(extrasolar_dir: Path = EXTRASOLAR_DIR) -> PlanetPages:
    """Every planet of the served extrasolar export below *extrasolar_dir*, and
    the name of each host, or none with no planets served.

    The served files, not the registry: the extrasolar export refuses some
    registry changes, and the site has a page only for what it serves. An
    alias number has no page of its own.

    Raises KeyError for an export whose system files have no page names
    (`names`): the lists and the search name a planet from them, so that
    export must run again first.
    """
    root = extrasolar_dir / "v1" / "x"
    if not (root / "metadata.json").exists():
        logger.warning("No planet pages: no extrasolar export at %s", root)
        return PlanetPages([], {})
    reader = ExportReader(root)
    if "planets" not in reader.metadata:
        logger.warning("No planet pages: the extrasolar export has no planets")
        return PlanetPages([], {})
    planets: list[tuple[int, int, str | None]] = []
    hosts: dict[int, str | None] = {}
    iau_hosts: set[int] = set()
    served_names: dict[str, Names] = {}
    for key in sorted({host["system"] for host in reader.planet_index()["hosts"]}):
        system = reader.system(key)
        if not all("names" in r for r in (*system["hosts"], *system["planets"])):
            raise KeyError(
                f"planets/{key}: the served extrasolar export has no page names;"
                " run space-map-export --only extrasolar"
            )
        for host in system["hosts"]:
            if host["planets"]:
                hosts[host["id"]] = host["name"]
                page = served_host(host)
                if page is not None and page.iau_named:
                    iau_hosts.add(host["id"])
            if host["name"] is not None:
                page_id = f"{STAR_PREFIX}{host['id']}"
                served_names[page_id] = Names(host["name"], host["names"])
        for p in system["planets"]:
            planets.append((p["host"], p["number"], p["name"]))
            served_names[planet_id(p["host"], p["number"])] = Names(
                p["name"], p["names"]
            )
    return PlanetPages(
        sorted(planets, key=lambda p: p[:2]),
        dict(sorted(hosts.items())),
        frozenset(iau_hosts),
        served_names,
    )


def planet_page_names(
    hosts: Collection[int], extrasolar_dir: Path = EXTRASOLAR_DIR
) -> dict[str, Names | None]:
    """The names of the pages of the served *hosts* and of their planets, by
    page id, from their system files alone. None for a page whose file gives
    it no name."""
    root = extrasolar_dir / "v1" / "x"
    if not (root / "metadata.json").exists():
        logger.warning("No planet pages: no extrasolar export at %s", root)
        return {}
    reader = ExportReader(root)
    if "planets" not in reader.metadata:
        logger.warning("No planet pages: the extrasolar export has no planets")
        return {}
    index = reader.planet_hosts()
    out: dict[str, Names | None] = {}
    for key in sorted({index[host]["system"] for host in hosts if host in index}):
        system = reader.system(key)
        for host in system["hosts"]:
            if host["planets"]:
                out[f"{STAR_PREFIX}{host['id']}"] = _page_names(host)
        for planet in system["planets"]:
            out[planet_id(planet["host"], planet["number"])] = _page_names(planet)
    return out


def _page_names(record: dict) -> Names | None:
    if record.get("name") is None:
        return None
    return Names(record["name"], record.get("names", {}))


def _planet_paths(
    planets: PlanetPages, objects: dict[str, str], entries: dict[tuple[int, int], str]
) -> list[str]:
    """The canonical path of each planet host, then of each planet, with the
    name the app gives it: the host's entry name, else its Metadata name; the
    planet's name in ``entries`` (its entry), else its system file name. A
    host with an entry is in ``objects`` already."""
    hosts = [
        _named(f"/x/{host}", name)
        for host, name in planets.hosts.items()
        if f"{STAR_PREFIX}{host}" not in objects
    ]
    logger.info(
        "sitemap: %d planets and %d hosts without an entry",
        len(planets.planets),
        len(hosts),
    )
    return hosts + [
        _named(f"/x/{host}/b/{number}", entries.get((host, number), name))
        for host, number, name in planets.planets
    ]


def write_sitemap(
    session: Session,
    out_dir: Path,
    names: ObjectNames,
    object_buckets: dict[str, int],
    group_buckets: dict[str, int],
    stars: list[StarObject],
    planets: PlanetPages,
    planet_entries: list[PlanetObject],
) -> SitemapPages:
    """Write the sitemap index ``v1/seo/sitemap.xml`` and its files
    ``sitemap-<n>.xml``, and return the pages that get a record.

    Reads the object and group bundles and the group index already in
    ``out_dir``; the bucket counts are those of ``metadata.json``. ``stars``
    are the registry's stars and star systems with an entry, ``planets`` the
    served planet pages and ``planet_entries`` the served planets with an
    entry, each read once for the export. Of the stars and systems, only the
    ones with a description or with planets are listed. Each planet with an
    entry gets a record.
    """
    pages = SitemapPages(
        objects=_notable_paths(
            session,
            out_dir,
            object_buckets,
            [f"{STAR_PREFIX}{star.id}" for star in stars],
            {f"{STAR_PREFIX}{host}" for host in planets.hosts},
        ),
        groups=_group_paths(
            out_dir, group_buckets[BASE_LOCALE], group_buckets["global"]
        ),
        features=_feature_paths(session, names.entities),
        planets=tuple(planet.obj_id for planet in planet_entries),
    )
    paths = [
        *pages.objects.values(),
        *pages.groups.values(),
        *(path for _, path in pages.features),
        *_planet_paths(
            planets,
            pages.objects,
            {(p.host, p.number): names.planet(p).name for p in planet_entries},
        ),
    ]
    lastmod = datetime.date.today().isoformat()
    seo_dir = out_dir / "seo"
    seo_dir.mkdir(parents=True, exist_ok=True)
    for stale in seo_dir.glob("sitemap-*.xml"):
        stale.unlink()
    files: list[str] = []
    for start in range(0, len(paths), _MAX_URLS_PER_FILE):
        files.append(f"sitemap-{len(files) + 1}.xml")
        chunk = paths[start : start + _MAX_URLS_PER_FILE]
        (seo_dir / files[-1]).write_bytes(_urlset(chunk, lastmod))
    (seo_dir / "sitemap.xml").write_bytes(_index(files, lastmod))
    logger.info("Sitemap: %d URLs in %d files in %s", len(paths), len(files), seo_dir)
    return pages
