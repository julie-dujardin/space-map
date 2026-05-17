"""Tests for the DeepL downloader's job enumeration. The actual API call is
not exercised (covered indirectly by the export-side cache reader tests)."""

from space_map_data.download.providers.deepl import _missing_per_context
from space_map_data.export.deepl import MessageValue, VariantBlock


_VARIANT: list[VariantBlock] = [
    {
        "declarations": ["input count", "local countPlural = count: plural"],
        "selectors": ["countPlural"],
        "match": {
            "countPlural=one": "Cleared {count} pinned object",
            "countPlural=other": "Cleared {count} pinned objects",
        },
    }
]


class TestMissingPerContext:
    """Per-locale untranslated-job grouping by context label, with dedup."""

    def test_plain_entry_routes_to_correct_bucket(self):
        entries: list[tuple[str, MessageValue]] = [
            ("page_title", "Space Map"),
            ("type_asteroid", "asteroid"),
        ]
        out = _missing_per_context(entries, cache={}, target_lang="fr")
        assert set(out) == {"default", "type"}
        assert out["default"][0][0] == "Space Map"
        assert out["type"][0][0] == "asteroid"

    def test_cached_entry_is_skipped(self):
        entries: list[tuple[str, MessageValue]] = [("page_title", "Space Map")]
        cache = {"default": {"Space Map": "Carte de l'espace"}}
        out = _missing_per_context(entries, cache, "fr")
        assert out == {}

    def test_variant_expands_into_one_job_per_category(self):
        entries: list[tuple[str, MessageValue]] = [("cleared_n_promoted", _VARIANT)]
        out = _missing_per_context(entries, cache={}, target_lang="fr")
        # fr has one + other categories → 2 distinct substituted sources.
        substituted = sorted(s for s, _ in out["default"])
        assert substituted == [
            "Cleared 1 pinned object",
            "Cleared 5 pinned objects",
        ]

    def test_variant_dedups_when_categories_collide_on_rep(self):
        # ru has one/few/many/other. 'many' and 'other' both rep=5 →
        # the substituted source is identical → only one job queued.
        entries: list[tuple[str, MessageValue]] = [("cleared_n_promoted", _VARIANT)]
        out = _missing_per_context(entries, cache={}, target_lang="ru")
        substituted = sorted(s for s, _ in out["default"])
        # 3 unique substitutions: one (rep=1), few (rep=3), many/other (rep=5).
        assert substituted == [
            "Cleared 1 pinned object",
            "Cleared 3 pinned objects",
            "Cleared 5 pinned objects",
        ]

    def test_variant_japanese_single_other_only(self):
        entries: list[tuple[str, MessageValue]] = [("cleared_n_promoted", _VARIANT)]
        out = _missing_per_context(entries, cache={}, target_lang="ja")
        substituted = [s for s, _ in out["default"]]
        # Only 'other' category in ja CLDR.
        assert substituted == ["Cleared 5 pinned objects"]

    def test_two_messages_same_context_share_bucket(self):
        entries: list[tuple[str, MessageValue]] = [
            ("page_title", "Hello"),
            ("loading", "World"),
        ]
        out = _missing_per_context(entries, cache={}, target_lang="fr")
        substituted = sorted(s for s, _ in out["default"])
        assert substituted == ["Hello", "World"]
