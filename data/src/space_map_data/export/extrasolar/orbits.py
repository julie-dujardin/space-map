"""Planet orbits in the frame of the scene.

The catalogues give an orbit on the plane of the sky: its inclination i to
that plane, the position angle Ω of its ascending node from north through
east, and the argument of periastron ω. The axes are north, east and the line
of sight away from the observer. So the ascending node is where the body
moves away from us, and an orbit with i < 90° turns from north to east.

The scene takes the orbit of the planet around its star as elements on the
ecliptic and equinox of J2000: a in AU, angles in degrees, the mean motion n
in degrees per day and the mean anomaly at an epoch in JD TDB. `elements`
turns the plane of the sky at the star's direction into that frame, with the
obliquity of the scene.

A published ω is the star's, as most radial-velocity and transit fits give
it. The planet's is then ω + 180°. A planet found by imaging keeps ω, because
its orbit is fitted to the planet's own positions.

The epoch fixes where the planet is on its orbit. A transit time is the
inferior conjunction, where the planet is nearest us. Without one, the epoch
is the periastron time. Times are as observed, with no light time removed.
"""

import math

import numpy as np

# The scene's mean obliquity of the ecliptic at J2000 (IAU 2006).
OBLIQUITY = 23.4392911
J2000 = 2_451_545.0
IMAGING = "Imaging"
# Where `ma` comes from.
TRANSIT, PERIASTRON, ASSUMED = "transit", "periastron", "assumed"

_COS_EPS = math.cos(math.radians(OBLIQUITY))
_SIN_EPS = math.sin(math.radians(OBLIQUITY))


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
    """The sky-plane angles of a star at `direction` as ecliptic J2000 angles.

    `omega` is the planet's own argument of periastron.
    """
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


def planet_omega(omega: float, method: str | None) -> float:
    """The planet's argument of periastron from a published ω."""
    return omega % 360 if method == IMAGING else (omega + 180) % 360


def elements(row: dict, direction: np.ndarray) -> dict | None:
    """The scene's elements of a planets table row, or None with no
    semi-major axis.

    `direction` points from us to the star (ICRS). An eccentricity outside
    [0, 1) is drawn as 0 and named in `replaced`.
    """
    a = row["semi_major_axis"]
    if a is None:
        return None
    replaced = []
    e = row["eccentricity"]
    if e is None or not 0 <= e < 1:
        replaced.append("eccentricity")
        e = 0.0
    inclination = row["inclination"]
    if "inclination" in row["assumed"] and row["node_inclination"] is not None:
        inclination = row["node_inclination"]
    omega = planet_omega(row["omega"], row["discovery_method"])
    i, om, w = ecliptic_angles(direction, inclination, row["node"] % 360, omega)
    period = row["period"]
    out = {
        "a": a,
        "e": e,
        "i": i,
        "om": om,
        "w": w,
        "ma": 0.0,
        "n": 360 / period if period else 0.0,
        "epoch": J2000,
        "phase": ASSUMED,
    }
    if row["transit_time"] is not None:
        # At inferior conjunction the planet's ω + ν is 270°.
        out["ma"] = mean_anomaly_from_true(270 - omega, e)
        out["epoch"] = row["transit_time"]
        out["phase"] = TRANSIT
    elif row["periastron_time"] is not None:
        out["epoch"] = row["periastron_time"]
        if "periastron_time" not in row["assumed"]:
            out["phase"] = PERIASTRON
    if replaced:
        out["replaced"] = replaced
    return out
