"""Load and extract Wikipedia summaries for export."""

import orjson
import logging
from dataclasses import dataclass
from urllib.parse import unquote

from space_map_data.constants.providers import LANGUAGES
from space_map_data.utils.paths import DOWNLOAD_DIR

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
    wiki_dir = DOWNLOAD_DIR / "wikipedia"
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


def load_wikipedia_image_filenames(qid: str) -> list[str]:
    """Collect unique original image filenames from all language Wikipedia summaries.

    Returns bare Commons filenames (URL-decoded) from the ``original.source`` field.
    """
    wiki_dir = DOWNLOAD_DIR / "wikipedia"
    seen: set[str] = set()
    result: list[str] = []
    for lang in LANGUAGES:
        path = wiki_dir / lang / f"{qid}.json"
        if not path.exists():
            continue
        page = orjson.loads(path.read_bytes())
        if page.get("missing"):
            continue
        src = (page.get("original") or {}).get("source")
        if not src:
            continue
        basename = unquote(src.rsplit("/", 1)[-1])
        if basename and basename not in seen:
            seen.add(basename)
            result.append(basename)
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
