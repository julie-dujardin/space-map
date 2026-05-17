"""Tests for space_map_data.export.deepl — DeepL cache layout, placeholder
substitution, variant expansion, and per-key/per-category lookup."""

from space_map_data.export.deepl import (
    CATEGORY_REPRESENTATIVE_COUNT,
    FIXED_COUNT_CATEGORIES,
    LOCALE_PLURAL_CATEGORIES,
    VariantBlock,
    context_label_for_key,
    expand_for_target,
    load_translations,
    lookup_translation,
    parse_message_value,
    restore_placeholders,
    substitute_placeholders,
)


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


class TestContextLabelForKey:
    """Prefix → context-label mapping. Longest-match wins."""

    def test_orbit_class_prefix(self):
        assert context_label_for_key("orbit_class_AMO") == "orbit_class"

    def test_object_type_beats_object(self):
        # 'object_type_' must resolve before a hypothetical 'object_' prefix.
        assert context_label_for_key("object_type_debris") == "object_type"

    def test_spectral_type_prefix(self):
        assert context_label_for_key("spectral_type_smassii") == "spectral_type"

    def test_no_prefix_falls_back_to_default(self):
        assert context_label_for_key("page_title") == "default"

    def test_partial_match_does_not_count(self):
        # 'typewriter' starts with 'type' but not 'type_', so default.
        assert context_label_for_key("typewriter") == "default"


class TestSubstitutePlaceholders:
    """Placeholder → numeric stand-in substitution and inverse map."""

    def test_no_placeholders_is_identity(self):
        substituted, inverse = substitute_placeholders("plain text")
        assert substituted == "plain text"
        assert inverse == {}

    def test_single_placeholder_gets_high_standin(self):
        substituted, inverse = substitute_placeholders("Error: {error}")
        assert substituted == "Error: 99001"
        assert inverse == {"99001": "{error}"}

    def test_multiple_distinct_placeholders_get_distinct_standins(self):
        substituted, inverse = substitute_placeholders("Using {value} · {source}")
        assert substituted == "Using 99001 · 99002"
        assert inverse == {"99001": "{value}", "99002": "{source}"}

    def test_repeated_placeholder_reuses_standin(self):
        # Same variable name → same stand-in (so DeepL keeps them aligned).
        substituted, inverse = substitute_placeholders("{n} → {n}")
        assert substituted == "99001 → 99001"
        assert inverse == {"99001": "{n}"}

    def test_selector_substitution_uses_rep_and_records_inverse(self):
        substituted, inverse = substitute_placeholders(
            "Cleared {count} pinned object",
            selector_var="count",
            selector_value="1",
        )
        assert substituted == "Cleared 1 pinned object"
        assert inverse == {"1": "{count}"}

    def test_selector_substitution_alongside_other_placeholder(self):
        substituted, inverse = substitute_placeholders(
            "Cleared {count} from {category}",
            selector_var="count",
            selector_value="5",
        )
        assert substituted == "Cleared 5 from 99001"
        assert inverse == {"5": "{count}", "99001": "{category}"}

    def test_restore_selector_false_keeps_literal(self):
        # Used for fixed-count categories: the rep number stays literal in
        # the cached translation rather than being restored back to {count}.
        substituted, inverse = substitute_placeholders(
            "Cleared {count} pinned object",
            selector_var="count",
            selector_value="1",
            restore_selector=False,
        )
        assert substituted == "Cleared 1 pinned object"
        assert inverse == {}  # selector NOT recorded for restoration

    def test_restore_selector_false_still_restores_other_placeholders(self):
        # Non-selector placeholders still get their normal high stand-in
        # and inverse entry even when restore_selector is False.
        substituted, inverse = substitute_placeholders(
            "Cleared {count} from {category}",
            selector_var="count",
            selector_value="0",
            restore_selector=False,
        )
        assert substituted == "Cleared 0 from 99001"
        assert inverse == {"99001": "{category}"}


class TestRestorePlaceholders:
    """Stand-in → placeholder substitution, longest-first to avoid prefix collisions."""

    def test_no_inverse_is_identity(self):
        assert restore_placeholders("any text", {}) == "any text"

    def test_basic_restore(self):
        assert restore_placeholders("Erreur : 99001", {"99001": "{error}"}) == (
            "Erreur : {error}"
        )

    def test_longest_first_avoids_prefix_collision(self):
        # Without longest-first, replacing '2' before '22' would corrupt '22'.
        text = "a 22 b 2 c"
        inverse = {"22": "{double}", "2": "{single}"}
        assert restore_placeholders(text, inverse) == "a {double} b {single} c"

    def test_roundtrip_with_selector(self):
        text = "Cleared {count} pinned object"
        substituted, inverse = substitute_placeholders(
            text, selector_var="count", selector_value="1"
        )
        assert restore_placeholders(substituted, inverse) == text


class TestParseMessageValue:
    """Decompose plain strings and variant arrays into translatable parts."""

    def test_plain_string(self):
        sv, sl, sources, raw = parse_message_value("Hello")
        assert sv is None
        assert sl is None
        assert sources == {None: "Hello"}
        assert raw is None

    def test_variant_extracts_selector_var_and_local(self):
        sv, sl, sources, raw = parse_message_value(_VARIANT)
        assert sv == "count"
        assert sl == "countPlural"
        assert sources == {
            "one": "Cleared {count} pinned object",
            "other": "Cleared {count} pinned objects",
        }
        assert raw is not None

    def test_empty_list_returns_empty(self):
        sv, sl, sources, raw = parse_message_value([])
        assert (sv, sl, sources, raw) == (None, None, {}, None)


class TestExpandForTarget:
    """English value → per-target-category translation jobs."""

    def test_plain_string_yields_single_job(self):
        jobs = expand_for_target("Hello", "fr")
        assert len(jobs) == 1
        target_cat, substituted, inverse = jobs[0]
        assert target_cat is None
        assert substituted == "Hello"
        assert inverse == {}

    def test_empty_plain_string_yields_nothing(self):
        assert expand_for_target("", "fr") == []

    def test_variant_french_two_categories(self):
        jobs = {cat: (sub, inv) for cat, sub, inv in expand_for_target(_VARIANT, "fr")}
        assert set(jobs) == {"one", "other"}
        assert jobs["one"][0] == "Cleared 1 pinned object"
        assert jobs["other"][0] == "Cleared 5 pinned objects"

    def test_variant_fixed_count_category_has_empty_inverse(self):
        # 'one' is a fixed-count category: the selector value (1) must stay
        # literal in the cached translation, so the inverse map records no
        # restoration for it.
        jobs = {cat: inv for cat, _sub, inv in expand_for_target(_VARIANT, "fr")}
        assert jobs["one"] == {}
        # 'other' is variable-count: the selector restoration is active.
        assert jobs["other"] == {"5": "{count}"}

    def test_variant_russian_dedupes_many_and_other_by_rep_collision(self):
        # ru CLDR: one, few, many, other — but 'many' and 'other' both rep=5,
        # so the substituted source collides. Expansion still emits one job
        # per target category (dedup is the downloader's responsibility);
        # the substituted text and inverse are identical.
        jobs = {cat: (sub, inv) for cat, sub, inv in expand_for_target(_VARIANT, "ru")}
        assert set(jobs) == {"one", "few", "many", "other"}
        assert jobs["one"][0] == "Cleared 1 pinned object"
        assert jobs["few"][0] == "Cleared 3 pinned objects"
        assert jobs["many"][0] == jobs["other"][0] == "Cleared 5 pinned objects"

    def test_variant_arabic_six_categories(self):
        jobs = {cat: (sub, inv) for cat, sub, inv in expand_for_target(_VARIANT, "ar")}
        assert set(jobs) == set(LOCALE_PLURAL_CATEGORIES["ar"])
        # Each category's substitution uses its representative count.
        for cat, (substituted, _) in jobs.items():
            assert cat is not None
            rep = CATEGORY_REPRESENTATIVE_COUNT[cat]
            assert rep in substituted, (cat, substituted)

    def test_variant_japanese_only_other(self):
        jobs = {cat: sub for cat, sub, _ in expand_for_target(_VARIANT, "ja")}
        assert set(jobs) == {"other"}


class TestLookupTranslation:
    """Cache lookup for plain strings and plural variants."""

    def test_plain_hit(self):
        cache = {"default": {"Hello": "Bonjour"}}
        assert lookup_translation(cache, "page_title", "Hello", "fr") == "Bonjour"

    def test_plain_miss_returns_none(self):
        cache = {"default": {"Hello": "Bonjour"}}
        assert lookup_translation(cache, "page_title", "Goodbye", "fr") is None

    def test_plain_uses_context_label_bucket(self):
        cache = {
            "default": {"Amor": "Amour"},
            "orbit_class": {"Amor": "Amor"},
        }
        # The orbit_class_AMO key should pull from the orbit_class bucket.
        out = lookup_translation(cache, "orbit_class_AMO", "Amor", "fr")
        assert out == "Amor"

    def test_plain_falls_back_to_default_bucket(self):
        cache = {"default": {"undocumented": "non documenté"}}
        # type_undocumented routes to the 'type' bucket which is missing;
        # fall back to default.
        out = lookup_translation(cache, "type_undocumented", "undocumented", "fr")
        assert out == "non documenté"

    def test_variant_french_returns_array_with_one_and_other(self):
        cache = {
            "default": {
                "Cleared 1 pinned object": "Suppression de 1 objet épinglé",
                "Cleared 5 pinned objects": "Suppression de {count} objets épinglés",
            }
        }
        out = lookup_translation(cache, "cleared_n_promoted", _VARIANT, "fr")
        assert isinstance(out, list)
        assert out[0]["selectors"] == ["countPlural"]
        assert out[0]["match"] == {
            "countPlural=one": "Suppression de 1 objet épinglé",
            "countPlural=other": "Suppression de {count} objets épinglés",
        }

    def test_variant_one_drops_placeholder_to_literal(self):
        # Legacy cache style: 'one' value has {count} restored. Lookup
        # substitutes it back to the literal '1' for natural reading.
        cache = {
            "default": {
                "Cleared 1 pinned object": "Suppression de {count} objet épinglé",
                "Cleared 5 pinned objects": "Suppression de {count} objets épinglés",
            }
        }
        out = lookup_translation(cache, "cleared_n_promoted", _VARIANT, "fr")
        assert isinstance(out, list)
        assert out[0]["match"]["countPlural=one"] == "Suppression de 1 objet épinglé"

    def test_variant_other_categories_keep_placeholder(self):
        # 'other' must keep {count} because the runtime count is variable.
        cache = {
            "default": {
                "Cleared 1 pinned object": "X 1 X",
                "Cleared 5 pinned objects": "Y {count} Y",
            }
        }
        out = lookup_translation(cache, "cleared_n_promoted", _VARIANT, "fr")
        assert isinstance(out, list)
        assert out[0]["match"]["countPlural=other"] == "Y {count} Y"

    def test_variant_arabic_zero_two_get_literal_counts(self):
        cache = {
            "default": {
                "Cleared 0 pinned objects": "z {count}",
                "Cleared 1 pinned object": "o {count}",
                "Cleared 2 pinned objects": "t {count}",
                "Cleared 3 pinned objects": "f {count}",
                "Cleared 5 pinned objects": "m {count}",
            }
        }
        out = lookup_translation(cache, "cleared_n_promoted", _VARIANT, "ar")
        assert isinstance(out, list)
        match = out[0]["match"]
        # Fixed-count categories: literal numbers.
        assert match["countPlural=zero"] == "z 0"
        assert match["countPlural=one"] == "o 1"
        assert match["countPlural=two"] == "t 2"
        # Variable-count categories: keep placeholder.
        assert match["countPlural=few"] == "f {count}"
        assert match["countPlural=many"] == "m {count}"
        assert match["countPlural=other"] == "m {count}"

    def test_variant_any_missing_returns_none(self):
        cache = {
            "default": {
                "Cleared 1 pinned object": "...",
                # 'other' missing
            }
        }
        out = lookup_translation(cache, "cleared_n_promoted", _VARIANT, "fr")
        assert out is None


class TestFixedCountCategories:
    """Catch regressions if the fixed-count category set drifts."""

    def test_includes_zero_one_two_only(self):
        assert FIXED_COUNT_CATEGORIES == frozenset({"zero", "one", "two"})

    def test_few_many_other_are_variable(self):
        for cat in ("few", "many", "other"):
            assert cat not in FIXED_COUNT_CATEGORIES


class TestLoadTranslations:
    """Migration from legacy flat cache + nested-bucket happy path."""

    def test_missing_file_returns_empty(self, tmp_path, monkeypatch):
        from space_map_data.export import deepl as deepl_mod

        monkeypatch.setattr(deepl_mod, "DEEPL_DIR", tmp_path)
        assert load_translations("fr") == {}

    def test_nested_cache_returned_as_is(self, tmp_path, monkeypatch):
        import orjson

        from space_map_data.export import deepl as deepl_mod

        monkeypatch.setattr(deepl_mod, "DEEPL_DIR", tmp_path)
        nested = {
            "default": {"Hello": "Bonjour"},
            "type": {"asteroid": "astéroïde"},
        }
        (tmp_path / "fr.json").write_bytes(orjson.dumps(nested))
        assert load_translations("fr") == nested

    def test_legacy_flat_cache_lifted_into_default_bucket(self, tmp_path, monkeypatch):
        import orjson

        from space_map_data.export import deepl as deepl_mod

        monkeypatch.setattr(deepl_mod, "DEEPL_DIR", tmp_path)
        flat = {"Hello": "Bonjour", "Goodbye": "Au revoir"}
        (tmp_path / "fr.json").write_bytes(orjson.dumps(flat))
        assert load_translations("fr") == {"default": flat}
