"""Tests for space_map_data.export.localization."""

from space_map_data.export.localization import _extract_symbol
from space_map_data.export.wikidata import WikidataEntity


def _entity_with_symbols(
    symbols: dict[str, str],
    ranks: dict[str, str] | None = None,
) -> WikidataEntity:
    """Build a WikidataEntity with P5061 (unit symbol) claims.

    *ranks* maps language codes to statement rank (default ``"normal"``).
    """
    stmts = []
    for lang, text in symbols.items():
        stmt: dict = {
            "mainsnak": {
                "datavalue": {
                    "value": {"language": lang, "text": text},
                },
            },
        }
        rank = (ranks or {}).get(lang, "normal")
        if rank != "normal":
            stmt["rank"] = rank
        stmts.append(stmt)
    return WikidataEntity(
        labels={},
        descriptions={},
        aliases={},
        claims={"P5061": stmts},
        sitelinks={},
    )


class TestExtractSymbol:
    """Tests for _extract_symbol with mul > lang > en fallback chain."""

    def test_mul_preferred_over_lang(self):
        entity = _entity_with_symbols({"mul": "€", "en": "EUR", "de": "EUR"})
        assert _extract_symbol(entity, "de") == "€"

    def test_mul_preferred_over_en(self):
        entity = _entity_with_symbols({"mul": "€", "en": "EUR"})
        assert _extract_symbol(entity, "en") == "€"

    def test_target_lang(self):
        entity = _entity_with_symbols({"en": "kg", "de": "kg"})
        assert _extract_symbol(entity, "de") == "kg"

    def test_falls_back_to_english(self):
        entity = _entity_with_symbols({"en": "kg"})
        assert _extract_symbol(entity, "ja") == "kg"

    def test_mul_only(self):
        entity = _entity_with_symbols({"mul": "€"})
        assert _extract_symbol(entity, "ja") == "€"

    def test_no_claims(self):
        entity = WikidataEntity(
            labels={},
            descriptions={},
            aliases={},
            claims={},
            sitelinks={},
        )
        assert _extract_symbol(entity, "en") is None

    def test_no_match(self):
        entity = _entity_with_symbols({"fr": "kg"})
        assert _extract_symbol(entity, "en") is None

    def test_preferred_rank_wins(self):
        entity = _entity_with_symbols(
            {"mul": "old", "en": "new"},
            ranks={"mul": "normal", "en": "preferred"},
        )
        assert _extract_symbol(entity, "en") == "new"

    def test_deprecated_excluded(self):
        entity = _entity_with_symbols(
            {"mul": "€", "en": "EUR"},
            ranks={"mul": "deprecated"},
        )
        assert _extract_symbol(entity, "en") == "EUR"
