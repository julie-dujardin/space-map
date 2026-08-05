"""The "Atmosphere of X" / "Internal structure of X" article, per locale.

One link at the foot of each half of the Structure tab. The tab itself is
charts and numbers with no prose in it, so this is the only place a reader is
told in words what they are looking at.

Coverage is lopsided and there is no English fallback, by the same decision the
ring articles ship under: a reader gets the article in the language they are
reading in or no link at all. Atmospheres are well covered (17 bodies, 12 of
them in English); interiors are not (10 bodies, 7 of which exist only in
Italian) — see the coverage comments in ``constants.{atmosphere,interior}``.
"""

from functools import cache

from space_map_data.constants.atmosphere.wikidata import ATMOSPHERE_PAGES
from space_map_data.constants.interior.wikidata import INTERIOR_PAGES
from space_map_data.export.objects.wikipedia import load_wikipedia_summaries_for_qid


@cache
def _summaries(qid: str):
    """Memoized per QID: the same page is otherwise read once per language."""
    return load_wikipedia_summaries_for_qid(qid)


def _page_localized(qids: tuple[str, ...], lang: str) -> dict | None:
    """First article in `qids` that this locale has, as `{extract, url}`.

    Requires an extract rather than just a link. A handful of articles open
    straight on a section heading and the API's intro extract comes back empty
    (pt "Estrutura interna da Lua", pt "Coroa solar", ru "Атмосфера Нептуна");
    the panel renders nothing without prose, so a link-only entry would ship as
    weight nobody sees.
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
