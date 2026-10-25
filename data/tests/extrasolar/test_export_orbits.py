"""Tests for the planet orbits of the extrasolar export, from the plane of the
sky to the scene's ecliptic frame."""

import math

import numpy as np
import pytest

from space_map_data.export.extrasolar import orbits

EPS = math.radians(orbits.OBLIQUITY)


def _row(**values) -> dict:
    row = {
        "semi_major_axis": 1.0,
        "period": 365.25,
        "eccentricity": 0.0,
        "inclination": 90.0,
        "node_inclination": None,
        "omega": 90.0,
        "node": 0.0,
        "transit_time": None,
        "periastron_time": 2_451_545.0,
        "discovery_method": "Radial Velocity",
        "assumed": [],
    }
    return row | values


def _direction(ra: float, dec: float) -> np.ndarray:
    ra, dec = math.radians(ra), math.radians(dec)
    return np.array(
        [math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)]
    )


def _to_ecliptic(v: np.ndarray) -> np.ndarray:
    return np.array(
        [
            v[0],
            v[1] * math.cos(EPS) + v[2] * math.sin(EPS),
            -v[1] * math.sin(EPS) + v[2] * math.cos(EPS),
        ]
    )


def _anomalies(mean_deg: float, e: float) -> tuple[float, float]:
    """True anomaly (rad) and radius factor r / a."""
    m = math.radians(mean_deg)
    big_e = m
    for _ in range(50):
        big_e -= (big_e - e * math.sin(big_e) - m) / (1 - e * math.cos(big_e))
    nu = 2 * math.atan2(
        math.sqrt(1 + e) * math.sin(big_e / 2), math.sqrt(1 - e) * math.cos(big_e / 2)
    )
    return nu, 1 - e * math.cos(big_e)


def _scene_position(el: dict, t: float) -> np.ndarray:
    """The frontend's orbitalElementsToPositionJD on the ecliptic, before
    its swap of axes into three.js."""
    nu, r = _anomalies(el["ma"] + el["n"] * (t - el["epoch"]), el["e"])
    x_orb, y_orb = el["a"] * r * math.cos(nu), el["a"] * r * math.sin(nu)
    w, i, om = (math.radians(el[k]) for k in ("w", "i", "om"))
    cw, sw, ci, si, co, so = (
        math.cos(w),
        math.sin(w),
        math.cos(i),
        math.sin(i),
        math.cos(om),
        math.sin(om),
    )
    x = (co * cw - so * sw * ci) * x_orb + (-co * sw - so * cw * ci) * y_orb
    y = (so * cw + co * sw * ci) * x_orb + (-so * sw + co * cw * ci) * y_orb
    z = sw * si * x_orb + cw * si * y_orb
    return np.array([x, y, z])


def _sky_position(
    ra: float,
    dec: float,
    a: float,
    e: float,
    i: float,
    node: float,
    omega: float,
    mean_deg: float,
) -> np.ndarray:
    """The textbook orbit on the sky (north, east, away from us), turned to
    ICRS by the star's own axes, then to the ecliptic."""
    nu, r = _anomalies(mean_deg, e)
    u = math.radians(omega) + nu
    i, node = math.radians(i), math.radians(node)
    north_offset = (
        a
        * r
        * (math.cos(node) * math.cos(u) - math.sin(node) * math.sin(u) * math.cos(i))
    )
    east_offset = (
        a
        * r
        * (math.sin(node) * math.cos(u) + math.cos(node) * math.sin(u) * math.cos(i))
    )
    away_offset = a * r * math.sin(u) * math.sin(i)
    ra, dec = math.radians(ra), math.radians(dec)
    north = np.array(
        [-math.sin(dec) * math.cos(ra), -math.sin(dec) * math.sin(ra), math.cos(dec)]
    )
    east = np.array([-math.sin(ra), math.cos(ra), 0.0])
    away = np.array(
        [math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)]
    )
    return _to_ecliptic(north_offset * north + east_offset * east + away_offset * away)


class TestEclipticAngles:
    """Cases checked by hand."""

    def test_a_face_on_orbit_at_ra_0_dec_0(self):
        # The orbit turns from north (ICRS +z) to east (ICRS +y), so its pole
        # points back at us, along ICRS -x: on the ecliptic, i = 90° and the
        # node is at longitude 270°. Periastron is north, at ecliptic
        # (0, sin ε, cos ε): ω = 90° + ε.
        i, om, w = orbits.ecliptic_angles(np.array([1.0, 0, 0]), 0.0, 0.0, 0.0)
        assert i == pytest.approx(90.0)
        assert om == pytest.approx(270.0)
        assert w == pytest.approx(90.0 + orbits.OBLIQUITY)

    def test_a_face_on_orbit_at_the_north_ecliptic_pole(self):
        # Seen from below the ecliptic, an orbit that turns north to east turns
        # clockwise on the ecliptic.
        pole = np.array([0.0, -math.sin(EPS), math.cos(EPS)])
        assert orbits.ecliptic_angles(pole, 0.0, 0.0, 0.0)[0] == pytest.approx(180.0)
        assert orbits.ecliptic_angles(pole, 180.0, 0.0, 0.0)[0] == pytest.approx(0.0)

    def test_the_scene_draws_the_orbit_of_the_sky(self):
        rng = np.random.default_rng(4)
        for _ in range(40):
            ra, dec = rng.uniform(0, 360), math.degrees(math.asin(rng.uniform(-1, 1)))
            e, i, node, omega = (
                rng.uniform(0, 0.9),
                rng.uniform(0, 180),
                rng.uniform(0, 360),
                rng.uniform(0, 360),
            )
            el = {"a": 2.0, "e": e, "ma": 0.0, "n": 1.0, "epoch": 0.0}
            el["i"], el["om"], el["w"] = orbits.ecliptic_angles(
                _direction(ra, dec), i, node, omega
            )
            for mean in (0.0, 37.0, 123.0, 250.0):
                expected = _sky_position(ra, dec, 2.0, e, i, node, omega, mean)
                assert _scene_position(el, mean) == pytest.approx(expected, abs=1e-9)


class TestElements:
    """The scene's elements of a planets table row."""

    def test_a_transit_puts_the_planet_between_us_and_its_star(self):
        rng = np.random.default_rng(7)
        for _ in range(20):
            ra, dec = rng.uniform(0, 360), rng.uniform(-80, 80)
            direction = _direction(ra, dec)
            row = _row(
                eccentricity=rng.uniform(0, 0.8),
                omega=rng.uniform(-180, 360),
                node=rng.uniform(0, 360),
                transit_time=2_459_000.5,
            )
            el = orbits.elements(row, direction)
            assert el is not None and el["phase"] == orbits.TRANSIT
            at = _scene_position(el, 2_459_000.5)
            towards_us = -_to_ecliptic(direction)
            assert at / np.linalg.norm(at) == pytest.approx(towards_us, abs=1e-9)

    def test_a_published_omega_is_the_stars(self):
        # ω* = 90° puts the transit at periastron (f = 90° − ω*).
        el = orbits.elements(
            _row(eccentricity=0.5, omega=90.0, transit_time=2_459_000.5),
            _direction(10, 20),
        )
        assert el is not None
        assert el["ma"] == pytest.approx(0.0, abs=1e-9)

    def test_an_imaged_planet_keeps_its_omega(self):
        # The planet's own ω = 90°: the conjunction is at ν = 180°.
        el = orbits.elements(
            _row(
                eccentricity=0.5,
                omega=90.0,
                transit_time=2_459_000.5,
                discovery_method=orbits.IMAGING,
            ),
            _direction(10, 20),
        )
        assert el is not None
        assert el["ma"] == pytest.approx(180.0)

    def test_mean_motion_and_epoch(self):
        el = orbits.elements(
            _row(period=4.0, periastron_time=2_450_000.0), _direction(0, 0)
        )
        assert el is not None
        assert el["n"] == 90.0
        assert (el["epoch"], el["ma"], el["phase"]) == (
            2_450_000.0,
            0.0,
            orbits.PERIASTRON,
        )

    def test_an_unknown_phase(self):
        row = _row(assumed=["periastron_time"])
        el = orbits.elements(row, _direction(0, 0))
        assert el is not None
        assert (el["epoch"], el["ma"], el["phase"]) == (
            orbits.J2000,
            0.0,
            orbits.ASSUMED,
        )

    def test_no_period_keeps_the_planet_at_rest(self):
        el = orbits.elements(_row(period=None), _direction(0, 0))
        assert el is not None and el["n"] == 0.0

    def test_no_semi_major_axis(self):
        assert orbits.elements(_row(semi_major_axis=None), _direction(0, 0)) is None

    @pytest.mark.parametrize("e", [280.0, 1.0, -0.1, None])
    def test_an_eccentricity_outside_0_to_1_is_replaced(self, e):
        el = orbits.elements(_row(eccentricity=e), _direction(0, 0))
        assert el is not None
        assert el["e"] == 0.0 and el["replaced"] == ["eccentricity"]

    def test_a_valid_orbit_replaces_nothing(self):
        el = orbits.elements(_row(eccentricity=0.2), _direction(0, 0))
        assert el is not None and "replaced" not in el

    def test_an_assumed_inclination_gives_way_to_the_sky_solution(self):
        direction = _direction(30, 40)
        row = _row(inclination=90.0, node_inclination=30.0, assumed=["inclination"])
        expected = orbits.ecliptic_angles(direction, 30.0, 0.0, 270.0)
        el = orbits.elements(row, direction)
        assert el is not None
        assert (el["i"], el["om"], el["w"]) == pytest.approx(expected)
        # A measured inclination stays.
        measured = orbits.elements(row | {"assumed": []}, direction)
        assert measured is not None
        assert measured["i"] == pytest.approx(
            orbits.ecliptic_angles(direction, 90.0, 0.0, 270.0)[0]
        )

    def test_angles_beyond_a_turn(self):
        direction = _direction(200, -10)
        a = orbits.elements(_row(omega=-233.0, node=390.0), direction)
        b = orbits.elements(_row(omega=127.0, node=30.0), direction)
        assert a is not None and b is not None
        assert (a["i"], a["om"], a["w"]) == pytest.approx((b["i"], b["om"], b["w"]))
