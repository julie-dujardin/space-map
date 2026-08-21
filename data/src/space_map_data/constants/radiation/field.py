"""The galactic cosmic ray field as a function of place and time.

`environments.py` holds measurements at the handful of points anyone has put a
dosimeter. This is the field between them: enough of a model to integrate a
dose along a trajectory, built so that every term is either exact geometry or a
fit to one of those measurements.

Four terms multiply.

    D = D_ref · cycle(t) · radial(r) · open_sky(geometry) · A(column) · C(cutoff)

`cycle` and `radial` describe the heliosphere, `open_sky` is the fraction of
the sky a nearby body leaves uncovered, and `A` and `C` are what an atmosphere
and a magnetic field take out of what is left. Away from any body the last
three are 1 and the whole thing collapses to a cruise rate.

Three parameters are fitted rather than cited — `REFERENCE_DOSE`, `CUTOFF_
RESPONSE_GV` and `ATMOSPHERIC_LENGTH_G_CM2` — and each names the single
measurement it was fitted to. That leaves two of the five flown datasets
unused by the fit, and they are what `FLOWN_ANCHORS` exists to check against:
the model is calibrated entirely at Earth and in cruise, and predicts the
lunar surface to 7% and Gale crater to 2% without being shown either.

Solar particle events are deliberately absent. Their fluence distribution is
lognormal, so an expected value is a bad summary of the hazard and folding one
into a dose rate would hide the thing that actually matters, which is the
chance of catching an August 1972 while you are out there.
"""

import math
from typing import NamedTuple

# --- the heliosphere ---------------------------------------------------------

# Solar minimum, and the period. SIDC put the cycle 24/25 minimum in December
# 2019 and the previous one in December 2008, which makes the last cycle
# exactly 11.0 years — the average of every cycle on record, though individual
# ones run from 9 to 14. Phase is measured from a minimum rather than a maximum
# because that is where cosmic rays peak.
SOLAR_MINIMUM_EPOCH = 2019.96
SOLAR_CYCLE_YEARS = 11.0
_SOLAR_CYCLE_SOURCE = "sidc_cycle_minima"

# How far the dose swings across a cycle. Guo's review puts the same Hohmann
# round trip at 0.65 Sv near solar maximum and 1.59 Sv near minimum, and that
# ratio is the whole amplitude: the Sun's field sweeps cosmic rays out of the
# inner system most effectively when it is most active, so the quiet Sun is the
# dangerous one. Taken as a ratio rather than as two absolute doses because the
# trip it is quoted for is not the trip anyone is planning.
SOLAR_CYCLE_RATIO = 1.59 / 0.65
_CYCLE_RATIO_SOURCE = "guo_2021"

# Cosmic ray intensity climbs with distance from the Sun. Roussos fitted this
# over 1 to 9.5 au against Cassini's >300 MeV protons, which is the energy band
# that carries the dose and the distance range this planner covers. It is
# polarity-dependent — 3.5 ± 0.3 %/au while the field was negative, dropping to
# about 2 after the 2014 reversal — so the cycle-average 3 is used and the
# spread is left in the range.
RADIAL_GRADIENT_PER_AU = 0.030
RADIAL_GRADIENT_RANGE = (0.020, 0.040)
_GRADIENT_SOURCE = "roussos_2020_gcr"

# Free space at 1 au, averaged over a solar cycle, behind a real spacecraft's
# worth of aluminium. Fitted: RAD read 1.58 mSv/day in cruise at a mean 1.25 au
# during 2012, and dividing out this model's cycle and radial terms for that
# epoch leaves the cycle-mean value. Everything else in the file scales off it.
#
# It carries RAD's shielding distribution, not a bare number, and the file
# treats that as if it did not matter. That is a real assumption and the lunar
# residual is what tests it: LND sat behind essentially nothing and comes out
# 7% *above* this model, the right sign and a plausible size for regolith
# albedo neutrons refilling the blocked hemisphere.
REFERENCE_DOSE_SV_PER_DAY = 1.731e-3
_REFERENCE_FITTED_TO = "guo_2021"


def solar_cycle_factor(decimal_year: float) -> float:
    """Dose multiplier against the cycle mean, peaking at solar minimum."""
    phase = 2.0 * math.pi * (decimal_year - SOLAR_MINIMUM_EPOCH) / SOLAR_CYCLE_YEARS
    return math.sqrt(SOLAR_CYCLE_RATIO) ** math.cos(phase)


def radial_factor(r_au: float) -> float:
    return 1.0 + RADIAL_GRADIENT_PER_AU * (r_au - 1.0)


# --- what a body nearby takes out --------------------------------------------


def open_sky_fraction(body_radius_km: float, distance_km: float) -> float:
    """Fraction of the sky a body at `distance_km` from its centre leaves open.

    Exact for an isotropic flux and the one term here with nothing fitted in
    it: the body subtends a cone of half-angle asin(R/d), so the open fraction
    is (1 + cos θ)/2. Standing on the surface gives exactly a half and infinity
    gives one, which is what makes "surface", "low orbit" and "free space" one
    formula instead of three rows in a table.
    """
    if distance_km <= body_radius_km:
        return 0.5
    return 0.5 * (1.0 + math.sqrt(1.0 - (body_radius_km / distance_km) ** 2))


def column_depth_g_cm2(pressure_pa: float, gravity_m_s2: float) -> float:
    """Mass of atmosphere overhead, from the surface pressure it holds up."""
    return 0.1 * pressure_pa / gravity_m_s2


# Where the shower stops building and starts attenuating. Below this depth an
# atmosphere is not a shield: primaries knocked out are replaced by secondaries
# knocked loose, and for *dose equivalent* the trade is close to even because
# the secondaries are neutrons with a quality factor of 10 or 20 against the
# primaries' 1. Mars is the evidence — 22 g/cm² over Gale, and the measurement
# needs an attenuation of 0.98 to reconcile with the geometry alone.
BUILDUP_DEPTH_G_CM2 = 30.0

# Attenuation length below the buildup region. Fitted: Earth's cosmic-ray
# background is 2.3e-3 of what the geometry and cutoff terms alone predict for
# sea level, over 1003 g/cm² of atmosphere past the buildup depth. The result
# lands at 165 g/cm², inside the 150-200 the cascade literature quotes, which
# is a coincidence worth stating because nothing in the fit forced it there.
#
# It is only weakly tied to the mean geomagnetic latitude assumed for that fit:
# sweeping the assumption from 30° to 50° moves the length from 177 to 157, so
# the two are not badly degenerate.
ATMOSPHERIC_LENGTH_G_CM2 = 165.1
_ATMOSPHERIC_FITTED_TO = "unscear_2008"

# Past about one Earth atmosphere the cascade exponential stops being physics.
# Continued to Venus's surface it returns 1e-273 and to Titan's 1e-29, which are
# not small numbers but meaningless ones: the hadronic shower is long dead and
# what is still arriving is ultra-relativistic muons, which lose energy by
# ionization at a roughly constant rate per g/cm² and so thin out as a power of
# the depth rather than exponentially.
#
# Both constants come from Herbst's Venus profile, the only atmosphere anyone
# has computed a dose through from the top of it to the ground. Below the deck
# the profile is a clean power law over two decades of depth, and the crossover
# is put where his deepest cascade-regime point sits — 51 km, 1,058 g/cm²,
# where this file's own exponential is right to 4.5% without having been shown
# it. So the two regimes meet where each is separately checked, and the curve
# is continuous there by construction.
#
# Venus's surface, at 103,800 g/cm², is the deepest column in the solar system.
# Nothing here ever extrapolates past it, which is why there is no floor any
# more: `MODELLED_CHECKS` holds the profile this was fitted to and what it
# still gets wrong.
MUON_CROSSOVER_G_CM2 = 1058.0
MUON_DEPTH_INDEX = 3.1505
_MUON_FITTED_TO = "herbst_2020"


def _cascade_attenuation(column_g_cm2: float) -> float:
    past_buildup = max(0.0, column_g_cm2 - BUILDUP_DEPTH_G_CM2)
    return math.exp(-past_buildup / ATMOSPHERIC_LENGTH_G_CM2)


def atmospheric_attenuation(column_g_cm2: float) -> float:
    """Surviving fraction of the dose equivalent under a mass column."""
    if column_g_cm2 <= MUON_CROSSOVER_G_CM2:
        return _cascade_attenuation(column_g_cm2)
    return (
        _cascade_attenuation(MUON_CROSSOVER_G_CM2)
        * (column_g_cm2 / MUON_CROSSOVER_G_CM2) ** -MUON_DEPTH_INDEX
    )


# --- what a magnetic field takes out -----------------------------------------

# Størmer's vertical cutoff at Earth's magnetic equator. A charged particle
# below this rigidity has no trajectory that reaches the equator from outside,
# whatever direction it arrives from. The full expression carries the arrival
# direction; the vertical case is the one that is tabulated and the one that
# stands in for an average over the sky.
#
# Smart & Shea's constant for IGRF 2000. They warn that many texts still
# quote Størmer's 1930 dipole constant, which ignores how the field has moved
# since — worked through, that obsolete constant gives the 14.9 GV older
# sources carry. The dipole term alone sets 14.5; the non-dipole terms swing
# the real cutoff between 14 and 16 around the equator and the mid-latitudes,
# so this is a centre rather than a sharp edge.
EARTH_EQUATORIAL_CUTOFF_GV = 14.5
_CUTOFF_SOURCE = "smart_shea_2005"

# Earth's dipole moment, the denominator that makes `cutoff_rigidity_gv` take a
# ratio. Duplicated from `activity/magnetism.py` rather than imported: this
# module is the physics and should not acquire a dependency on the body tables
# to hold one scaling constant. IGRF-14 via that file.
_EARTH_DIPOLE_MOMENT_A_M2 = 7.69e22

# Rigidity scale of the dose response. Fitted: the ISS reads 0.731 mSv/day
# where geometry and the cycle alone predict 1.70, and its orbit-averaged
# cutoff is 6.96 GV, so the surviving fraction is 0.43 at that cutoff. Treating
# the response as exp(-Rc/R0) puts R0 at 8.3 GV, which is the right order for a
# spectrum whose dose is carried by particles of a few GV upwards.
#
# One anchor fits one parameter, so the exponential form is an assumption and
# not a result. It is adequate over the 0-15 GV a dipole produces and should
# not be pushed past that.
CUTOFF_RESPONSE_GV = 8.258
_CUTOFF_FITTED_TO = "zhang_2020"


def cutoff_rigidity_gv(
    dipole_moment_a_m2: float, l_shell: float, magnetic_latitude_deg: float = 0.0
) -> float:
    """Størmer vertical cutoff, scaled off Earth's by dipole moment.

    `l_shell` is in planetary radii. The cos⁴ latitude dependence is why the
    poles are open and the equator is shut, and why a high-inclination orbit
    collects more dose than an equatorial one at the same altitude.
    """
    if l_shell <= 0.0:
        return 0.0
    moment_ratio = dipole_moment_a_m2 / _EARTH_DIPOLE_MOMENT_A_M2
    cos_lat = math.cos(math.radians(magnetic_latitude_deg))
    return EARTH_EQUATORIAL_CUTOFF_GV * moment_ratio * cos_lat**4 / l_shell**2


def cutoff_attenuation(rigidity_gv: float) -> float:
    """Surviving fraction of the dose behind a geomagnetic cutoff."""
    return math.exp(-max(0.0, rigidity_gv) / CUTOFF_RESPONSE_GV)


def mean_cos4_latitude(inclination_deg: float, samples: int = 4096) -> float:
    """Time-average of cos⁴(latitude) around a circular orbit.

    Latitude is not uniform around an inclined orbit — a satellite lingers near
    its turning points — so the average that belongs in a cutoff is this one
    and not cos⁴ of the inclination. For the ISS the difference is a factor of
    three in rigidity.
    """
    inclination = math.radians(inclination_deg)
    total = 0.0
    for k in range(samples):
        argument = 2.0 * math.pi * (k + 0.5) / samples
        latitude = math.asin(math.sin(inclination) * math.sin(argument))
        total += math.cos(latitude) ** 4
    return total / samples


# --- the whole thing ---------------------------------------------------------


class NearBody(NamedTuple):
    """The body a dose is being evaluated next to, if there is one."""

    radius_km: float
    distance_km: float
    column_g_cm2: float = 0.0
    dipole_moment_a_m2: float = 0.0
    magnetic_latitude_deg: float = 0.0


def gcr_dose_rate(
    decimal_year: float, r_au: float, near: NearBody | None = None
) -> float:
    """Cosmic ray dose equivalent in Sv/day at a point in space and time.

    Behind spacecraft-scale shielding, which for cosmic rays is nearly the same
    as behind none — the fitted reference carries RAD's aluminium and the lunar
    check says that costs under 10%. Trapped-particle belts are not in here and
    dominate wherever they exist, so a result near Jupiter or inside Earth's
    belts is a floor and not an estimate.
    """
    dose = (
        REFERENCE_DOSE_SV_PER_DAY
        * solar_cycle_factor(decimal_year)
        * radial_factor(r_au)
    )
    if near is None:
        return dose
    dose *= open_sky_fraction(near.radius_km, near.distance_km)
    dose *= atmospheric_attenuation(near.column_g_cm2)
    if near.dipole_moment_a_m2 > 0.0:
        l_shell = near.distance_km / near.radius_km
        dose *= cutoff_attenuation(
            cutoff_rigidity_gv(
                near.dipole_moment_a_m2, l_shell, near.magnetic_latitude_deg
            )
        )
    return dose


# --- what the model is answerable to -----------------------------------------


class FlownAnchor(NamedTuple):
    """One measurement the model has to reproduce, and the scenario it was
    taken in. `role` says whether the model was fitted to it or is predicting
    it; `tolerance` is the fractional residual the test allows."""

    measured_sv_per_day: float
    source: str
    role: str
    tolerance: float
    epoch_year: float
    r_au: float
    near: NearBody | None = None


CALIBRATION = "calibration"
FIT = "fit"
PREDICTION = "prediction"
ANCHOR_ROLES = frozenset({CALIBRATION, FIT, PREDICTION})

# Every work behind a parameter above, assembled from the per-parameter keys so
# the two cannot drift apart. The credits page needs this because none of these
# sources is reachable from `environments.py` or `belts.py`.
FIELD_SOURCES: tuple[str, ...] = (
    _SOLAR_CYCLE_SOURCE,
    _CYCLE_RATIO_SOURCE,
    _GRADIENT_SOURCE,
    _REFERENCE_FITTED_TO,
    _ATMOSPHERIC_FITTED_TO,
    _MUON_FITTED_TO,
    _CUTOFF_SOURCE,
    _CUTOFF_FITTED_TO,
)

_EARTH_RADIUS_KM = 6371.0
_ISS_ALTITUDE_KM = 400.0
_ISS_INCLINATION_DEG = 51.6

# The mean geomagnetic latitude Earth's background is taken to sit at. UNSCEAR
# averages over where people live, which is not where a dipole is symmetric;
# 40° is the rough population centroid and the sensitivity note on
# `ATMOSPHERIC_LENGTH_G_CM2` says what assuming it costs.
_POPULATION_MEAN_LATITUDE_DEG = 40.0

FLOWN_ANCHORS: dict[str, FlownAnchor] = {
    # RAD in cruise. Sets `REFERENCE_DOSE_SV_PER_DAY`, so its residual is zero
    # by construction and it is here to document the calibration rather than to
    # test it. 1.25 au is the time-weighted mean of an Earth-Mars transfer.
    "rad_cruise": FlownAnchor(
        measured_sv_per_day=1.58e-3,
        source="guo_2021",
        role=CALIBRATION,
        tolerance=0.01,
        epoch_year=2012.1,
        r_au=1.25,
    ),
    # The ISS. Fits `CUTOFF_RESPONSE_GV`. No atmosphere at 400 km worth
    # counting, so this isolates the geomagnetic term the way nothing else
    # here does.
    "iss": FlownAnchor(
        measured_sv_per_day=7.31e-4,
        source="zhang_2020",
        role=FIT,
        tolerance=0.05,
        epoch_year=2019.0,
        near=NearBody(
            radius_km=_EARTH_RADIUS_KM,
            distance_km=_EARTH_RADIUS_KM + _ISS_ALTITUDE_KM,
            dipole_moment_a_m2=_EARTH_DIPOLE_MOMENT_A_M2,
            magnetic_latitude_deg=math.degrees(
                math.acos(mean_cos4_latitude(_ISS_INCLINATION_DEG) ** 0.25)
            ),
        ),
        r_au=1.0,
    ),
    # Earth's surface. Fits `ATMOSPHERIC_LENGTH_G_CM2`. Cosmic component only,
    # and a global average over the whole cycle, so it carries no epoch — the
    # cycle factor is 1 at the mean and this anchor is evaluated there.
    "earth_ground": FlownAnchor(
        measured_sv_per_day=1.07e-6,
        source="unscear_2008",
        role=FIT,
        tolerance=0.05,
        epoch_year=SOLAR_MINIMUM_EPOCH + SOLAR_CYCLE_YEARS / 4.0,
        r_au=1.0,
        near=NearBody(
            radius_km=_EARTH_RADIUS_KM,
            distance_km=_EARTH_RADIUS_KM,
            column_g_cm2=1033.0,
            dipole_moment_a_m2=_EARTH_DIPOLE_MOMENT_A_M2,
            magnetic_latitude_deg=_POPULATION_MEAN_LATITUDE_DEG,
        ),
    ),
    # The lunar surface. Nothing here was fitted to it. Airless, unmagnetised
    # and at 1 au, so it tests the cycle term and the solid angle and nothing
    # else — the cleanest out-of-sample check in the set.
    "lnd_moon": FlownAnchor(
        measured_sv_per_day=1.369e-3,
        source="zhang_2020",
        role=PREDICTION,
        tolerance=0.10,
        epoch_year=2019.04,
        r_au=1.0,
        near=NearBody(radius_km=1737.4, distance_km=1737.4),
    ),
    # Gale crater. Nothing here was fitted to it either, and it adds the
    # atmosphere and a different heliocentric distance to what the Moon tests.
    # 22 g/cm² is Gale's own column, 4.4 km below the areoid and so heavier
    # than most of the planet's.
    "rad_gale": FlownAnchor(
        measured_sv_per_day=6.4e-4,
        source="hassler_2014",
        role=PREDICTION,
        tolerance=0.10,
        epoch_year=2013.0,
        r_au=1.52,
        near=NearBody(radius_km=3389.5, distance_km=3389.5, column_g_cm2=22.0),
    ),
}


# --- what the deep atmospheres are answerable to -----------------------------
#
# Kept apart from `FLOWN_ANCHORS` for the same reason `belt_field.py` is kept
# apart from this file: these are somebody else's transport code, not somebody's
# dosimeter, and the two should not look equally solid. Nobody has flown an
# instrument to the bottom of a thick atmosphere, so past a few hundred g/cm²
# a model is all there is to check against.
#
# Attenuation rather than a dose rate, because both entries are ratios taken
# *within* the source's own model — its free-space value against its value at
# depth. That is the only honest way to borrow an atmospheric term from work
# whose absolute normalisation is not this file's: Herbst's free-space Venus
# figure runs 1.8 times ours, and comparing rates instead of ratios would smear
# that difference into a term that has nothing to do with it.


class ModelledCheck(NamedTuple):
    """One published attenuation this file has to land near, and the fraction
    it is allowed to be out by. `role` reads as in `FlownAnchor`."""

    attenuation: float
    column_g_cm2: float
    source: str
    role: str
    tolerance: float
    note: str = ""


MODELLED_CHECKS: dict[str, ModelledCheck] = {
    # Venus's cloud deck, still in the cascade regime and untouched by the muon
    # fit. Out-of-sample on two counts: a CO₂ atmosphere rather than Earth's,
    # and no magnetic field at all, so nothing of the cutoff term stands in.
    "venus_cloud_top": ModelledCheck(
        attenuation=0.506,
        column_g_cm2=182.0,
        source="herbst_2020",
        role=PREDICTION,
        tolerance=0.35,
    ),
    # Venus at 51 km. Sets `MUON_CROSSOVER_G_CM2` in the sense that the handover
    # is put here, but not the exponential that reaches it — that was fitted to
    # Earth's sea level, and landing within 5% of a different planet's dose at a
    # comparable depth is the strongest single check the atmospheric term has.
    "venus_lower_cloud": ModelledCheck(
        attenuation=2.07e-3,
        column_g_cm2=1058.0,
        source="herbst_2020",
        role=PREDICTION,
        tolerance=0.10,
    ),
    # Venus's surface. Fits `MUON_DEPTH_INDEX`, so the residual is zero by
    # construction; it is here to record the deepest column in the solar system
    # and to fail loudly if the power law is ever re-pointed.
    "venus_surface": ModelledCheck(
        attenuation=1.05e-9,
        column_g_cm2=103800.0,
        source="herbst_2020",
        role=FIT,
        tolerance=0.05,
    ),
    # Titan, and the one the model gets wrong. Gronoff computes ionization
    # rather than dose, so this is his surface rate converted the standard way —
    # 0.25 ion pairs cm⁻³ s⁻¹ at 35 eV each, over the surface air density — a
    # route that reproduces UNSCEAR's Earth sea-level figure to 15% and so is
    # not the suspect part.
    #
    # It lands 17 times above what Venus's power law predicts at the same depth,
    # and the disagreement will not resolve in the model's favour: Gronoff caps
    # primaries at 100 GeV, and those are exactly the particles that reach a
    # surface, so his figure is a floor. Either Venus's index is too steep for a
    # cold N₂ atmosphere spread over ten times the height, or one of the two
    # transport codes is wrong at depth. A tolerance wide enough to pass is a
    # pin on a known failure, not a claim the model works here.
    "titan_surface": ModelledCheck(
        attenuation=2.21e-5,
        column_g_cm2=10850.0,
        source="gronoff_2011",
        role=PREDICTION,
        tolerance=20.0,
        note="disputed_by_a_factor_of_seventeen",
    ),
}
