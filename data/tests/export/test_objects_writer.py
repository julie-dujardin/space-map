"""Tests for space_map_data.export.objects.writer."""

import gzip
import math
import orjson
from unittest.mock import MagicMock

from space_map_data.export.objects.writer import (
    K_GLOBAL,
    _iso_currency_code,
    _pick_attrs,
    hash_bucket,
    write_object_bundles,
)
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


class TestHashBucket:
    def test_is_deterministic(self):
        assert hash_bucket("spkid-54352560", 1000) == hash_bucket(
            "spkid-54352560", 1000
        )

    def test_stays_in_range(self):
        for i in range(200):
            assert 0 <= hash_bucket(f"spkid-{i}", 17) < 17

    def test_different_ids_distribute(self):
        # Cheap sanity check — 50 distinct ids across 10 buckets should hit >= 7 buckets.
        buckets = {hash_bucket(f"spkid-{i}", 10) for i in range(50)}
        assert len(buckets) >= 7


class TestWriteObjectBundles:
    """write_object_bundles hash-buckets ids, writes one gzipped JSON per bucket."""

    def test_global_bundle_count_is_ceil_total_over_k(self, tmp_path):
        # 250 objects → N = ceil(250 / 100) = 3 global buckets
        global_data = {f"spkid-{i}": {"id": f"spkid-{i}"} for i in range(250)}
        ns = write_object_bundles(tmp_path, global_data, {})
        assert ns["global"] == math.ceil(250 / K_GLOBAL)
        out_dir = tmp_path / "objects" / "__global__"
        files = sorted(out_dir.iterdir())
        assert len(files) == ns["global"]
        # Each file decompresses to a dict keyed by object id; union covers all inputs.
        seen: set[str] = set()
        for f in files:
            entries = orjson.loads(gzip.decompress(f.read_bytes()))
            seen.update(entries)
            # Every entry must hash into its file's bucket.
            bucket = int(f.name.split(".", 1)[0])
            for obj_id in entries:
                assert hash_bucket(obj_id, ns["global"]) == bucket
        assert seen == set(global_data)

    def test_localized_n_is_per_language(self, tmp_path):
        # en has 400 entries → ceil(400/200) = 2. fr has 50 → ceil(50/200) = 1.
        localized = {
            "en": {f"spkid-{i}": {"name": f"n{i}"} for i in range(400)},
            "fr": {f"spkid-{i}": {"name": f"f{i}"} for i in range(50)},
        }
        ns = write_object_bundles(tmp_path, {}, localized)
        assert ns["en"] == 2
        assert ns["fr"] == 1
        assert (tmp_path / "objects" / "en").exists()
        assert (tmp_path / "objects" / "fr").exists()

    def test_empty_language_yields_zero_and_no_directory(self, tmp_path):
        ns = write_object_bundles(tmp_path, {}, {"ja": {}, "ru": {}})
        assert ns["global"] == 0
        assert ns["ja"] == 0
        assert ns["ru"] == 0
        assert not (tmp_path / "objects" / "ja").exists()
        assert not (tmp_path / "objects" / "ru").exists()
