"""Tests for space_map_data.export.localization."""

import orjson
import pytest

from space_map_data.export import localization
from space_map_data.export.localization import _extract_symbol, _merge_into_file
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
    """Tests for _extract_symbol with lang > mul > en fallback chain."""

    def test_lang_preferred_over_mul(self):
        entity = _entity_with_symbols({"mul": "€", "de": "EUR"})
        assert _extract_symbol(entity, "de") == "EUR"

    def test_mul_preferred_over_en(self):
        entity = _entity_with_symbols({"mul": "€", "en": "EUR"})
        assert _extract_symbol(entity, "ja") == "€"

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


class TestMergeIntoFile:
    """_merge_into_file: fill-only merge, base-equal omission, and pruning."""

    @pytest.fixture
    def msg_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(localization, "MESSAGES_DIR", tmp_path)
        return tmp_path

    @staticmethod
    def _read(msg_dir, lang: str) -> dict:
        return orjson.loads((msg_dir / f"{lang}.json").read_bytes())

    def test_base_keeps_every_key(self, msg_dir):
        fresh = {"property_name_mass": "Mass", "group_name_foo": "Foo"}
        base = _merge_into_file(
            "en", fresh, set(fresh), ("property_name_", "group_name_")
        )
        assert base == fresh
        assert self._read(msg_dir, "en") == fresh

    def test_omits_value_identical_to_base(self, msg_dir):
        prefixes = ("property_name_", "group_name_")
        fresh_en = {"property_name_mass": "Mass", "group_name_foo": "Foo"}
        live = set(fresh_en)
        base = _merge_into_file("en", fresh_en, live, prefixes)

        fresh_fr = {"property_name_mass": "Masse", "group_name_foo": "Foo"}
        _merge_into_file("fr", fresh_fr, live, prefixes, base)

        fr = self._read(msg_dir, "fr")
        assert fr["property_name_mass"] == "Masse"
        assert (
            "group_name_foo" not in fr
        )  # identical to en → falls back at compile time

    def test_manual_keys_untouched(self, msg_dir):
        prefixes = ("property_name_",)
        (msg_dir / "fr.json").write_bytes(orjson.dumps({"tab_images": "Images"}))
        _merge_into_file(
            "fr",
            {"property_name_mass": "Masse"},
            {"property_name_mass"},
            prefixes,
            {"property_name_mass": "Mass"},
        )
        fr = self._read(msg_dir, "fr")
        assert fr["tab_images"] == "Images"  # non-prefixed hand key preserved
        assert fr["property_name_mass"] == "Masse"

    def test_existing_translation_wins_over_fresh(self, msg_dir):
        prefixes = ("property_name_",)
        (msg_dir / "fr.json").write_bytes(
            orjson.dumps({"property_name_mass": "Masse (hand)"})
        )
        _merge_into_file(
            "fr",
            {"property_name_mass": "Masse (auto)"},
            {"property_name_mass"},
            prefixes,
            {"property_name_mass": "Mass"},
        )
        assert self._read(msg_dir, "fr")["property_name_mass"] == "Masse (hand)"

    def test_unmanaged_generated_keys_kept_and_resorted(self, msg_dir):
        # A groups-only run must leave the same key order a full run would.
        (msg_dir / "en.json").write_bytes(
            orjson.dumps(
                {
                    "tab_images": "Images",
                    "group_name_foo": "Foo",
                    "property_name_mass": "Mass",
                    "unit_name_hour": "hour",
                }
            )
        )
        _merge_into_file(
            "en", {"group_name_bar": "Bar"}, {"group_name_bar"}, ("group_name_",)
        )
        en = self._read(msg_dir, "en")
        assert list(en) == [
            "tab_images",
            "group_name_bar",
            "property_name_mass",
            "unit_name_hour",
        ]  # group_name_foo stale-pruned, unmanaged keys survive in sorted position

    def test_stale_generated_key_pruned(self, msg_dir):
        prefixes = ("property_name_",)
        (msg_dir / "fr.json").write_bytes(
            orjson.dumps({"property_name_old": "Vieux", "property_name_mass": "Masse"})
        )
        _merge_into_file(
            "fr",
            {"property_name_mass": "Masse"},
            {"property_name_mass"},
            prefixes,
            {"property_name_mass": "Mass"},
        )
        fr = self._read(msg_dir, "fr")
        assert "property_name_old" not in fr  # no longer live → pruned
        assert fr["property_name_mass"] == "Masse"
