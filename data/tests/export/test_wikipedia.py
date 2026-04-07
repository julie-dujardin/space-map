"""Tests for space_map_data.export.objects.wikipedia."""

from space_map_data.export.objects.wikipedia import WikipediaSummary, _extract_wikipedia


# ---------------------------------------------------------------------------
# WikipediaSummary.to_dict
# ---------------------------------------------------------------------------


class TestToDict:
    def test_filters_none(self):
        s = WikipediaSummary(extract="Hello", thumbnail=None)
        d = s.to_dict()
        assert "extract" in d
        assert "thumbnail" not in d

    def test_all_fields(self):
        s = WikipediaSummary(
            extract="text",
            description="desc",
            thumbnail="thumb.jpg",
            image="img.jpg",
            url="https://example.com",
        )
        assert len(s.to_dict()) == 5

    def test_empty(self):
        assert WikipediaSummary().to_dict() == {}


# ---------------------------------------------------------------------------
# _extract_wikipedia
# ---------------------------------------------------------------------------


class TestExtractWikipedia:
    def test_full_page(self):
        page = {
            "extract": "Earth is a planet.",
            "description": "third planet from the Sun",
            "thumbnail": {"source": "thumb.jpg"},
            "original": {"source": "full.jpg"},
            "fullurl": "https://en.wikipedia.org/wiki/Earth",
        }
        result = _extract_wikipedia(page)
        assert result is not None
        assert result.extract == "Earth is a planet."
        assert result.description == "third planet from the Sun"
        assert result.thumbnail == "thumb.jpg"
        assert result.image == "full.jpg"
        assert result.url == "https://en.wikipedia.org/wiki/Earth"

    def test_missing_page(self):
        assert _extract_wikipedia({"missing": True}) is None

    def test_empty_extract_treated_as_none(self):
        page = {"extract": "", "fullurl": "https://example.com"}
        result = _extract_wikipedia(page)
        assert result is not None
        assert result.extract is None
        assert result.url == "https://example.com"

    def test_no_thumbnail(self):
        page = {"extract": "text"}
        result = _extract_wikipedia(page)
        assert result is not None
        assert result.thumbnail is None

    def test_all_empty_returns_none(self):
        page = {"extract": "", "description": ""}
        assert _extract_wikipedia(page) is None
