"""Tests for the lines in the stars' units and the luminosity of the far regions."""

import numpy as np
import pytest

from space_map_data.emission import lines, regions, sources


class TestLines:
    def test_the_red_channel_holds_only_the_656_nm_lines(self):
        assert np.allclose(lines.RED_RGB, (1, 0, 0))
        assert lines.HBETA_RGB[0] == 0
        assert lines.HBETA_RGB.max() == 1

    def test_each_channel_dims_at_its_own_line(self):
        assert lines.K_EMISSION[1] == lines.K_EMISSION[2] == lines.K_LINE["hbeta"]
        assert lines.K_LINE["nii_6584"] < lines.K_EMISSION[0] < lines.K_LINE["nii_6548"]

    def test_the_colour_sums_to_one(self):
        assert lines.COLOUR.sum() == pytest.approx(1.0)

    def test_a_rayleigh_is_its_photon_rate(self):
        # 1 R is 10^10 / 4 pi photons m^-2 s^-1 sr^-1: an emissivity along 1 pc that
        # sends this.
        photons_per_m3 = 1e10 / lines.PC_M
        w_per_m3 = photons_per_m3 * lines.HALPHA_PHOTON_J
        assert lines.column_to_rayleigh(w_per_m3) == pytest.approx(1.0)

    def test_the_stored_unit_goes_both_ways(self):
        assert lines.display_to_emissivity(
            lines.emissivity_to_display(3e-27)
        ) == pytest.approx(3e-27)

    def test_luminosity_and_emissivity_agree(self):
        # One pc^3 of emissivity e is a luminosity of e times a pc^3.
        e = 1e-26
        erg_s = e * 1e7 * lines.PC_M**3
        assert lines.luminosity_to_display(erg_s) == pytest.approx(
            lines.emissivity_to_display(e)
        )


class TestRegions:
    def test_one_jansky_at_one_kpc_matches_condon(self):
        # Condon 1992: Q = 6.3e52 (nu / GHz)^0.1 L_nu / 1e27 erg s^-1 Hz^-1 at 10^4 K.
        l_nu = 4 * np.pi * (1e3 * lines.PC_CM) ** 2 * 1e-23
        condon = 6.3e52 * 1.4**0.1 * l_nu / 1e27
        assert regions.rate_of_radio(1.0, 1.0) == pytest.approx(condon, rel=0.02)

    def test_case_b_gives_kennicutts_halpha_per_photon(self):
        # L(H-alpha) = 1.37e-12 Q erg/s (Kennicutt 1998, case B at 10^4 K).
        assert regions.HALPHA_PER_PHOTON_ERG == pytest.approx(1.37e-12, rel=0.01)

    def test_the_infrared_flux_inverts_makais_fit(self):
        row = sources.WiseRow(
            "G", "K", 30.0, 0.0, 60.0, 5.0, "x",
            np.nan, np.nan, 82.188 * 2.0**0.822, np.nan, np.nan, np.nan, "",
        )  # fmt: skip
        assert regions.infrared_radio_flux(row) == pytest.approx(2.0)

    def test_the_radio_flux_is_the_mean_of_both_surveys(self):
        row = sources.WiseRow(
            "G", "K", 30.0, 0.0, 60.0, 5.0, "x", 1.0, 3.0, np.nan, np.nan, np.nan,
            np.nan, "",
        )  # fmt: skip
        assert regions.radio_flux(row) == 2.0

    def test_the_size_fit_finds_a_line(self):
        r = np.array([1.0, 10.0, 100.0])
        slope, offset, scatter = regions.size_fit(r, 10.0 ** (47 + 1.5 * np.log10(r)))
        assert (slope, offset, scatter) == pytest.approx((1.5, 47.0, 0.0), abs=1e-9)

    def test_the_size_rate_is_the_mean_of_the_scatter(self):
        rng = np.random.default_rng(3)
        radius = 10.0 ** rng.uniform(0, 2, 200_000)
        rate = 10.0 ** (47 + 1.4 * np.log10(radius) + rng.normal(0, 0.55, len(radius)))
        slope, offset, scatter = regions.size_fit(radius, rate)
        predicted = regions.size_rate(radius, slope, offset, scatter)
        assert predicted.sum() == pytest.approx(rate.sum(), rel=0.03)
        # The median alone falls short by the lognormal mean, about 2.2 at 0.55 dex.
        assert regions.lognormal_mean(0.55) == pytest.approx(2.23, abs=0.01)

    def test_paint_keeps_the_flux(self):
        found = regions.Regions(
            ["a"], np.array([[1000.0, 0, 0]]), np.array([5.0]), np.array([1e49]),
            np.array([0]), np.array([1e37]), np.array([1.0]), np.array([1000.0]),
            np.array([0.0]), np.array([0.0]),
        )  # fmt: skip
        painted = regions.paint(found, np.array([1e37]), 32)
        pixel_sr = 4 * np.pi / (12 * 32**2)
        flux = 1e37 / (4 * np.pi * (1000 * lines.PC_CM) ** 2)
        photons = painted.sum() * pixel_sr * 1e6 / (4 * np.pi)
        assert photons * lines.HALPHA_PHOTON_J * 1e7 == pytest.approx(flux)


def test_w40_takes_its_measured_distance_and_falls_in_the_cube():
    assert (
        regions.DISTANCE_OVERRIDES["G028.746+03.458"][0] * 1e3 < regions.LOCAL_REACH_PC
    )
