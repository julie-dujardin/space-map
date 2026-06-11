"""Tests for space_map_data.constants.earth_sats.orbit_class — shape-class
boundaries (eccentricity cut, sync band, graveyard, HIGH) and inclination
bands."""

from space_map_data.constants.earth_sats.orbit_class import (
    EarthOrbitClass,
    classify_earth_orbit,
)


def shape(peri: float, apo: float, inc: float | None = None) -> EarthOrbitClass:
    return classify_earth_orbit(peri, apo, inc)[0]


class TestLowOrbits:
    """VLEO/LEO apogee cuts and the LEO-only inclination bands."""

    def test_vleo(self):
        assert shape(350, 450) == EarthOrbitClass.VLEO

    def test_leo(self):
        assert shape(500, 1500) == EarthOrbitClass.LEO

    def test_sso_band_on_leo(self):
        assert classify_earth_orbit(500, 800, 97.5) == [
            EarthOrbitClass.LEO,
            EarthOrbitClass.SSO,
        ]

    def test_no_band_above_leo(self):
        assert classify_earth_orbit(2500, 20000, 97.5) == [EarthOrbitClass.MEO]


class TestEccentricityCut:
    """GCAT's e = 0.5 boundary splits HEO from the MEO catch-all."""

    def test_decayed_gto_debris_is_heo(self):
        # peri raised by perturbations; e ≈ 0.64.
        assert shape(3010, 35752) == EarthOrbitClass.HEO

    def test_just_below_cut_is_meo(self):
        # e ≈ 0.49.
        assert shape(8019, 35550) == EarthOrbitClass.MEO

    def test_molniya_shape_without_inclination_is_heo(self):
        # Apogee past the GTO ceiling, so only the e-cut can claim it.
        assert shape(600, 43000) == EarthOrbitClass.HEO

    def test_near_circular_subsync_disposal_is_meo(self):
        # e ≈ 0.03; was a fall-through HEO before the cut existed.
        assert shape(33223, 35986) == EarthOrbitClass.MEO

    def test_mildly_eccentric_low_orbit_is_meo(self):
        # e ≈ 0.12; apogee above LEO but nowhere near "highly elliptical".
        assert shape(1000, 3000) == EarthOrbitClass.MEO

    def test_circular_meo(self):
        assert shape(20180, 20230) == EarthOrbitClass.MEO


class TestSyncBand:
    """GSO band square, eccentric strip, and the graveyard floor."""

    def test_geo(self):
        assert shape(35780, 35790, 0.1) == EarthOrbitClass.GEO

    def test_igso(self):
        assert shape(35700, 35850, 55.0) == EarthOrbitClass.IGSO

    def test_gso_without_inclination(self):
        assert shape(35000, 36000) == EarthOrbitClass.GSO

    def test_graveyard_in_band(self):
        assert shape(36100, 36300, 1.0) == EarthOrbitClass.GRA

    def test_graveyard_eccentric_strip(self):
        # Perigee above the disposal floor, apogee well out of the band.
        assert shape(36500, 45000) == EarthOrbitClass.GRA

    def test_gso_eccentric_strip_below_floor(self):
        assert shape(34500, 45000) == EarthOrbitClass.GSO


class TestHighEarthOrbit:
    """HIGH: perigee entirely above the sync band, apogee below cislunar."""

    def test_supersync_near_circular(self):
        assert shape(38453, 39290) == EarthOrbitClass.HIGH

    def test_tess_like(self):
        assert shape(108000, 375000) == EarthOrbitClass.HIGH

    def test_low_perigee_stays_cis(self):
        assert shape(2000, 100000) == EarthOrbitClass.CIS

    def test_beyond_cislunar_is_vheo(self):
        assert shape(200000, 600000) == EarthOrbitClass.VHEO


class TestSpecificEccentricClasses:
    """MOL/TUN/GTO carve-outs take precedence over the eccentricity cut."""

    def test_molniya(self):
        assert shape(600, 39000, 63.0) == EarthOrbitClass.MOL

    def test_tundra(self):
        assert shape(24000, 47000, 63.4) == EarthOrbitClass.TUN

    def test_gto(self):
        assert shape(250, 35786, 28.5) == EarthOrbitClass.GTO

    def test_missing_perigee_unclassified(self):
        assert classify_earth_orbit(None, 35786, 28.5) == []
