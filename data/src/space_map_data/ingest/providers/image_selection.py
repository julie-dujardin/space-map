"""Compute the per-object best Commons image and cache it to disk.

For each object that has a Wikidata QID we discover the direct image
candidates (P18 ∪ P154 ∪ Wikipedia pageimages across LANGUAGES), group them
into derivative-tree components via on-disk metadata, and pick the highest-
scoring file per tree (assessment > pageimage-frequency > globalusage —
see :mod:`space_map_data.utils.image_scoring`).

The result is cached at ``DOWNLOAD_DIR/commons/object_images.json`` keyed by
``Object.id`` (e.g. ``naif-199``). The export reads this cache instead of
re-walking sources, and the existing ``image_available`` flag is derived
from the same output.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone

import orjson
from sqlalchemy import update
from tqdm import tqdm

from space_map_data.constants.providers import LANGUAGES, PROVIDERS
from space_map_data.models.object import Object
from space_map_data.utils import image_scoring
from space_map_data.utils.commons_images import (
    canonical_filename,
    is_excluded,
    is_servable_on_disk,
    parse_upload_url,
    read_download_metadata,
    read_manual_extras,
)
from space_map_data.utils.db import get_session
from space_map_data.utils.paths import DOWNLOAD_DIR

logger = logging.getLogger(__name__)

OBJECT_IMAGES_PATH = DOWNLOAD_DIR / PROVIDERS.COMMONS / "object_images.json"

SCHEMA_VERSION = 1


def ingest() -> None:
    """Build ``object_images.json`` and update ``image_available`` accordingly."""
    session = get_session()

    objects = (
        session.query(Object.id, Object.wikidata_qid)
        .filter(Object.wikidata_qid.is_not(None))
        .all()
    )

    metadata_cache: dict[str, dict | None] = {}
    qid_cache: dict[str, list[dict]] = {}
    selections: dict[str, list[dict]] = {}

    for obj_id, qid in tqdm(objects, desc="Selecting per-object images", unit="obj"):
        selected = qid_cache.get(qid)
        if selected is None:
            selected = _select_for_qid(qid, metadata_cache)
            qid_cache[qid] = selected
        if selected:
            selections[obj_id] = selected

    _merge_manual_extras(selections)

    _write_cache(selections)
    _update_image_available_flag(session, set(selections))
    logger.info(
        "Wrote %s with images for %d / %d QID-linked objects",
        OBJECT_IMAGES_PATH.name,
        len(selections),
        len(objects),
    )


def _select_for_qid(qid: str, metadata_cache: dict[str, dict | None]) -> list[dict]:
    """Pick the best-of-tree image list for one QID."""
    direct, kind_of, pageimage_count = _collect_candidates(qid)
    if not direct:
        return []

    discovery_order = {name: i for i, name in enumerate(direct)}
    metadata_by_filename = _MetadataView(metadata_cache)

    components = image_scoring.tree_components(direct, metadata_by_filename)
    seen: set[str] = set()
    out: list[dict] = []
    for component in components:
        if not component:
            continue
        # ``best_in_tree`` walks the full tree from every candidate in the
        # component, so a tree-only file (not in the direct list) can win
        # on a stronger assessment / globalusage signal.
        best = image_scoring.best_in_tree(
            component,
            metadata_by_filename,
            pageimage_count,
            discovery_order,
        )
        if best in seen:
            continue
        if not is_servable_on_disk(best):
            # Tree-only winners can be non-servable (different license);
            # fall back to scanning the direct candidates in this
            # component for a servable choice.
            best = next(
                (name for name in component if is_servable_on_disk(name)),
                None,
            )
            if best is None or best in seen:
                continue
        seen.add(best)
        out.append({"file": best, "kind": kind_of.get(best, "photo")})
    return out


def _collect_candidates(
    qid: str,
) -> tuple[list[str], dict[str, str], dict[str, int]]:
    """Return ``(direct_order, kind_of, pageimage_count)`` for a QID.

    ``direct_order`` is the deduped, ordered list of canonical filenames
    discovered as P18, then Wikipedia pageimages, then P154 (matching the
    "primary first" semantics of :func:`collect_qid_commons_filenames`).
    ``pageimage_count[name]`` counts how many language wikis picked
    ``name`` as their pageimage for this object.
    """
    wikidata_dir = DOWNLOAD_DIR / PROVIDERS.WIKIDATA / "objects"
    wiki_dir = DOWNLOAD_DIR / PROVIDERS.WIKIPEDIA

    photos_from_wikidata: list[str] = []
    logos_from_wikidata: list[str] = []
    entity_path = wikidata_dir / f"{qid}.json"
    if entity_path.exists():
        try:
            entity = orjson.loads(entity_path.read_bytes())
        except orjson.JSONDecodeError:
            entity = None
        if entity:
            claims = entity.get("claims", {})
            for stmt in claims.get("P18", []):
                if stmt.get("rank") == "deprecated":
                    continue
                v = stmt.get("mainsnak", {}).get("datavalue", {}).get("value")
                if isinstance(v, str) and v:
                    photos_from_wikidata.append(canonical_filename(v))
            for stmt in claims.get("P154", []):
                if stmt.get("rank") == "deprecated":
                    continue
                v = stmt.get("mainsnak", {}).get("datavalue", {}).get("value")
                if isinstance(v, str) and v:
                    logos_from_wikidata.append(canonical_filename(v))

    photos_from_wikipedia: list[str] = []
    pageimage_count: dict[str, int] = defaultdict(int)
    for lang in LANGUAGES:
        page_path = wiki_dir / lang / f"{qid}.json"
        if not page_path.exists():
            continue
        try:
            page = orjson.loads(page_path.read_bytes())
        except orjson.JSONDecodeError:
            continue
        if page.get("missing"):
            continue
        src = (page.get("original") or {}).get("source")
        if not src:
            continue
        parsed = parse_upload_url(src)
        if parsed is None:
            continue
        repo, filename = parsed
        if repo != "commons":
            continue
        canonical = canonical_filename(filename)
        photos_from_wikipedia.append(canonical)
        pageimage_count[canonical] += 1

    direct: list[str] = []
    seen: set[str] = set()
    kind_of: dict[str, str] = {}
    for name in photos_from_wikidata + photos_from_wikipedia:
        if name in seen or is_excluded(name):
            continue
        seen.add(name)
        kind_of[name] = "photo"
        direct.append(name)
    for name in logos_from_wikidata:
        if name in seen or is_excluded(name):
            continue
        seen.add(name)
        kind_of[name] = "logo"
        direct.append(name)

    return direct, kind_of, dict(pageimage_count)


class _MetadataView:
    """Dict-like lazy reader for ``DOWNLOAD_DIR/commons/images/<f>/metadata.json``.

    The scoring helpers only call ``.get(filename)``; routing every lookup
    through a shared cache means we touch each ``metadata.json`` at most
    once across the whole ingest run, even when the same file is referenced
    by many QIDs.
    """

    def __init__(self, cache: dict[str, dict | None]) -> None:
        self._cache = cache

    def get(self, filename: str) -> dict | None:
        if filename in self._cache:
            return self._cache[filename]
        meta = read_download_metadata(filename)
        self._cache[filename] = meta
        return meta


def _merge_manual_extras(selections: dict[str, list[dict]]) -> None:
    """Append manual-extra entries to the per-object selections in place.

    Files not yet on disk or with a non-servable license are dropped with a
    warning — the downloader is responsible for fetching them, so absence
    here means the manual entry was added without re-running download, or
    the upstream license disqualifies it.
    """
    for obj_id, entries in read_manual_extras().items():
        existing = selections.setdefault(obj_id, [])
        existing_files = {e["file"] for e in existing}
        for entry in entries:
            file = entry["file"]
            if file in existing_files:
                continue
            if not is_servable_on_disk(file):
                logger.warning(
                    "Manual-extra image %s for %s not servable (download missing "
                    "or non-servable license); skipping",
                    file,
                    obj_id,
                )
                continue
            existing.append(entry)
            existing_files.add(file)
        if not existing:
            selections.pop(obj_id, None)


def _write_cache(selections: dict[str, list[dict]]) -> None:
    OBJECT_IMAGES_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "objects": dict(sorted(selections.items())),
    }
    OBJECT_IMAGES_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def _update_image_available_flag(session, ids_with_images: set[str]) -> None:
    """Set ``Object.image_available`` based on the freshly-written cache."""
    session.query(Object).update({Object.image_available: False})
    if ids_with_images:
        session.execute(
            update(Object)
            .where(Object.id.in_(list(ids_with_images)))
            .values(image_available=True)
        )
    session.commit()


def read_object_images() -> dict[str, list[dict]]:
    """Return the cached ``{object_id: [{file, kind}, ...]}`` mapping.

    Returns an empty dict if the cache hasn't been generated yet (export
    runs before ingest; or a fresh checkout). Callers fall back to no
    images, matching the previous behaviour.
    """
    if not OBJECT_IMAGES_PATH.exists():
        return {}
    try:
        payload = orjson.loads(OBJECT_IMAGES_PATH.read_bytes())
    except orjson.JSONDecodeError:
        logger.warning("Corrupt %s; ignoring", OBJECT_IMAGES_PATH)
        return {}
    return payload.get("objects") or {}
