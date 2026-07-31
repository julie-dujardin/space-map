"""Download Wikipedia page summaries for Wikidata-matched objects."""

import json
import logging
import time
from collections import defaultdict
from itertools import islice
from pathlib import Path
from typing import Iterator

import httpx
from httpx import Response
from space_map_data.constants.nomenclature.quadrangles import quadrangle_qids
from space_map_data.constants.providers import LANGUAGES
from space_map_data.constants.wikidata_topics import topic_page_qids
from space_map_data.export.groups.registry import GROUPS
from space_map_data.utils.paths import SOURCES_METADATA_DIR
from tqdm import tqdm

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader

logger = logging.getLogger(__name__)

AFTER_REQUEST_DELAY_SECONDS = 1
BATCH_SIZE = 20


def _batched(
    iterable: list[tuple[str, str]], n: int
) -> Iterator[list[tuple[str, str]]]:
    """Yield successive n-sized chunks from a list."""
    it = iter(iterable)
    while batch := list(islice(it, n)):
        yield batch


class WikipediaDownloader(Downloader):
    name = PROVIDERS.WIKIPEDIA

    # Wikidata entity subdirs to scan for sitelinks. Each holds a different
    # primary entity class (objects / IAU nomenclature features / hand-authored
    # manual objects); all expose `sitelinks.<lang>wiki`, so the task collector
    # treats them uniformly.
    _ENTITY_SUBDIRS = ("objects", "nomenclature", "manual")

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = SOURCES_METADATA_DIR / "wikipedia"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        wikidata_dir = SOURCES_METADATA_DIR / "wikidata"
        entity_dirs = [wikidata_dir / sub for sub in self._ENTITY_SUBDIRS]
        present = [d for d in entity_dirs if d.exists()]
        if not present:
            raise FileNotFoundError(
                f"None of the Wikidata entity dirs exist under {wikidata_dir} "
                f"({', '.join(self._ENTITY_SUBDIRS)}) — download wikidata first"
            )

        extra = (
            self._group_entity_files()
            + self._quadrangle_entity_files()
            + self._topic_entity_files()
        )
        tasks_by_lang = self._collect_tasks(present, extra)
        if not tasks_by_lang:
            logger.info("No summaries to fetch")
            return

        self._fetch_summaries(tasks_by_lang, limit=limit)

        total = sum(len(items) for items in tasks_by_lang.values())
        self._save_metadata(
            "https://{lang}.wikipedia.org/w/api.php?action=query",
            total,
            complete=False,  # No global complete is needed
        )

    def _group_entity_files(self) -> list[Path]:
        """Group QIDs are stored alongside other referenced entities, not in the
        scanned subdirs — pick them out explicitly from the GROUPS registry."""
        referenced = SOURCES_METADATA_DIR / "wikidata" / "referenced"
        files: list[Path] = []
        for group in GROUPS:
            if group.wikidata_qid is None:
                continue
            path = referenced / f"{group.wikidata_qid}.json"
            if path.exists():
                files.append(path)
        return files

    def _quadrangle_entity_files(self) -> list[Path]:
        """IAU quadrangles are referenced entities too — their articles back the
        Surface tab's description of a selected chart."""
        referenced = SOURCES_METADATA_DIR / "wikidata" / "referenced"
        return [
            path
            for qid in sorted(quadrangle_qids())
            if (path := referenced / f"{qid}.json").exists()
        ]

    def _topic_entity_files(self) -> list[Path]:
        """Detail-panel topic pages (atmosphere, interior, rings, concepts).

        Coverage across these is uneven and deliberately not filled in from
        English, so a QID missing a sitelink for a language simply yields no
        task for it.
        """
        referenced = SOURCES_METADATA_DIR / "wikidata" / "referenced"
        return [
            path
            for qid in sorted(topic_page_qids())
            if (path := referenced / f"{qid}.json").exists()
        ]

    def _collect_tasks(
        self,
        wikidata_dirs: list[Path],
        extra_files: list[Path] | None = None,
    ) -> dict[str, list[tuple[str, str]]]:
        """Read Wikidata entity files and extract sitelinks for target languages.

        Scans every dir in *wikidata_dirs* plus any *extra_files*, skipping
        already-downloaded summaries and de-duplicating tasks on (qid, lang).
        Returns dict mapping language code to list of (qid, title) tuples.
        """
        by_lang: dict[str, list[tuple[str, str]]] = defaultdict(list)
        seen: set[tuple[str, str]] = set()
        skipped = 0

        entity_files = sorted(f for d in wikidata_dirs for f in d.glob("Q*.json"))
        entity_files.extend(extra_files or [])
        for entity_file in tqdm(
            entity_files, desc="Collecting Wikipedia tasks", unit="entity"
        ):
            qid = entity_file.stem
            entity = json.loads(entity_file.read_text())
            sitelinks = entity.get("sitelinks", {})

            for lang in LANGUAGES:
                wiki_key = f"{lang}wiki"
                if wiki_key not in sitelinks:
                    continue
                if (qid, lang) in seen:
                    continue
                seen.add((qid, lang))
                if (self.out_dir / lang / f"{qid}.json").exists():
                    skipped += 1
                    continue
                title = sitelinks[wiki_key]["title"]
                by_lang[lang].append((qid, title))

        total = sum(len(items) for items in by_lang.values())
        logger.info(
            "Found %s summaries to fetch (%s already on disk) from %d entities "
            "across %d dir(s)",
            f"{total:,}",
            f"{skipped:,}",
            len(entity_files),
            len(wikidata_dirs),
        )
        return by_lang

    def _request(self, url: str, **kwargs: object) -> Response:
        """Make an HTTP request, with retry on 429 Too Many Requests."""
        while True:
            response = self.client.get(url, timeout=30.0, **kwargs)  # type: ignore[arg-type]

            if response.status_code == 429:
                retry_after = int(response.headers.get("retry-after", 60))
                logger.warning("Wikipedia 429 — sleeping %ds", retry_after)
                time.sleep(retry_after)
            else:
                return response

    def _fetch_summaries(
        self,
        tasks_by_lang: dict[str, list[tuple[str, str]]],
        *,
        limit: int | None,
    ) -> None:
        """Fetch Wikipedia summaries in batches."""
        total = sum(len(items) for items in tasks_by_lang.values())

        with tqdm(total=total, desc="Wikipedia summaries", unit="page") as pbar:
            remaining = limit
            for lang, items in tasks_by_lang.items():
                if remaining is not None:
                    items = items[:remaining]
                    remaining -= len(items)
                if not items:
                    continue

                out_dir = self.out_dir / lang
                out_dir.mkdir(exist_ok=True)

                for batch in _batched(items, BATCH_SIZE):
                    self._fetch_batch(lang, batch, out_dir)
                    pbar.update(len(batch))
                    time.sleep(AFTER_REQUEST_DELAY_SECONDS)

    def _fetch_batch(
        self,
        lang: str,
        batch: list[tuple[str, str]],
        out_dir: Path,
    ) -> None:
        """Fetch and save a single batch of pages from the Action API."""
        title_to_qid = {title: qid for qid, title in batch}
        titles = "|".join(title for _, title in batch)

        try:
            response = self._request(
                f"https://{lang}.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "prop": "extracts|pageimages|description|info",
                    "inprop": "url",
                    "exintro": True,
                    "explaintext": True,
                    "piprop": "thumbnail|original",
                    "pithumbsize": 300,
                    "titles": titles,
                    "format": "json",
                    "formatversion": 2,
                },
            )
            response.raise_for_status()
        except Exception:
            logger.warning(
                "Failed to fetch batch of %d pages for %s",
                len(batch),
                lang,
            )
            return

        data = response.json()
        pages = data.get("query", {}).get("pages", [])

        for page in pages:
            title = page.get("title", "")
            qid = title_to_qid.get(title)
            if qid is None:
                # Title may have been normalized by the API
                normalized = {
                    n["from"]: n["to"]
                    for n in data.get("query", {}).get("normalized", [])
                }
                for orig, norm in normalized.items():
                    if norm == title and orig in title_to_qid:
                        qid = title_to_qid[orig]
                        break

            if qid is None:
                logger.debug("Could not map page back to QID: %s", title)
                continue

            if page.get("missing"):
                logger.debug("No article: %s/%s (%s)", lang, qid, title)
                continue

            out_file = out_dir / f"{qid}.json"
            out_file.write_text(json.dumps(page, ensure_ascii=False, indent=2))
