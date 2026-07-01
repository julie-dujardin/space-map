"""Fetch natural-body shape models listed in the bodies manifests.

The manifests under ``sources/models/bodies/<tier>/manifest.yaml`` are the
source of truth: hand-curated per-body entries whose ``files`` carry exact
archive URLs (PDS SBN, JAXA DARTS, ESAC, ...), so one provider covers every
archive and the URL set stays reproducible. DAMIT is catalog-shaped and has
its own provider.

Deliberately sequential (slow backup uplink); every run rechecks the file
list, so new manifest entries are picked up without any force flag.
"""

import logging
from pathlib import Path

import httpx
import yaml

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader
from space_map_data.download.providers.three_d.resumable import download_resumable
from space_map_data.utils.paths import SOURCES_MODELS_BODIES_DIR

logger = logging.getLogger(__name__)

# DAMIT's tier dir is owned by its own provider.
MANIFEST_TIERS = ("missions", "radar")


def iter_manifest_files(tier: str | None = None) -> list[tuple[Path, str, Path]]:
    """Yield (tier_dir, url, dest_path) for every manifest file entry."""
    out: list[tuple[Path, str, Path]] = []
    for tier_name in MANIFEST_TIERS:
        if tier and tier_name != tier:
            continue
        manifest = SOURCES_MODELS_BODIES_DIR / tier_name / "manifest.yaml"
        if not manifest.is_file():
            continue
        doc = yaml.safe_load(manifest.read_text()) or {}
        for entry in doc.get("entries") or []:
            for f in entry.get("files") or []:
                out.append((manifest.parent, f["url"], manifest.parent / f["path"]))
    return out


class BodyShapesDownloader(Downloader):
    """Mirror manifest-listed shape models into sources/models/bodies/."""

    name = PROVIDERS.BODY_SHAPES

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = SOURCES_MODELS_BODIES_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def is_complete(self, limit: int | None) -> bool:
        # Always re-run; per-file existence checks make it incremental.
        return False

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        files = iter_manifest_files()
        missing = [(u, d) for _, u, d in files if not d.exists()]
        logger.info(
            "body shapes: %d manifest files, %d to fetch", len(files), len(missing)
        )
        failures = 0
        for url, dest in missing:
            if not download_resumable(self.client, url, dest):
                failures += 1
        if failures:
            logger.error("body shapes: %d file(s) failed", failures)
        self._save_metadata(
            "sources/models/bodies/*/manifest.yaml",
            len(files) - failures,
            complete=failures == 0,
        )
