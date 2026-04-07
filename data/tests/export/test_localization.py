"""Tests for space_map_data.export.localization."""

from space_map_data.export.localization import _extract_symbol
from space_map_data.export.wikidata import WikidataEntity


def _entity_with_symbols(symbols: dict[str, str]) -> WikidataEntity:
    """Build a WikidataEntity with P5061 (unit symbol) claims."""
    stmts = []
    for lang, text in symbols.items():
        stmts.append(
            {
                "mainsnak": {
                    "datavalue": {
                        "value": {"language": lang, "text": text},
                    },
                },
            }
        )
    return WikidataEntity(
        labels={},
        descriptions={},
        aliases={},
        claims={"P5061": stmts},
        sitelinks={},
    )


class TestExtractSymbol:
    def test_target_lang(self):
        entity = _entity_with_symbols({"en": "kg", "de": "kg"})
        assert _extract_symbol(entity, "de") == "kg"

    def test_falls_back_to_english(self):
        entity = _entity_with_symbols({"en": "kg"})
        assert _extract_symbol(entity, "ja") == "kg"

    def test_no_claims(self):
        entity = WikidataEntity(
            labels={},
            descriptions={},
            aliases={},
            claims={},
            sitelinks={},
        )
        assert _extract_symbol(entity, "en") is None

    def test_en_no_match(self):
        entity = _entity_with_symbols({"fr": "kg"})
        assert _extract_symbol(entity, "en") is None
