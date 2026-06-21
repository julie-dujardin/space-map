"""Load and extract Wikipedia summaries for export."""

import orjson
import logging
from dataclasses import dataclass

from space_map_data.constants.providers import LANGUAGES
from space_map_data.utils.paths import SOURCES_METADATA_DIR

logger = logging.getLogger(__name__)


@dataclass
class WikipediaSummary:
    extract: str | None = None
    description: str | None = None
    url: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


def load_wikipedia_summaries_for_qid(qid: str) -> dict[str, WikipediaSummary]:
    """Load Wikipedia summaries for a single QID. Returns {lang: WikipediaSummary}."""
    wiki_dir = SOURCES_METADATA_DIR / "wikipedia"
    result: dict[str, WikipediaSummary] = {}
    for lang in LANGUAGES:
        path = wiki_dir / lang / f"{qid}.json"
        if not path.exists():
            continue
        page = orjson.loads(path.read_bytes())
        summary = _extract_wikipedia(page)
        if summary:
            result[lang] = summary
    return result


def load_wikipedia_sections_for_qid(qid: str) -> dict[str, WikipediaSummary]:
    """Curated article-section extract, hand-placed under wikipedia_sections/.

    English is the source; locales without their own file fall back to it. Same
    shape as :func:`load_wikipedia_summaries_for_qid` so callers can merge it
    over the (often sparse) Wikidata sitelink summary.
    """
    sections_dir = SOURCES_METADATA_DIR / "wikipedia_sections"

    def _load(lang: str) -> WikipediaSummary | None:
        path = sections_dir / lang / f"{qid}.json"
        return (
            _extract_wikipedia(orjson.loads(path.read_bytes()))
            if path.exists()
            else None
        )

    fallback = _load("en")
    result: dict[str, WikipediaSummary] = {}
    for lang in LANGUAGES:
        if summary := (_load(lang) or fallback):
            result[lang] = summary
    return result


def _extract_wikipedia(page: dict) -> WikipediaSummary | None:
    """Extract display-relevant fields from a Wikipedia API response."""
    if page.get("missing"):
        return None
    summary = WikipediaSummary(
        extract=page.get("extract") or None,
        description=page.get("description") or None,
        url=page.get("fullurl") or None,
    )
    if not summary.to_dict():
        return None
    return summary
