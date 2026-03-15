"""Download Wikipedia page summaries for Wikidata-matched objects."""

import json
import logging
import time
from collections import defaultdict
from itertools import islice
from pathlib import Path
from typing import Iterator

from httpx import Response
from tqdm import tqdm

from space_map_data.download.downloader import Downloader

logger = logging.getLogger(__name__)

LANGUAGES = ("en", "fr", "ja", "zh", "ar", "ru")

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
    name = "wikipedia"

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        wikidata_dir = self.out_dir.parent / "wikidata" / "entities"
        if not wikidata_dir.exists():
            raise FileNotFoundError(
                f"Wikidata entities not found at {wikidata_dir} "
                "— download wikidata first"
            )

        tasks_by_lang = self._collect_tasks(wikidata_dir)
        if not tasks_by_lang:
            logger.info("No summaries to fetch")
            return

        self._fetch_summaries(tasks_by_lang, limit=limit)

        total = sum(len(items) for items in tasks_by_lang.values())
        self._save_metadata(
            "https://{lang}.wikipedia.org/w/api.php?action=query",
            total,
            complete=limit is None or total <= limit,
        )

    def _collect_tasks(self, wikidata_dir: Path) -> dict[str, list[tuple[str, str]]]:
        """Read Wikidata entity files and extract sitelinks for target languages.

        Skips already-downloaded summaries.
        Returns dict mapping language code to list of (qid, title) tuples.
        """
        by_lang: dict[str, list[tuple[str, str]]] = defaultdict(list)
        skipped = 0

        entity_files = sorted(wikidata_dir.glob("Q*.json"))
        for entity_file in tqdm(
            entity_files, desc="Collecting Wikipedia tasks", unit="entity"
        ):
            qid = entity_file.stem
            entity = json.loads(entity_file.read_text())
            sitelinks = entity.get("sitelinks", {})

            for lang in LANGUAGES:
                wiki_key = f"{lang}wiki"
                if wiki_key in sitelinks:
                    if (self.out_dir / lang / f"{qid}.json").exists():
                        skipped += 1
                        continue
                    title = sitelinks[wiki_key]["title"]
                    by_lang[lang].append((qid, title))

        total = sum(len(items) for items in by_lang.values())
        logger.info(
            "Found %s summaries to fetch (%s already on disk) from %d entities",
            f"{total:,}",
            f"{skipped:,}",
            len(entity_files),
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
            out_file.write_text(json.dumps(page, ensure_ascii=False))
