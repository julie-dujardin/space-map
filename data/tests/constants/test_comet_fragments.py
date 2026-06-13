"""Tests for split-comet fragment designation parsing."""

import pytest

from space_map_data.constants.comet_fragments import (
    FragmentDesignation,
    split_fragment,
)
from space_map_data.models.object.sbdb import CometPrefix


class TestSplitFragment:
    """split_fragment isolates the parent designation + fragment letters."""

    @pytest.mark.parametrize(
        ("pdes", "prefix", "expected"),
        [
            ("73P-C", CometPrefix.P, FragmentDesignation("73P", "C")),
            ("73P-AA", CometPrefix.P, FragmentDesignation("73P", "AA")),
            ("73P-BY", CometPrefix.P, FragmentDesignation("73P", "BY")),
            ("C/2019 Y4-A", CometPrefix.C, FragmentDesignation("C/2019 Y4", "A")),
            ("1993 F2-A", CometPrefix.D, FragmentDesignation("1993 F2", "A")),
            ("332P-B", CometPrefix.P, FragmentDesignation("332P", "B")),
        ],
    )
    def test_recognizes_fragments(self, pdes, prefix, expected):
        assert split_fragment(pdes, prefix) == expected

    @pytest.mark.parametrize(
        ("pdes", "prefix"),
        [
            ("73P", CometPrefix.P),  # intact parent, no suffix
            ("C/2019 Y4", CometPrefix.C),
            ("433", CometPrefix.P),  # numbered asteroid (hypothetical prefix)
            ("2010 AB12", CometPrefix.C),  # provisional, no trailing -letters
        ],
    )
    def test_non_fragments_return_none(self, pdes, prefix):
        assert split_fragment(pdes, prefix) is None

    @pytest.mark.parametrize(
        ("pdes", "prefix"),
        [
            ("6344 P-L", None),  # Palomar-Leiden survey asteroid, no comet prefix
            ("3138 T-1", None),  # Trojan survey asteroid
            ("6344 P-L", CometPrefix.A),  # asteroidal prefix is not a comet
            ("12P-X", CometPrefix.I),  # interstellar prefix excluded
        ],
    )
    def test_non_comet_prefix_excluded(self, pdes, prefix):
        assert split_fragment(pdes, prefix) is None

    def test_none_pdes(self):
        assert split_fragment(None, CometPrefix.P) is None
