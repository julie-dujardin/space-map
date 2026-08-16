"""Sitemap generation for the notable-object subset.

Enumerates the promoted set plus anything with a real Wikidata presence, and
writes a single ``v1/seo/sitemap.xml``. Canonical URL shape mirrors
``frontend/src/lib/state/url.ts``: ``/<type>/<id>/<name>`` for objects,
``/g/<slug>`` for groups, ``/<type>/<id>/f/<featureId>/<name>`` for features.
"""

import datetime
import logging
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

import orjson
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from space_map_data.constants.promoted import PROMOTED_EXTRA_IDS
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

# Object id prefix → URL type segment. Inverse of urlTypeToIdPrefix in url.ts.
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


def _object_path(obj_id: str, name: str | None) -> str | None:
    """Canonical ``/<type>/<id>/<name>`` path for an object id, or None if the
    id uses an unknown scheme."""
    prefix, _, numeric = obj_id.partition("-")
    letter = _PREFIX_TO_TYPE.get(prefix)
    if letter is None or not numeric:
        return None
    path = f"/{letter}/{numeric}"
    if name:
        path += "/" + quote(name, safe=_URI_SAFE)
    return path


def _notable_paths(session: Session) -> list[str]:
    """Canonical paths for every notable object: promoted types, curated extras,
    or a Wikidata presence at or above the sitelink floor."""
    rows = session.execute(
        select(Object.id, Object.name).where(
            or_(
                Object.object_type.in_(_SITEMAP_TYPES),
                Object.id.in_(PROMOTED_EXTRA_IDS),
                Object.sitelinks_count >= SITELINKS_THRESHOLD,
            )
        )
    ).all()
    paths: list[str] = []
    skipped = 0
    for obj_id, name in rows:
        path = _object_path(obj_id, name)
        if path is None:
            skipped += 1
            continue
        paths.append(path)
    if skipped:
        logger.warning("sitemap: skipped %d objects with unmapped id scheme", skipped)
    return paths


def _feature_paths(
    session: Session, wikidata_entities: WikidataEntityCache
) -> list[str]:
    """Canonical paths for surface features at or above the sitelink floor.

    Most of the 16k gazetteer entries are anonymous craters with no description
    worth indexing; the Wikidata-backed ones clear the bar.
    """
    rows = session.execute(
        select(
            Feature.feature_id,
            Feature.object_id,
            Feature.name,
            Feature.unicode_name,
            Feature.wikidata_qid,
        ).where(Feature.wikidata_qid.isnot(None), Feature.object_id.isnot(None))
    ).all()
    paths: list[str] = []
    skipped = 0
    for feature_id, object_id, name, unicode_name, qid in rows:
        wd = wikidata_entities.get_feature_entity(qid)
        if not wd or len(wd["sitelinks"]) < SITELINKS_THRESHOLD:
            continue
        base = _object_path(object_id, None)
        if base is None:
            skipped += 1
            continue
        canonical = unicode_name or name
        paths.append(f"{base}/f/{feature_id}/{quote(canonical, safe=_URI_SAFE)}")
    if skipped:
        logger.warning("sitemap: skipped %d features with unmapped host id", skipped)
    logger.info(
        "sitemap: %d of %d Wikidata-backed features meet the %d-sitelink floor",
        len(paths),
        len(rows),
        SITELINKS_THRESHOLD,
    )
    return paths


def _group_paths(out_dir: Path) -> list[str]:
    """``/g/<slug>`` for every exported group. Slug is already descriptive, so
    no name segment."""
    index = out_dir / "groups" / "__index__.json"
    if not index.exists():
        logger.warning("sitemap: %s missing; no group URLs emitted", index)
        return []
    slugs = orjson.loads(index.read_bytes())
    return [f"/g/{slug}" for slug in slugs]


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
    session: Session, out_dir: Path, wikidata_entities: WikidataEntityCache
) -> int:
    """Write ``v1/seo/sitemap.xml`` and return the URL count.

    Reads the group index that the groups tier already wrote to ``out_dir``.
    """
    paths = (
        _notable_paths(session)
        + _group_paths(out_dir)
        + _feature_paths(session, wikidata_entities)
    )
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
    return len(paths)
