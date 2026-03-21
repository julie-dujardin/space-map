"""Load and extract Wikipedia summaries for export."""

import logging

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.wikidata import load_json_dir
from space_map_data.utils.paths import DOWNLOAD_DIR

logger = logging.getLogger(__name__)


def load_wikipedia_summaries() -> dict[str, dict[str, dict]]:
    """Load Wikipedia summaries into {qid: {lang: summary_dict}}."""
    wiki_dir = DOWNLOAD_DIR / "wikipedia"
    if not wiki_dir.exists():
        logger.info("No Wikipedia summaries found")
        return {}

    result: dict[str, dict[str, dict]] = {}
    for lang in LANGUAGES:
        lang_dir = wiki_dir / lang
        for qid, page in load_json_dir(lang_dir):
            summary = _extract_wikipedia(page)
            if summary:
                result.setdefault(qid, {})[lang] = summary

    total = sum(len(langs) for langs in result.values())
    logger.info("Loaded %d Wikipedia summaries for %d entities", total, len(result))
    return result


def _extract_wikipedia(page: dict) -> dict | None:
    """Extract display-relevant fields from a Wikipedia API response."""
    if page.get("missing"):
        return None
    data: dict = {}
    if extract := page.get("extract"):
        data["extract"] = extract
    if desc := page.get("description"):
        data["description"] = desc
    if thumb := page.get("thumbnail", {}).get("source"):
        data["thumbnail"] = thumb
    if original := page.get("original", {}).get("source"):
        data["image"] = original
    if url := page.get("fullurl"):
        data["url"] = url
    return data or None
