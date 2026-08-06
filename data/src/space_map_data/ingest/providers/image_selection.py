"""Compute the per-object/feature/group best Commons image, cache to disk.

For each QID-linked entity we discover the direct image candidates (P18 ∪
{aux} ∪ Wikipedia pageimages across LANGUAGES — aux is P154 "logo" for
objects/groups and P242 "locator" for nomenclature features), group them
into derivative-tree components via on-disk metadata, and pick the highest-
scoring file per tree (assessment > pageimage-frequency > globalusage — see
:mod:`space_map_data.utils.image_scoring`).

The results are cached at:

* ``OBJECT_IMAGES_PATH`` keyed by ``Object.id`` (e.g. ``naif-199``). Drives
  the ``image_available`` flag on Object rows.
* ``FEATURE_IMAGES_PATH`` keyed by IAU ``Feature.feature_id`` (stringified).
* ``GROUP_IMAGES_PATH`` keyed by ``Group.slug``.
* ``RING_IMAGES_PATH`` keyed by the ringed body's ``Object.id`` — pictures of
  the ring system rather than of the planet wearing it.

Exports read these caches instead of re-walking sources.
"""

import json
import logging
from collections import Counter
from collections.abc import Container, Sequence
from datetime import datetime, timezone
from pathlib import Path

import orjson
from sqlalchemy import or_, update
from tqdm import tqdm

from space_map_data.constants.categories import (
    ASTEROIDS_SLUG,
    COMET_ORBIT_CLASSES,
    COMETS_SLUG,
    DEBRIS_SLUG,
    DWARF_PLANETS_SLUG,
    MOONS_SLUG,
    PLANETS_SLUG,
    PROBES_SLUG,
    RING_SYSTEMS_SLUG,
    SATELLITES_SLUG,
    SOLAR_SYSTEM_SLUG,
)
from space_map_data.constants.countries import COUNTRY_BY_CODE, COUNTRY_SLUG_PREFIX
from space_map_data.constants.earth_sats.constellations import CONSTELLATION_SLUG_PREFIX
from space_map_data.constants.earth_sats.launch_sites import (
    LAUNCH_SITE_BY_CODE,
    LAUNCH_SITE_SLUG_PREFIX,
)
from space_map_data.constants.earth_sats.manufacturers import MANUFACTURER_BY_QID
from space_map_data.constants.earth_sats.operators import OPERATOR_BY_QID
from space_map_data.constants.earth_sats.organizations import (
    ORGANIZATION_SLUG_PREFIX,
)
from space_map_data.constants.atmosphere.wikidata import ATMOSPHERE_PAGES
from space_map_data.constants.interior.wikidata import INTERIOR_PAGES
from space_map_data.constants.rings.wikidata import RING_SYSTEM_PAGES
from space_map_data.export.groups.earth_sat import (
    LAGRANGE_ORBIT_CENTERS,
    primary_orbit_class_slug,
)
from space_map_data.export.groups.registry import (
    CLASS_SLUG_PREFIX,
    GROUPS,
    SMALL_BODY_FLAG_SLUG_PREFIX,
    GroupCategory,
)
from space_map_data.export.groups.small_body import _exported_sbdb_filter
from space_map_data.export.objects.missions import build_probe_missions
from space_map_data.models.feature import Feature
from space_map_data.models.object import Object, ObjectType
from space_map_data.models.object.sbdb import SBDB
from space_map_data.models.object.satcat import Satcat
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

# Member-photo fallback for groups whose own QID yielded no image (orbit classes,
# obscure operators, etc.). Walks member objects in sitelink-rank order and picks
# from their Commons photos. Tuned so the gallery always has enough to show.
GROUP_FALLBACK_TARGET_COUNT = 15
GROUP_FALLBACK_PER_MEMBER_CAP = 3
GROUP_FALLBACK_MIN_GALLERY_DIM = 800
GROUP_FALLBACK_MIN_HERO_DIM = 1600
# Subjects that keep their cutaways and schematics: things humans built, where
# the schematic is often the only illustration there is. Everything else drops
# them — see ``image_exclusion_reason(drop_subject_diagrams=...)``.
_SCHEMATIC_OBJECT_TYPES = frozenset(
    {ObjectType.spacecraft.value, ObjectType.debris.value}
)
# A group follows its members. `applies_to` answers this for every group except
# the browse categories, which share one value whatever they hold — so the three
# whose members are craft are named.
_SCHEMATIC_GROUP_CATEGORIES = frozenset({GroupCategory.EARTH_SAT, GroupCategory.PROBE})
_SCHEMATIC_CATEGORY_SLUGS = frozenset({SATELLITES_SLUG, DEBRIS_SLUG, PROBES_SLUG})
# Earth-sat filter mirrored from `membership.build_earth_groups_data` so the
# fallback's member set matches the rows actually shipped per zone.
_FALLBACK_SAT_TYPE_VALUES = [ObjectType.spacecraft.value, ObjectType.debris.value]
_FALLBACK_EARTH_OBJECT_ID = "naif-399"


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
    # Only built things keep their schematics: a cutaway of a planet or a ring
    # system restates a view the app renders, but for a probe the schematic is
    # often the only illustration that exists.
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

    # Groups: registry-driven (referenced/ also holds operators/countries), plus
    # the dynamically-built probe missions keyed by their mission QID. Country
    # groups are skipped here: their own Wikidata image is a geographic locator
    # map, irrelevant to a space map, so they draw solely from member photos via
    # the fallback below.
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
    # Picture-less groups (no own QID or QID yielded no image) fall back to
    # photos of their member objects, ranked by member sitelink count.
    _fill_groups_from_members(
        group_selections,
        metadata_cache,
        wikidata_root / "objects",
        session,
        craft_groups,
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

    Subjects in ``keep_diagrams`` keep their cutaways and schematics; every
    other subject drops them (see ``drop_subject_diagrams``). The two answers
    are cached separately, since one QID can be reached from both sides.
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

    # Drop redundant candidates (orbit diagrams, comparison diagrams, locator
    # maps) up front so a servable real photo elsewhere in the tree wins. An
    # object whose only candidate was an orbit diagram correctly ends up
    # image-less — the app draws the orbit itself.
    # Feature locator maps (red-dot/outline "where is this crater") are
    # redundant with the app showing the feature's position; objects/groups
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

    The tables map a body to the articles *about* one aspect of it — its rings,
    its atmosphere, its insides. Those articles are already downloaded (the
    panels cite them), and their pictures are scored by the same tree walk as
    everything else. The body's own images are no use for this: a portrait of
    the planet says nothing about the rings it wears.
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

    Its own Wikidata item is the generic "planetary ring" concept and the
    member fallback would fill a page about rings with portraits of Jupiter and
    Saturn, so the systems' own pictures lead. Saturn goes first, because the
    first image is what the collection's tile shows and its rings are what the
    subject is recognised by.
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


def _fill_groups_from_members(
    selections: dict[str, list[dict]],
    metadata_cache: dict[str, dict | None],
    wikidata_dir: Path,
    session,
    craft_groups: Container[str],
) -> None:
    """Augment every group's selection in-place with member-object photos.

    Existing entries (logo / group-own image) keep their slots — they were
    deliberately chosen — and member photos append to fill out the gallery
    up to :data:`GROUP_FALLBACK_TARGET_COUNT`. Groups that arrived empty
    additionally get a hero photo promoted to index 0 when a member supplies
    one above :data:`GROUP_FALLBACK_MIN_HERO_DIM`. Members are walked in
    descending sitelink order, each contributing at most
    :data:`GROUP_FALLBACK_PER_MEMBER_CAP` photos.
    """
    members_by_slug = _build_group_member_qids(session)
    sitelink_cache: dict[str, int] = {}
    metadata_view = _MetadataView(metadata_cache)

    filled_empty = 0
    augmented = 0
    skipped_no_members = 0
    # Static registry groups, plus slugs that only live in the member map
    # (dynamically-built probe missions).
    static_slugs = [g.slug for g in GROUPS]
    extra_slugs = [s for s in members_by_slug if s not in set(static_slugs)]
    for slug in tqdm(
        static_slugs + extra_slugs,
        desc="Augmenting groups with member photos",
        unit="group",
    ):
        qids = members_by_slug.get(slug)
        if not qids:
            if not selections.get(slug):
                skipped_no_members += 1
            continue
        existing = list(selections.get(slug) or ())
        remaining = GROUP_FALLBACK_TARGET_COUNT - len(existing)
        if remaining <= 0:
            continue
        ranked = _rank_members_by_sitelinks(qids, wikidata_dir, sitelink_cache)
        picks = _pick_fallback_images(
            ranked,
            metadata_view,
            metadata_cache,
            wikidata_dir,
            target_count=remaining,
            exclude_files={e["file"] for e in existing},
            promote_hero=not existing,
            drop_diagrams=slug not in craft_groups,
        )
        if not picks:
            continue
        selections[slug] = existing + picks
        if existing:
            augmented += 1
        else:
            filled_empty += 1

    logger.info(
        "Member-photo group fallback: filled %d previously empty groups, "
        "augmented %d existing ones; %d groups had no qid-bearing members",
        filled_empty,
        augmented,
        skipped_no_members,
    )


def _build_group_member_qids(session) -> dict[str, list[str]]:
    """Return ``{slug: [member_qid, ...]}`` for every fallback-eligible group.

    Members are bodies with a Wikidata QID; objects without one can't
    contribute Wikidata-sourced photos and would just bloat the walk.
    """
    out: dict[str, list[str]] = {}

    # Small-body groups: orbit class + NEO/PHA flags from SBDB.
    sb_rows = (
        session.query(Object.wikidata_qid, SBDB.class_, SBDB.neo, SBDB.pha)
        .join(Object, Object.id == SBDB.object_id)
        .filter(*_exported_sbdb_filter())
        .filter(Object.wikidata_qid.is_not(None))
        .all()
    )
    for qid, cls, neo, pha in sb_rows:
        out.setdefault(f"{CLASS_SLUG_PREFIX}{cls.name}", []).append(qid)
        category = COMETS_SLUG if cls in COMET_ORBIT_CLASSES else ASTEROIDS_SLUG
        out.setdefault(category, []).append(qid)
        if neo:
            out.setdefault(f"{SMALL_BODY_FLAG_SLUG_PREFIX}neo", []).append(qid)
        if pha:
            out.setdefault(f"{SMALL_BODY_FLAG_SLUG_PREFIX}pha", []).append(qid)

    # Earth-sat groups: constellation/operator/launch-site/manufacturer/country
    # — mirror the filter in `membership.build_earth_groups_data` so the
    # member set matches the rows actually shipped.
    earth_rows = (
        session.query(
            Object.wikidata_qid,
            Satcat.constellation_slug,
            Satcat.operator_qids,
            Satcat.manufacturer_qids,
            Satcat.launch_site_code,
            Satcat.country_codes,
        )
        .join(Object.satcat)
        .filter(
            Object.spkid.is_(None),
            Object.object_type.in_(_FALLBACK_SAT_TYPE_VALUES),
            Object.parent_id == _FALLBACK_EARTH_OBJECT_ID,
            Object.wikidata_qid.is_not(None),
        )
        .all()
    )
    for qid, c_slug, op_qids, mfr_qids, site_code, country_codes in earth_rows:
        out.setdefault(SATELLITES_SLUG, []).append(qid)
        if c_slug:
            out.setdefault(f"{CONSTELLATION_SLUG_PREFIX}{c_slug}", []).append(qid)
        for op_qid in op_qids or ():
            op = OPERATOR_BY_QID.get(op_qid)
            if op is not None:
                out.setdefault(f"{ORGANIZATION_SLUG_PREFIX}{op.slug}", []).append(qid)
        for m_qid in mfr_qids or ():
            mfr = MANUFACTURER_BY_QID.get(m_qid)
            if mfr is not None:
                out.setdefault(f"{ORGANIZATION_SLUG_PREFIX}{mfr.slug}", []).append(qid)
        if site_code:
            site = LAUNCH_SITE_BY_CODE.get(site_code)
            if site is not None:
                out.setdefault(f"{LAUNCH_SITE_SLUG_PREFIX}{site.slug}", []).append(qid)
        for code in country_codes or ():
            country = COUNTRY_BY_CODE.get(code)
            if country is not None:
                out.setdefault(f"{COUNTRY_SLUG_PREFIX}{country.slug}", []).append(qid)

    # Earth-sat orbit zones: their generic orbit-concept QIDs rarely have a
    # usable Commons image (Lagrange zones have none), so each zone's gallery is
    # filled from member-sat photos. Lagrange sats are Sun-parented, admitted by
    # orbit_center.
    zone_rows = (
        session.query(
            Object.wikidata_qid,
            Satcat.perigee,
            Satcat.apogee,
            Satcat.orbit_center,
        )
        .join(Object.satcat)
        .filter(
            Object.spkid.is_(None),
            Object.object_type.in_(_FALLBACK_SAT_TYPE_VALUES),
            Object.wikidata_qid.is_not(None),
            or_(
                Object.parent_id == _FALLBACK_EARTH_OBJECT_ID,
                Satcat.orbit_center.in_(LAGRANGE_ORBIT_CENTERS),
            ),
        )
        .all()
    )
    for qid, perigee, apogee, orbit_center in zone_rows:
        slug = primary_orbit_class_slug(perigee, apogee, orbit_center)
        if slug is not None:
            out.setdefault(slug, []).append(qid)

    # Body-aggregating categories: the planets, dwarf planets and moons, plus
    # the Solar System root (Sun + planets — a curated hero set, not the whole
    # catalogue). The Wikidata class entities (Q634/Q2199/Q2537) rarely carry a
    # usable photo, so these pages lean on the member fallback for their hero +
    # gallery, ranked by member sitelink count (top moon, top dwarf, ...).
    def _typed_qids(*types: ObjectType) -> list[str]:
        return [
            qid
            for (qid,) in session.query(Object.wikidata_qid)
            .filter(
                Object.object_type.in_([t.value for t in types]),
                Object.wikidata_qid.is_not(None),
            )
            .all()
        ]

    planet_qids = _typed_qids(ObjectType.planet)
    if planet_qids:
        out[PLANETS_SLUG] = planet_qids
    dwarf_qids = _typed_qids(ObjectType.dwarf_planet)
    if dwarf_qids:
        out[DWARF_PLANETS_SLUG] = dwarf_qids
    moon_qids = _typed_qids(ObjectType.moon)
    if moon_qids:
        out[MOONS_SLUG] = moon_qids
    solar = _typed_qids(ObjectType.star) + planet_qids
    if solar:
        out[SOLAR_SYSTEM_SLUG] = solar

    # Probe missions: primary craft + sibling QIDs, so a mission whose own QID
    # has no Commons image fills from its craft (e.g. Pioneer Venus Multiprobe).
    for mission in build_probe_missions():
        qids = [
            o.wikidata_qid
            for o in (mission.primary, *mission.members)
            if o.wikidata_qid
        ]
        if qids:
            out[mission.slug] = qids
    return out


def _rank_members_by_sitelinks(
    qids: list[str], wikidata_dir: Path, cache: dict[str, int]
) -> list[str]:
    """Return ``qids`` sorted by descending sitelink count, lex QID as tiebreak."""
    unique: list[str] = []
    seen: set[str] = set()
    for qid in qids:
        if qid in seen:
            continue
        seen.add(qid)
        unique.append(qid)
    return sorted(
        unique,
        key=lambda q: (-_get_sitelink_count(q, wikidata_dir, cache), q),
    )


def _get_sitelink_count(qid: str, wikidata_dir: Path, cache: dict[str, int]) -> int:
    """Number of Wikipedia sitelinks for ``qid``; 0 when missing or corrupt."""
    if qid in cache:
        return cache[qid]
    path = wikidata_dir / f"{qid}.json"
    count = 0
    if path.exists():
        try:
            entity = orjson.loads(path.read_bytes())
        except orjson.JSONDecodeError:
            logger.warning("Corrupt Wikidata JSON, skipping sitelinks: %s", path)
        else:
            sitelinks = entity.get("sitelinks") or {}
            if isinstance(sitelinks, dict):
                count = len(sitelinks)
    cache[qid] = count
    return count


def _pick_fallback_images(
    ranked_qids: list[str],
    metadata_view: "_MetadataView",
    metadata_cache: dict[str, dict | None],
    wikidata_dir: Path,
    *,
    target_count: int = GROUP_FALLBACK_TARGET_COUNT,
    exclude_files: set[str] | None = None,
    promote_hero: bool = True,
    drop_diagrams: bool = False,
) -> list[dict]:
    """Pick up to ``target_count`` member photos for one group.

    When ``promote_hero`` is True (the group has no pre-existing entry the
    hero would displace), the first photo of the highest-sitelink member
    that clears :data:`GROUP_FALLBACK_MIN_HERO_DIM` leads the result; if no
    member qualifies, the gallery leader survives at lower resolution rather
    than ship no image. ``exclude_files`` is a set of Commons filenames
    already chosen elsewhere (e.g. by the existing P154 pass) and must not
    be re-emitted. Each member's :func:`_select_for_qid` result is computed
    once and reused across hero scan and gallery fill.
    """
    if target_count <= 0:
        return []
    photos_cache: dict[str, list[dict]] = {}

    def member_photos(qid: str) -> list[dict]:
        cached = photos_cache.get(qid)
        if cached is None:
            picks = _select_for_qid(
                qid,
                metadata_cache,
                wikidata_dir,
                aux_pid="P154",
                aux_kind="logo",
                drop_diagrams=drop_diagrams,
            )
            # Radar shape-model renders count as gallery photos (they were
            # plain "photo" before tagging); only logos/locators are unwanted.
            cached = [p for p in picks if p["kind"] in ("photo", "radar")]
            photos_cache[qid] = cached
        return cached

    chosen: list[dict] = []
    used_files: set[str] = set(exclude_files or ())
    contributed: dict[str, int] = {}

    if promote_hero:
        # Prepend the first hero-resolution photo so it lands at index 0.
        # Counts toward the contributing member's allocation so we don't
        # accidentally let one member supply 4 images (hero + 3 gallery).
        for qid in ranked_qids:
            hero = next(
                (
                    p
                    for p in member_photos(qid)
                    if p["file"] not in used_files
                    and _resolution_at_least(
                        metadata_view.get(p["file"]), GROUP_FALLBACK_MIN_HERO_DIM
                    )
                ),
                None,
            )
            if hero is not None:
                chosen.append(hero)
                used_files.add(hero["file"])
                contributed[qid] = 1
                break

    def fill(per_member_cap: int) -> None:
        for qid in ranked_qids:
            if len(chosen) >= target_count:
                return
            picks_for_member = contributed.get(qid, 0)
            if picks_for_member >= per_member_cap:
                continue
            for pick in member_photos(qid):
                file = pick["file"]
                if file in used_files:
                    continue
                if not _resolution_at_least(
                    metadata_view.get(file), GROUP_FALLBACK_MIN_GALLERY_DIM
                ):
                    continue
                chosen.append(pick)
                used_files.add(file)
                picks_for_member += 1
                contributed[qid] = picks_for_member
                if len(chosen) >= target_count or picks_for_member >= per_member_cap:
                    break

    fill(GROUP_FALLBACK_PER_MEMBER_CAP)
    if len(chosen) < target_count:
        # Drop the per-member cap so prolific contributors backfill the
        # gallery instead of leaving it half-empty.
        fill(target_count)
    return chosen


def _resolution_at_least(metadata: dict | None, min_dim: int) -> bool:
    """True when ``min(width, height) >= min_dim`` in the Commons imageinfo."""
    if not metadata:
        return False
    info = metadata.get("imageinfo") or {}
    width = info.get("width")
    height = info.get("height")
    if not isinstance(width, int) or not isinstance(height, int):
        return False
    return min(width, height) >= min_dim


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
