"""Download Wikimedia Commons images and their license/description metadata.

Collects image filenames from Wikidata P18/P154 claims plus Wikipedia pageimages, then
downloads the source file and fetches rich metadata (license, author, description in
every language) via the Commons Action API. License servability is evaluated at
download time and persisted into the metadata file so later phases don't re-decide.

On-disk layout (see :mod:`space_map_data.utils.commons_images`)::

    DOWNLOAD_DIR/commons/images/<filename>/source.<ext>
    DOWNLOAD_DIR/commons/images/<filename>/metadata.json

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

import httpx
from httpx import Response
from tqdm import tqdm

from space_map_data.constants.providers import PROVIDERS
from space_map_data.constants.wikidata_topics import topic_page_qids
from space_map_data.download.downloader import Downloader
from space_map_data.export.groups.registry import GROUPS
from space_map_data.utils.commons_images import (
    COMMONS_DIR,
    FEATURE_WIKIDATA_IMAGE_PIDS,
    IMAGES_DIR,
    canonical_filename,
    download_metadata_path,
    extract_wikidata_filenames,
    image_dir,
    is_excluded,
    license_is_servable,
    parse_upload_url,
    read_download_metadata,
    read_manual_extras,
    source_path,
    write_download_metadata,
)
from space_map_data.utils.commons_wikitext import parse_wikitext
from space_map_data.utils.paths import SOURCES_METADATA_DIR

logger = logging.getLogger(__name__)

AFTER_REQUEST_DELAY_SECONDS = 1
METADATA_BATCH_SIZE = 50
# Without this, a flag or logo on 100k+ pages can churn a single batch through
# thousands of requests; scoring only uses len(entries), so saturation is fine.
GLOBALUSAGE_MAX_PAGES_PER_BATCH = 5

# TODO: locally-hosted (non-Commons) images are currently recorded in
# ``non_commons_skipped.json`` and skipped. To actually include them we'd need to hit each
# language wiki's own Action API for imageinfo (commons.wikimedia.org returns "missing"
# for them). Almost all of them are non-free anyway, so export filters them out — revisit
# only if that policy changes.


class CommonsDownloader(Downloader):
    """Download Wikimedia Commons images and their metadata."""

    name = PROVIDERS.COMMONS

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = COMMONS_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        wikidata_root = SOURCES_METADATA_DIR / "wikidata"
        objects_dir = wikidata_root / "objects"
        nomenclature_dir = wikidata_root / "nomenclature"
        referenced_dir = wikidata_root / "referenced"
        if not objects_dir.exists() and not nomenclature_dir.exists():
            raise FileNotFoundError(
                f"None of the Wikidata entity dirs exist under {wikidata_root} "
                "(objects, nomenclature) — download wikidata first"
            )

        IMAGES_DIR.mkdir(parents=True, exist_ok=True)

        commons_filenames, non_commons = self._collect_filenames(
            objects_dir if objects_dir.exists() else None,
            nomenclature_dir if nomenclature_dir.exists() else None,
            referenced_dir if referenced_dir.exists() else None,
        )
        self._write_non_commons_skipped(non_commons)

        discovered = sorted(commons_filenames)
        if limit is not None:
            discovered = discovered[:limit]

        # Metadata first: it's cheap and tells us the derivative graph. We
        # transitively follow ``derived_from`` and ``other_versions`` so the
        # graph covers an image's parents and siblings — different language
        # wikis pick different hero images, and merging their descriptions
        # gives the original richer coverage. Globalusage and SDC each get
        # their own pass (different APIs / pagination needs). Source bytes
        # only get downloaded after, for the original discovery set.
        graph = self._fetch_metadata(discovered)
        self._fetch_globalusage(sorted(graph))
        self._fetch_sdc(sorted(graph))
        self._download_images(discovered)

        self._save_metadata(
            "https://commons.wikimedia.org/w/api.php?action=query&prop=imageinfo",
            len(commons_filenames),
            complete=False,
        )

    def _collect_filenames(
        self,
        objects_dir: Path | None,
        nomenclature_dir: Path | None,
        referenced_dir: Path | None,
    ) -> tuple[set[str], dict[str, dict]]:
        """Collect image filenames from Wikidata claims and Wikipedia summaries.

        Returns ``(commons_filenames, non_commons)`` where ``non_commons`` maps filename
        to ``{"url", "repo", "referenced_from": [lang/QID, ...]}``. Objects contribute
        P18/P154; nomenclature features contribute P18/P242 (locator maps); groups
        (constellations) contribute P18/P154 from their referenced entities.
        """
        commons: set[str] = set()
        non_commons: dict[str, dict] = {}

        # 1) Wikidata image claims — always Commons filenames by policy.
        # Object entities ship P18 (photo) + P154 (logo); nomenclature
        # features ship P18 (photo) + P242 (locator map); groups pull the
        # same PIDs as objects but are registry-driven (referenced/ also
        # holds operators/countries).
        scans: list[tuple[str, list[Path], tuple[str, ...]]] = []
        if objects_dir is not None:
            scans.append(
                ("objects", sorted(objects_dir.glob("Q*.json")), ("P18", "P154"))
            )
        if nomenclature_dir is not None:
            scans.append(
                (
                    "nomenclature",
                    sorted(nomenclature_dir.glob("Q*.json")),
                    FEATURE_WIKIDATA_IMAGE_PIDS,
                )
            )
        if referenced_dir is not None:
            scans.append(
                ("groups", self._group_entity_files(referenced_dir), ("P18", "P154"))
            )
            # Topic pages carry a single illustrative P18 and no logo.
            scans.append(("topics", self._topic_entity_files(referenced_dir), ("P18",)))
        for label, entity_files, pids in scans:
            for entity_file in tqdm(
                entity_files,
                desc=f"Scanning Wikidata ({label}) for images",
                unit="entity",
            ):
                try:
                    entity = json.loads(entity_file.read_text())
                except json.JSONDecodeError:
                    logger.warning("Skipping invalid entity file %s", entity_file)
                    continue
                commons |= extract_wikidata_filenames(entity, pids)

        # 2) Wikipedia pageimages — split commons vs local wiki based on URL.
        wiki_dir = SOURCES_METADATA_DIR / "wikipedia"
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

        # 3) Manually-curated extras keyed by Object.id. Only the filenames
        # matter here — the per-object mapping is consumed downstream by
        # ``image_selection`` to merge them into ``object_images.json``.
        manual_files: set[str] = set()
        for entries in read_manual_extras().values():
            for entry in entries:
                manual_files.add(entry["file"])
        manual_files = {f for f in manual_files if not is_excluded(f)}
        new_manual = manual_files - commons
        commons |= manual_files
        if new_manual:
            logger.info("Added %d filename(s) from manual-extra.json", len(new_manual))

        logger.info(
            "Commons filenames: %s unique; non-Commons (local wiki): %s",
            f"{len(commons):,}",
            f"{len(non_commons):,}",
        )
        return commons, non_commons

    @staticmethod
    def _topic_entity_files(referenced_dir: Path) -> list[Path]:
        """Resolve detail-panel topic QIDs to entity files under ``referenced/``."""
        return [
            path
            for qid in sorted(topic_page_qids())
            if (path := referenced_dir / f"{qid}.json").exists()
        ]

    @staticmethod
    def _group_entity_files(referenced_dir: Path) -> list[Path]:
        """Resolve registered group QIDs to entity files under ``referenced/``."""
        out: list[Path] = []
        for group in GROUPS:
            if group.wikidata_qid is None:
                continue
            path = referenced_dir / f"{group.wikidata_qid}.json"
            if path.exists():
                out.append(path)
        return out

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

    def _fetch_metadata(self, filenames: list[str]) -> set[str]:
        """Fetch metadata for ``filenames`` and follow derivative links transitively.

        Bulk-queries ``METADATA_BATCH_SIZE`` filenames at a time with
        ``iiextmetadatamultilang=1`` so every language variant lands in one
        file. Writes ``metadata.json`` under each image's dir with the
        ``license_servable`` flag precomputed.

        After each batch, parsed ``derived_from`` (parents) and
        ``other_versions`` (siblings/children) join the BFS frontier so we
        end up with a connected derivative graph — useful for the export
        step, which can later merge richer descriptions/categories from
        derivatives back into the original.

        Existing files are skipped unless they pre-date the ``wikitext``
        field (added together with derivative-of parsing) — those get
        re-fetched so the schema converges. ``missing: true`` stubs stay
        skipped: the file is gone upstream.

        Returns the full set of filenames whose metadata is now on disk
        (initial discovery set ∪ everything we descended into).
        """
        graph: set[str] = set()
        frontier: set[str] = {f for f in filenames if not is_excluded(f)}
        iteration = 0
        total_missing = 0

        while frontier:
            iteration += 1
            graph |= frontier

            to_fetch = sorted(f for f in frontier if _needs_metadata_refresh(f))
            already_have = sorted(f for f in frontier if not _needs_metadata_refresh(f))

            logger.info(
                "Commons metadata iter %d: frontier=%s, to_fetch=%s (graph total=%s)",
                iteration,
                f"{len(frontier):,}",
                f"{len(to_fetch):,}",
                f"{len(graph):,}",
            )

            new_links: set[str] = set()

            if to_fetch:
                desc = (
                    "Commons metadata"
                    if iteration == 1
                    else f"Commons metadata iter {iteration}"
                )
                with tqdm(total=len(to_fetch), desc=desc, unit="file") as pbar:
                    for batch in batched(to_fetch, METADATA_BATCH_SIZE):
                        missing, links = self._fetch_metadata_batch(list(batch))
                        total_missing += missing
                        new_links |= links
                        pbar.update(len(batch))
                        time.sleep(AFTER_REQUEST_DELAY_SECONDS)

            # Pick up graph links from files that were already on disk so
            # re-runs keep expanding the graph instead of plateauing on the
            # initial discovery set.
            for f in already_have:
                meta = read_download_metadata(f)
                if not meta:
                    continue
                new_links.update(meta.get("derived_from") or ())
                new_links.update(meta.get("other_versions") or ())

            # Advance: drop excluded filenames and anything we've already seen.
            frontier = {
                f for f in new_links if f and f not in graph and not is_excluded(f)
            }

        if total_missing:
            logger.warning(
                "%d Commons metadata pages returned as missing "
                "(image likely deleted/renamed upstream)",
                total_missing,
            )
        return graph

    def _fetch_metadata_batch(self, filenames: list[str]) -> tuple[int, set[str]]:
        """Fetch one batch of metadata.

        Asks for ``imageinfo`` (license, dimensions, EXIF-derived dates) and
        ``revisions`` (raw wikitext) in the same call — the API supports both
        in a single ``query`` action. Wikitext gives us derivative-of and
        other-versions links that no structured field exposes.

        Returns ``(missing_count, links)`` where ``links`` is the union of
        ``derived_from`` (parents) and ``other_versions`` (siblings/children)
        across the batch — feeds the BFS expansion in :meth:`_fetch_metadata`.
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
            return 0, set()

        data = response.json()
        pages = data.get("query", {}).get("pages", [])
        # API may normalize titles (e.g. spaces <-> underscores); map back.
        normalized = {
            n["to"]: n["from"] for n in data.get("query", {}).get("normalized", [])
        }

        fetched_at = datetime.now(timezone.utc).isoformat()
        missing = 0
        links: set[str] = set()
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
            links.update(derived_from)
            links.update(other_versions)

            image_dir(filename).mkdir(parents=True, exist_ok=True)
            # Read-merge-write so ``sdc`` and ``globalusage`` from later
            # steps (each in its own pass) survive a metadata refresh.
            # ``pageid`` (and the ``M<pageid>`` MediaInfo form) survive
            # Commons renames where filenames do not; ``sha1`` content-
            # addresses the file bytes. Wikitext is kept raw so we can
            # re-parse it later without re-fetching the whole batch.
            existing = read_download_metadata(filename) or {}
            existing.pop("missing", None)  # file is reachable now
            existing.update(
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
                }
            )
            write_download_metadata(filename, existing)

        return missing, links

    def _fetch_globalusage(self, filenames: list[str]) -> None:
        """Fetch globalusage (cross-wiki page references) per file.

        Persists entries under ``metadata["globalusage"]``. Resumable — files
        with the field already set are skipped. Counts may saturate for very
        popular files; scoring only uses ``len(entries)`` so that's fine.
        """
        targets: list[str] = []
        for f in filenames:
            meta = read_download_metadata(f) or {}
            if meta.get("missing"):
                continue
            if "globalusage" in meta:
                continue
            targets.append(f)
        logger.info(
            "Commons globalusage: %s total, %s to fetch",
            f"{len(filenames):,}",
            f"{len(targets):,}",
        )
        if not targets:
            return

        with tqdm(total=len(targets), desc="Commons globalusage", unit="file") as pbar:
            for batch in batched(targets, METADATA_BATCH_SIZE):
                self._fetch_globalusage_batch(list(batch))
                pbar.update(len(batch))
                time.sleep(AFTER_REQUEST_DELAY_SECONDS)

    def _fetch_globalusage_batch(self, filenames: list[str]) -> None:
        """Paginate ``globalusage`` for one batch and merge into metadata.json.

        Capped at ``GLOBALUSAGE_MAX_PAGES_PER_BATCH``; titles the cursor
        never reached are retried one at a time.
        """
        titles = "|".join(f"File:{f}" for f in filenames)
        params: dict[str, object] = {
            "action": "query",
            "prop": "globalusage",
            "gulimit": "max",
            "titles": titles,
            "format": "json",
            "formatversion": 2,
        }
        # Accumulate across continuation pages: filename -> list of entries.
        accumulated: dict[str, list[dict]] = {f: [] for f in filenames}
        normalized_map: dict[str, str] = {}
        pages_fetched = 0
        capped = False

        while True:
            try:
                response = self._request(
                    "https://commons.wikimedia.org/w/api.php", params=params
                )
                response.raise_for_status()
            except Exception:
                logger.error(
                    "Failed to fetch globalusage batch of %d files", len(filenames)
                )
                return

            data = response.json()
            pages_fetched += 1
            for n in data.get("query", {}).get("normalized", []) or []:
                normalized_map[n["to"]] = n["from"]
            for page in data.get("query", {}).get("pages", []) or []:
                api_title = page.get("title", "")
                original = normalized_map.get(api_title, api_title)
                filename = canonical_filename(original.removeprefix("File:"))
                if filename not in accumulated:
                    continue
                for entry in page.get("globalusage") or []:
                    accumulated[filename].append(entry)

            cont = data.get("continue")
            if not cont:
                break
            if pages_fetched >= GLOBALUSAGE_MAX_PAGES_PER_BATCH:
                capped = True
                break
            # Carry continuation tokens forward; replace any prior values.
            params = {**params, **cont}
            time.sleep(AFTER_REQUEST_DELAY_SECONDS)

        for filename, entries in accumulated.items():
            meta = read_download_metadata(filename)
            if meta is None:
                continue
            meta["globalusage"] = entries
            write_download_metadata(filename, meta)

        if not capped:
            return
        # Cursor parked inside a popular file; titles after it never got served.
        blocked = [f for f in filenames if not accumulated[f]]
        if not blocked:
            return
        logger.info(
            "Commons globalusage: batch capped after %d pages; "
            "retrying %d blocked files individually",
            pages_fetched,
            len(blocked),
        )
        for f in blocked:
            time.sleep(AFTER_REQUEST_DELAY_SECONDS)
            self._fetch_globalusage_batch([f])

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
