"""Tests for the tidal lock of a planet: Gladman et al.'s despinning time
against the age of its star, and Hut's pseudo-synchronous spin."""

import pytest

from space_map_data.constants.planets.families import (
    EARTH_MASSES_PER_JUPITER,
    EARTH_RADII_PER_JUPITER,
)
from space_map_data.export.extrasolar.tidal_lock import (
    lock_time,
    pseudo_synchronous_ratio,
    tidally_locked,
)

EARTH_MASS = 1 / EARTH_MASSES_PER_JUPITER
EARTH_RADIUS = 1 / EARTH_RADII_PER_JUPITER
HOST = {"mass": 1.0, "age": None}


class TestLockTime:
    """The despinning time in years."""

    def test_the_earth_around_the_sun(self):
        """About 2 × 10¹¹ years with Q = 100 and k₂ = 0.3: the Earth is not
        locked."""
        years = lock_time(1.0, EARTH_MASS, EARTH_RADIUS, 1.0)
        assert years == pytest.approx(2.0e11, rel=0.05)

    def test_a_planet_with_an_envelope_despins_slower(self):
        """Above 1.6 Earth radii, Q is 1000 times larger and k₂ 5/3 as
        large."""
        rocky = lock_time(0.05, 0.01, 1.59 * EARTH_RADIUS, 0.5)
        gas = lock_time(0.05, 0.01, 1.61 * EARTH_RADIUS, 0.5)
        size = (1.59 / 1.61) ** 3
        assert gas / rocky == pytest.approx(1000 * 0.3 / 0.5 * size)

    def test_the_sixth_power_of_the_distance(self):
        near = lock_time(0.1, 1.0, 1.0, 1.0)
        assert lock_time(0.2, 1.0, 1.0, 1.0) == pytest.approx(64 * near)


class TestPseudoSynchronousRatio:
    """Hut 1981, eq. 42."""

    def test_a_circular_orbit_is_synchronous(self):
        assert pseudo_synchronous_ratio(0.0) == 1.0

    def test_the_tolerance_is_near_an_eccentricity_of_0_09(self):
        assert pseudo_synchronous_ratio(0.09) < 1.05 < pseudo_synchronous_ratio(0.1)


class TestTidallyLocked:
    """Locked when the despinning time is shorter than the star's age and
    the spin is near synchronous."""

    def test_a_close_rocky_planet_is_locked(self):
        values = {"semi_major_axis": 0.03, "mass": 0.002, "radius": 0.08}
        assert tidally_locked(values | {"star_mass": 0.09}, HOST) is True

    def test_a_far_planet_is_not(self):
        values = {"semi_major_axis": 0.8, "mass": 0.03, "radius": 0.19}
        assert tidally_locked(values | {"star_mass": 0.86}, HOST) is False

    def test_the_age_of_the_star_counts(self):
        """2 × 10¹¹ years: locked around a star of 1000 Gyr, not at 1 Gyr."""
        values = {"semi_major_axis": 1.0, "mass": EARTH_MASS, "radius": EARTH_RADIUS}
        assert tidally_locked(values, HOST) is False
        assert tidally_locked(values, HOST | {"age": 1000.0}) is True

    def test_the_host_mass_stands_in_for_the_fit(self):
        values = {"semi_major_axis": 0.03, "mass": 0.002, "radius": 0.08}
        assert tidally_locked(values, {"mass": 0.09, "age": None}) is True

    @pytest.mark.parametrize("missing", ["semi_major_axis", "mass", "radius"])
    def test_unknown_without_a_value(self, missing):
        values = {"semi_major_axis": 0.03, "mass": 0.002, "radius": 0.08}
        del values[missing]
        assert tidally_locked(values, HOST) is None

    def test_unknown_without_a_star_mass(self):
        values = {"semi_major_axis": 0.03, "mass": 0.002, "radius": 0.08}
        assert tidally_locked(values, {"mass": None, "age": None}) is None

    def test_a_despun_eccentric_planet_is_not_locked(self):
        """HAT-P-11 b despins in about 10⁶ years, but at e = 0.26 it spins
        about 1.4 times per orbit."""
        values = {
            "semi_major_axis": 0.05254,
            "mass": 0.0736,
            "radius": 0.389,
            "star_mass": 0.81,
        }
        host = {"mass": 0.81, "age": 6.5}
        assert lock_time(0.05254, 0.0736, 0.389, 0.81) < 1e7
        assert tidally_locked(values | {"eccentricity": 0.2644}, host) is False
        assert tidally_locked(values | {"eccentricity": 0.0}, host) is True

    def test_a_small_eccentricity_stays_locked(self):
        values = {"semi_major_axis": 0.03, "mass": 0.002, "radius": 0.08}
        assert tidally_locked(values | {"eccentricity": 0.05}, HOST) is True

    def test_unknown_with_an_eccentricity_outside_the_ellipse(self):
        values = {"semi_major_axis": 0.03, "mass": 0.002, "radius": 0.08}
        assert tidally_locked(values | {"eccentricity": 1.2}, HOST) is None
