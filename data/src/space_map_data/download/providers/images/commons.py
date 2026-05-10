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
    read_download_metadata,
    source_path,
    write_download_metadata,
)
from space_map_data.utils.commons_wikitext import parse_wikitext
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
        self._fetch_sdc(to_process)

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
        flag precomputed.

        Existing files are skipped unless they pre-date the ``wikitext`` field
        (added together with derivative-of / other-versions parsing) — those
        get re-fetched so the metadata schema converges across the corpus.
        ``missing: true`` stubs stay skipped: the file is gone upstream, no
        amount of re-fetching brings it back.
        """
        pending = [f for f in filenames if _needs_metadata_refresh(f)]
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
        """Fetch one batch of metadata. Returns the count of missing pages.

        Asks for ``imageinfo`` (license, dimensions, EXIF-derived dates) and
        ``revisions`` (raw wikitext) in the same call — the API supports both
        in a single ``query`` action. Wikitext gives us derivative-of and
        other-versions links that no structured field exposes.
        """
        titles = "|".join(f"File:{f}" for f in filenames)
        try:
            response = self._request(
                "https://commons.wikimedia.org/w/api.php",
                params={
                    "action": "query",
                    "prop": "imageinfo|revisions",
                    "iiprop": "extmetadata|url|mime|size|sha1|user|timestamp",
                    "iiextmetadatamultilang": 1,
                    "rvprop": "content",
                    "rvslots": "main",
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

            wikitext = _extract_wikitext(page)
            derived_from, other_versions = parse_wikitext(wikitext or "")

            image_dir(filename).mkdir(parents=True, exist_ok=True)
            # ``pageid`` (and the ``M<pageid>`` MediaInfo form) survive Commons
            # renames where filenames do not; ``sha1`` content-addresses the
            # file bytes. Wikitext is kept raw so we can re-parse it later if
            # the parser improves, without re-fetching the whole batch.
            write_download_metadata(
                filename,
                {
                    "filename": filename,
                    "pageid": page.get("pageid"),
                    "sha1": info.get("sha1"),
                    "fetched_at": fetched_at,
                    "imageinfo": info,
                    "license_servable": servable,
                    "wikitext": wikitext,
                    "derived_from": derived_from,
                    "other_versions": other_versions,
                },
            )

        return missing

    def _fetch_sdc(self, filenames: list[str]) -> None:
        """Fetch Structured Data on Commons (SDC) for each downloaded file.

        Uses the Wikibase API on the Commons MediaInfo entity ``M<pageid>``
        to retrieve labels, descriptions, and statements (depicts P180,
        creator P170, inception P571, copyright status P6216, based on P144,
        derivative work P4969, ...). The raw entity is merged into the
        existing ``metadata.json`` so the structured fields complement the
        wikitext we already saved.

        Files whose ``metadata.json`` already has an ``sdc`` key (success or
        explicit ``null``) are skipped so the step is resumable.
        """
        targets: list[tuple[str, int]] = []
        for filename in filenames:
            meta = read_download_metadata(filename)
            if not meta:
                continue
            if "sdc" in meta:
                continue
            pageid = meta.get("pageid")
            if not isinstance(pageid, int):
                continue
            targets.append((filename, pageid))

        logger.info(
            "Commons SDC: %s total, %s to fetch",
            f"{len(filenames):,}",
            f"{len(targets):,}",
        )
        if not targets:
            return

        with tqdm(total=len(targets), desc="Commons SDC", unit="file") as pbar:
            for batch in batched(targets, METADATA_BATCH_SIZE):
                self._fetch_sdc_batch(list(batch))
                pbar.update(len(batch))
                time.sleep(AFTER_REQUEST_DELAY_SECONDS)

    def _fetch_sdc_batch(self, batch: list[tuple[str, int]]) -> None:
        """Fetch one batch of SDC entities and merge each into its metadata.json."""
        ids = "|".join(f"M{pageid}" for _, pageid in batch)
        try:
            response = self._request(
                "https://commons.wikimedia.org/w/api.php",
                params={
                    "action": "wbgetentities",
                    "ids": ids,
                    # ``claims`` is the legacy prop name; the response calls
                    # the field ``statements`` for MediaInfo entities.
                    "props": "labels|descriptions|claims",
                    "format": "json",
                    "formatversion": 2,
                },
            )
            response.raise_for_status()
        except Exception:
            logger.error("Failed to fetch SDC batch of %d files", len(batch))
            return

        data = response.json()
        entities = data.get("entities") or {}

        for filename, pageid in batch:
            entity = entities.get(f"M{pageid}")
            sdc: dict | None
            if entity is None:
                logger.warning("No SDC entity for %s (M%d)", filename, pageid)
                sdc = None
            elif entity.get("missing") is not None:
                # MediaInfo entity simply hasn't been created yet — every
                # Commons file gets one lazily. Persist as null so the next
                # run doesn't keep retrying.
                sdc = None
            else:
                sdc = entity

            meta = read_download_metadata(filename)
            if meta is None:
                # imageinfo step didn't produce a file (deleted/renamed).
                continue
            meta["sdc"] = sdc
            write_download_metadata(filename, meta)


def _needs_metadata_refresh(filename: str) -> bool:
    """True if a file's metadata.json should be (re-)fetched.

    Returns True when the file is absent, corrupt, or pre-dates the
    ``wikitext`` schema addition. Returns False for ``missing: true`` stubs
    (image gone upstream) and for entries that already have wikitext.
    """
    path = download_metadata_path(filename)
    if not path.exists():
        return True
    meta = read_download_metadata(filename)
    if meta is None:
        return True
    if meta.get("missing"):
        return False
    return "wikitext" not in meta


def _extract_wikitext(page: dict) -> str | None:
    """Pluck the main-slot wikitext from a ``query`` API page object.

    Returns ``None`` if revisions/slots/content aren't present (e.g. the file
    has no current revision, or the API omitted them for any reason).
    """
    revisions = page.get("revisions") or []
    if not revisions:
        return None
    slots = revisions[0].get("slots") or {}
    main = slots.get("main") or {}
    content = main.get("content")
    return content if isinstance(content, str) else None
