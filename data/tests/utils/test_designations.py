"""Tests for provisional-designation display and the IAU-named test."""

from space_map_data.utils.designations import (
    format_provisional_designation,
    is_iau_named,
)


class TestFormatProvisionalDesignation:
    """NAIF's compressed spelling → the IAU's."""

    def test_compressed_forms(self):
        assert format_provisional_designation("S2019_S37") == "S/2019 S 37"
        assert format_provisional_designation("S2020 S48") == "S/2020 S 48"
        assert format_provisional_designation("S2003_J9") == "S/2003 J 9"

    def test_already_formatted(self):
        assert format_provisional_designation("S/2019 S 37") == "S/2019 S 37"

    def test_minor_planet_form_untouched(self):
        # The parenthesised host number doesn't fit the pattern; leave it be.
        assert (
            format_provisional_designation("S/2008 (524531) 1") == "S/2008 (524531) 1"
        )

    def test_empty(self):
        assert format_provisional_designation(None) is None
        assert format_provisional_designation("") is None


class TestIsIauNamed:
    """A moon's `name` is only a name when it isn't its designation."""

    def test_real_names(self):
        assert is_iau_named("Titan", None)
        assert is_iau_named("Phobos", "S1877_M1")

    def test_name_restating_the_designation(self):
        assert not is_iau_named("S2010_J1", "S2010_J1")
        # The DB normalizes some spellings, so compare on alphanumerics only.
        assert not is_iau_named("S2003_J18", "2003J18")

    def test_designation_with_nothing_to_compare_against(self):
        assert not is_iau_named("S2002_N5", None)
        assert not is_iau_named("2023U1", None)
        assert not is_iau_named("S/2008 (524531) 1", None)

    def test_missing_name(self):
        assert not is_iau_named(None, "S2019_S37")
        assert not is_iau_named("", "S2019_S37")

    def test_non_ascii_name(self):
        # Gǃòʼé‑Hú, S/2008 (229762) 1 — click consonants, and mojibake of it,
        # which a "does the name contain a digit" test misreads (the mangled
        # form holds a superscript two).
        assert is_iau_named("Gǃòʼé‑Hú", "S/2008 (229762) 1")
        assert is_iau_named("GÇƒÃ²Ê¼Ã©ÇƒHÃº", "S/2008 (229762) 1")
