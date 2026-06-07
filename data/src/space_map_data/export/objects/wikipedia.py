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
    # Plain pageimage URLs from the Action API — bypass the object image
    # pipeline. Currently consumed only by group bundles.
    thumbnail_url: str | None = None
    image_url: str | None = None

    # Fields that ride alongside the text summary but are surfaced elsewhere
    # (group bundle header) — not part of the object `wikipedia` section.
    _DICT_EXCLUDE = frozenset({"thumbnail_url", "image_url"})

    def to_dict(self) -> dict:
        return {
            k: v
            for k, v in self.__dict__.items()
            if v is not None and k not in self._DICT_EXCLUDE
        }


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


def _extract_wikipedia(page: dict) -> WikipediaSummary | None:
    """Extract display-relevant fields from a Wikipedia API response."""
    if page.get("missing"):
        return None
    thumb = page.get("thumbnail") or {}
    original = page.get("original") or {}
    summary = WikipediaSummary(
        extract=page.get("extract") or None,
        description=page.get("description") or None,
        url=page.get("fullurl") or None,
        thumbnail_url=thumb.get("source") or None,
        image_url=original.get("source") or None,
    )
    if not summary.to_dict():
        return None
    return summary
