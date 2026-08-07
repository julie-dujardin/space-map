"""Texture download manifests, merged into one entry list.

Layout under ``textures/`` mirrors the download dir it describes: the root
manifest covers the flat per-body surface textures in ``surfaces/``, and each
manually-staged asset (``star-map/``, ``night/earth/``, ``displacement/moon/``,
…) carries its own manifest at the position of the directory holding its
files. That mirroring is what lets each entry's source directory be recovered
from its manifest's own path, now that the manifests no longer sit next to
their bytes.

``clouds/`` and ``rings/`` are excluded — they use their own metadata files,
written by their downloaders rather than by hand.
"""

import logging
from collections.abc import Iterator
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

MANIFESTS_DIR = Path(__file__).parent / "textures"
MANIFEST_NAME = "download-metadata.yaml"
# The root manifest's entries are the only ones whose files don't live in the
# directory the manifest mirrors.
SURFACES_SUBDIR = "surfaces"


def load_entries(textures_dir: Path) -> list[dict]:
    """Every texture entry, stamped with ``_source_dir``: the directory holding
    its files, resolved under ``textures_dir`` (the textures source root)."""
    entries: list[dict] = []
    for manifest, source_dir in _manifests(textures_dir):
        bodies = (yaml.safe_load(manifest.read_text()) or {}).get("bodies") or []
        valid = [entry for entry in bodies if isinstance(entry, dict)]
        if len(valid) != len(bodies):
            logger.warning(
                "Dropping %d empty/invalid body entries from %s",
                len(bodies) - len(valid),
                manifest.relative_to(MANIFESTS_DIR.parent),
            )
        for entry in valid:
            entry["_source_dir"] = source_dir
        entries.extend(valid)
    return entries


def _manifests(textures_dir: Path) -> Iterator[tuple[Path, Path]]:
    """Each manifest with the directory its entries' files live in."""
    yield MANIFESTS_DIR / MANIFEST_NAME, textures_dir / SURFACES_SUBDIR
    # Depth 1 is a bodyless asset (star-map/), depth 2 a per-body one
    # (night/earth/).
    extra = sorted(
        list(MANIFESTS_DIR.glob(f"*/{MANIFEST_NAME}"))
        + list(MANIFESTS_DIR.glob(f"*/*/{MANIFEST_NAME}"))
    )
    for manifest in extra:
        yield manifest, textures_dir / manifest.parent.relative_to(MANIFESTS_DIR)
