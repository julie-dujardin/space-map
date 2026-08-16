"""What a trapped-particle belt does to something flying through it.

`field.py` is deliberately GCR only, and says so: a belt is a table entry, not a
term. This is the exception that proves it. A swing-by past Jupiter is the one
manoeuvre a trajectory planner will happily propose that is dominated entirely
by trapped particles, and answering "how much radiation" with a cosmic ray
number there is not conservative, it is wrong by five orders of magnitude.

So this module is kept apart from `field.py` rather than folded into it, because
the two are not equally solid and should not look it. The cosmic ray field is
fitted at Earth and in cruise and then predicts the lunar surface to 7% and Gale
crater to 2%. This is a three-parameter profile with two anchors, and its two
out-of-sample checks land a factor of four either side of it. Both are useful;
only one is precise, and a reader deserves to be able to tell which is which.

The model is one radial profile and one shielding curve.

    dose(pass) = ∫ rate(L(t)) dt      rate(L) = R_peak · (L/L_peak)^-n  outside
                                                R_peak                  inside

`L` is the distance from the planet's centre in planetary radii, which for an
equatorial pass is the L-shell. Every pass is treated as equatorial; a polar one
crosses the belt where it is thinner and takes appreciably less, which is the
larger of the two known errors here and is quantified below.

Only Jupiter is modelled. Earth's crossing is a flat number in `belts.py`
measured by Apollo 11, which is the better answer where it applies, and nobody
has published a dose profile for Saturn, Uranus or Neptune on terms a body
absorbs. A pass by one of those reports that it crossed a belt and declines to
put a figure on it.

Everything here is an absorbed dose in grays. It is not converted to sieverts
and should not be: the flux is mostly electrons, whose quality factor is one, so
the two would be numerically close anyway — but at the hundreds of grays this
returns the distinction has stopped mattering, because that is deterministic
injury rather than a stochastic risk, and a sievert is a unit for the latter.
"""

import math

# --- the shielding curve -----------------------------------------------------

# Figure 6.5 of the Europa lander study plots dose rate against aluminium
# thickness at Europa's trailing hemisphere. The reference point is the thinnest
# shielding it draws, about 0.4 mm of aluminium.
BELT_REFERENCE_SHIELDING_G_CM2 = 0.11

# The same figure falls two decades between that point and 10 mm of aluminium,
# which is 2.7 g/cm². One exponential through those two points.
_THICK_SHIELDING_G_CM2 = 2.7
_DECADES_ACROSS_THE_CURVE = 2.0
BELT_SHIELDING_LENGTH_G_CM2 = (
    _THICK_SHIELDING_G_CM2 - BELT_REFERENCE_SHIELDING_G_CM2
) / (_DECADES_ACROSS_THE_CURVE * math.log(10.0))
_SHIELDING_SOURCE = "europa_lander_sdt_2016"

# Past the end of that curve the exponential is extrapolation and a bad one: at
# 20 g/cm² it returns 1e-11, and what actually happens is that the electrons stop
# and their bremsstrahlung does not, so the curve flattens onto a tail this model
# knows nothing about. Held at the two decades the source figure actually spans.
# A result at the floor is an upper bound, and the same caution applies to it as
# to `ATTENUATION_FLOOR` in `field.py`.
BELT_SHIELDING_FLOOR = 1.0e-2


def belt_shielding_factor(shielding_g_cm2: float) -> float:
    """Dose behind `shielding_g_cm2`, relative to the reference thickness."""
    past = shielding_g_cm2 - BELT_REFERENCE_SHIELDING_G_CM2
    if past <= 0.0:
        return 1.0
    return max(BELT_SHIELDING_FLOOR, math.exp(-past / BELT_SHIELDING_LENGTH_G_CM2))


# --- the radial profile ------------------------------------------------------

# Where Jupiter's MeV electrons maximise, from the belt structure chapter. The
# same value `belts.py` carries as Jupiter's `peak_radii`.
JOVIAN_PEAK_L = 3.0
_PEAK_SOURCE = "roussos_2020"

# How fast intensity falls outside the peak. Not fitted here: Johnson's table
# gives globally averaged energy fluxes at Europa (L = 9.4) and Callisto
# (L = 26.3) on identical terms, 5e10 against 2e8 keV cm⁻² s⁻¹, and a power law
# through those two is a slope of 5.37. Energy flux stands in for dose rate,
# which assumes the spectrum keeps its shape across that span.
#
# It matters that this came from somewhere independent. A profile fitted to the
# two dose anchors alone would have had nothing to set its outer slope with and
# would have fallen off far too fast — an earlier lognormal attempt put Callisto
# 66,000 times below Europa, where Johnson says 250.
_EUROPA_L, _CALLISTO_L = 9.4, 26.3
_EUROPA_FLUX, _CALLISTO_FLUX = 5.0e10, 2.0e8
JOVIAN_OUTER_SLOPE = math.log(_EUROPA_FLUX / _CALLISTO_FLUX) / math.log(
    _CALLISTO_L / _EUROPA_L
)
_SLOPE_SOURCE = "johnson_2004"

# Dose rate at the peak, behind the reference shielding. Fitted, to Pioneer 10's
# whole-pass dose — see `BELT_ANCHORS`. Inside the peak the profile is held flat
# at this rather than extrapolated inward, because nothing here constrains that
# branch: the one measurement inside L = 3 is Pioneer 11's, and it was a polar
# pass, so it cannot separate a radial decline from a latitude one. Flat is the
# conservative reading of an unknown, and a pass inside the peak is an upper
# bound rather than an estimate.
JOVIAN_PEAK_GY_PER_DAY = 2.414e5
_PEAK_RATE_FITTED_TO = "miller_1976"


def jovian_belt_rate_gy_per_day(l_shell: float) -> float:
    """Absorbed dose rate at `l_shell`, behind the reference shielding."""
    if l_shell <= 0.0:
        return 0.0
    if l_shell <= JOVIAN_PEAK_L:
        return JOVIAN_PEAK_GY_PER_DAY
    return JOVIAN_PEAK_GY_PER_DAY * (l_shell / JOVIAN_PEAK_L) ** -JOVIAN_OUTER_SLOPE


# --- integrating a pass ------------------------------------------------------

# Jupiter, for turning a periapsis in km into an L and a hyperbola into a clock.
JUPITER_RADIUS_KM = 71492.0
JUPITER_MU_KM3_S2 = 1.26686534e8

_SEC_PER_DAY = 86400.0
# Steps across the whole pass. The integrand is smooth and strongly peaked at
# periapsis; a few hundred already converges to well under a percent, and the
# cost of being generous is nothing because this runs once per route.
_PASS_STEPS = 2000


def belt_pass_dose_gy(
    periapsis_km: float,
    v_infinity_kms: float,
    shielding_g_cm2: float,
    *,
    radius_km: float = JUPITER_RADIUS_KM,
    mu_km3_s2: float = JUPITER_MU_KM3_S2,
) -> float:
    """Absorbed dose of one hyperbolic pass, grays.

    The craft is taken to enter and leave along the asymptotes of the hyperbola
    the swing-by is solved as, and to fly it in the magnetic equator. The
    integral is over true anomaly with the time from Kepler's equation, so the
    weighting is by how long the pass spends at each distance and not by how far
    it travels there — which is the whole reason Pioneer 11 survived a closer
    approach than Pioneer 10.
    """
    if periapsis_km <= 0.0 or v_infinity_kms <= 0.0:
        return 0.0

    semi_major = -mu_km3_s2 / v_infinity_kms**2
    eccentricity = 1.0 - periapsis_km / semi_major
    if eccentricity <= 1.0:
        return 0.0
    semi_latus = periapsis_km * (1.0 + eccentricity)

    # Stop just short of the asymptote, where r runs to infinity and the
    # integrand to zero anyway.
    nu_limit = math.acos(-1.0 / eccentricity) * 0.999
    mean_motion_factor = math.sqrt((-semi_major) ** 3 / mu_km3_s2)

    def time_at(nu: float) -> float:
        tanh_h = math.sqrt((eccentricity - 1.0) / (eccentricity + 1.0)) * math.tan(
            nu / 2.0
        )
        anomaly = math.atanh(max(-0.999999999, min(0.999999999, tanh_h)))
        return mean_motion_factor * (eccentricity * math.sinh(anomaly) - anomaly)

    total = 0.0
    previous_time = None
    for step in range(_PASS_STEPS + 1):
        nu = -nu_limit + 2.0 * nu_limit * step / _PASS_STEPS
        radius = semi_latus / (1.0 + eccentricity * math.cos(nu))
        now = time_at(nu)
        if previous_time is not None:
            rate = jovian_belt_rate_gy_per_day(radius / radius_km)
            total += rate * (now - previous_time) / _SEC_PER_DAY
        previous_time = now

    return total * belt_shielding_factor(shielding_g_cm2)


# --- what the belt model is answerable to ------------------------------------

# Aluminium, for turning the Pioneers' published shield thickness into a column.
_ALUMINIUM_G_CM3 = 2.7
# Both Pioneers reported an interior dose behind 0.3 cm of aluminium.
PIONEER_SHIELDING_G_CM2 = 0.3 * _ALUMINIUM_G_CM3

# Neither Pioneer's arrival speed is carried in this repo, so the integral
# assumes a fast direct transfer's excess. It barely matters: sweeping it from 5
# to 15 km/s moves the fitted peak rate by ±8%, which is nothing against the
# factor of four the anchors disagree by.
PIONEER_V_INFINITY_KMS = 9.5


class BeltAnchor:
    """One flown Jupiter pass, and what the model owes it."""

    def __init__(
        self,
        measured_gy: float,
        source: str,
        role: str,
        tolerance: float,
        periapsis_radii: float,
        note: str = "",
    ) -> None:
        self.measured_gy = measured_gy
        self.source = source
        self.role = role
        self.tolerance = tolerance
        self.periapsis_radii = periapsis_radii
        self.note = note


FIT = "fit"
PREDICTION = "prediction"

BELT_ANCHORS: dict[str, BeltAnchor] = {
    # Pioneer 10. Sets `JOVIAN_PEAK_GY_PER_DAY`, so its residual is zero by
    # construction. Periapsis 130,354 km above the cloud tops is 2.82 planetary
    # radii, near enough the peak to make this a clean normalisation, and the
    # pass was close to equatorial — which is the geometry the model assumes.
    # 4.5e5 rad interior is 4,500 Gy.
    "pioneer_10": BeltAnchor(
        measured_gy=4.5e3,
        source="miller_1976",
        role=FIT,
        tolerance=0.02,
        periapsis_radii=(130354.0 + JUPITER_RADIUS_KM) / JUPITER_RADIUS_KM,
    ),
    # Pioneer 11. Never fitted to. It went three times closer — 42,760 km up,
    # 1.60 radii — and took a quarter of what Pioneer 10 did, which is the whole
    # argument for integrating a pass rather than reading a periapsis off a
    # chart: it was travelling at 47.5 km/s and it went over the pole.
    #
    # The model over-predicts it by about four. Both reasons are known and
    # neither is fixable here: the pass was polar, where the trapped population
    # is thinner than the equator this model assumes, and it was inside the peak,
    # where the profile is deliberately held flat as an upper bound. A tolerance
    # this loose is not a passing grade, it is a pin on a known bias — it exists
    # so that a change which makes the bias worse fails.
    "pioneer_11": BeltAnchor(
        measured_gy=1.2e3,
        source="miller_1976",
        role=PREDICTION,
        tolerance=5.0,
        periapsis_radii=(42760.0 + JUPITER_RADIUS_KM) / JUPITER_RADIUS_KM,
        note="polar_and_fast",
    ),
}

# The other out-of-sample check, which is a rate rather than a pass and so does
# not fit the shape above. Europa's environment entry is 1e3 Sv/day at the
# surface behind 0.11 g/cm², and JPL has already halved that for the moon
# blocking half the sky, so free space in the same orbit is twice it.
#
# The model, normalised on Pioneer 10, gives 526 Gy/day there — under by 3.8.
# Taken with Pioneer 11 being over by 3.9, the two bracket the model rather than
# agreeing with it, and the honest reading is that anything this returns is good
# to a factor of about four. The likeliest cause of the split is that the
# Pioneers' dose was largely protons, which are far more centrally peaked than
# the electrons Europa's figure is made of, so one profile cannot serve both.
EUROPA_ORBIT_GY_PER_DAY = 2.0e3
EUROPA_ORBIT_L = _EUROPA_L
BELT_MODEL_UNCERTAINTY_FACTOR = 4.0

BELT_FIELD_SOURCES: tuple[str, ...] = (
    _SHIELDING_SOURCE,
    _PEAK_SOURCE,
    _SLOPE_SOURCE,
    _PEAK_RATE_FITTED_TO,
)
