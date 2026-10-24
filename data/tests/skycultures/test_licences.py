"""Tests for reading a culture's licence and its distribution tier."""

from space_map_data.skycultures.licences import (
    DATA,
    ILLUSTRATIONS,
    NO_DERIVATIVES,
    NO_LICENCE,
    NON_COMMERCIAL,
    OPEN,
    TK_LABELS,
    UNDECIDED,
    UNKNOWN_LICENCE,
    Part,
    licence_section,
    normalise,
    read_licence,
)

POTAWATOMI = """## License

License (artwork): CC BY-NC-SA 4.0

The artwork in this Sky Culture may be shared for non-commercial purposes.

License (Sky Culture): CC BY-SA 4.0

### Licenses and Permissions Justification

The artwork is licensed under CC BY-NC-SA 4.0.

**TK Non-Commercial (TK NC)**

This material has been designated as being available for non-commercial use.
"""


class TestSection:
    """The statement is the text under the `## License` heading."""

    def test_stops_at_the_next_level_two_heading(self):
        text = "# A\n\n## License\n\nCC BY 4.0\n\n## Acknowledgements\n\nThanks\n"
        assert licence_section(text) == "CC BY 4.0"

    def test_keeps_sub_headings(self):
        section = licence_section(POTAWATOMI)
        assert section is not None and "TK Non-Commercial" in section

    def test_empty_section_and_no_section(self):
        assert licence_section("## License\n") == ""
        assert licence_section("# Title\n") is None


class TestNormalise:
    """Each licence in one spelling."""

    def test_spellings(self):
        assert normalise("CC BY-ND 4.0 International") == "CC BY-ND 4.0"
        assert normalise("CC BY-SA 3.0 Unported") == "CC BY-SA 3.0"
        assert normalise("CC BY-SA") == "CC BY-SA"
        assert normalise("GNU GPL v2.0") == "GPL-2.0"
        assert normalise("Illustrations: Free Art License") == "Free Art License"
        assert normalise("All rights reserved") is None


class TestReadLicence:
    """Tiers and flags for the forms the cultures use."""

    def test_single_licence(self):
        licence = read_licence("CC BY-SA 4.0")
        assert (licence.data, licence.illustrations, licence.flags) == (OPEN, OPEN, ())

    def test_no_derivatives_stays_open_and_is_flagged(self):
        licence = read_licence("CC BY-ND 4.0")
        assert licence.data == OPEN
        assert licence.flags == (NO_DERIVATIVES,)

    def test_non_commercial_no_derivatives(self):
        licence = read_licence("CC BY-NC-ND 4.0")
        assert licence.data == NON_COMMERCIAL
        assert set(licence.flags) == {NO_DERIVATIVES, NON_COMMERCIAL}

    def test_parts_for_data_and_illustrations(self):
        licence = read_licence(
            "Text and data: GNU GPL v2.0\n\nIllustrations: Free Art License"
        )
        assert licence.parts == (
            Part(DATA, "GPL-2.0"),
            Part(ILLUSTRATIONS, "Free Art License"),
        )

    def test_traditional_knowledge_nc_label_makes_all_non_commercial(self):
        licence = read_licence(licence_section(POTAWATOMI))
        assert licence.parts == (
            Part(ILLUSTRATIONS, "CC BY-NC-SA 4.0"),
            Part(DATA, "CC BY-SA 4.0"),
        )
        assert (licence.data, licence.illustrations) == (NON_COMMERCIAL, NON_COMMERCIAL)
        assert TK_LABELS in licence.flags and NON_COMMERCIAL in licence.flags

    def test_missing_statement_is_non_commercial_and_flagged(self):
        for text in (None, ""):
            licence = read_licence(text)
            assert (licence.data, licence.illustrations) == (
                NON_COMMERCIAL,
                NON_COMMERCIAL,
            )
            assert licence.flags == (NO_LICENCE,)

    def test_unreadable_statement_is_undecided(self):
        licence = read_licence("Ask the author first.")
        assert (licence.data, licence.flags) == (UNDECIDED, (UNKNOWN_LICENCE,))

    def test_as_dict_carries_the_statement(self):
        out = read_licence("CC BY 4.0").as_dict()
        assert out["text"] == "CC BY 4.0"
        assert out["parts"] == [{"applies_to": "all", "licence": "CC BY 4.0"}]
        assert out["distribution"] == OPEN
