"""Move build-only sidecar metadata out of EXPORT_DIR into EXPORT_METADATA_DIR.

Frees the CDN deploy from carrying files the frontend never fetches. Targets:

    EXPORT_DIR/v1/position/probes/**/*.meta.json
    EXPORT_DIR/v1/position/earth/**/*.meta.json
    EXPORT_DIR/v1/textures/<id>/metadata.json
    EXPORT_DIR/v1/rings/<id>/metadata.json

Each file moves to the same relative path under EXPORT_METADATA_DIR. Safe to
re-run: files already at the destination are left in place; if the source
still exists and contents differ, the script aborts so the conflict gets
inspected manually.

Run from data/:

    uv run python scripts/migrate_sidecar_metadata.py            # dry-run
    uv run python scripts/migrate_sidecar_metadata.py --apply
"""

import argparse
import logging
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "data" / "src"))

from space_map_data.export.sidecar_io import mirror_path  # noqa: E402
from space_map_data.utils.paths import EXPORT_DIR, EXPORT_METADATA_DIR  # noqa: E402

log = logging.getLogger("migrate_sidecar_metadata")


def _iter_targets() -> list[Path]:
    """All sidecar metadata files currently under EXPORT_DIR."""
    v1 = EXPORT_DIR / "v1"
    targets: list[Path] = []
    targets += sorted((v1 / "position" / "probes").rglob("*.meta.json"))
    targets += sorted((v1 / "position" / "earth").rglob("*.meta.json"))
    for body_root in (v1 / "textures", v1 / "rings"):
        if not body_root.exists():
            continue
        for body_dir in sorted(body_root.iterdir()):
            if not body_dir.is_dir():
                continue
            meta = body_dir / "metadata.json"
            if meta.exists():
                targets.append(meta)
    return targets


def _move(src: Path, dst: Path, apply: bool) -> str:
    """Return a one-word status: moved, exists, skip, conflict."""
    if not src.exists():
        return "skip"
    if dst.exists():
        if dst.read_bytes() == src.read_bytes():
            if apply:
                src.unlink()
            return "exists"
        return "conflict"
    if apply:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
    return "moved"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually move files. Without this flag, only counts are reported.",
    )
    args = parser.parse_args()

    logging.basicConfig(format="%(message)s", level=logging.INFO)

    if not EXPORT_DIR.exists():
        log.error("EXPORT_DIR does not exist: %s", EXPORT_DIR)
        return 1

    targets = _iter_targets()
    log.info(
        "%s: %d candidate sidecar(s) under %s",
        "MIGRATE" if args.apply else "DRY-RUN",
        len(targets),
        EXPORT_DIR,
    )
    log.info("Destination root: %s", EXPORT_METADATA_DIR)

    counts: dict[str, int] = {"moved": 0, "exists": 0, "skip": 0, "conflict": 0}
    conflicts: list[Path] = []
    for src in targets:
        dst = mirror_path(src)
        status = _move(src, dst, apply=args.apply)
        counts[status] += 1
        if status == "conflict":
            conflicts.append(src)

    for k, v in counts.items():
        log.info("  %-9s %d", k, v)

    if conflicts:
        log.error(
            "Conflicts (source kept, destination differs):\n  %s",
            "\n  ".join(str(p) for p in conflicts),
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
