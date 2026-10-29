"""Orbits from the plane of the sky to the frame of the scene.

A catalogue gives an orbit on the plane of the sky: its inclination i to
that plane, the position angle Ω of its ascending node from north through
east, and the argument of periastron ω. The axes are north, east and the line
of sight away from the observer. So the ascending node is where the body
moves away from us, and an orbit with i < 90° turns from north to east.

The scene takes an orbit as elements on the ecliptic and equinox of J2000,
with the obliquity of the scene.
"""

import math

import numpy as np

# The scene's mean obliquity of the ecliptic at J2000 (IAU 2006).
OBLIQUITY = 23.4392911
J2000 = 2_451_545.0

_COS_EPS = math.cos(math.radians(OBLIQUITY))
_SIN_EPS = math.sin(math.radians(OBLIQUITY))


def direction(ra: float, dec: float) -> np.ndarray:
    """The ICRS unit vector at `ra` and `dec`, in degrees."""
    ra, dec = math.radians(ra), math.radians(dec)
    return np.array(
        [math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)]
    )


def sky_axes(direction: np.ndarray) -> np.ndarray:
    """North, east and away from us at `direction` (ICRS), as rows."""
    ra = math.atan2(direction[1], direction[0])
    dec = math.atan2(direction[2], math.hypot(direction[0], direction[1]))
    north = (
        -math.sin(dec) * math.cos(ra),
        -math.sin(dec) * math.sin(ra),
        math.cos(dec),
    )
    east = (-math.sin(ra), math.cos(ra), 0.0)
    away = (math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec))
    return np.array([north, east, away])


def orbit_axes(i: float, node: float, omega: float) -> tuple[np.ndarray, np.ndarray]:
    """The unit vectors to periastron (P) and 90° on along the motion (Q), in
    the axes of the elements' reference plane. Angles in degrees."""
    i, node, omega = math.radians(i), math.radians(node), math.radians(omega)
    cn, sn = math.cos(node), math.sin(node)
    cw, sw = math.cos(omega), math.sin(omega)
    ci, si = math.cos(i), math.sin(i)
    p = np.array([cn * cw - sn * sw * ci, sn * cw + cn * sw * ci, sw * si])
    q = np.array([-cn * sw - sn * cw * ci, -sn * sw + cn * cw * ci, cw * si])
    return p, q


def to_ecliptic(vector: np.ndarray) -> np.ndarray:
    x, y, z = vector
    return np.array([x, y * _COS_EPS + z * _SIN_EPS, -y * _SIN_EPS + z * _COS_EPS])


def angles_of(p: np.ndarray, q: np.ndarray) -> tuple[float, float, float]:
    """i, Ω and ω in degrees of the orbit with axes P and Q in a right-handed
    frame."""
    h = np.cross(p, q)
    h /= np.linalg.norm(h)
    i = math.degrees(math.acos(max(-1.0, min(1.0, h[2]))))
    if math.hypot(h[0], h[1]) < 1e-12:
        node = 0.0
    else:
        node = math.atan2(h[0], -h[1])
    line = np.array([math.cos(node), math.sin(node), 0.0])
    omega = math.atan2(float(np.dot(p, np.cross(h, line))), float(np.dot(p, line)))
    return i, math.degrees(node) % 360, math.degrees(omega) % 360


def ecliptic_angles(
    direction: np.ndarray, i: float, node: float, omega: float
) -> tuple[float, float, float]:
    """The sky-plane angles of an orbit at `direction` as ecliptic J2000
    angles. `omega` is the argument of periastron of the body that moves."""
    axes = sky_axes(direction)
    p_sky, q_sky = orbit_axes(i, node, omega)
    # The rows are the sky axes, so the transpose maps a sky vector to ICRS.
    p = to_ecliptic(axes.T @ p_sky)
    q = to_ecliptic(axes.T @ q_sky)
    return angles_of(p, q)


def mean_anomaly_from_true(nu: float, e: float) -> float:
    """Degrees, both ways."""
    nu = math.radians(nu)
    anomaly = 2 * math.atan2(
        math.sqrt(1 - e) * math.sin(nu / 2), math.sqrt(1 + e) * math.cos(nu / 2)
    )
    return math.degrees(anomaly - e * math.sin(anomaly)) % 360
