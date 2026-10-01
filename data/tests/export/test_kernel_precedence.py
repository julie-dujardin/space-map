"""`kernel_precedence` decides which kernel wins where two cover the same ET.

Filename order alone gets it backwards for the cruise kernels added to
Galileo and Deep Impact, so both are pinned here.
"""

from space_map_data.export.position.probes.kernels import kernel_precedence

PREDICT, DEFAULT, RECON = 0, 1, 2


class TestKernelPrecedence:
    """Reconstruction furnshes last and wins; predicts furnsh first."""

    def test_recon_and_predict_tokens(self):
        assert kernel_precedence("juno_rec_orbit.bsp") == RECON
        assert kernel_precedence("gaia_flp_2020.bsp") == PREDICT
        assert kernel_precedence("s970311a.bsp") == DEFAULT

    def test_galileo_reanalysis_outranks_the_cruise_series(self):
        # `raj2021` is the 2021 reanalysis of the Jupiter tour; the `s<date>`
        # cruise files name-sort after it and would otherwise win the overlap.
        assert kernel_precedence("gll_951120_021126_raj2021.bsp") == RECON
        assert kernel_precedence("s980326a.bsp") == DEFAULT

    def test_deep_impact_preencounter_never_displaces_an_encounter(self):
        # `preenc174` spans both comet encounters and name-sorts last, so
        # only the tier keeps it under them.
        assert kernel_precedence("dif_preenc174_nav_v1.bsp") == PREDICT
        assert kernel_precedence("dii_preenc174_nav_v1.bsp") == PREDICT
        assert kernel_precedence("di_finalenc_nav_v3.bsp") > PREDICT
        assert kernel_precedence("dif_dixi_nav_v1.bsp") > PREDICT

    def test_substring_hits_do_not_trigger(self):
        # "merged" contains "rec" but is not a reconstruction claim.
        assert kernel_precedence("voyager_1.ST+1991_a54418u.merged.bsp") == DEFAULT

    def test_europa_clipper_newest_flown_delivery_wins(self):
        # `cruiseNNN-final` is flown up to its delivery and predicted after,
        # so a later-starting `reconstruct` arc must load after it.
        names = [
            "trj_250515-250626-dco2507090443-cruise006-reconstruct-OD067-v1.bsp",
            "trj_250318-251018-dco2506180204-cruise008-final-OD064-v1.bsp",
            "trj_260808-270123-dco2609230549-cruise019-predict-OD092-v1.bsp",
            "trj_241014-241103-dco2410142047-postLaunch-OD001-v1.bsp",
            "ref_trj_241014_340903_21F31_MEGA_L241014_A300411_LP05_V7_scpse.bsp",
        ]
        assert sorted(names, key=lambda n: (kernel_precedence(n), n)) == [
            "ref_trj_241014_340903_21F31_MEGA_L241014_A300411_LP05_V7_scpse.bsp",
            "trj_260808-270123-dco2609230549-cruise019-predict-OD092-v1.bsp",
            "trj_241014-241103-dco2410142047-postLaunch-OD001-v1.bsp",
            "trj_250318-251018-dco2506180204-cruise008-final-OD064-v1.bsp",
            "trj_250515-250626-dco2507090443-cruise006-reconstruct-OD067-v1.bsp",
        ]
