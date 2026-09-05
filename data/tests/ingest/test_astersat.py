"""Tests for space_map_data.ingest.providers.objects.astersat."""

import pytest

from space_map_data.ingest.providers.objects.astersat import _fold, _parse_orbit

# The header AsterSat prints above every ephemeris, trimmed to what we read.
_PAGE = """<html><body><pre>
AsterSat: Satellites of asteroids ephemeris. Version 22.03.25
Ephemerides for Object: (22) Kalliope Satellite: Linus
Main body radius=   83.100 km
Satellite radius=   14.000 km
Observations on the time interval 2001.662-2021.958 =  20.296 y  7413.1 d
 139 observations giving RMS=  0.024 arcsec
Satellite orbit (geoequat J2000):
Epoch=52000.000000 (MJD) = 2001  4  1
a=   1078.300 km   n=100.11980010 deg/day   Period=   3.595692 day
e= 0.003814004      i= 94.38318390 deg
M0=  8.797198 deg  omega=251.182253 deg  Omega=285.358496 deg
Mass of the system=      0.51284487 km^3/s^2 = 7.686524e+18 kg
</pre></body></html>"""


@pytest.fixture
def row():
    parsed = _parse_orbit(_PAGE)
    assert parsed is not None
    return parsed


class TestParseOrbit:
    """The element block is read out of the response header."""

    def test_full_element_set(self, row):
        assert row["frame"] == "geoequat J2000"
        assert row["epoch_mjd"] == 52000.0
        assert row["a_km"] == 1078.300
        assert row["e"] == 0.003814004
        assert row["i"] == 94.38318390
        assert row["om"] == 285.358496
        assert row["w"] == 251.182253
        assert row["ma"] == 8.797198
        assert row["n"] == 100.11980010
        assert row["per_d"] == 3.595692

    def test_fit_provenance(self, row):
        assert row["n_obs"] == 139
        assert row["rms_arcsec"] == 0.024
        assert (row["obs_arc_start"], row["obs_arc_end"]) == (2001.662, 2021.958)
        assert row["primary_radius_km"] == 83.100
        assert row["satellite_radius_km"] == 14.000

    def test_elements_agree_with_the_published_system_mass(self, row):
        """Kepler's third law ties a, n and GM — a mis-parse would break it."""
        import math

        n_rad_s = math.radians(row["n"]) / 86400.0
        assert n_rad_s**2 * row["a_km"] ** 3 == pytest.approx(row["gm"], rel=1e-3)

    def test_a_refused_request_has_no_orbit(self):
        """The service answers 200 with an exit code and no block."""
        assert _parse_orbit("<pre>AsterSat ... exit N 8008</pre>") is None


class TestFold:
    """AsterSat's display labels and our designations differ cosmetically."""

    @pytest.mark.parametrize(
        "left,right",
        [
            ("S/2001(107)1", "S/2001 (107) 1"),
            ("Ilmare", "Ilmarë"),
            ("Pichi unem", "Pichi üñëm"),
            ("G!o'e!Hu", "Gǃòʼé ǃHú"),
        ],
    )
    def test_labels_that_should_match(self, left, right):
        assert _fold(left) == _fold(right)

    def test_different_moons_stay_apart(self):
        assert _fold("S/2001 (107) 1") != _fold("S/2016 (107) 1")
