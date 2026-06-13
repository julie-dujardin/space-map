"""Tests for COSPAR/OBJECT_ID-prefix constellation matching —
``slug_from_cospar`` and the ``OBJECT_ID_PREFIX_TO_SLUG`` table."""

from space_map_data.constants.earth_sats.constellations import (
    CONSTELLATION_BY_SLUG,
    OBJECT_ID_PREFIX_TO_SLUG,
    slug_from_cospar,
)


class TestSlugFromCospar:
    """Launch-ID prefix matching against the OBJECT_ID (COSPAR designator)."""

    def test_exact_launch_core(self):
        assert slug_from_cospar("1979-017") == "solwind-debris"

    def test_parent_payload_suffix_matches(self):
        # startswith semantics: the intact payload (…A) shares the launch core.
        assert slug_from_cospar("1979-017A") == "solwind-debris"

    def test_debris_piece_suffix_matches(self):
        assert slug_from_cospar("1979-017DA") == "solwind-debris"

    def test_other_launches(self):
        assert slug_from_cospar("2019-006A") == "microsat-r-debris"
        assert slug_from_cospar("1991-063XY") == "uars-debris"
        assert slug_from_cospar("2013-030B") == "resurs-p1-debris"

    def test_unknown_launch_is_none(self):
        assert slug_from_cospar("9999-999A") is None

    def test_none_and_empty(self):
        assert slug_from_cospar(None) is None
        assert slug_from_cospar("") is None

    def test_unrelated_prefix_does_not_match(self):
        # A different launch in the same year must not collide.
        assert slug_from_cospar("1979-018A") is None


class TestObjectIdPrefixTable:
    """Integrity of the generated prefix→slug table."""

    def test_every_prefix_resolves_to_a_real_constellation(self):
        for slug in OBJECT_ID_PREFIX_TO_SLUG.values():
            assert slug in CONSTELLATION_BY_SLUG

    def test_sorted_longest_prefix_first(self):
        lengths = [len(p) for p in OBJECT_ID_PREFIX_TO_SLUG]
        assert lengths == sorted(lengths, reverse=True)

    def test_table_covers_all_specs_with_object_id_prefix(self):
        expected = {
            p
            for c in CONSTELLATION_BY_SLUG.values()
            if c.object_id_prefix is not None
            for p in (
                c.object_id_prefix
                if isinstance(c.object_id_prefix, tuple)
                else (c.object_id_prefix,)
            )
        }
        assert set(OBJECT_ID_PREFIX_TO_SLUG) == expected
