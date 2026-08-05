"""The Structure tab's two Wikipedia blurbs.

Runs against the real downloaded summaries — the point of most of these is
that a row in the table actually resolves to prose on disk, which a mocked
loader cannot tell us.
"""

import pytest

from space_map_data.constants.atmosphere.facts import ATMOSPHERE_FACTS
from space_map_data.constants.atmosphere.wikidata import ATMOSPHERE_PAGES
from space_map_data.constants.interior.bodies import INTERIOR_FACTS
from space_map_data.constants.interior.wikidata import INTERIOR_PAGES
from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.objects.topic_pages import (
    _page_localized,
    atmosphere_page_localized,
    interior_page_localized,
)


def _locales(resolve, body_id: str) -> dict[str, dict]:
    return {
        lang: page for lang in LANGUAGES if (page := resolve(body_id, lang)) is not None
    }


class TestShape:
    """What an entry carries."""

    def test_body_without_a_page_gets_nothing(self):
        # Enceladus has both an interior and an atmosphere in the tab and an
        # article for neither.
        assert interior_page_localized("naif-602", "en") is None
        assert atmosphere_page_localized("naif-602", "en") is None

    def test_locale_without_the_article_gets_nothing(self):
        # The Italian-only series is the whole reason there is no English
        # fallback: falling back would mean falling back to nothing.
        assert interior_page_localized("naif-599", "it") is not None
        assert interior_page_localized("naif-599", "en") is None

    def test_extract_and_url(self):
        page = atmosphere_page_localized("naif-499", "en")
        assert page is not None
        assert page["extract"].startswith("The atmosphere of Mars")
        assert page["url"] == "https://en.wikipedia.org/wiki/Atmosphere_of_Mars"

    def test_link_only_entries_are_dropped(self):
        # pt "Estrutura interna da Lua" exists and opens on a section heading,
        # so its intro extract comes back empty. The panel renders nothing
        # without prose, so the entry must not ship.
        assert interior_page_localized("naif-301", "pt") is None

    def test_url_comes_from_the_article_the_extract_came_from(self):
        first, second = "Q_no_such_page", "Q1664027"
        page = _page_localized((first, second), "en")
        assert page is not None
        assert "wikipedia.org" in page["url"]


class TestCoverage:
    """That the tables resolve to something, per body."""

    @pytest.mark.parametrize("body", sorted(INTERIOR_PAGES))
    def test_every_interior_row_reaches_prose_somewhere(self, body: str):
        assert _locales(interior_page_localized, body), body

    @pytest.mark.parametrize("body", sorted(ATMOSPHERE_PAGES))
    def test_every_atmosphere_row_reaches_prose_somewhere(self, body: str):
        assert _locales(atmosphere_page_localized, body), body

    def test_pages_describe_bodies_the_tab_draws(self):
        # A page for a body with no facts would be a blurb under a section the
        # Structure tab never renders.
        assert not set(INTERIOR_PAGES) - set(INTERIOR_FACTS)
        assert not set(ATMOSPHERE_PAGES) - set(ATMOSPHERE_FACTS)
