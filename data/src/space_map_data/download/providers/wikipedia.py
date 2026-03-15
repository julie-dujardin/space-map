"""Download Wikipedia page summaries for Wikidata-matched objects."""

import json
import logging
import time
from pathlib import Path
from urllib.parse import quote

from httpx import Response
from tqdm import tqdm

from space_map_data.download.downloader import Downloader

logger = logging.getLogger(__name__)

LANGUAGES = ("en", "fr", "ja", "zh", "ar", "ru")

AFTER_RQUEST_DELAY_SECONDS = 1


class WikipediaDownloader(Downloader):
    name = "wikipedia"

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        wikidata_dir = self.out_dir.parent / "wikidata" / "entities"
        if not wikidata_dir.exists():
            raise FileNotFoundError(
                f"Wikidata entities not found at {wikidata_dir} "
                "— download wikidata first"
            )

        tasks = self._collect_tasks(wikidata_dir)
        if not tasks:
            logger.info("No sitelinks found for target languages")
            return

        self._fetch_summaries(tasks, limit=limit)

        self._save_metadata(
            "https://en.wikipedia.org/api/rest_v1/page/summary/",
            len(tasks),
            complete=limit is None or len(tasks) <= limit,
        )

    def _collect_tasks(self, wikidata_dir: Path) -> list[tuple[str, str, str]]:
        """Read Wikidata entity files and extract sitelinks for target languages.

        Returns list of (qid, lang, title) tuples.
        """
        tasks: list[tuple[str, str, str]] = []

        entity_files = sorted(wikidata_dir.glob("Q*.json"))
        for entity_file in entity_files:
            qid = entity_file.stem
            entity = json.loads(entity_file.read_text())
            sitelinks = entity.get("sitelinks", {})

            for lang in LANGUAGES:
                wiki_key = f"{lang}wiki"
                if wiki_key in sitelinks:
                    title = sitelinks[wiki_key]["title"]
                    tasks.append((qid, lang, title))

        logger.info(
            "Found %s summaries to fetch across %d languages from %d entities",
            f"{len(tasks):,}",
            len(LANGUAGES),
            len(entity_files),
        )
        return tasks

    def _get_page(self, url: str) -> Response:
        """Fetch a Wikipedia page, with retry on 429 Too Many Requests."""
        while True:
            response = self.client.get(url, timeout=30.0)

            if response.status_code == 429:
                retry_after = int(response.headers.get("retry-after", 60))
                logger.warning("Wikipedia 429 — sleeping %ds", retry_after)
                time.sleep(retry_after)
            else:
                return response

    def _fetch_summaries(
        self, tasks: list[tuple[str, str, str]], *, limit: int | None
    ) -> None:
        """Fetch Wikipedia summaries, skipping already downloaded."""
        # Filter out already-downloaded summaries
        to_fetch = [
            (qid, lang, title)
            for qid, lang, title in tasks
            if not (self.out_dir / lang / f"{qid}.json").exists()
        ]
        if limit is not None:
            to_fetch = to_fetch[:limit]

        if not to_fetch:
            logger.info("All summaries already downloaded")
            return

        logger.info(
            "Fetching %s summaries (%s already on disk)",
            f"{len(to_fetch):,}",
            f"{len(tasks) - len(to_fetch):,}",
        )

        for qid, lang, title in tqdm(to_fetch, desc="Wikipedia summaries", unit="page"):
            url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(title, safe='')}"

            try:
                response = self._get_page(url)
            except Exception:
                logger.warning("Failed to fetch %s/%s (%s)", lang, qid, title)
                continue

            if response.status_code == 404:
                logger.debug("No article: %s/%s (%s)", lang, qid, title)
                continue

            response.raise_for_status()

            out_dir = self.out_dir / lang
            out_dir.mkdir(exist_ok=True)
            out_file = out_dir / f"{qid}.json"
            out_file.write_bytes(response.content)

            time.sleep(AFTER_RQUEST_DELAY_SECONDS)
