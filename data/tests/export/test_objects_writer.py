"""Tests for space_map_data.export.objects.writer."""

from space_map_data.export.objects.writer import _pick_attrs
from tests.conftest import make_object


class TestPickAttrs:
    def test_extracts_present(self):
        obj = make_object(name="Earth", wikidata_qid="Q2", sbdb_spkid=None)
        result = _pick_attrs(obj, ("name", "wikidata_qid", "sbdb_spkid"))
        assert result == {"name": "Earth", "wikidata_qid": "Q2"}

    def test_all_none(self):
        obj = make_object(
            wikidata_qid=None,
            sbdb_spkid=None,
            celestrak_norad_cat_id=None,
        )
        result = _pick_attrs(
            obj, ("wikidata_qid", "sbdb_spkid", "celestrak_norad_cat_id")
        )
        assert result == {}

    def test_all_present(self):
        obj = make_object(name="Earth", wikidata_qid="Q2", horizons_naif_id=399)
        result = _pick_attrs(obj, ("name", "wikidata_qid", "horizons_naif_id"))
        assert result == {
            "name": "Earth",
            "wikidata_qid": "Q2",
            "horizons_naif_id": 399,
        }

    def test_works_on_plain_object(self):
        """_pick_attrs is generic — works on any object with attributes."""

        class Bag:
            x = 1
            y = None
            z = "hello"

        result = _pick_attrs(Bag(), ("x", "y", "z"))
        assert result == {"x": 1, "z": "hello"}
