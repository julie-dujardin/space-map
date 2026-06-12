"""Group export: per-group bundles + membership index for /g/<slug> pages."""

import logging
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
from space_map_data.export.groups.registry import GroupType
from space_map_data.export.groups.small_body import (
    build_small_body_group_stats,
    write_orbit_samples,
)
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.utils.paths import EXPORT_DIR

logger = logging.getLogger(__name__)


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
            small_body_stats.discovery_histograms,
            earth_launch_histograms,
        )

    extra_member_counts.update(category_data.member_counts)
    extra_notable_members = dict(small_body_stats.notable_members)
    extra_notable_members.update(category_data.notable_members)
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
        extra_notable_members=extra_notable_members,
        category_children=category_data.children,
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
