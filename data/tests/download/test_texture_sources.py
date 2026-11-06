"""Tests for the texture-sources scraper's options."""

import httpx
import pytest

from space_map_data.download.providers.metadata import texture_sources
from space_map_data.download.providers.metadata.texture_sources import (
    TextureSourcesDownloader,
)


class TestRescrape:
    """The runner's --force only skips `is_complete`, which never holds here."""

    @pytest.fixture
    def scraped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(texture_sources, "SOURCE_METADATA_DIR", tmp_path)
        monkeypatch.setattr(texture_sources, "HTML_CACHE_DIR", tmp_path / "html")
        monkeypatch.setattr(texture_sources, "PARSED_DIR", tmp_path / "parsed")
        entry = {"source": "https://svs.gsfc.nasa.gov/1234", "file": "a.jpg"}
        monkeypatch.setattr(texture_sources, "load_entries", lambda _dir: [entry])
        calls: list[bool] = []

        def scrape(self, site, url, stem, *, rescrape):
            calls.append(rescrape)
            return {"title": stem}

        monkeypatch.setattr(TextureSourcesDownloader, "_fetch_and_parse", scrape)
        return calls

    def test_a_page_is_scraped_once(self, scraped):
        provider = TextureSourcesDownloader(httpx.Client())
        provider.download()
        provider.download()
        assert scraped == [False]

    def test_the_force_of_the_runner_does_not_scrape_again(self, scraped):
        provider = TextureSourcesDownloader(httpx.Client())
        provider.download()
        provider.download(limit=50_000, epoch=None, force=True)
        assert scraped == [False]

    def test_rescrape_scrapes_again(self, scraped):
        provider = TextureSourcesDownloader(httpx.Client())
        provider.download()
        provider.download(rescrape=True)
        assert scraped == [False, True]
