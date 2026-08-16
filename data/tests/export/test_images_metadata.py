"""Export-side sanitization of Commons artist/description fields."""

from space_map_data.export.images import _locale_field, _strip_html


class TestStripHtml:
    """`_strip_html` reduces attacker-editable Commons HTML to plain text."""

    def test_plain_text_passthrough(self) -> None:
        assert _strip_html("Jane Doe") == "Jane Doe"

    def test_drops_tags_keeps_text(self) -> None:
        assert _strip_html('<a href="/wiki/User:X">Jane</a>') == "Jane"

    def test_strips_active_content(self) -> None:
        # The XSS vector: no tag survives, so nothing can fire downstream.
        out = _strip_html('<img src=x onerror="alert(1)">caption')
        assert "<" not in out
        assert "onerror" not in out
        assert out == "caption"

    def test_block_tags_become_newlines(self) -> None:
        assert _strip_html("<p>one</p><p>two</p>") == "one\ntwo"

    def test_br_becomes_newline(self) -> None:
        assert _strip_html("a<br>b") == "a\nb"

    def test_collapses_whitespace_within_markup(self) -> None:
        # Collapses only when there's markup to strip; plain strings stay byte-for-byte.
        assert _strip_html("a   \t <b>b</b>") == "a b"
        assert _strip_html("a   \t b") == "a   \t b"


class TestLocaleField:
    """`_locale_field` normalizes + sanitizes bare-string and multilang values."""

    def test_bare_string_stripped(self) -> None:
        assert _locale_field({"value": "<b>Jane</b>"}) == "Jane"

    def test_multilang_each_value_stripped(self) -> None:
        field = {"value": {"en": "<i>Author</i>", "fr": "Auteur", "_type": "x"}}
        assert _locale_field(field) == {"en": "Author", "fr": "Auteur"}

    def test_empty_after_strip_collapses_to_none(self) -> None:
        assert _locale_field({"value": "   "}) is None

    def test_none_field(self) -> None:
        assert _locale_field(None) is None
