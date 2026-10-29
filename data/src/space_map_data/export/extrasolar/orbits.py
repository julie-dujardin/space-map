"""Planet orbits in the frame of the scene.

The scene takes the orbit of the planet around its star as elements on the
ecliptic and equinox of J2000 (`frame`): a in AU, angles in degrees, the mean
motion n in degrees per day and the mean anomaly at an epoch in JD TDB.
`elements` turns the plane of the sky at the star's direction into that
frame.

A published ω is the star's, as most radial-velocity and transit fits give
it. The planet's is then ω + 180°. A planet found by imaging keeps ω, because
its orbit is fitted to the planet's own positions.

The epoch fixes where the planet is on its orbit. A transit time is the
inferior conjunction, where the planet is nearest us. Without one, the epoch
is the periastron time. Times are as observed, with no light time removed.
"""

import numpy as np

from space_map_data.extrasolar.frame import (
    J2000,
    ecliptic_angles,
    mean_anomaly_from_true,
)

IMAGING = "Imaging"
# Where `ma` comes from.
TRANSIT, PERIASTRON, ASSUMED = "transit", "periastron", "assumed"


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
