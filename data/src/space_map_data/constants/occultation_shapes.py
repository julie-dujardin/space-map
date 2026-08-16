"""Spin poles and triaxial shapes measured by stellar occultation.

These four ringed bodies need a pole to draw the ring's equatorial plane, but
none has one in SPICE PCK or DAMIT's lightcurve inversions. Occultation
literature fits the ring plane and the limb from the same chords, giving both
pole and semi-axes at better accuracy than a lightcurve.

Poles are the ring poles (every system here is equatorial; for Haumea and
Quaoar the moons' orbits agree). Fits are mirror-ambiguous, so each paper's
preferred solution is taken — the mirror is the same plane with opposite
spin sense, undistinguishable and irrelevant to any rendered pixel.

W is unmeasured for all four: no map texture to align, so the prime meridian
is zero at J2000 and only the rotation rate carries information.
"""

import math
from typing import NamedTuple

from space_map_data.constants.orientation import ORIENTATION_SOURCE_OCCULTATION

# J2000 mean obliquity, for the two poles published in ecliptic coordinates.
_OBLIQUITY_DEG = 23.4392911


class OccultationShape(NamedTuple):
    """One body's occultation-derived spin state and ellipsoid."""

    naif_id: int
    # Ring/spin pole, ICRS J2000.
    pole_ra_deg: float
    pole_dec_deg: float
    # Sidereal rotation period. Haumea's and Quaoar's are lightcurve values;
    # the sign follows the chosen pole and is not itself measured.
    period_h: float
    # Best-fitting ellipsoid semi-axes, a >= b >= c, km.
    semi_axes_km: tuple[float, float, float]
    # Paper the pole is taken from, exported so the sidebar credits it
    # instead of the PCK these bodies never appear in.
    pole_reference_title: str
    pole_reference_url: str


def _from_ecliptic(lambda_deg: float, beta_deg: float) -> tuple[float, float]:
    """Ecliptic (λ, β) → equatorial (α, δ), both J2000, in degrees."""
    lam, beta = math.radians(lambda_deg), math.radians(beta_deg)
    eps = math.radians(_OBLIQUITY_DEG)
    x = math.cos(beta) * math.cos(lam)
    y = math.cos(beta) * math.sin(lam) * math.cos(eps) - math.sin(beta) * math.sin(eps)
    z = math.cos(beta) * math.sin(lam) * math.sin(eps) + math.sin(beta) * math.cos(eps)
    return math.degrees(math.atan2(y, x)) % 360.0, math.degrees(math.asin(z))


# Semi-axes and rotation periods are Table 4 of Sicardy et al. 2024
# (doi:10.1007/s00159-024-00156-x), which collects them from the papers each
# body's ring catalogue entry cites. Poles are the ring poles from those same
# papers.
OCCULTATION_SHAPES: tuple[OccultationShape, ...] = (
    # Chariklo — C1R's pole, Morgado et al. 2021.
    OccultationShape(
        2010199,
        151.03,
        41.81,
        7.004,
        (143.8, 135.2, 99.1),
        "Morgado et al. 2021 (A&A 652, A141)",
        "https://doi.org/10.1051/0004-6361/202141543",
    ),
    # Haumea — Ortiz et al. 2017. The elongation is real and extreme: the long
    # axis is more than twice the polar one.
    OccultationShape(
        2136108,
        285.1,
        -10.6,
        3.915341,
        (1161.0, 852.0, 513.0),
        "Ortiz et al. 2017 (Nature 550, 219)",
        "https://doi.org/10.1038/nature24051",
    ),
    # Quaoar — Q1R's preferred pole, Pereira et al. 2023.
    OccultationShape(
        2050000,
        259.82,
        53.45,
        17.6788,
        (580.0, 513.0, 471.0),
        "Pereira et al. 2023 (A&A 673, L4)",
        "https://doi.org/10.1051/0004-6361/202346365",
    ),
    # Chiron — Pereira et al. 2025 publish the ring pole in ecliptic
    # coordinates (λ = 151.3°, β = 19.9°); this converts to the RA 160 ± 10,
    # Dec 28 ± 10 the review quotes for the same solution.
    OccultationShape(
        2002060,
        *_from_ecliptic(151.3, 19.9),
        5.917813,
        (126.0, 109.0, 68.0),
        "Pereira et al. 2025 (ApJL 992, L19)",
        "https://doi.org/10.3847/2041-8213/ae0b6d",
    ),
)


def occultation_orientations() -> dict[int, dict]:
    """`{naif_id: IAU orientation polynomial}`, in the shape the export's
    orientation table uses. No precession terms: none is measured.

    Carries its own provenance: these poles are published measurements, not
    PCK constants, and the sidebar credits whichever the record names.
    """
    return {
        shape.naif_id: {
            "pole_ra_0": shape.pole_ra_deg,
            "pole_ra_1": 0.0,
            "pole_dec_0": shape.pole_dec_deg,
            "pole_dec_1": 0.0,
            "w0": 0.0,
            "w1": 360.0 * 24.0 / shape.period_h,
            "w2": 0.0,
            "source": ORIENTATION_SOURCE_OCCULTATION,
            "reference": {
                "title": shape.pole_reference_title,
                "url": shape.pole_reference_url,
            },
        }
        for shape in OCCULTATION_SHAPES
    }


def occultation_radii() -> dict[int, dict[str, float]]:
    """`{naif_id: {a, b, c}}` km, in the shape the export's radii table uses."""
    return {
        shape.naif_id: dict(zip("abc", shape.semi_axes_km, strict=True))
        for shape in OCCULTATION_SHAPES
    }
