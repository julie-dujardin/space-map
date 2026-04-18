"""Tests for space_map_data.export.objects.writer."""

from unittest.mock import MagicMock

from space_map_data.export.objects.writer import _iso_currency_code, _pick_attrs
from tests.conftest import make_object


def _entity_snak(qid: str) -> dict:
    return {
        "snaktype": "value",
        "datavalue": {
            "value": {"entity-type": "item", "numeric-id": int(qid[1:]), "id": qid},
            "type": "wikibase-entityid",
        },
    }


def _string_snak(val: str) -> dict:
    return {"snaktype": "value", "datavalue": {"value": val, "type": "string"}}


def _stmt(snak: dict, *, rank: str = "normal") -> dict:
    return {"mainsnak": snak, "type": "statement", "rank": rank}


def _currency_entity(iso_code: str) -> dict:
    """Build a minimal Wikidata entity that looks like a currency."""
    return {
        "labels": {"en": iso_code},
        "claims": {
            "P31": [_stmt(_entity_snak("Q8142"))],
            "P498": [_stmt(_string_snak(iso_code))],
        },
        "sitelinks": {},
    }


class TestIsoCurrencyCode:
    """Tests for _iso_currency_code helper."""

    def test_returns_iso_code_for_currency(self):
        cache = MagicMock()
        cache.get_referenced.return_value = _currency_entity("EUR")
        assert _iso_currency_code("Q4916", cache) == "EUR"

    def test_returns_none_for_non_currency(self):
        cache = MagicMock()
        cache.get_referenced.return_value = {
            "labels": {"en": "kilometre"},
            "claims": {
                "P31": [_stmt(_entity_snak("Q3647172"))],
            },
            "sitelinks": {},
        }
        assert _iso_currency_code("Q828224", cache) is None

    def test_returns_none_for_unknown_qid(self):
        cache = MagicMock()
        cache.get_referenced.return_value = None
        assert _iso_currency_code("Q999999", cache) is None


class TestPickAttrs:
    def test_extracts_present(self):
        obj = make_object(name="Earth", wikidata_qid="Q2", spkid=None)
        result = _pick_attrs(obj, ("name", "wikidata_qid", "spkid"))
        assert result == {"name": "Earth", "wikidata_qid": "Q2"}

    def test_all_none(self):
        obj = make_object(
            wikidata_qid=None,
            spkid=None,
            norad_cat_id=None,
        )
        result = _pick_attrs(obj, ("wikidata_qid", "spkid", "norad_cat_id"))
        assert result == {}

    def test_all_present(self):
        obj = make_object(name="Earth", wikidata_qid="Q2", naif_id=399)
        result = _pick_attrs(obj, ("name", "wikidata_qid", "naif_id"))
        assert result == {
            "name": "Earth",
            "wikidata_qid": "Q2",
            "naif_id": 399,
        }

    def test_works_on_plain_object(self):
        """_pick_attrs is generic — works on any object with attributes."""

        class Bag:
            x = 1
            y = None
            z = "hello"

        result = _pick_attrs(Bag(), ("x", "y", "z"))
        assert result == {"x": 1, "z": "hello"}
