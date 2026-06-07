"""Group export: per-group bundles + membership index for /g/<slug> pages."""

import logging
from pathlib import Path

import orjson
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from space_map_data.export.groups.bundles import write_group_bundles
from space_map_data.export.groups.membership import (
    build_earth_earliest_launches,
    build_earth_membership,
    write_earth_membership,
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
        membership = build_earth_membership(session)
        earliest_launches = build_earth_earliest_launches(session)
    write_earth_membership(out_dir, membership)

    member_counts = {slug: len(ids) for slug, ids in membership.items()}
    return write_group_bundles(
        out_dir, wikidata_entities, member_counts, earliest_launches
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
