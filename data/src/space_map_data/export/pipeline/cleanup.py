"""Output-directory lifecycle: pre-flight DB check, wipe stale outputs, prune orphans."""

import logging
import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path

from sqlalchemy.orm import Session

from space_map_data.export.pipeline.manifest import ZoomSnapshots
from space_map_data.export.position.layout import position_zone_dir
from space_map_data.models.object import (
    CelesTrak,
    Horizons,
    Object,
    Satcat,
    SBDB,
    SBDBMoon,
)

logger = logging.getLogger(__name__)


_POSITION_INCREMENTAL_ZONES = {"earth", "probes", "small_bodies"}

# Minimum row count required per table for a healthy export. Below this we
# assume the ingest aborted partway and refuse to run rather than ship an
# export with whole zones silently missing.
_MIN_ROWS_PER_TABLE = 10
_EXPECTED_TABLES = (Object, CelesTrak, Horizons, Satcat, SBDB, SBDBMoon)


def precheck_tables(session: Session) -> None:
    """Raise if any expected table has fewer than `_MIN_ROWS_PER_TABLE` rows."""
    empty = []
    for model in _EXPECTED_TABLES:
        n = session.query(model).limit(_MIN_ROWS_PER_TABLE).count()
        if n < _MIN_ROWS_PER_TABLE:
            empty.append(f"{model.__tablename__}={n}")
    if empty:
        raise RuntimeError(
            f"Export pre-check failed: tables below {_MIN_ROWS_PER_TABLE} rows "
            f"({', '.join(empty)}). Re-run ingest before exporting."
        )


def remove_old_outputs(out_dir: Path, keep_object_outputs: bool = False) -> None:
    """Remove all chunk output directories before a fresh export.

    Top-level dirs in `_POSITION_INCREMENTAL_ZONES` (`earth`, `probes`,
    `small_bodies`) manage their own per-chunk sidecars (see the per-zone
    `sidecar.py` modules); wiping them would defeat the skip-reexport
    logic, so they're left for the writer to overwrite or skip in place.
    Stale parts inside an incremental zone (e.g. an asteroid class shrank,
    so a part is now orphan) are cleaned up post-export by
    :func:`prune_small_bodies`.

    Chebyshev-owned dirs (`major/0`, `major_asteroids`, `moons/<parent>`)
    are also preserved — the chebyshev pass wipes them itself when its
    inputs changed (`_wipe_chebyshev_outputs`), so a signature-skipped pass
    keeps valid files.

    Every other zone under `position/` is wiped — the elements writers
    don't atomic-overwrite, and stale part files for bodies that have left
    a zone would otherwise linger forever.

    `keep_object_outputs=True` (tier-B inputs unchanged) preserves
    `objects/` and `nomenclature/details/` so the skipped bundle writers
    don't leave the export without them.
    """
    pos = out_dir / "position"
    if pos.exists():
        for child in pos.iterdir():
            if not child.is_dir():
                child.unlink()
                continue
            if child.name in _POSITION_INCREMENTAL_ZONES:
                continue
            if child.name == "major_asteroids":
                continue
            if child.name == "major":
                # zoom 0 is chebyshev's; 1/2 are elements zooms.
                for sub in child.iterdir():
                    if sub.is_dir() and sub.name != "0":
                        shutil.rmtree(sub)
                continue
            if child.name == "moons":
                # Numeric children = flat elements `moons` chunks; named children
                # (`moons/<parent>`) are chebyshev tiers, wiped by the cheb pass.
                for sub in child.iterdir():
                    if sub.is_dir() and sub.name.isdigit():
                        shutil.rmtree(sub)
                continue
            shutil.rmtree(child)
    if not keep_object_outputs:
        p = out_dir / "objects"
        if p.exists():
            shutil.rmtree(p)
        # Nomenclature details bucket count depends on K_GLOBAL / K_LOCALIZED;
        # tuning either leaves stale-numbered files behind that the writer
        # never touches, so wipe it here. Positions / labels use stable
        # per-body filenames the writer overwrites in place — but a body that
        # loses all its features (e.g. a name-collision match fixed upstream)
        # leaves an orphan file the writer never revisits, so those are pruned
        # post-export by :func:`prune_nomenclature`.
        p = out_dir / "nomenclature" / "details"
        if p.exists():
            shutil.rmtree(p)
    # The previous schema shipped a per-body `__global__/{body}.json.gz`
    # marker file alongside positions; the new schema replaces it with
    # per-language label files. Drop the legacy dir so old artefacts
    # don't linger on the CDN after an in-place re-export.
    p = out_dir / "nomenclature" / "__global__"
    if p.exists():
        shutil.rmtree(p)
    # System metadata is regenerated each export (individual textures are not)
    for d in ("textures/systems", "systems"):
        p = out_dir / d
        if p.exists():
            shutil.rmtree(p)
    # Legacy image layout before the per-filename bundle refactor. Deleting
    # unconditionally is safe: the new layout writes to ``images/<filename>/``
    # dirs alongside these (never inside them), so this never hits new output.
    for d in ("images/thumb", "images/full", "images/metadata"):
        p = out_dir / d
        if p.exists():
            shutil.rmtree(p)


def prune_nomenclature(out_dir: Path, keep_body_ids: Iterable[str]) -> None:
    """Delete orphan per-body marker files under `nomenclature/positions` and
    `nomenclature/labels/<lang>`.

    The marker writers overwrite stable `{body_id}` filenames in place but
    never delete, so a body that no longer yields renderable features (e.g.
    an asteroid that shared a moon's name until an upstream match fix) leaves
    its file shipping forever. Runs every export — including tier-B-skipped
    ones, where the writers don't run but stale files can still linger.
    """
    keep = set(keep_body_ids)
    nomen = out_dir / "nomenclature"
    deleted = 0

    positions = nomen / "positions"
    if positions.exists():
        for f in positions.glob("*.bin.gz"):
            if f.name.removesuffix(".bin.gz") not in keep:
                f.unlink()
                deleted += 1

    labels = nomen / "labels"
    if labels.exists():
        for lang_dir in labels.iterdir():
            if not lang_dir.is_dir():
                continue
            for f in lang_dir.glob("*.txt.gz"):
                if f.name.removesuffix(".txt.gz") not in keep:
                    f.unlink()
                    deleted += 1

    if deleted:
        logger.info("Pruned %d orphan nomenclature marker files", deleted)


def _planned_small_body_paths(
    out_dir: Path,
    zone_structure: Mapping[str, Mapping[int, ZoomSnapshots]],
) -> set[Path]:
    """Return the set of `.bin.gz` paths this run intends to keep under
    `position/small_bodies/`, derived from `zone_structure`.

    Used by :func:`prune_small_bodies` to delete anything not in the set.
    """
    planned: set[Path] = set()
    for zone, zoom_map in zone_structure.items():
        if not zone.startswith("small_bodies/"):
            continue
        for zoom, zoom_snaps in zoom_map.items():
            for snap in zoom_snaps.snapshots:
                base = position_zone_dir(out_dir, zone, zoom)
                if snap.time is not None:
                    base = base / snap.time
                for part in range(snap.num_parts):
                    planned.add(base / f"{part}.bin.gz")
    return planned


def prune_small_bodies(
    out_dir: Path,
    zone_structure: Mapping[str, Mapping[int, ZoomSnapshots]],
) -> None:
    """Delete on-disk parts under `position/small_bodies/` not in this run's
    plan, plus their sidecars in the metadata mirror.

    Incremental export preserves `position/small_bodies/` across runs (see
    `_POSITION_INCREMENTAL_ZONES`); without a prune pass, orphans from class
    shrinkage (fewer parts), removed classes, or moved-to-different-zone
    bodies would linger forever.

    Sidecar mirroring: parts live in `EXPORT_DIR/position/small_bodies/...`
    and sidecars in `EXPORT_METADATA_DIR/position/small_bodies/...`; both
    sides are walked so a sidecar whose binary already vanished (e.g. partial
    deletion from a prior crash) is also cleaned up.
    """
    from space_map_data.export.position.elements import (
        sidecar,
    )  # local import: avoid cycle
    from space_map_data.export.pipeline.incremental import ZONE_META_NAME

    planned = _planned_small_body_paths(out_dir, zone_structure)
    planned_dirs = {p.parent for p in planned}
    sb_dir = out_dir / "position" / "small_bodies"
    deleted = 0
    if sb_dir.exists():
        for bin_path in sb_dir.rglob("*.bin.gz"):
            if bin_path in planned:
                continue
            bin_path.unlink()
            part_idx = bin_path.name.removesuffix(".bin.gz")
            meta_path = sidecar.mirror_path(bin_path.parent / f"{part_idx}.meta.json")
            meta_path.unlink(missing_ok=True)
            deleted += 1
        for d in sorted((d for d in sb_dir.rglob("*") if d.is_dir()), reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass  # not empty — keep

    # Catch orphan sidecars whose binaries already vanished (e.g. a class was
    # fully removed before this run, leaving only the metadata mirror behind).
    meta_sb_dir = sidecar.mirror_path(sb_dir)
    if meta_sb_dir.exists():
        for meta_path in meta_sb_dir.rglob("*.meta.json"):
            rel_dir = meta_path.relative_to(meta_sb_dir).parent
            if meta_path.name == ZONE_META_NAME:
                # Zone-level stats sidecar: orphan iff its zone has no
                # planned parts this run (class removed / moved).
                if sb_dir / rel_dir not in planned_dirs:
                    meta_path.unlink()
                    deleted += 1
                continue
            part_idx = meta_path.name.removesuffix(".meta.json")
            if sb_dir / rel_dir / f"{part_idx}.bin.gz" not in planned:
                meta_path.unlink()
                deleted += 1
        for d in sorted(
            (d for d in meta_sb_dir.rglob("*") if d.is_dir()), reverse=True
        ):
            try:
                d.rmdir()
            except OSError:
                pass

    if deleted:
        logger.info("Pruned %d orphan small_bodies parts/sidecars", deleted)
