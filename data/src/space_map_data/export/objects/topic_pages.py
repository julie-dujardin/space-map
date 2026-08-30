"""The "Atmosphere of X" / "Internal structure of X" / "Exploration of X"
article, per locale.

One link at the foot of each half of the Structure tab and one atop the
Probes tab, the only prose next to their charts and lists. No English fallback, same as the ring articles: a reader gets the
article in their own language or no link. See coverage comments in
``constants.{atmosphere,interior}``.
"""

from functools import cache

from space_map_data.constants.atmosphere.wikidata import ATMOSPHERE_PAGES
from space_map_data.constants.interior.wikidata import INTERIOR_PAGES
from space_map_data.constants.spacecraft.wikidata import EXPLORATION_PAGES
from space_map_data.export.objects.wikipedia import load_wikipedia_summaries_for_qid


@cache
def _summaries(qid: str):
    """Memoized per QID: the same page is otherwise read once per language."""
    return load_wikipedia_summaries_for_qid(qid)


def _page_localized(qids: tuple[str, ...], lang: str) -> dict | None:
    """First article in `qids` that this locale has, as `{extract, url}`.

    Requires an extract, not just a link — some articles open on a section
    heading with an empty intro extract, and the panel needs prose to render.
    """
    entry: dict = {}
    for qid in qids:
        summary = _summaries(qid).get(lang)
        if summary and summary.extract:
            entry.setdefault("extract", summary.extract)
            if summary.url:
                entry.setdefault("url", summary.url)
    return entry or None


def interior_page_localized(body_id: str, lang: str) -> dict | None:
    return _page_localized(INTERIOR_PAGES.get(body_id, ()), lang)


def atmosphere_page_localized(body_id: str, lang: str) -> dict | None:
    return _page_localized(ATMOSPHERE_PAGES.get(body_id, ()), lang)


def exploration_page_localized(body_id: str, lang: str) -> dict | None:
    return _page_localized(EXPLORATION_PAGES.get(body_id, ()), lang)
