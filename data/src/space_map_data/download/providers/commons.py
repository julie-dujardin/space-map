"""Download Wikimedia Commons images for Wikidata P18 (image) and P154 (logo)."""

import json
import logging
import time
from pathlib import Path
from urllib.parse import quote, unquote

from tqdm import tqdm

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader
from space_map_data.utils.paths import DOWNLOAD_DIR, EXPORT_DIR

logger = logging.getLogger(__name__)

_IMAGE_PIDS = ("P18", "P154")
AFTER_REQUEST_DELAY_SECONDS = 1


def _extract_filenames(entity: dict) -> set[str]:
    """Extract unique image filenames from P18 and P154 claims."""
    filenames: set[str] = set()
    claims = entity.get("claims", {})
    for pid in _IMAGE_PIDS:
        for stmt in claims.get(pid, []):
            if stmt.get("rank") == "deprecated":
                continue
            val = stmt.get("mainsnak", {}).get("datavalue", {}).get("value")
            if isinstance(val, str) and val:
                filenames.add(val)
    return filenames


def _sanitize_filename(filename: str) -> str:
    """Normalise a Commons filename for local storage.

    Wikimedia uses underscores internally; the raw claim value may contain
    spaces or underscores interchangeably.  We keep the original form so
    round-tripping back to a Commons URL stays correct.
    """
    return unquote(filename)


class CommonsDownloader(Downloader):
    """Download Wikimedia Commons images (P18 + P154) for all Wikidata entities."""

    name = PROVIDERS.COMMONS

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        wikidata_dir = DOWNLOAD_DIR / PROVIDERS.WIKIDATA / "objects"
        if not wikidata_dir.exists():
            raise FileNotFoundError(
                f"Wikidata objects not found at {wikidata_dir} "
                "— download wikidata first"
            )

        images_dir = EXPORT_DIR / "v1" / "images"
        thumb_dir = images_dir / "thumb"
        full_dir = images_dir / "full"
        thumb_dir.mkdir(parents=True, exist_ok=True)
        full_dir.mkdir(parents=True, exist_ok=True)

        # Collect all unique filenames from Wikidata entities
        all_filenames: set[str] = set()
        entity_files = sorted(wikidata_dir.glob("Q*.json"))
        for entity_file in tqdm(
            entity_files, desc="Scanning Wikidata for images", unit="entity"
        ):
            try:
                entity = json.loads(entity_file.read_text())
            except json.JSONDecodeError:
                logger.warning("Skipping invalid entity file %s", entity_file)
                continue
            all_filenames |= _extract_filenames(entity)

        logger.info("Found %s unique Commons filenames", f"{len(all_filenames):,}")

        # Also collect Wikipedia pageimage filenames not covered by P18/P154
        wiki_dir = DOWNLOAD_DIR / PROVIDERS.WIKIPEDIA
        if wiki_dir.exists():
            wiki_filenames = self._collect_wikipedia_image_filenames(wiki_dir)
            new = wiki_filenames - all_filenames
            if new:
                logger.info(
                    "Found %d additional image filenames from Wikipedia pageimages",
                    len(new),
                )
                all_filenames |= new

        # Determine which need downloading
        to_download: list[str] = []
        for filename in sorted(all_filenames):
            safe = _sanitize_filename(filename)
            if not (thumb_dir / safe).exists():
                to_download.append(filename)

        logger.info(
            "Commons images: %s total, %s to download",
            f"{len(all_filenames):,}",
            f"{len(to_download):,}",
        )

        if limit is not None:
            to_download = to_download[:limit]

        if not to_download:
            self._save_metadata(
                "https://commons.wikimedia.org/wiki/Special:FilePath/",
                len(all_filenames),
                complete=True,
            )
            return

        failed = 0
        for filename in tqdm(to_download, desc="Commons images", unit="img"):
            safe = _sanitize_filename(filename)
            encoded = quote(filename)

            # Download thumbnail (300px)
            thumb_ok = self._download_one(
                f"https://commons.wikimedia.org/wiki/Special:FilePath/{encoded}?width=300",
                thumb_dir / safe,
            )
            # Download full-size
            full_ok = self._download_one(
                f"https://commons.wikimedia.org/wiki/Special:FilePath/{encoded}",
                full_dir / safe,
            )
            if not thumb_ok and not full_ok:
                failed += 1
            time.sleep(AFTER_REQUEST_DELAY_SECONDS)

        if failed:
            logger.warning("Failed to download %d images", failed)

        self._save_metadata(
            "https://commons.wikimedia.org/wiki/Special:FilePath/",
            len(all_filenames),
            complete=len(to_download)
            == len(all_filenames) - (len(all_filenames) - len(to_download)),
        )

    def _download_one(self, url: str, out_path: Path) -> bool:
        """Download a single image URL to disk. Returns True on success."""
        if out_path.exists():
            return True
        try:
            response = self.client.get(url, timeout=30.0)
            if response.status_code == 429:
                retry_after = int(response.headers.get("retry-after", 60))
                logger.warning("Commons 429 — sleeping %ds", retry_after)
                time.sleep(retry_after)
                response = self.client.get(url, timeout=30.0)
            response.raise_for_status()
        except Exception:
            logger.warning("Failed to download %s", url)
            return False
        out_path.write_bytes(response.content)
        return True

    def _collect_wikipedia_image_filenames(self, wiki_dir: Path) -> set[str]:
        """Extract original image filenames from all downloaded Wikipedia summaries."""
        filenames: set[str] = set()
        for summary_file in wiki_dir.glob("*/Q*.json"):
            try:
                page = json.loads(summary_file.read_text())
            except json.JSONDecodeError:
                continue
            src = (page.get("original") or {}).get("source")
            if not src:
                continue
            # Extract filename from URL path
            basename = unquote(src.rsplit("/", 1)[-1])
            if basename:
                filenames.add(basename)
        return filenames
