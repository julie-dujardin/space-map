"""Compute the per-object and per-feature best Commons image, cache to disk.

For each object/feature that has a Wikidata QID we discover the direct image
candidates (P18 ∪ {aux} ∪ Wikipedia pageimages across LANGUAGES — aux is P154
"logo" for objects and P242 "locator" for nomenclature features), group them
into derivative-tree components via on-disk metadata, and pick the highest-
scoring file per tree (assessment > pageimage-frequency > globalusage — see
:mod:`space_map_data.utils.image_scoring`).

The results are cached at:

* ``OBJECT_IMAGES_PATH`` keyed by ``Object.id`` (e.g. ``naif-199``). Drives
  the ``image_available`` flag on Object rows.
* ``FEATURE_IMAGES_PATH`` keyed by IAU ``Feature.feature_id`` (stringified).

Exports read these caches instead of re-walking sources.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import orjson
from sqlalchemy import update
from tqdm import tqdm

from space_map_data.models.feature import Feature
from space_map_data.models.object import Object
from space_map_data.utils import image_scoring
from space_map_data.utils.commons_images import (
    COMMONS_DIR,
    collect_qid_image_candidates,
    is_servable_on_disk,
    read_download_metadata,
    read_manual_extras,
)
from space_map_data.utils.db import get_session
from space_map_data.utils.paths import SOURCES_METADATA_DIR

logger = logging.getLogger(__name__)

OBJECT_IMAGES_PATH = COMMONS_DIR / "object_images.json"
FEATURE_IMAGES_PATH = COMMONS_DIR / "feature_images.json"

SCHEMA_VERSION = 1


def ingest() -> None:
    """Build object/feature image caches and update ``image_available``."""
    session = get_session()
    metadata_cache: dict[str, dict | None] = {}

    objects = (
        session.query(Object.id, Object.wikidata_qid)
        .filter(Object.wikidata_qid.is_not(None))
        .all()
    )
    qid_cache: dict[str, list[dict]] = {}
    selections: dict[str, list[dict]] = {}

    for obj_id, qid in tqdm(objects, desc="Selecting per-object images", unit="obj"):
        selected = qid_cache.get(qid)
        if selected is None:
            selected = _select_for_qid(
                qid,
                metadata_cache,
                SOURCES_METADATA_DIR / "wikidata" / "objects",
                aux_pid="P154",
                aux_kind="logo",
            )
            qid_cache[qid] = selected
        if selected:
            selections[obj_id] = selected

    _merge_manual_extras(selections)

    _write_cache(OBJECT_IMAGES_PATH, "objects", selections)
    _update_image_available_flag(session, set(selections))
    logger.info(
        "Wrote %s with images for %d / %d QID-linked objects",
        OBJECT_IMAGES_PATH.name,
        len(selections),
        len(objects),
    )

    # Features ride on the same selection logic but key by feature_id and pull
    # P242 (locator map) instead of P154 (logo) as the aux image kind.
    feature_rows = (
        session.query(Feature.feature_id, Feature.wikidata_qid)
        .filter(Feature.wikidata_qid.is_not(None))
        .all()
    )
    feature_qid_cache: dict[str, list[dict]] = {}
    feature_selections: dict[str, list[dict]] = {}
    for feature_id, qid in tqdm(
        feature_rows, desc="Selecting per-feature images", unit="feat"
    ):
        selected = feature_qid_cache.get(qid)
        if selected is None:
            selected = _select_for_qid(
                qid,
                metadata_cache,
                SOURCES_METADATA_DIR / "wikidata" / "nomenclature",
                aux_pid="P242",
                aux_kind="locator",
            )
            feature_qid_cache[qid] = selected
        if selected:
            feature_selections[str(feature_id)] = selected
    _write_cache(FEATURE_IMAGES_PATH, "features", feature_selections)
    logger.info(
        "Wrote %s with images for %d / %d QID-linked features",
        FEATURE_IMAGES_PATH.name,
        len(feature_selections),
        len(feature_rows),
    )


def _select_for_qid(
    qid: str,
    metadata_cache: dict[str, dict | None],
    wikidata_dir: Path,
    *,
    aux_pid: str,
    aux_kind: str,
) -> list[dict]:
    """Pick the best-of-tree image list for one QID."""
    direct, kind_of, pageimage_count = collect_qid_image_candidates(
        qid,
        wikidata_dir=wikidata_dir,
        wiki_dir=SOURCES_METADATA_DIR / "wikipedia",
        aux_pid=aux_pid,
        aux_kind=aux_kind,
    )
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


class _MetadataView:
    """Dict-like lazy reader for ``IMAGES_DIR/<f>/metadata.json``.

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


def _write_cache(
    out_path: Path, payload_key: str, selections: dict[str, list[dict]]
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        payload_key: dict(sorted(selections.items())),
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


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
    return _read_cache(OBJECT_IMAGES_PATH, "objects")


def read_feature_images() -> dict[str, list[dict]]:
    """Return the cached ``{feature_id: [{file, kind}, ...]}`` mapping."""
    return _read_cache(FEATURE_IMAGES_PATH, "features")


def _read_cache(path: Path, payload_key: str) -> dict[str, list[dict]]:
    if not path.exists():
        return {}
    try:
        payload = orjson.loads(path.read_bytes())
    except orjson.JSONDecodeError:
        logger.warning("Corrupt %s; ignoring", path)
        return {}
    return payload.get(payload_key) or {}
