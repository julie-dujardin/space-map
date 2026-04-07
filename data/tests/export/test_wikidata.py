"""Tests for space_map_data.export.wikidata (entity parsing and name resolution)."""

from space_map_data.export.wikidata import (
    WikidataEntity,
    _extract_lang_aliases,
    _extract_lang_values,
    _extract_sitelinks,
    _parse_entity,
    resolve_name,
)
from tests.conftest import make_object


# ---------------------------------------------------------------------------
# _extract_lang_values
# ---------------------------------------------------------------------------


class TestExtractLangValues:
    def test_dict_format(self):
        data = {"en": {"value": "Earth", "language": "en"}}
        assert _extract_lang_values(data) == {"en": "Earth"}

    def test_string_format(self):
        data = {"en": "Earth", "fr": "Terre"}
        assert _extract_lang_values(data) == {"en": "Earth", "fr": "Terre"}

    def test_empty(self):
        assert _extract_lang_values({}) == {}

    def test_mixed_formats(self):
        data = {
            "en": {"value": "Earth", "language": "en"},
            "fr": "Terre",
        }
        assert _extract_lang_values(data) == {"en": "Earth", "fr": "Terre"}


# ---------------------------------------------------------------------------
# _extract_lang_aliases
# ---------------------------------------------------------------------------


class TestExtractLangAliases:
    def test_normal(self):
        data = {
            "en": [{"value": "Terra"}, {"value": "Blue Planet"}],
            "fr": [{"value": "Planète bleue"}],
        }
        result = _extract_lang_aliases(data)
        assert result == {
            "en": ["Terra", "Blue Planet"],
            "fr": ["Planète bleue"],
        }

    def test_skips_empty_values(self):
        data = {"en": [{"not_value": "x"}]}
        assert _extract_lang_aliases(data) == {}

    def test_empty(self):
        assert _extract_lang_aliases({}) == {}


# ---------------------------------------------------------------------------
# _extract_sitelinks
# ---------------------------------------------------------------------------


class TestExtractSitelinks:
    def test_extracts_lang(self):
        data = {"enwiki": {"title": "Earth"}, "frwiki": {"title": "Terre"}}
        assert _extract_sitelinks(data) == {"en": "Earth", "fr": "Terre"}

    def test_commonswiki_uses_commons_key(self):
        """commonswiki produces lang='commons' — not filtered, but distinct from real langs."""
        data = {"commonswiki": {"title": "Earth"}}
        assert _extract_sitelinks(data) == {"commons": "Earth"}

    def test_skips_wiki_only(self):
        """A bare 'wiki' key produces an empty lang string and is skipped."""
        data = {"wiki": {"title": "Earth"}}
        assert _extract_sitelinks(data) == {}

    def test_requires_dict_value(self):
        data = {"enwiki": "not a dict"}
        assert _extract_sitelinks(data) == {}

    def test_requires_title_key(self):
        data = {"enwiki": {"url": "https://en.wikipedia.org/wiki/Earth"}}
        assert _extract_sitelinks(data) == {}


# ---------------------------------------------------------------------------
# _parse_entity
# ---------------------------------------------------------------------------


class TestParseEntity:
    def test_minimal_with_labels(self):
        entity = {"labels": {"en": {"value": "Earth"}}}
        result = _parse_entity(entity)
        assert result is not None
        assert result["labels"] == {"en": "Earth"}

    def test_returns_none_when_empty(self):
        assert _parse_entity({}) is None
        assert _parse_entity({"labels": {}, "descriptions": {}, "aliases": {}}) is None

    def test_preserves_claims(self):
        claims = {"P31": [{"mainsnak": {}}]}
        entity = {"labels": {"en": {"value": "Earth"}}, "claims": claims}
        result = _parse_entity(entity)
        assert result is not None
        assert result["claims"] is claims

    def test_full_entity(self):
        entity = {
            "labels": {"en": {"value": "Earth"}},
            "descriptions": {"en": {"value": "third planet"}},
            "aliases": {"en": [{"value": "Terra"}]},
            "claims": {"P31": []},
            "sitelinks": {"enwiki": {"title": "Earth"}},
        }
        result = _parse_entity(entity)
        assert result is not None
        assert result["labels"] == {"en": "Earth"}
        assert result["descriptions"] == {"en": "third planet"}
        assert result["aliases"] == {"en": ["Terra"]}
        assert result["sitelinks"] == {"en": "Earth"}


# ---------------------------------------------------------------------------
# resolve_name
# ---------------------------------------------------------------------------


class TestResolveName:
    def _wd(self, labels: dict[str, str]) -> WikidataEntity:
        return WikidataEntity(
            labels=labels,
            descriptions={},
            aliases={},
            claims={},
            sitelinks={},
        )

    def test_uses_target_lang(self):
        obj = make_object(name="Earth")
        wd = self._wd({"de": "Erde", "en": "Earth"})
        assert resolve_name(obj, "de", wd) == "Erde"

    def test_falls_back_to_english(self):
        obj = make_object(name="Earth")
        wd = self._wd({"en": "Earth"})
        assert resolve_name(obj, "ja", wd) == "Earth"

    def test_falls_back_to_obj_name(self):
        obj = make_object(name="Earth")
        assert resolve_name(obj, "en", None) == "Earth"

    def test_no_entity_no_name(self):
        obj = make_object(name=None)
        assert resolve_name(obj, "en", None) is None
