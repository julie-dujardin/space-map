"""Spin poles and triaxial shapes measured for bodies that appear in no kernel.

These bodies have no PCK entry, so without this table they render as featureless
spheres sized from a thermal diameter. The literature fits them a body-fixed
ellipsoid instead: occultation chords give the limb directly, and for a fast
rotator the amplitude of the rotational light curve over many years gives the
axis ratios and the pole. Each record names the work behind its shape and the
work behind its pole, because those are often not the same paper.

Fits are mirror-ambiguous, so each paper's preferred solution is taken — the
mirror is the same plane with opposite spin sense, undistinguishable and
irrelevant to any rendered pixel.

W is unmeasured throughout: no map texture to align, so the prime meridian is
zero at J2000 and only the rotation rate carries information. A body whose pole
is unpublished ships its shape alone and renders untilted.
"""

import math
from typing import NamedTuple

from space_map_data.constants.orientation import (
    ORIENTATION_SOURCE_OCCULTATION,
    ORIENTATION_SOURCE_PHOTOMETRY,
)

# J2000 mean obliquity, for the poles published in ecliptic coordinates.
_OBLIQUITY_DEG = 23.4392911


class Reference(NamedTuple):
    """The work a measurement is read off, as the sidebar credits it."""

    title: str
    url: str


class MeasuredShape(NamedTuple):
    """One body's measured ellipsoid and, where published, its spin state."""

    naif_id: int
    # Best-fitting ellipsoid semi-axes, a >= b >= c, km.
    semi_axes_km: tuple[float, float, float]
    shape_reference: Reference
    # How the ellipsoid was measured — occultation chords or a light curve.
    shape_source: str
    # Spin pole, ICRS J2000, and the sidereal rotation period. None together
    # when no pole is published: the shape still ships, the tilt does not.
    pole_ra_deg: float | None = None
    pole_dec_deg: float | None = None
    period_h: float | None = None
    pole_reference: Reference | None = None


def _from_ecliptic(lambda_deg: float, beta_deg: float) -> tuple[float, float]:
    """Ecliptic (λ, β) → equatorial (α, δ), both J2000, in degrees."""
    lam, beta = math.radians(lambda_deg), math.radians(beta_deg)
    eps = math.radians(_OBLIQUITY_DEG)
    x = math.cos(beta) * math.cos(lam)
    y = math.cos(beta) * math.sin(lam) * math.cos(eps) - math.sin(beta) * math.sin(eps)
    z = math.cos(beta) * math.sin(lam) * math.sin(eps) + math.sin(beta) * math.cos(eps)
    return math.degrees(math.atan2(y, x)) % 360.0, math.degrees(math.asin(z))


_SICARDY_2024 = Reference(
    "Sicardy et al. 2024 (A&ARv 32, 6)",
    "https://doi.org/10.1007/s00159-024-00156-x",
)
_MORGADO_2021 = Reference(
    "Morgado et al. 2021 (A&A 652, A141)",
    "https://doi.org/10.1051/0004-6361/202141543",
)
_ORTIZ_2017 = Reference(
    "Ortiz et al. 2017 (Nature 550, 219)",
    "https://doi.org/10.1038/nature24051",
)
_PEREIRA_2023 = Reference(
    "Pereira et al. 2023 (A&A 673, L4)",
    "https://doi.org/10.1051/0004-6361/202346365",
)
_PEREIRA_2025 = Reference(
    "Pereira et al. 2025 (ApJL 992, L19)",
    "https://doi.org/10.3847/2041-8213/ae0b6d",
)
_ROMMEL_2025 = Reference(
    "Rommel et al. 2025 (PSJ 6, 48)",
    "https://doi.org/10.3847/PSJ/adabc1",
)
_RIZOS_2024 = Reference(
    "Rizos et al. 2024 (A&A 689, A82)",
    "https://doi.org/10.1051/0004-6361/202450833",
)
_FERNANDEZ_VALENZUELA_2017 = Reference(
    "Fernández-Valenzuela et al. 2017 (MNRAS 466, 4147)",
    "https://doi.org/10.1093/mnras/stw3264",
)
_FERNANDEZ_VALENZUELA_2019 = Reference(
    "Fernández-Valenzuela et al. 2019 (ApJL 883, L21)",
    "https://doi.org/10.3847/2041-8213/ab40c2",
)
_FERNANDEZ_VALENZUELA_2025 = Reference(
    "Fernández-Valenzuela et al. 2025 (Nat. Commun. 16, 10926)",
    "https://doi.org/10.1038/s41467-025-65749-1",
)
_VARA_LUBIANO_2022 = Reference(
    "Vara-Lubiano et al. 2022 (A&A 663, A121)",
    "https://doi.org/10.1051/0004-6361/202141842",
)
_DIAS_OLIVEIRA_2017 = Reference(
    "Dias-Oliveira et al. 2017 (AJ 154, 22)",
    "https://doi.org/10.3847/1538-3881/aa74e9",
)
_TEGLER_2005 = Reference(
    "Tegler et al. 2005 (Icarus 175, 390)",
    "https://doi.org/10.1016/j.icarus.2004.12.011",
)
_FARNHAM_2001 = Reference(
    "Farnham 2001 (Icarus 152, 238)",
    "https://doi.org/10.1006/icar.2001.6656",
)

# The four ringed bodies. Semi-axes and rotation periods are Table 4 of Sicardy
# et al. 2024, which collects them from the papers each body's ring catalogue
# entry cites. Poles are the ring poles from those same papers, and every
# system here is equatorial (for Haumea and Quaoar the moons' orbits agree).
_RINGED: tuple[MeasuredShape, ...] = (
    # Chariklo — C1R's pole.
    MeasuredShape(
        2010199,
        (143.8, 135.2, 99.1),
        _SICARDY_2024,
        ORIENTATION_SOURCE_OCCULTATION,
        151.03,
        41.81,
        7.004,
        _MORGADO_2021,
    ),
    # Haumea — the elongation is real and extreme: the long axis is more than
    # twice the polar one.
    MeasuredShape(
        2136108,
        (1161.0, 852.0, 513.0),
        _ORTIZ_2017,
        ORIENTATION_SOURCE_OCCULTATION,
        285.1,
        -10.6,
        3.915341,
        _ORTIZ_2017,
    ),
    # Quaoar — Q1R's preferred pole. The semi-axes are the triaxial branch of a
    # shape that is still open: a 37-event fit (Margoti et al. 2026,
    # arXiv:2607.06450) reads the same chords as an oblate 566.1/566.1/511.2,
    # which would halve the rotation period to 8.8394 h and move Q1R off the
    # 3:1 spin-orbit resonance to 1/6 and Q2R from 5/7 to 5/14. Its authors
    # note that this costs the resonances and makes the whole light-curve
    # amplitude albedo, and close by saying the shape "remains to be defined" —
    # so the branch the rings and the light curve agree on is kept here.
    MeasuredShape(
        2050000,
        (580.0, 513.0, 471.0),
        _SICARDY_2024,
        ORIENTATION_SOURCE_OCCULTATION,
        259.82,
        53.45,
        17.6788,
        _PEREIRA_2023,
    ),
    # Chiron — the ring pole is published in ecliptic coordinates
    # (λ = 151.3°, β = 19.9°); this converts to the RA 160 ± 10, Dec 28 ± 10
    # the review quotes for the same solution.
    MeasuredShape(
        2002060,
        (126.0, 109.0, 68.0),
        _SICARDY_2024,
        ORIENTATION_SOURCE_OCCULTATION,
        *_from_ecliptic(151.3, 19.9),
        5.917813,
        _PEREIRA_2025,
    ),
)

# Ringless bodies whose ellipsoid is published on its own. Each is a body the
# map already draws from a thermal diameter alone.
_UNRINGED: tuple[MeasuredShape, ...] = (
    # Huya — an oblate spheroid, a = b by construction. The pole is the orbit
    # pole of its satellite, which the same work takes to lie in Huya's
    # equatorial plane.
    MeasuredShape(
        2038628,
        (218.05, 218.05, 187.5),
        _ROMMEL_2025,
        ORIENTATION_SOURCE_OCCULTATION,
        20.8,
        34.9,
        6.725,
        _ROMMEL_2025,
    ),
    # Varuna — the only shape here read off photometry rather than chords: the
    # light-curve amplitude drifted from 0.41 to 0.55 mag over 19 years, which
    # fixes the axis ratios (b/a = 0.60, c/b = 0.72) and the pole together.
    # The paper's own largest semi-axis, 550 km, scales them, and reproduces
    # the 700 km volume-equivalent diameter it quotes.
    MeasuredShape(
        2020000,
        (550.0, 330.0, 237.6),
        _FERNANDEZ_VALENZUELA_2019,
        ORIENTATION_SOURCE_PHOTOMETRY,
        *_from_ecliptic(53.0, -64.0),
        6.343572,
        _FERNANDEZ_VALENZUELA_2019,
    ),
    # Bienor — nearly three times longer than it is wide, the most elongated
    # body in this table. The chords date the shape; the pole is the earlier
    # photometric solution the occultation work adopts, prograde branch.
    MeasuredShape(
        2054598,
        (127.0, 55.0, 45.0),
        _RIZOS_2024,
        ORIENTATION_SOURCE_OCCULTATION,
        *_from_ecliptic(35.0, 50.0),
        9.1736,
        _FERNANDEZ_VALENZUELA_2017,
    ),
    # 2003 VS2 — chords plus the rotational light curve give all three axes.
    MeasuredShape(
        2084922,
        (339.0, 235.0, 226.0),
        _VARA_LUBIANO_2022,
        ORIENTATION_SOURCE_OCCULTATION,
        *_from_ecliptic(228.0, 39.0),
        7.41753,
        _VARA_LUBIANO_2022,
    ),
    # Achlys (2003 AZ84) — a Jacobi ellipsoid fitted to two occultations two
    # years apart. Only the aspect angle is constrained, not where the pole
    # points, so the shape ships without one.
    MeasuredShape(
        2208996,
        (470.0, 383.0, 245.0),
        _DIAS_OLIVEIRA_2017,
        ORIENTATION_SOURCE_OCCULTATION,
    ),
    # Pholus — ratios and pole from the light curve, absolute size from Herschel.
    # Tegler's own dimensions (310 x 160 x 150 km across) assume a 4 % albedo;
    # Herschel since measured 15.5 %, halving every length, so the published
    # axis ratios (a/b = 1.9, c/b = 0.9) are scaled here to that survey's
    # 99 +/- 15 km diameter (Duffard et al. 2014, A&A 564, A92,
    # doi:10.1051/0004-6361/201322377) instead. Farnham's independent solution
    # agrees on the ratios and puts the same pole within 5 degrees.
    MeasuredShape(
        2005145,
        (78.6, 41.4, 37.3),
        _TEGLER_2005,
        ORIENTATION_SOURCE_PHOTOMETRY,
        *_from_ecliptic(145.0, 30.0),
        9.982214,
        _FARNHAM_2001,
    ),
    # Hi'iaka — the first trans-Neptunian moon other than Charon measured by
    # multi-chord occultation. Its limb's position angle puts its spin axis on
    # Haumea's within the error bars, so it takes Haumea's pole.
    MeasuredShape(
        120136108,
        (240.0, 180.0, 143.0),
        _FERNANDEZ_VALENZUELA_2025,
        ORIENTATION_SOURCE_OCCULTATION,
        285.1,
        -10.6,
        9.68,
        _FERNANDEZ_VALENZUELA_2025,
    ),
)

MEASURED_SHAPES: tuple[MeasuredShape, ...] = _RINGED + _UNRINGED


def measured_orientations() -> dict[int, dict]:
    """`{naif_id: IAU orientation polynomial}`, in the shape the export's
    orientation table uses. No precession terms: none is measured. Bodies with
    no published pole are absent.

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
            "source": shape.shape_source,
            "reference": dict(shape.pole_reference._asdict()),
        }
        for shape in MEASURED_SHAPES
        if shape.pole_ra_deg is not None
        and shape.period_h is not None
        and shape.pole_reference is not None
    }


def measured_radii() -> dict[int, dict[str, float]]:
    """`{naif_id: {a, b, c}}` km, in the shape the export's radii table uses."""
    return {
        shape.naif_id: dict(zip("abc", shape.semi_axes_km, strict=True))
        for shape in MEASURED_SHAPES
    }


def measured_shape_references() -> dict[int, tuple[str, Reference]]:
    """`{naif_id: (shape_source, reference)}` — who measured each ellipsoid.

    The pole says nothing about the size rows and is often a different work, so
    the sidebar credits the shape from here rather than reading it off the pole.
    """
    return {
        shape.naif_id: (shape.shape_source, shape.shape_reference)
        for shape in MEASURED_SHAPES
    }
