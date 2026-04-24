"""Download Wikimedia Commons images and their license/description metadata.

Collects image filenames from Wikidata P18/P154 claims plus Wikipedia pageimages, then
downloads the source file and fetches rich metadata (license, author, description in
every language) via the Commons Action API. License servability is evaluated at
download time and persisted into the metadata file so later phases don't re-decide.

On-disk layout (see :mod:`space_map_data.utils.commons_images`)::

    DOWNLOAD_DIR/images/<filename>/source.<ext>
    DOWNLOAD_DIR/images/<filename>/metadata.json

Images hosted on a specific language wiki (ar/en/fr/ru/...) rather than on Commons are
recorded separately and skipped — see the TODO below.
"""

import json
import logging
import time
from datetime import datetime, timezone
from itertools import batched
from pathlib import Path
from urllib.parse import quote

from httpx import Response
from tqdm import tqdm

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader
from space_map_data.utils.commons_images import (
    IMAGES_DIR,
    canonical_filename,
    download_metadata_path,
    extract_wikidata_filenames,
    image_dir,
    is_excluded,
    license_is_servable,
    parse_upload_url,
    source_path,
    write_download_metadata,
)
from space_map_data.utils.paths import DOWNLOAD_DIR

logger = logging.getLogger(__name__)

AFTER_REQUEST_DELAY_SECONDS = 1
METADATA_BATCH_SIZE = 50

# TODO: locally-hosted (non-Commons) images are currently recorded in
# ``non_commons_skipped.json`` and skipped. To actually include them we'd need to hit each
# language wiki's own Action API for imageinfo (commons.wikimedia.org returns "missing"
# for them). Almost all of them are non-free anyway, so export filters them out — revisit
# only if that policy changes.


class CommonsDownloader(Downloader):
    """Download Wikimedia Commons images and their metadata."""

    name = PROVIDERS.COMMONS

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        wikidata_dir = DOWNLOAD_DIR / PROVIDERS.WIKIDATA / "objects"
        if not wikidata_dir.exists():
            raise FileNotFoundError(
                f"Wikidata objects not found at {wikidata_dir} "
                "— download wikidata first"
            )

        IMAGES_DIR.mkdir(parents=True, exist_ok=True)

        commons_filenames, non_commons = self._collect_filenames(wikidata_dir)
        self._write_non_commons_skipped(non_commons)

        to_process = sorted(commons_filenames)
        if limit is not None:
            to_process = to_process[:limit]

        self._download_images(to_process)
        self._fetch_metadata(to_process)

        self._save_metadata(
            "https://commons.wikimedia.org/w/api.php?action=query&prop=imageinfo",
            len(commons_filenames),
            complete=False,
        )

    def _collect_filenames(
        self, wikidata_dir: Path
    ) -> tuple[set[str], dict[str, dict]]:
        """Collect image filenames from Wikidata claims and Wikipedia summaries.

        Returns ``(commons_filenames, non_commons)`` where ``non_commons`` maps filename
        to ``{"url", "repo", "referenced_from": [lang/QID, ...]}``.
        """
        commons: set[str] = set()
        non_commons: dict[str, dict] = {}

        # 1) Wikidata P18/P154 claims — always Commons filenames by policy.
        entity_files = sorted(wikidata_dir.glob("Q*.json"))
        for entity_file in tqdm(
            entity_files, desc="Scanning Wikidata for images", unit="entity"
        ):
            try:
                entity = json.loads(entity_file.read_text())
            except json.JSONDecodeError:
                logger.warning("Skipping invalid entity file %s", entity_file)
                continue
            commons |= extract_wikidata_filenames(entity)

        # 2) Wikipedia pageimages — split commons vs local wiki based on URL.
        wiki_dir = DOWNLOAD_DIR / PROVIDERS.WIKIPEDIA
        if wiki_dir.exists():
            summary_files = list(wiki_dir.glob("*/Q*.json"))
            for summary_file in tqdm(
                summary_files, desc="Scanning Wikipedia for images", unit="page"
            ):
                try:
                    page = json.loads(summary_file.read_text())
                except json.JSONDecodeError:
                    continue
                src = (page.get("original") or {}).get("source")
                if not src:
                    continue
                parsed = parse_upload_url(src)
                if parsed is None:
                    logger.warning("Unrecognized image URL: %s", src)
                    continue
                repo, filename = parsed
                filename = canonical_filename(filename)
                if is_excluded(filename):
                    continue
                ref = f"{summary_file.parent.name}/{summary_file.stem}"
                if repo == "commons":
                    commons.add(filename)
                else:
                    entry = non_commons.setdefault(
                        filename,
                        {"url": src, "repo": repo, "referenced_from": []},
                    )
                    entry["referenced_from"].append(ref)

        # Apply exclusion to Wikidata-sourced filenames too.
        excluded = {f for f in commons if is_excluded(f)}
        if excluded:
            commons -= excluded
            logger.info(
                "Filtered out %d excluded-prefix image filenames", len(excluded)
            )

        logger.info(
            "Commons filenames: %s unique; non-Commons (local wiki): %s",
            f"{len(commons):,}",
            f"{len(non_commons):,}",
        )
        return commons, non_commons

    def _write_non_commons_skipped(self, non_commons: dict[str, dict]) -> None:
        """Record locally-hosted images that we're skipping.

        Written to the downloads dir (not export) since the export pipeline doesn't
        consume them.
        """
        if not non_commons:
            return
        out_path = self.out_dir / "non_commons_skipped.json"
        payload = {
            "written_at": datetime.now(timezone.utc).isoformat(),
            "count": len(non_commons),
            "note": (
                "Images found in Wikipedia pageimages but hosted on a specific language "
                "wiki rather than Commons. Metadata fetching would require per-wiki "
                "API calls. Almost all are non-free, so export filters them out."
            ),
            "files": [
                {"filename": f, **info} for f, info in sorted(non_commons.items())
            ],
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        logger.info(
            "Recorded %d non-Commons images -> %s", len(non_commons), out_path.name
        )

    def _download_images(self, filenames: list[str]) -> None:
        """Download source bytes for each filename (if not already on disk)."""
        to_download = [f for f in filenames if not source_path(f).exists()]
        logger.info(
            "Commons images: %s total, %s to download",
            f"{len(filenames):,}",
            f"{len(to_download):,}",
        )
        if not to_download:
            return

        failed = 0
        for filename in tqdm(to_download, desc="Commons images", unit="img"):
            encoded = quote(filename)
            target = source_path(filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not self._download_one(
                f"https://commons.wikimedia.org/wiki/Special:FilePath/{encoded}",
                target,
            ):
                failed += 1
            time.sleep(AFTER_REQUEST_DELAY_SECONDS)

        if failed:
            logger.error("Failed to download %d images", failed)

    def _download_one(self, url: str, out_path: Path) -> bool:
        """Download a single image URL to disk. Returns True on success."""
        if out_path.exists():
            return True
        try:
            response = self._request(url)
            response.raise_for_status()
        except Exception:
            logger.error("Failed to download %s", url)
            return False
        out_path.write_bytes(response.content)
        return True

    def _request(self, url: str, **kwargs: object) -> Response:
        """HTTP request with retry on 429 Too Many Requests."""
        while True:
            response = self.client.get(url, timeout=60.0, **kwargs)  # type: ignore[arg-type]
            if response.status_code == 429:
                retry_after = int(response.headers.get("retry-after", 60))
                logger.warning("Commons 429 — sleeping %ds", retry_after)
                time.sleep(retry_after)
                continue
            return response

    def _fetch_metadata(self, filenames: list[str]) -> None:
        """Fetch image metadata (license, description, author, ...) from Commons.

        Bulk-queries ``METADATA_BATCH_SIZE`` filenames at a time with
        ``iiextmetadatamultilang=1`` so every language variant lands in one file.
        Writes ``metadata.json`` under each image's dir with the ``license_servable``
        flag precomputed. Existing files are skipped.
        """
        pending = [f for f in filenames if not download_metadata_path(f).exists()]
        logger.info(
            "Commons metadata: %s total, %s to fetch",
            f"{len(filenames):,}",
            f"{len(pending):,}",
        )
        if not pending:
            return

        missing_pages = 0
        with tqdm(total=len(pending), desc="Commons metadata", unit="file") as pbar:
            for batch in batched(pending, METADATA_BATCH_SIZE):
                missing_pages += self._fetch_metadata_batch(list(batch))
                pbar.update(len(batch))
                time.sleep(AFTER_REQUEST_DELAY_SECONDS)

        if missing_pages:
            logger.warning(
                "%d Commons metadata pages returned as missing "
                "(image likely deleted/renamed upstream)",
                missing_pages,
            )

    def _fetch_metadata_batch(self, filenames: list[str]) -> int:
        """Fetch one batch of metadata. Returns the count of missing pages."""
        titles = "|".join(f"File:{f}" for f in filenames)
        try:
            response = self._request(
                "https://commons.wikimedia.org/w/api.php",
                params={
                    "action": "query",
                    "prop": "imageinfo",
                    "iiprop": "extmetadata|url|mime|size|sha1|user|timestamp",
                    "iiextmetadatamultilang": 1,
                    "titles": titles,
                    "format": "json",
                    "formatversion": 2,
                },
            )
            response.raise_for_status()
        except Exception:
            logger.error("Failed to fetch metadata batch of %d files", len(filenames))
            return 0

        data = response.json()
        pages = data.get("query", {}).get("pages", [])
        # API may normalize titles (e.g. spaces <-> underscores); map back.
        normalized = {
            n["to"]: n["from"] for n in data.get("query", {}).get("normalized", [])
        }

        fetched_at = datetime.now(timezone.utc).isoformat()
        missing = 0
        for page in pages:
            api_title = page.get("title", "")
            original_title = normalized.get(api_title, api_title)
            filename = canonical_filename(original_title.removeprefix("File:"))

            if page.get("missing"):
                logger.warning("No metadata for File:%s (missing on Commons)", filename)
                missing += 1
                # Persist a stub so downstream phases can tell "we tried" from
                # "we haven't looked yet" and don't re-queue this file every run.
                image_dir(filename).mkdir(parents=True, exist_ok=True)
                write_download_metadata(
                    filename,
                    {
                        "filename": filename,
                        "fetched_at": fetched_at,
                        "missing": True,
                        "license_servable": False,
                    },
                )
                continue

            imageinfo = page.get("imageinfo") or []
            if not imageinfo:
                logger.warning("No imageinfo returned for File:%s", filename)
                continue

            info = imageinfo[0]
            em = info.get("extmetadata") or {}
            servable, reason = license_is_servable(em)
            if not servable:
                logger.info(
                    "Image %s not servable: %s",
                    filename,
                    reason or "license check failed",
                )

            image_dir(filename).mkdir(parents=True, exist_ok=True)
            # ``pageid`` (and the ``M<pageid>`` MediaInfo form) survive Commons
            # renames where filenames do not; ``sha1`` content-addresses the
            # file bytes. Captured for future use — nothing reads them yet.
            write_download_metadata(
                filename,
                {
                    "filename": filename,
                    "pageid": page.get("pageid"),
                    "sha1": info.get("sha1"),
                    "fetched_at": fetched_at,
                    "imageinfo": info,
                    "license_servable": servable,
                },
            )

        return missing
