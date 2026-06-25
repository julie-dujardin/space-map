"""Group export: per-group bundles + membership index for /g/<slug> pages."""

import csv
import io
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import orjson
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from space_map_data.export.groups.bundles import write_group_bundles
from space_map_data.export.groups.categories import build_category_data
from space_map_data.export.groups.earth_sat import (
    build_earth_orbit_classes,
    write_earth_orbit_samples,
)
from space_map_data.export.groups.membership import (
    build_earth_groups_data,
    write_earth_membership,
)
from space_map_data.export.groups.registry import (
    ORGANIZATION_BUS_CHILDREN,
    Group,
    GroupCategory,
    GroupType,
)
from space_map_data.export.groups.small_body import (
    _exported_sbdb_filter,
    build_small_body_group_stats,
    write_orbit_samples,
)
from space_map_data.constants.comet_fragments import family_group_slug
from space_map_data.export.notable import NotableObject
from space_map_data.export.objects.fragments import build_comet_families
from space_map_data.export.objects.missions import build_probe_missions
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.models.object.main import Object
from space_map_data.models.object.sbdb import SBDB
from space_map_data.utils.paths import EXPORT_DIR, SOURCES_METADATA_DIR

logger = logging.getLogger(__name__)


@dataclass
class SplitCometGroups:
    """Dynamic group pages for parentless split-comet families."""

    groups: list[Group] = field(default_factory=list)
    member_counts: dict[str, int] = field(default_factory=dict)
    notable_members: dict[str, list[NotableObject]] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)


@dataclass
class MissionGroups:
    """Dynamic group pages for probe missions (primary + sibling craft)."""

    groups: list[Group] = field(default_factory=list)
    member_counts: dict[str, int] = field(default_factory=dict)
    notable_members: dict[str, list[NotableObject]] = field(default_factory=dict)
    primary_ids: dict[str, str] = field(default_factory=dict)


def _mission_groups() -> MissionGroups:
    """One group page per probe mission, built from the probe registry.

    The mission's Wikidata QID (set on the primary as ``primary_qid``) drives
    the sidebar; members list the primary first, then its sibling craft. The
    ``primary_ids`` map gives each page a focus redirect to its primary probe.
    """
    out = MissionGroups()
    for mission in build_probe_missions():
        members = [mission.primary, *mission.members]
        out.groups.append(
            Group(
                slug=mission.slug,
                type=GroupType.MISSION,
                applies_to=GroupCategory.PROBE,
                wikidata_qid=mission.mission_qid,
            )
        )
        out.member_counts[mission.slug] = len(members)
        out.notable_members[mission.slug] = members
        out.primary_ids[mission.slug] = mission.primary_object_id
    logger.info("Mission group pages: %d", len(out.groups))
    return out


# Wikidata properties whose match CSVs key on a comet's designation.
_DESIGNATION_MATCH_PIDS = ("P5736", "P490")


def _designation_qids() -> dict[str, list[str]]:
    """``{comet designation: [qid]}`` from the P5736/P490 Wikidata match CSVs.

    Mirrors the ingest reader, but keyed on the full designation (``C/1860 D1``)
    so a parentless family — which matches no object — can still be linked to
    its Wikidata item when an editor sets the designation property there.
    """
    matches_dir = SOURCES_METADATA_DIR / "wikidata" / "ids" / "matches"
    out: dict[str, set[str]] = defaultdict(set)
    for pid in _DESIGNATION_MATCH_PIDS:
        path = matches_dir / f"{pid}.csv"
        if not path.exists():
            continue
        for row in csv.reader(io.StringIO(path.read_text())):
            if row and len(row) > 1 and row[1]:
                out[row[0]].update(row[1].split())
    return {designation: sorted(qids) for designation, qids in out.items()}


def _split_comet_groups(
    session: Session, wikidata_entities: WikidataEntityCache
) -> SplitCometGroups:
    """One group page per parentless split-comet family (no intact body).

    Families with an intact parent get their fragment list on that body's
    object page instead. Members are restricted to exported fragments, so a
    family whose pieces are all unexported (Shoemaker-Levy 9 — all D-prefix)
    yields no page. A family's Wikidata QID comes from its fragments' own links
    where possible, else a direct designation lookup (catches comets an editor
    linked by designation but that no fragment matched).
    """
    families = build_comet_families(session, wikidata_entities)
    designation_qids = _designation_qids()
    exported = {
        object_id
        for (object_id,) in session.query(SBDB.object_id)
        .join(Object, Object.id == SBDB.object_id)
        .filter(*_exported_sbdb_filter())
        .all()
    }
    out = SplitCometGroups()
    skipped: list[str] = []
    by_designation = 0
    for family in families.values():
        if family.parent_object_id is not None:
            continue
        members = [f for f in family.fragments if f.object_id in exported]
        if not members:
            skipped.append(family.parent_pdes)
            continue
        qid = family.parent_qid
        name = family.parent_name
        if qid is None:
            candidates = designation_qids.get(family.designation, [])
            if len(candidates) == 1:
                qid = candidates[0]
                wd = wikidata_entities.get_entity(qid)
                name = (wd["labels"].get("en") if wd else None) or name
                by_designation += 1
        slug = family_group_slug(family.parent_pdes)
        out.groups.append(
            Group(
                slug=slug,
                type=GroupType.SPLIT_COMET,
                applies_to=GroupCategory.SMALL_BODY,
                wikidata_qid=qid,
            )
        )
        out.member_counts[slug] = len(members)
        out.notable_members[slug] = members
        out.names[slug] = name
    enriched = sum(1 for g in out.groups if g.wikidata_qid)
    logger.info(
        "Split-comet group pages: %d parentless families (%d with a Wikidata QID, "
        "%d of those via designation lookup), %d skipped (no exported fragments): %s",
        len(out.groups),
        enriched,
        by_designation,
        len(skipped),
        ", ".join(skipped) if skipped else "[]",
    )
    return out


def run_groups_tier(
    engine: Engine,
    out_dir: Path,
    wikidata_entities: WikidataEntityCache,
) -> dict[str, int]:
    """Build + write the groups tier; returns bucket counts for metadata.json."""
    with Session(engine) as session:
        build = build_earth_groups_data(session)
        small_body_stats = build_small_body_group_stats(session)
        earth_orbit_stats = build_earth_orbit_classes(session)
        build.membership[GroupType.EARTH_ORBIT_CLASS] = earth_orbit_stats.membership
        build.stats[GroupType.EARTH_ORBIT_CLASS] = earth_orbit_stats.satcat_stats

        extra_member_counts = dict(small_body_stats.member_counts)
        extra_member_counts.update(earth_orbit_stats.member_counts)
        # Counts the category builder needs to rank constellations + drop empty
        # zones: membership-backed groups plus the small-body/earth extras.
        all_counts = {
            slug: len(ids)
            for mem in build.membership.values()
            for slug, ids in mem.items()
        }
        all_counts.update(extra_member_counts)
        earth_launch_histograms = {
            slug: s.launch_histogram
            for slug, s in earth_orbit_stats.satcat_stats.items()
            if s.launch_histogram
        }
        category_data = build_category_data(
            session,
            all_counts,
            small_body_stats.named_counts,
            small_body_stats.discovery_histograms,
            earth_launch_histograms,
        )
        split_comets = _split_comet_groups(session, wikidata_entities)
    missions = _mission_groups()

    # Each constellation lists the buses its members fly, most-used first; the
    # chip count is the within-constellation tally, not the bus's global total.
    constellation_bus_children = {
        c_slug: sorted(counts, key=lambda s: (-counts[s], s))
        for c_slug, counts in build.constellation_bus_counts.items()
    }

    extra_member_counts.update(category_data.member_counts)
    extra_member_counts.update(split_comets.member_counts)
    extra_member_counts.update(missions.member_counts)
    extra_named_counts = dict(small_body_stats.named_counts)
    extra_named_counts.update(category_data.named_counts)
    extra_notable_members = dict(small_body_stats.notable_members)
    extra_notable_members.update(category_data.notable_members)
    extra_notable_members.update(split_comets.notable_members)
    extra_notable_members.update(missions.notable_members)
    extra_notable_members.update(earth_orbit_stats.notable_members)
    # Category discovery charts ride the same per-slug path as small-body
    # classes; satellite launch charts need their own override since categories
    # carry no GroupSatcatStats.
    extra_histograms = dict(small_body_stats.discovery_histograms)
    extra_histograms.update(category_data.discovery_histograms)

    write_earth_membership(out_dir, build.membership)
    write_orbit_samples(out_dir, small_body_stats.orbit_samples)
    write_earth_orbit_samples(out_dir, earth_orbit_stats.orbit_samples)

    return write_group_bundles(
        out_dir,
        wikidata_entities,
        build.membership,
        build.stats,
        extra_member_counts=extra_member_counts,
        extra_histograms=extra_histograms,
        extra_launch_histograms=category_data.launch_histograms,
        extra_largest_bodies=small_body_stats.largest_bodies,
        extra_pha_counts=small_body_stats.pha_counts,
        extra_named_counts=extra_named_counts,
        extra_notable_members=extra_notable_members,
        extra_moon_counts=category_data.moon_counts,
        extra_primary_ids=missions.primary_ids,
        child_slugs_by_group={
            **category_data.children,
            **ORGANIZATION_BUS_CHILDREN,
            **constellation_bus_children,
        },
        child_counts_by_group=build.constellation_bus_counts,
        extra_groups=(*split_comets.groups, *missions.groups),
        extra_group_names=split_comets.names,
    )


def update_metadata_group_bundles(out_dir: Path, group_bundles: dict[str, int]) -> None:
    """Patch only ``group_bundles`` in metadata.json (for additive runs)."""
    path = out_dir / "metadata.json"
    metadata = orjson.loads(path.read_bytes()) if path.exists() else {}
    metadata["group_bundles"] = group_bundles
    path.write_bytes(orjson.dumps(metadata, option=orjson.OPT_INDENT_2))


def export_groups_only(engine: Engine) -> None:
    """Additive run: write groups + membership + patch metadata.json only."""
    from space_map_data.export.localization import write_group_messages

    out_dir = EXPORT_DIR / "v1"
    if not out_dir.exists():
        raise SystemExit(f"Export dir {out_dir} missing — run a full export first.")
    wikidata_entities = WikidataEntityCache()
    group_bundles = run_groups_tier(engine, out_dir, wikidata_entities)
    update_metadata_group_bundles(out_dir, group_bundles)
    write_group_messages(wikidata_entities)
    logger.info("Groups-only export complete (%d bundles)", group_bundles["global"])
