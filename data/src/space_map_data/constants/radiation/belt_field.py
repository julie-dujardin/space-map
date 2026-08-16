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

The model is one radial profile per planet and one shielding curve for all of
them.

    dose(pass) = ∫ rate(L(t)) dt

`L` is the distance from the planet's centre in planetary radii, which for an
equatorial pass is the L-shell. Every pass is treated as equatorial; a polar one
crosses the belt where it is thinner and takes appreciably less, which is the
larger of the two known errors here and is quantified below.

Three planets are modelled and they are not equally well known. Jupiter is a
fitted analytic profile with flown anchors. Saturn and Neptune are digitised
from JPL's engineering models — curves someone else fitted to Pioneer, Voyager
and Cassini data — so the shape is theirs and only the reading off the page is
ours. Uranus has no published profile at all, only a single flown pass in
`belts.py`, and stays unpriced rather than being given a shape borrowed from
Neptune. Earth's crossing is likewise a flat number in `belts.py` measured by
Apollo 11, which is the better answer where it applies.

Everything here is an absorbed dose in grays. It is not converted to sieverts
and should not be: the flux is mostly electrons, whose quality factor is one, so
the two would be numerically close anyway — but at the hundreds of grays this
returns the distinction has stopped mattering, because that is deterministic
injury rather than a stochastic risk, and a sievert is a unit for the latter.
"""

import math
from typing import NamedTuple

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
# A result at the floor is an upper bound rather than an estimate. `field.py`
# used to carry a floor of its own for the same reason and no longer needs one,
# because Venus supplied a second regime to hand over to; nothing here has an
# equivalent, so this stays a floor.
BELT_SHIELDING_FLOOR = 1.0e-2

# SATRAD draws its own dose-depth curves for the same Jovian orbits and they
# fall about three times faster: 1 to 100 mils of aluminium takes Europa's orbit
# down by fifty, which is a length of 0.17 g/cm² against the 0.56 above. The two
# figures are for different spectra and neither is wrong, but the disagreement
# is real and larger than it looks — it is why this model and the lander study
# agree within a quarter at 100 mils and differ tenfold at 0.11 g/cm².
#
# Nothing here is changed for it, because every crewed answer is already on the
# floor: at the 10 g/cm² a pressure vessel carries, both lengths are far past
# where the curve is held flat, and the result is identical either way.


def belt_attenuation(shielding_g_cm2: float) -> float:
    """Surviving fraction behind `shielding_g_cm2`, against the 0.11 reference."""
    past = shielding_g_cm2 - BELT_REFERENCE_SHIELDING_G_CM2
    if past <= 0.0:
        return 1.0
    return max(BELT_SHIELDING_FLOOR, math.exp(-past / BELT_SHIELDING_LENGTH_G_CM2))


def belt_shielding_factor(shielding_g_cm2: float, reference_g_cm2: float) -> float:
    """Dose behind `shielding_g_cm2`, relative to what a profile was quoted at.

    Profiles do not share a reference thickness — Jupiter's comes off a figure
    drawn at 0.11 g/cm², Saturn's and Neptune's off JPL curves at 100 mils of
    aluminium — so the ratio of two points on one curve is what converts them.
    """
    return belt_attenuation(shielding_g_cm2) / belt_attenuation(reference_g_cm2)


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

# 100 mils of aluminium, the thickness JPL's engineering models are drawn at and
# the one Saturn's and Neptune's profiles below are therefore quoted behind.
JPL_SHELL_G_CM2 = 2.54 * 0.1 * 2.70


class BeltProfile(NamedTuple):
    """How hard a planet's belt hits, against distance from its centre.

    `samples` are (planetary radii, Gy/day) in ascending order, interpolated
    log-log between neighbours because both axes span decades. Outside the last
    one the profile continues as a power law of index `outer_slope`. Inside the
    first, `flat_inside` says whether the rate is held at that first sample —
    true only where nothing measures the inner branch, which makes a close pass
    an upper bound rather than an estimate.
    """

    body_id: str
    samples: tuple[tuple[float, float], ...]
    shielding_g_cm2: float
    sources: tuple[str, ...]
    # None continues the slope the last two samples already imply, which is what
    # a digitised curve wants. Jupiter's single sample has no such segment and
    # must state one.
    outer_slope: float | None = None
    flat_inside: bool = True


def belt_rate_gy_per_day(profile: BeltProfile, l_shell: float) -> float:
    """Absorbed dose rate at `l_shell`, behind the profile's own shielding."""
    if l_shell <= 0.0:
        return 0.0
    samples = profile.samples
    first_l, first_rate = samples[0]
    if l_shell <= first_l:
        if profile.flat_inside or len(samples) < 2:
            return first_rate
        # Continue the innermost segment's slope rather than inventing a shape.
        second_l, second_rate = samples[1]
        index = math.log(second_rate / first_rate) / math.log(second_l / first_l)
        return first_rate * (l_shell / first_l) ** index
    for (low_l, low_rate), (high_l, high_rate) in zip(samples, samples[1:]):
        if l_shell <= high_l:
            index = math.log(high_rate / low_rate) / math.log(high_l / low_l)
            return low_rate * (l_shell / low_l) ** index
    last_l, last_rate = samples[-1]
    slope = profile.outer_slope
    if slope is None:
        previous_l, previous_rate = samples[-2]
        slope = -math.log(last_rate / previous_rate) / math.log(last_l / previous_l)
    return last_rate * (l_shell / last_l) ** -slope


BELT_PROFILES: dict[str, BeltProfile] = {
    # Jupiter. The one profile here that is fitted rather than read: a single
    # peak, a slope from Johnson's satellite fluxes, and a normalisation from
    # Pioneer 10's pass. Everything about how it was arrived at is above.
    "naif-599": BeltProfile(
        body_id="naif-599",
        samples=((JOVIAN_PEAK_L, JOVIAN_PEAK_GY_PER_DAY),),
        outer_slope=JOVIAN_OUTER_SLOPE,
        shielding_g_cm2=BELT_REFERENCE_SHIELDING_G_CM2,
        sources=(_PEAK_SOURCE, _SLOPE_SOURCE, _PEAK_RATE_FITTED_TO),
    ),
    # Saturn, from SATRAD's dose-depth curves. Read at 100 mils, where the same
    # figure also draws Jupiter at the same three distances, so the two belts
    # can be compared without either model's normalisation cancelling wrongly:
    # Saturn is fifty times gentler at 2.55 radii and three hundred thousand
    # times gentler at 9.47. The gap widens outward because Saturn's belt stops
    # — Tethys sweeps it clean at L = 4.9 — and Jupiter's never does.
    #
    # 2.55 is as far in as the figure goes and is near the peak `belts.py`
    # carries at 2.5, so inside it the rate is held flat on the same reasoning
    # as Jupiter's. The steep tail past 9.47 is not extrapolation into the
    # unknown: it is the belt having ended.
    "naif-699": BeltProfile(
        body_id="naif-699",
        samples=((2.55, 42.9), (5.95, 2.86), (9.47, 2.14e-3)),
        shielding_g_cm2=JPL_SHELL_G_CM2,
        sources=("garrett_2005",),
    ),
    # Neptune, from NMOD's dose rate against L. The one profile here with its
    # inner branch measured, so it is not held flat: the rate falls away inside
    # L = 7 rather than plateauing, and holding it flat would overstate a close
    # pass a hundredfold. Two peaks with a dip between them at L = 5, which is
    # the shape a single power law cannot carry and the reason this is a table.
    #
    # The report's own summary — 1000 rad(Si) in 100 days at the worst L — is
    # 0.1 Gy/day against the 0.138 read off the peak here, which is the accuracy
    # to expect from reading a log axis.
    "naif-899": BeltProfile(
        body_id="naif-899",
        samples=(
            (2.2, 1.296e-3),
            (3.7, 3.456e-2),
            (5.0, 8.64e-3),
            (7.0, 0.1382),
            (9.0, 2.592e-2),
            (12.0, 1.728e-3),
            (18.0, 5.18e-5),
            (27.0, 7.78e-7),
        ),
        shielding_g_cm2=JPL_SHELL_G_CM2,
        sources=("garrett_2017",),
        flat_inside=False,
    ),
}


def jovian_belt_rate_gy_per_day(l_shell: float) -> float:
    """Absorbed dose rate at `l_shell`, behind the reference shielding."""
    return belt_rate_gy_per_day(BELT_PROFILES["naif-599"], l_shell)


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
    profile: BeltProfile | None = None,
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
    if profile is None:
        profile = BELT_PROFILES["naif-599"]

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
            rate = belt_rate_gy_per_day(profile, radius / radius_km)
            total += rate * (now - previous_time) / _SEC_PER_DAY
        previous_time = now

    return total * belt_shielding_factor(shielding_g_cm2, profile.shielding_g_cm2)


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
    *sorted({key for profile in BELT_PROFILES.values() for key in profile.sources}),
)
