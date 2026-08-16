"""Compute the per-object/feature/group best Commons image, cache to disk.

For each QID-linked entity, discover direct image candidates (P18 ∪ {aux} ∪
Wikipedia pageimages — aux is P154 "logo" for objects/groups and P242
"locator" for features), group into derivative-tree components via on-disk
metadata, and pick the highest-scoring file per tree (assessment >
pageimage-frequency > globalusage, see :mod:`space_map_data.utils.image_scoring`).

Cached at ``OBJECT_IMAGES_PATH`` (keyed by ``Object.id``, drives
``image_available``), ``FEATURE_IMAGES_PATH`` (by ``Feature.feature_id``),
``GROUP_IMAGES_PATH`` (by ``Group.slug``), and ``RING_IMAGES_PATH`` (by the
ringed body's ``Object.id`` — pictures of the ring system, not the planet).
Exports read these caches instead of re-walking sources.
"""

import json
import logging
from collections import Counter
from collections.abc import Container, Sequence
from datetime import datetime, timezone
from pathlib import Path

import orjson
from sqlalchemy import update
from tqdm import tqdm

from space_map_data.constants.categories import (
    DEBRIS_SLUG,
    PROBES_SLUG,
    RING_SYSTEMS_SLUG,
    SATELLITES_SLUG,
)
from space_map_data.constants.countries import COUNTRY_SLUG_PREFIX
from space_map_data.constants.atmosphere.wikidata import ATMOSPHERE_PAGES
from space_map_data.constants.interior.wikidata import INTERIOR_PAGES
from space_map_data.constants.rings.wikidata import RING_SYSTEM_PAGES
from space_map_data.export.groups.registry import (
    GROUPS,
    GroupCategory,
)
from space_map_data.export.objects.missions import build_probe_missions
from space_map_data.models.feature import Feature
from space_map_data.models.object import Object, ObjectType
from space_map_data.utils import image_scoring
from space_map_data.utils.commons_images import (
    COMMONS_DIR,
    collect_qid_image_candidates,
    image_exclusion_reason,
    is_radar_render,
    is_servable_on_disk,
    read_download_metadata,
    read_manual_extras,
)
from space_map_data.utils.db import get_session
from space_map_data.utils.paths import SOURCES_METADATA_DIR

logger = logging.getLogger(__name__)

OBJECT_IMAGES_PATH = COMMONS_DIR / "object_images.json"
FEATURE_IMAGES_PATH = COMMONS_DIR / "feature_images.json"
GROUP_IMAGES_PATH = COMMONS_DIR / "group_images.json"
RING_IMAGES_PATH = COMMONS_DIR / "ring_images.json"
TOPIC_IMAGES_PATH = COMMONS_DIR / "topic_images.json"

# Topic shelves: the articles about a body's envelope and its insides, which
# illustrate what the Structure tab describes in prose. Keyed ``<topic>:<id>``
# in one cache, since both sides are the same shape as the ring selection.
TOPIC_PAGE_TABLES: tuple[tuple[str, dict[str, tuple[str, ...]]], ...] = (
    ("atmosphere", ATMOSPHERE_PAGES),
    ("interior", INTERIOR_PAGES),
)

SCHEMA_VERSION = 1

# Built things keep cutaways/schematics — often the only illustration a
# probe has. Everything else drops them, see ``image_exclusion_reason``.
_SCHEMATIC_OBJECT_TYPES = frozenset(
    {ObjectType.spacecraft.value, ObjectType.debris.value}
)
# `applies_to` covers most groups; browse categories share one value
# regardless of contents, so the three whose members are craft are named.
_SCHEMATIC_GROUP_CATEGORIES = frozenset({GroupCategory.EARTH_SAT, GroupCategory.PROBE})
_SCHEMATIC_CATEGORY_SLUGS = frozenset({SATELLITES_SLUG, DEBRIS_SLUG, PROBES_SLUG})


def ingest() -> None:
    """Build object/feature/group image caches and update ``image_available``."""
    session = get_session()
    metadata_cache: dict[str, dict | None] = {}
    wikidata_root = SOURCES_METADATA_DIR / "wikidata"

    object_rows = (
        session.query(Object.id, Object.wikidata_qid, Object.object_type)
        .filter(Object.wikidata_qid.is_not(None))
        .all()
    )
    objects = [(oid, qid) for oid, qid, _ in object_rows]
    # Only built things keep schematics: a planet cutaway restates a view the
    # app renders, but for a probe it's often the only illustration there is.
    craft = {
        oid for oid, _, obj_type in object_rows if obj_type in _SCHEMATIC_OBJECT_TYPES
    }
    selections = _select_for_qids(
        objects,
        metadata_cache,
        wikidata_root / "objects",
        aux_pid="P154",
        aux_kind="logo",
        desc="Selecting per-object images",
        unit="obj",
        keep_diagrams=craft,
    )
    _merge_manual_extras(selections)
    _write_cache(OBJECT_IMAGES_PATH, "objects", selections)
    _update_image_available_flag(session, set(selections))
    _log_written(OBJECT_IMAGES_PATH, "objects", selections, objects)

    # Nomenclature features key by feature_id and use P242 (locator map) as aux.
    features = [
        (str(fid), qid)
        for fid, qid in session.query(Feature.feature_id, Feature.wikidata_qid)
        .filter(Feature.wikidata_qid.is_not(None))
        .all()
    ]
    feature_selections = _select_for_qids(
        features,
        metadata_cache,
        wikidata_root / "nomenclature",
        aux_pid="P242",
        aux_kind="locator",
        desc="Selecting per-feature images",
        unit="feat",
    )
    _write_cache(FEATURE_IMAGES_PATH, "features", feature_selections)
    _log_written(FEATURE_IMAGES_PATH, "features", feature_selections, features)

    # Country groups are skipped: their own Wikidata image is a geographic
    # locator map, irrelevant to a space map. Their Images tab is the member
    # shelves the export builds, like any other collection's.
    groups = [
        (g.slug, g.wikidata_qid)
        for g in GROUPS
        if g.wikidata_qid and not g.slug.startswith(COUNTRY_SLUG_PREFIX)
    ]
    missions = build_probe_missions()
    groups += [(m.slug, m.mission_qid) for m in missions]
    craft_groups = {
        g.slug
        for g in GROUPS
        if g.applies_to in _SCHEMATIC_GROUP_CATEGORIES
        or g.slug in _SCHEMATIC_CATEGORY_SLUGS
    } | {m.slug for m in missions}
    group_selections = _select_for_qids(
        groups,
        metadata_cache,
        wikidata_root / "referenced",
        aux_pid="P154",
        aux_kind="logo",
        desc="Selecting per-group images",
        unit="group",
        keep_diagrams=craft_groups,
    )
    # One selection, two consumers: each ringed body's own Rings tab, and the
    # collection page that pools them.
    ring_images = _select_ring_images(metadata_cache, wikidata_root / "referenced")
    _write_cache(RING_IMAGES_PATH, "ring_systems", ring_images)
    _fill_ring_systems(group_selections, ring_images)
    # Atmosphere and interior articles: one shelf each on the body's Images tab.
    _write_cache(
        TOPIC_IMAGES_PATH,
        "topics",
        _select_topic_images(metadata_cache, wikidata_root / "referenced"),
    )
    _write_cache(GROUP_IMAGES_PATH, "groups", group_selections)
    _log_written(GROUP_IMAGES_PATH, "groups", group_selections, groups)


def _select_for_qids(
    items: Sequence[tuple[str, str]],
    metadata_cache: dict[str, dict | None],
    wikidata_dir: Path,
    *,
    aux_pid: str,
    aux_kind: str,
    desc: str,
    unit: str,
    keep_diagrams: Container[str] = frozenset(),
) -> dict[str, list[dict]]:
    """Run :func:`_select_for_qid` over ``(key, qid)`` pairs, deduping per QID.

    Subjects in ``keep_diagrams`` keep cutaways/schematics, others drop them;
    cached separately per QID since either answer may be needed.
    """
    qid_cache: dict[tuple[str, bool], list[dict]] = {}
    selections: dict[str, list[dict]] = {}
    excluded: Counter[str] = Counter()
    for key, qid in tqdm(items, desc=desc, unit=unit):
        drop_diagrams = key not in keep_diagrams
        selected = qid_cache.get((qid, drop_diagrams))
        if selected is None:
            selected = _select_for_qid(
                qid,
                metadata_cache,
                wikidata_dir,
                aux_pid=aux_pid,
                aux_kind=aux_kind,
                excluded=excluded,
                drop_diagrams=drop_diagrams,
            )
            qid_cache[(qid, drop_diagrams)] = selected
        if selected:
            selections[key] = selected
    if excluded:
        logger.info(
            "Skipped %d redundant candidate image(s) by category (%s)",
            sum(excluded.values()),
            ", ".join(f"{reason}: {n}" for reason, n in excluded.most_common()),
        )
    return selections


def _log_written(
    path: Path,
    label: str,
    selections: dict[str, list[dict]],
    items: Sequence[tuple[str, str]],
) -> None:
    logger.info(
        "Wrote %s with images for %d / %d QID-linked %s",
        path.name,
        len(selections),
        len(items),
        label,
    )


def _select_for_qid(
    qid: str,
    metadata_cache: dict[str, dict | None],
    wikidata_dir: Path,
    *,
    aux_pid: str,
    aux_kind: str,
    excluded: Counter[str] | None = None,
    drop_diagrams: bool = False,
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

    metadata_by_filename = _MetadataView(metadata_cache)

    # Drop redundant candidates (orbit diagrams, locator maps) up front so a
    # servable real photo elsewhere in the tree wins; an object whose only
    # candidate was a diagram correctly ends up image-less. Feature locator
    # maps are redundant with the app's own position marker; objects/groups
    # keep locator-categorised images (e.g. constellation coverage maps).
    drop_locator_maps = aux_kind == "locator"

    def _acceptable(name: str) -> bool:
        reason = image_exclusion_reason(
            name,
            metadata_by_filename.get(name),
            drop_locator_maps=drop_locator_maps,
            drop_subject_diagrams=drop_diagrams,
        )
        if reason is not None:
            if excluded is not None:
                excluded[reason] += 1
            return False
        return is_servable_on_disk(name)

    direct = [name for name in direct if _acceptable(name)]
    if not direct:
        return []

    discovery_order = {name: i for i, name in enumerate(direct)}
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
        if not _acceptable(best):
            # Tree-only winners can be non-servable (different license) or
            # redundant noise; fall back to scanning the direct candidates in
            # this component for an acceptable choice.
            best = next((name for name in component if _acceptable(name)), None)
            if best is None or best in seen:
                continue
        seen.add(best)
        kind = (
            "radar"
            if is_radar_render(metadata_by_filename.get(best))
            else kind_of.get(best, "photo")
        )
        out.append({"file": best, "kind": kind})
    return out


def _select_from_pages(
    pages: dict[str, tuple[str, ...]],
    metadata_cache: dict[str, dict | None],
    referenced_dir: Path,
) -> dict[str, list[dict]]:
    """Pictures from a topic-page table, keyed by the body each row is about.

    Uses the topic articles (rings, atmosphere, interior), not the body's own
    images — a portrait of the planet says nothing about the rings it wears.
    """
    out: dict[str, list[dict]] = {}
    for body, qids in pages.items():
        picks: list[dict] = []
        seen: set[str] = set()
        for qid in qids:
            for entry in _select_for_qid(
                qid,
                metadata_cache,
                referenced_dir,
                aux_pid="P154",
                aux_kind="logo",
                drop_diagrams=True,
            ):
                if entry["file"] in seen:
                    continue
                seen.add(entry["file"])
                picks.append(entry)
        if picks:
            out[body] = picks
    return out


def _log_page_selection(
    label: str, pages: dict[str, tuple[str, ...]], out: dict[str, list[dict]]
) -> None:
    missing = [body for body in pages if body not in out]
    logger.info(
        "%s images: %d picture(s) across %d of %d articles%s",
        label,
        sum(len(v) for v in out.values()),
        len(out),
        len(pages),
        f"; nothing for {', '.join(missing)}" if missing else "",
    )


def _select_ring_images(
    metadata_cache: dict[str, dict | None],
    referenced_dir: Path,
) -> dict[str, list[dict]]:
    """Pictures of each ring system, keyed by the host body.

    Two of the eight bodies contribute nothing: neither Haumea nor Quaoar has a
    ring article in any language. Their tiles fall back to the ring plane.
    """
    out = _select_from_pages(RING_SYSTEM_PAGES, metadata_cache, referenced_dir)
    _log_page_selection("Ring system", RING_SYSTEM_PAGES, out)
    return out


def _select_topic_images(
    metadata_cache: dict[str, dict | None],
    referenced_dir: Path,
) -> dict[str, list[dict]]:
    """Pictures from each body's atmosphere and interior articles.

    One flat cache keyed ``<topic>:<object_id>``, since a body can be in both
    tables and the export asks for one topic at a time.
    """
    out: dict[str, list[dict]] = {}
    for topic, pages in TOPIC_PAGE_TABLES:
        picks = _select_from_pages(pages, metadata_cache, referenced_dir)
        _log_page_selection(topic.capitalize(), pages, picks)
        out.update({f"{topic}:{body}": entries for body, entries in picks.items()})
    return out


def _fill_ring_systems(
    selections: dict[str, list[dict]],
    ring_images: dict[str, list[dict]],
) -> None:
    """Pool the per-system pictures onto the Ring Systems collection page.

    The page's own Wikidata item is the generic "planetary ring" concept, so
    the member fallback would show portraits of Jupiter/Saturn instead of
    rings; the systems' own pictures lead, with Saturn's first since its
    rings are the page's tile image.
    """
    exemplar = "naif-699"
    # `sorted` is stable, so the rest keep the catalogue's order behind Saturn.
    bodies = sorted(ring_images, key=lambda body: body != exemplar)
    existing = list(selections.get(RING_SYSTEMS_SLUG) or ())
    seen = {entry["file"] for entry in existing}
    picks: list[dict] = []
    for body in bodies:
        for entry in ring_images[body]:
            if entry["file"] in seen:
                continue
            seen.add(entry["file"])
            picks.append(entry)
    if not picks:
        logger.warning(
            "Ring Systems page: no image selected from any ring article; the "
            "page falls back to the %d image(s) its own concept item carries",
            len(existing),
        )
        return
    selections[RING_SYSTEMS_SLUG] = picks + existing
    logger.info(
        "Ring Systems page: %d image(s) from the ring articles, ahead of %d "
        "from the concept item",
        len(picks),
        len(existing),
    )


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

    Drops entries not yet downloaded or with a non-servable license, with
    a warning — the downloader is responsible for fetching them.
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
    runs before ingest; or a fresh checkout).
    """
    return _read_cache(OBJECT_IMAGES_PATH, "objects")


def read_feature_images() -> dict[str, list[dict]]:
    """Return the cached ``{feature_id: [{file, kind}, ...]}`` mapping."""
    return _read_cache(FEATURE_IMAGES_PATH, "features")


def read_group_images() -> dict[str, list[dict]]:
    """Return the cached ``{group_slug: [{file, kind}, ...]}`` mapping."""
    return _read_cache(GROUP_IMAGES_PATH, "groups")


def read_topic_images() -> dict[str, list[dict]]:
    """Topic-article pictures keyed ``<topic>:<object_id>``."""
    return _read_cache(TOPIC_IMAGES_PATH, "topics")


def read_ring_images() -> dict[str, list[dict]]:
    """Return the cached ``{body_id: [{file, kind}, ...]}`` mapping."""
    return _read_cache(RING_IMAGES_PATH, "ring_systems")


def _read_cache(path: Path, payload_key: str) -> dict[str, list[dict]]:
    if not path.exists():
        return {}
    try:
        payload = orjson.loads(path.read_bytes())
    except orjson.JSONDecodeError:
        logger.warning("Corrupt %s; ignoring", path)
        return {}
    return payload.get(payload_key) or {}
