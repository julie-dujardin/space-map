"""`is_spacecraft_naif` decides which NAIF targets become probe rows.

Sample-return capsules are numbered like the sub-NAIFs the rules exclude, so
both the exclusions and the exceptions are pinned here.
"""

from space_map_data.probes.probe_id import is_spacecraft_naif


class TestSubNaifExclusions:
    """Landing sites and instrument frames never get a probe row."""

    def test_landing_site_naif_excluded(self):
        assert not is_spacecraft_naif(-253900, {-253, -253900})

    def test_instrument_frame_under_a_known_parent_excluded(self):
        assert not is_spacecraft_naif(-76501, {-76, -76501})

    def test_instrument_pattern_needs_the_parent_present(self):
        # -1176 is CAPSTONE, not a sub-NAIF of -1: without -1 in the target
        # set there is no parent to be a frame of.
        assert is_spacecraft_naif(-1176, {-1176})

    def test_positive_naif_is_never_a_spacecraft(self):
        # Mission kernels carry planetary segments (Venus 299, Earth 399)
        # alongside the spacecraft.
        assert not is_spacecraft_naif(299, {-18, 299})


class TestSampleReturnCapsules:
    """Each capsule separates and flies its own entry, so each is a probe."""

    def test_stardust_src_survives_the_landing_site_rule(self):
        assert is_spacecraft_naif(-29900, {-29, -29900})

    def test_genesis_src_survives_the_landing_site_rule(self):
        assert is_spacecraft_naif(-47900, {-47, -47900})

    def test_orex_src_survives_the_instrument_frame_rule(self):
        assert is_spacecraft_naif(-64090, {-64, -64090})
