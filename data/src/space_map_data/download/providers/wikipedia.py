"""Download Wikipedia page summaries for Wikidata-matched objects."""

import json
import logging
import time
from collections import defaultdict
from itertools import islice
from pathlib import Path
from typing import Iterator, NamedTuple

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


class Task(NamedTuple):
    """One page to fetch. ``follow_redirects`` is set for the curated concept
    pages only — see :meth:`WikipediaDownloader._fetch_batch`."""

    qid: str
    title: str
    follow_redirects: bool


def _batched(iterable: list[Task], n: int) -> Iterator[list[Task]]:
    """Yield successive n-sized chunks from a list."""
    it = iter(iterable)
    while batch := list(islice(it, n)):
        yield batch


def _is_redirect_stub(path: Path) -> bool:
    """Whether a stored page is a redirect with nothing on it.

    The API answers a redirect title with the stub itself, extract empty, so
    such a file is a fetch that has to be redone rather than a page with no
    intro.
    """
    try:
        page = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return bool(page.get("redirect")) and not (page.get("extract") or "").strip()


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
    ) -> dict[str, list[Task]]:
        """Read Wikidata entity files and extract sitelinks for target languages.

        Scans every dir in *wikidata_dirs* plus any *extra_files*, skipping
        already-downloaded summaries and de-duplicating tasks on (qid, lang).
        Returns dict mapping language code to the pages to fetch.

        *extra_files* are the curated concept pages, which resolve redirects and
        so are re-fetched when what's on disk is a redirect stub from before
        that was so.
        """
        curated = {path.stem for path in extra_files or ()}
        by_lang: dict[str, list[Task]] = defaultdict(list)
        seen: set[tuple[str, str]] = set()
        skipped = 0
        refetched: list[str] = []

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
                stored = self.out_dir / lang / f"{qid}.json"
                if stored.exists():
                    if not (qid in curated and _is_redirect_stub(stored)):
                        skipped += 1
                        continue
                    refetched.append(f"{lang}/{qid}")
                title = sitelinks[wiki_key]["title"]
                by_lang[lang].append((Task(qid, title, qid in curated)))

        total = sum(len(items) for items in by_lang.values())
        logger.info(
            "Found %s summaries to fetch (%s already on disk) from %d entities "
            "across %d dir(s)",
            f"{total:,}",
            f"{skipped:,}",
            len(entity_files),
            len(wikidata_dirs),
        )
        if refetched:
            logger.info(
                "Re-fetching %d curated page(s) stored as redirect stubs: %s",
                len(refetched),
                ", ".join(sorted(refetched)),
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
        tasks_by_lang: dict[str, list[Task]],
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

                # Redirect resolution is a per-request switch, so the two kinds
                # of page cannot share a batch.
                for follow in (False, True):
                    group = [task for task in items if task.follow_redirects is follow]
                    for batch in _batched(group, BATCH_SIZE):
                        self._fetch_batch(lang, batch, out_dir, follow_redirects=follow)
                        pbar.update(len(batch))
                        time.sleep(AFTER_REQUEST_DELAY_SECONDS)

    def _fetch_batch(
        self,
        lang: str,
        batch: list[Task],
        out_dir: Path,
        *,
        follow_redirects: bool,
    ) -> None:
        """Fetch and save a single batch of pages from the Action API.

        Redirects are followed only for the curated concept pages. An object's
        sitelink usually redirects into a list ("7509 Gamzatov" →
        "List of minor planets: 7001–8000"), whose lead is about the list and
        not the object; a concept's redirects to the article that took the
        subject over (en "Planetary ring" → "Ring system"), which is the page
        the blurb wants.
        """
        params: dict[str, object] = {
            "action": "query",
            "prop": "extracts|pageimages|description|info",
            "inprop": "url",
            "exintro": True,
            "explaintext": True,
            "piprop": "thumbnail|original",
            "pithumbsize": 300,
            "titles": "|".join(task.title for task in batch),
            "format": "json",
            "formatversion": 2,
        }
        # An API boolean is true whenever it is present, whatever its value, so
        # not following redirects means leaving the parameter out entirely.
        if follow_redirects:
            params["redirects"] = True

        try:
            response = self._request(
                f"https://{lang}.wikipedia.org/w/api.php",
                params=params,
            )
            response.raise_for_status()
        except Exception:
            logger.warning(
                "Failed to fetch batch of %d pages for %s",
                len(batch),
                lang,
            )
            return

        query = response.json().get("query", {})
        pages = {page.get("title", ""): page for page in query.get("pages", [])}
        # Both hops the API may report, walked from the title we asked for:
        # normalization first, then the redirect it lands on. A redirect to a
        # *section* is kept apart from one to a whole page.
        hops = {
            hop["from"]: (hop["to"], hop.get("tofragment"))
            for key in ("normalized", "redirects")
            for hop in query.get(key, [])
        }

        for task in batch:
            title = task.title
            sectioned = False
            walked: set[str] = set()
            while title in hops and title not in walked:
                walked.add(title)
                title, fragment = hops[title]
                sectioned = sectioned or fragment is not None

            # A subject folded into a section of a broader article ("Cassini
            # Division" → "Rings of Saturn#Cassini Division") leaves the lead
            # about the parent, so there is nothing here to quote.
            if sectioned:
                logger.info(
                    "Redirects into a section, no summary: %s/%s (%s → %s)",
                    lang,
                    task.qid,
                    task.title,
                    title,
                )
                continue

            page = pages.get(title)
            if page is None:
                logger.debug("No page returned for %s/%s (%s)", lang, task.qid, title)
                continue
            if page.get("missing"):
                logger.debug("No article: %s/%s (%s)", lang, task.qid, title)
                continue
            if not (page.get("extract") or "").strip():
                logger.debug(
                    "Empty extract, saving anyway: %s/%s (%s)", lang, task.qid, title
                )

            out_file = out_dir / f"{task.qid}.json"
            out_file.write_text(json.dumps(page, ensure_ascii=False, indent=2))
