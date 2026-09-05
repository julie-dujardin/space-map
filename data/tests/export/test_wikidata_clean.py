"""Tests for the label and text cleaning in space_map_data.export.wikidata."""

from space_map_data.export.wikidata import clean_label, clean_text


class TestCleanLabel:
    """Invisible marks, whitespace runs, disambiguators and minus-as-dash."""

    def test_strips_bidi_and_zero_width_marks(self):
        assert clean_label("Interim Cryogenic Propulsion Stage\u200e") == (
            "Interim Cryogenic Propulsion Stage"
        )
        assert clean_label("C/1995 Q1\u200e\u200b") == "C/1995 Q1"

    def test_collapses_whitespace_runs(self):
        assert clean_label("SECOR  8") == "SECOR 8"
        assert clean_label(" Vela\t6A ") == "Vela 6A"

    def test_drops_trailing_disambiguator(self):
        assert clean_label("Mazaalai (satellite)") == "Mazaalai"
        assert clean_label("Ramses (spacecraft)") == "Ramses"
        # Only the catalogue kinds go; a body's qualifier is part of its name.
        assert clean_label("Ceres (dwarf planet)") == "Ceres (dwarf planet)"

    def test_minus_between_letters_becomes_a_dash(self):
        assert clean_label("Cassini\u2212Huygens") == "Cassini\u2013Huygens"
        # A minus beside a digit is arithmetic, not punctuation.
        assert clean_label("2010 XY\u22121") == "2010 XY\u22121"


class TestCleanText:
    """Prose keeps its parentheticals; only marks and whitespace runs go."""

    def test_keeps_parenthetical(self):
        assert clean_text("A probe (spacecraft) that\u200b  flew") == (
            "A probe (spacecraft) that flew"
        )
