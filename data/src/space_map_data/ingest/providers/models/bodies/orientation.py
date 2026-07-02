"""DAMIT spin state → the PCK-style (α₀, δ₀, W₀, Ẇ) the export/frontend expect.

DAMIT gives an ecliptic-J2000 pole (λ, β), sidereal period P (hours), and a
rotation phase φ₀ at epoch JD₀ (Kaasalainen convex-inversion convention). The
frontend's ``bodyQuaternion`` instead consumes the IAU polynomial: equatorial
pole (α₀, δ₀) and prime-meridian angle W(d) = W₀ + Ẇ·d (d = days since J2000),
with W measured eastward from the equatorial ascending node. We convert the
pole via the J2000 obliquity and solve W₀ by matching the model's prime
meridian to the frontend's W-frame at JD₀ — no closed-form node offset, so the
handedness/epoch conventions can't drift.
"""

import math

import numpy as np

# J2000 mean obliquity of the ecliptic (matches frontend orientation.ts).
_OBLIQUITY_DEG = 23.4392911
_J2000_JD = 2451545.0


def _rz_coord(gamma_deg: float) -> np.ndarray:
    """DAMIT coordinate-rotation matrix about z (passive; = active R_z(−γ))."""
    c, s = _cos_sin(gamma_deg)
    return np.array([[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]])


def _ry_coord(gamma_deg: float) -> np.ndarray:
    c, s = _cos_sin(gamma_deg)
    return np.array([[c, 0.0, -s], [0.0, 1.0, 0.0], [s, 0.0, c]])


def _rx_active(gamma_deg: float) -> np.ndarray:
    """Active rotation about x — ecliptic→equatorial uses +ε."""
    c, s = _cos_sin(gamma_deg)
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])


def _cos_sin(deg: float) -> tuple[float, float]:
    r = math.radians(deg)
    return math.cos(r), math.sin(r)


def damit_to_iau(
    lambda_deg: float, beta_deg: float, period_h: float, phi0_deg: float, jd0: float
) -> dict:
    """Return ``{pole_ra_0, pole_ra_1, pole_dec_0, pole_dec_1, w0, w1, w2}`` (deg).

    Convex models carry no precession, so the ``_1``/``w2`` terms are zero.
    """
    ecl_to_eq = _rx_active(_OBLIQUITY_DEG)

    # Ecliptic pole → equatorial (α₀, δ₀).
    pole_ecl = np.array(
        [
            math.cos(math.radians(beta_deg)) * math.cos(math.radians(lambda_deg)),
            math.cos(math.radians(beta_deg)) * math.sin(math.radians(lambda_deg)),
            math.sin(math.radians(beta_deg)),
        ]
    )
    pole_eq = ecl_to_eq @ pole_ecl
    pole_eq /= np.linalg.norm(pole_eq)
    alpha0 = math.degrees(math.atan2(pole_eq[1], pole_eq[0])) % 360.0
    delta0 = math.degrees(math.asin(max(-1.0, min(1.0, pole_eq[2]))))

    # Prime-meridian (body +x) direction at JD₀, in equatorial coords.
    a_mat = _rz_coord(phi0_deg) @ _ry_coord(90.0 - beta_deg) @ _rz_coord(lambda_deg)
    prime_ecl = a_mat.T @ np.array([1.0, 0.0, 0.0])
    prime_eq = ecl_to_eq @ prime_ecl
    prime_eq /= np.linalg.norm(prime_eq)

    # Equatorial ascending node Q = frontend's W=0 axis; W is the signed angle
    # Q → prime meridian about the pole (right-handed), matching bodyQuaternion.
    ra = math.radians(alpha0)
    node = np.array([-math.sin(ra), math.cos(ra), 0.0])
    node /= np.linalg.norm(node)
    w_at_jd0 = math.degrees(
        math.atan2(
            float(np.dot(np.cross(node, prime_eq), pole_eq)),
            float(np.dot(node, prime_eq)),
        )
    )

    w1 = 360.0 * 24.0 / period_h  # deg/day; W and DAMIT φ share the pole + sense
    w0 = (w_at_jd0 - w1 * (jd0 - _J2000_JD)) % 360.0
    return {
        "pole_ra_0": alpha0,
        "pole_ra_1": 0.0,
        "pole_dec_0": delta0,
        "pole_dec_1": 0.0,
        "w0": w0,
        "w1": w1,
        "w2": 0.0,
    }
