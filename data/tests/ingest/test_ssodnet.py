"""Tests for the SsODNet ingest."""

from space_map_data.ingest.providers.objects.ssodnet import mass_sigma


class TestMassSigma:
    def test_half_the_interval(self):
        """Gonggong: 1.7535e21 kg, -4.3e19 / +4.3e19."""
        assert mass_sigma(-4.3e19, 4.3e19) == 4.3e19

    def test_an_asymmetric_interval(self):
        assert mass_sigma(-2.0, 4.0) == 3.0

    def test_no_error_is_none(self):
        """Hermes: the BFT gives a mass and no error."""
        assert mass_sigma(None, None) is None
