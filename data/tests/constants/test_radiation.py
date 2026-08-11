"""Radiation facts: vocabulary and citation invariants, and the ordering
between bodies that any correct version of this table has to preserve."""

import pytest

from space_map_data.constants.activity.schema import Measurement
from space_map_data.constants.interior.bodies import INTERIOR_FACTS
from space_map_data.constants.radiation.belt_field import (
    BELT_ANCHORS,
    BELT_FIELD_SOURCES,
    BELT_MODEL_UNCERTAINTY_FACTOR,
    BELT_SHIELDING_FLOOR,
    EUROPA_ORBIT_GY_PER_DAY,
    EUROPA_ORBIT_L,
    JOVIAN_PEAK_GY_PER_DAY,
    JOVIAN_PEAK_L,
    JUPITER_RADIUS_KM,
    PIONEER_SHIELDING_G_CM2,
    PIONEER_V_INFINITY_KMS,
    belt_pass_dose_gy,
    belt_shielding_factor,
    jovian_belt_rate_gy_per_day,
)
from space_map_data.constants.radiation.belts import TRAPPED_BELTS
from space_map_data.constants.radiation.environments import (
    INTERPLANETARY_DOSE,
    RADIATION_ENVIRONMENTS,
)
from space_map_data.constants.radiation.field import (
    ANCHOR_ROLES,
    ATTENUATION_FLOOR,
    BUILDUP_DEPTH_G_CM2,
    FIELD_SOURCES,
    FLOWN_ANCHORS,
    PREDICTION,
    SOLAR_CYCLE_RATIO,
    SOLAR_CYCLE_YEARS,
    SOLAR_MINIMUM_EPOCH,
    atmospheric_attenuation,
    column_depth_g_cm2,
    cutoff_rigidity_gv,
    gcr_dose_rate,
    mean_cos4_latitude,
    open_sky_fraction,
    solar_cycle_factor,
)
from space_map_data.constants.radiation.references import RADIATION_SOURCES
from space_map_data.constants.radiation.schema import (
    DOSE_KINDS,
    TRAPPED,
    DoseRate,
    RadiationEnvironment,
    TrappedBelt,
)

ENVIRONMENT_IDS = sorted(RADIATION_ENVIRONMENTS)
BELT_IDS = sorted(TRAPPED_BELTS)
ALL_IDS = sorted(set(ENVIRONMENT_IDS) | set(BELT_IDS))

DOSED_IDS = sorted(
    object_id
    for object_id, env in RADIATION_ENVIRONMENTS.items()
    if env.surface_dose or env.orbit_dose
)


def _measurements(entry: RadiationEnvironment | TrappedBelt):
    """Every Measurement in one body's record, through the DoseRate wrapper."""
    for field in entry:
        if isinstance(field, Measurement):
            yield field
        elif isinstance(field, DoseRate):
            yield field.sv_per_day


def _source_keys() -> set[str]:
    keys: set[str] = set()
    for env in RADIATION_ENVIRONMENTS.values():
        keys |= set(env.kind_sources)
        keys |= {m.source for m in _measurements(env)}
    for belt in TRAPPED_BELTS.values():
        keys |= set(belt.sources)
        keys |= {m.source for m in _measurements(belt)}
    keys.add(INTERPLANETARY_DOSE.sv_per_day.source)
    keys |= set(FIELD_SOURCES)
    keys |= {a.source for a in FLOWN_ANCHORS.values()}
    keys |= set(BELT_FIELD_SOURCES)
    keys |= {a.source for a in BELT_ANCHORS.values()}
    return keys


class TestVocabulary:
    """An unrecognised kind renders as a raw key or as nothing at all."""

    @pytest.mark.parametrize("object_id", ENVIRONMENT_IDS)
    def test_kinds_are_known(self, object_id: str):
        assert RADIATION_ENVIRONMENTS[object_id].kind in DOSE_KINDS


class TestCitations:
    """The credits page renders `RADIATION_SOURCES`; a `source` string with no
    entry there ships a number with nothing behind it."""

    def test_every_source_is_citable(self):
        assert _source_keys() <= set(RADIATION_SOURCES)

    def test_no_reference_is_orphaned(self):
        assert set(RADIATION_SOURCES) <= _source_keys()

    @pytest.mark.parametrize("key", sorted(RADIATION_SOURCES))
    def test_references_carry_a_panel_note(self, key: str):
        assert RADIATION_SOURCES[key].note

    @pytest.mark.parametrize("object_id", DOSED_IDS)
    def test_a_number_names_the_work_it_came_from(self, object_id: str):
        """A classification can rest on arithmetic — Titan's does — but a dose
        rate is somebody's measurement or somebody's model, and it has to say
        whose."""
        for measurement in _measurements(RADIATION_ENVIRONMENTS[object_id]):
            assert measurement.source

    @pytest.mark.parametrize("object_id", ENVIRONMENT_IDS)
    def test_every_classification_names_a_work(self, object_id: str):
        """`kind` is the one field with full coverage, so it is the one a
        reader will trust without looking. Every rung of it is somebody's
        finding — that Mercury cannot hold a belt, that Titan's cascade stops
        65 km up — and none of it is self-evident from the body."""
        assert RADIATION_ENVIRONMENTS[object_id].kind_sources


class TestMeasurements:
    """`Measurement` exists so a bound never reads as a value."""

    @pytest.mark.parametrize(
        "object_id, table",
        [(i, RADIATION_ENVIRONMENTS) for i in ENVIRONMENT_IDS]
        + [(i, TRAPPED_BELTS) for i in BELT_IDS],
    )
    def test_ranges_bracket_their_value(self, object_id: str, table: dict):
        for measurement in _measurements(table[object_id]):
            if measurement.range is None:
                continue
            low, high = measurement.range
            assert low <= high
            assert low <= measurement.value <= high

    @pytest.mark.parametrize("object_id", DOSED_IDS)
    def test_doses_are_positive(self, object_id: str):
        """Sieverts per day. A zero or a negative here is a unit slip, and the
        table spans ten orders of magnitude so a slip would not look wrong."""
        for measurement in _measurements(RADIATION_ENVIRONMENTS[object_id]):
            assert measurement.value > 0


class TestCrossTable:
    """The two tables describe the same bodies, and have to agree with the
    rest of the constants and with each other."""

    @pytest.mark.parametrize("object_id", ALL_IDS)
    def test_a_body_is_spelled_the_way_the_rest_of_the_constants_spell_it(
        self, object_id: str
    ):
        """An id nothing else uses is a body nothing will ever match — Vesta's
        `naif-2000004` cost it a whole block silently. See the same test in
        `test_activity.py`."""
        assert object_id in INTERIOR_FACTS

    @pytest.mark.parametrize("object_id", BELT_IDS)
    def test_a_belt_belongs_to_a_body_that_could_hold_one(self, object_id: str):
        """A belt needs a field to be trapped in. Mercury is the awkward case
        and the reason this checks the environment rather than the magnetism
        table: its belt is real but intermittent, so its dose environment is
        `cosmic` while it still gets an entry here."""
        assert object_id in RADIATION_ENVIRONMENTS

    @pytest.mark.parametrize("object_id", BELT_IDS)
    def test_belt_extents_are_ordered(self, object_id: str):
        """Inner, peak, outer, in radii, in that order. Any two of the three
        may be absent — Jupiter's belts have no outer edge to quote."""
        belt = TRAPPED_BELTS[object_id]
        bounds = [
            m.value
            for m in (belt.inner_radii, belt.peak_radii, belt.outer_radii)
            if m is not None
        ]
        assert bounds == sorted(bounds)

    @pytest.mark.parametrize("object_id", BELT_IDS)
    def test_a_belt_starts_above_the_body(self, object_id: str):
        """L is measured in planetary radii from the centre, so an inner edge
        below 1 would be inside the planet."""
        inner = TRAPPED_BELTS[object_id].inner_radii
        if inner is None:
            return
        assert inner.value > 1.0


class TestOrdering:
    """Relations between bodies that hold whatever the numbers are revised to.
    Each of these has been got wrong in a published table somewhere."""

    def test_the_moon_is_harsher_than_mars(self):
        """Both are cosmic-ray environments and the only difference is Mars's
        atmosphere, so the airless one has to read higher. If this ever flips,
        a solar-cycle correction has been applied to one and not the other."""
        moon = RADIATION_ENVIRONMENTS["naif-301"].surface_dose
        mars = RADIATION_ENVIRONMENTS["naif-499"].surface_dose
        assert moon and mars
        assert moon.sv_per_day.value > mars.sv_per_day.value

    def test_free_space_is_harsher_than_any_surface_it_shields(self):
        """A body blocks the lower half of the sky. No cosmic-ray surface can
        read above open space at 1 AU; only a trapped environment can."""
        for object_id in DOSED_IDS:
            env = RADIATION_ENVIRONMENTS[object_id]
            if env.kind == TRAPPED or env.surface_dose is None:
                continue
            assert (
                env.surface_dose.sv_per_day.value
                <= INTERPLANETARY_DOSE.sv_per_day.value
            )

    def test_earths_orbit_is_harsher_than_its_ground(self):
        """The atmosphere is worth a factor of several hundred, and it is the
        largest single ratio in the table between two figures for one body."""
        earth = RADIATION_ENVIRONMENTS["naif-399"]
        assert earth.surface_dose and earth.orbit_dose
        assert (
            earth.orbit_dose.sv_per_day.value
            > earth.surface_dose.sv_per_day.value * 100
        )

    def test_europa_is_in_a_different_regime_entirely(self):
        """The point of the table. If Europa ever comes within three orders of
        magnitude of a cosmic-ray surface, a unit has been dropped: rads to
        grays is a factor of 100 and per-second to per-day is 86,400."""
        europa = RADIATION_ENVIRONMENTS["naif-502"].surface_dose
        moon = RADIATION_ENVIRONMENTS["naif-301"].surface_dose
        assert europa and moon
        assert europa.sv_per_day.value > moon.sv_per_day.value * 1e3


class TestFlownData:
    """The whole case for the field model. It is calibrated in cruise and at
    Earth, and everything else it says is extrapolation from those — so what
    matters is not that the fits fit, but that the two anchors nothing was
    fitted to come out right anyway."""

    @pytest.mark.parametrize("name", sorted(FLOWN_ANCHORS))
    def test_the_model_reproduces_what_was_measured(self, name: str):
        anchor = FLOWN_ANCHORS[name]
        predicted = gcr_dose_rate(anchor.epoch_year, anchor.r_au, anchor.near)
        residual = abs(predicted / anchor.measured_sv_per_day - 1.0)
        assert residual <= anchor.tolerance, (
            f"{name}: predicted {predicted:.3e}, measured "
            f"{anchor.measured_sv_per_day:.3e} ({100 * residual:+.1f}%)"
        )

    @pytest.mark.parametrize("name", sorted(FLOWN_ANCHORS))
    def test_roles_are_known(self, name: str):
        assert FLOWN_ANCHORS[name].role in ANCHOR_ROLES

    def test_the_moon_and_mars_are_never_fitted_to(self):
        """The guard that keeps this suite honest. Every parameter in the model
        has an anchor it was fitted to, and a residual can always be made to
        vanish by fitting to one more. These two have to stay out of sample or
        the agreement stops meaning anything."""
        assert FLOWN_ANCHORS["lnd_moon"].role == PREDICTION
        assert FLOWN_ANCHORS["rad_gale"].role == PREDICTION

    def test_something_is_being_predicted(self):
        assert sum(a.role == PREDICTION for a in FLOWN_ANCHORS.values()) >= 2


class TestGeometry:
    """`open_sky_fraction` is the only term with nothing fitted into it, so it
    is the one that has to be exactly right."""

    def test_a_surface_sees_half_the_sky(self):
        assert open_sky_fraction(1737.4, 1737.4) == pytest.approx(0.5)

    def test_far_away_sees_all_of_it(self):
        assert open_sky_fraction(6371.0, 6371.0 * 1e6) == pytest.approx(1.0, abs=1e-9)

    def test_it_climbs_with_altitude(self):
        radius = 6371.0
        seen = [open_sky_fraction(radius, radius + alt) for alt in (0, 400, 2000, 1e5)]
        assert seen == sorted(seen)

    def test_inside_the_body_is_clamped_not_undefined(self):
        """A trajectory sampler can hand this a point fractionally inside the
        surface. It must not take the root of a negative number."""
        assert open_sky_fraction(6371.0, 6000.0) == pytest.approx(0.5)


class TestAtmosphere:
    """A thin atmosphere is not a shield, and the code has to say so."""

    def test_a_thin_column_barely_attenuates(self):
        """Mars is the evidence: at Gale's 22 g/cm² the secondaries knocked
        loose roughly replace the primaries knocked out, once quality factors
        are counted. Anything that made this materially less than 1 would
        break the Gale prediction."""
        assert atmospheric_attenuation(22.0) == pytest.approx(1.0)

    def test_nothing_overhead_attenuates_nothing(self):
        assert atmospheric_attenuation(0.0) == pytest.approx(1.0)

    def test_earths_column_is_worth_more_than_two_decades(self):
        assert atmospheric_attenuation(1033.0) == pytest.approx(2.3e-3, rel=0.1)

    def test_it_falls_monotonically_past_the_buildup_depth(self):
        depths = [BUILDUP_DEPTH_G_CM2 + d for d in (0, 100, 500, 1000)]
        seen = [atmospheric_attenuation(d) for d in depths]
        assert seen == sorted(seen, reverse=True)

    def test_a_giant_column_reports_the_floor_not_a_fantasy(self):
        """Titan's 10,900 g/cm² sends the cascade exponential to 1e-29, which
        is not a small number but a meaningless one — what gets through a
        column that deep is muons obeying a different law. The floor is how
        the model admits it has stopped knowing."""
        assert atmospheric_attenuation(10_900.0) == ATTENUATION_FLOOR

    def test_column_depth_recovers_earths_thousand_g_per_cm2(self):
        assert column_depth_g_cm2(101_325.0, 9.80665) == pytest.approx(1033.2, rel=1e-3)

    def test_column_depth_is_pressure_over_gravity(self):
        assert column_depth_g_cm2(2000.0, 4.0) == pytest.approx(
            2.0 * column_depth_g_cm2(1000.0, 4.0)
        )
        assert column_depth_g_cm2(1000.0, 8.0) == pytest.approx(
            0.5 * column_depth_g_cm2(1000.0, 4.0)
        )


class TestCutoff:
    """The term that separates low Earth orbit from free space by more than
    the planet blocking half the sky accounts for."""

    def test_no_field_means_no_cutoff(self):
        assert cutoff_rigidity_gv(0.0, 1.0, 0.0) == 0.0

    def test_earths_equator_matches_the_tabulated_value(self):
        assert cutoff_rigidity_gv(7.69e22, 1.0, 0.0) == pytest.approx(14.9, rel=0.01)

    def test_the_poles_are_open(self):
        """cos⁴ latitude is why cosmic rays reach the ground at the poles and
        not at the equator, and why a polar orbit costs more dose than an
        equatorial one at the same altitude."""
        assert cutoff_rigidity_gv(7.69e22, 1.0, 90.0) == pytest.approx(0.0, abs=1e-12)

    def test_it_falls_off_with_distance(self):
        near = cutoff_rigidity_gv(7.69e22, 1.5, 0.0)
        far = cutoff_rigidity_gv(7.69e22, 6.0, 0.0)
        assert near == pytest.approx(far * 16.0, rel=1e-6)

    def test_an_inclined_orbit_averages_below_its_own_inclination(self):
        """A satellite lingers near its turning points, so the mean of cos⁴ is
        not cos⁴ of the mean. Getting this wrong is a factor of three in the
        ISS cutoff and would drag the fitted response with it."""
        assert mean_cos4_latitude(51.6) == pytest.approx(0.527, rel=0.01)
        assert mean_cos4_latitude(0.0) == pytest.approx(1.0)


class TestSolarCycle:
    """GCR dose peaks when the Sun is quiet, which is the counterintuitive
    half of the subject and the easiest sign error to ship."""

    def test_the_quiet_sun_is_the_dangerous_one(self):
        at_minimum = solar_cycle_factor(SOLAR_MINIMUM_EPOCH)
        at_maximum = solar_cycle_factor(SOLAR_MINIMUM_EPOCH + SOLAR_CYCLE_YEARS / 2.0)
        assert at_minimum > at_maximum

    def test_the_swing_is_the_ratio_guo_measured(self):
        at_minimum = solar_cycle_factor(SOLAR_MINIMUM_EPOCH)
        at_maximum = solar_cycle_factor(SOLAR_MINIMUM_EPOCH + SOLAR_CYCLE_YEARS / 2.0)
        assert at_minimum / at_maximum == pytest.approx(SOLAR_CYCLE_RATIO)

    def test_the_mean_is_one(self):
        """The reference dose is defined as the cycle mean, so a quarter cycle
        off a minimum has to leave it untouched."""
        quarter = SOLAR_MINIMUM_EPOCH + SOLAR_CYCLE_YEARS / 4.0
        assert solar_cycle_factor(quarter) == pytest.approx(1.0)

    def test_it_repeats(self):
        assert solar_cycle_factor(2030.0) == pytest.approx(
            solar_cycle_factor(2030.0 + SOLAR_CYCLE_YEARS)
        )

    def test_a_trip_to_jupiter_is_harsher_than_the_same_trip_at_1_au(self):
        """The radial gradient, end to end. Nothing else in the model makes
        the outer system worse than the inner one."""
        inner = gcr_dose_rate(2030.0, 1.0)
        outer = gcr_dose_rate(2030.0, 5.2)
        assert outer > inner
        assert outer / inner == pytest.approx(1.126, rel=0.01)


class TestBeltShielding:
    """The curve is two decades of measured aluminium and a floor, and the
    floor is the interesting part: without it a crew vault reads as immunity."""

    def test_the_reference_thickness_is_unity(self):
        assert belt_shielding_factor(0.11) == pytest.approx(1.0)

    def test_thinner_than_the_reference_is_not_amplified(self):
        assert belt_shielding_factor(0.0) == pytest.approx(1.0)

    def test_the_source_figures_two_decades_are_reproduced(self):
        assert belt_shielding_factor(2.7) == pytest.approx(0.01, rel=0.02)

    def test_a_crew_vault_lands_on_the_floor_rather_than_at_zero(self):
        """20 g/cm² through the bare exponential is 1e-11, which would read as
        a Jupiter pass being survivable behind a thick enough wall."""
        assert belt_shielding_factor(20.0) == BELT_SHIELDING_FLOOR

    @pytest.mark.parametrize("thickness", [0.11, 1.0, 2.7, 5.0, 50.0])
    def test_the_factor_never_leaves_its_bounds(self, thickness: float):
        assert BELT_SHIELDING_FLOOR <= belt_shielding_factor(thickness) <= 1.0


class TestBeltProfile:
    """A peaked profile, flat inside the peak on purpose."""

    def test_the_peak_is_where_the_belt_chapter_puts_it(self):
        """The profile and the table have to name the same L, or the model is
        peaked somewhere the belt it claims to describe is not."""
        peak = TRAPPED_BELTS["naif-599"].peak_radii
        assert peak is not None
        assert JOVIAN_PEAK_L == peak.value

    def test_inside_the_peak_is_held_flat(self):
        assert jovian_belt_rate_gy_per_day(1.5) == JOVIAN_PEAK_GY_PER_DAY
        assert jovian_belt_rate_gy_per_day(JOVIAN_PEAK_L) == JOVIAN_PEAK_GY_PER_DAY

    def test_it_falls_away_outside_the_peak(self):
        rates = [jovian_belt_rate_gy_per_day(x) for x in (3.0, 5.0, 9.4, 15.0, 26.3)]
        assert rates == sorted(rates, reverse=True)

    def test_callisto_sits_where_johnson_puts_it_against_europa(self):
        """The outer slope came from this ratio, so it is a round trip — but it
        is the one that stops the profile collapsing, and an earlier form got
        it wrong by three orders of magnitude."""
        ratio = jovian_belt_rate_gy_per_day(9.4) / jovian_belt_rate_gy_per_day(26.3)
        assert ratio == pytest.approx(250.0, rel=0.01)


class TestBeltPasses:
    """The flown passes, and the bias the model is known to carry."""

    @pytest.mark.parametrize("key", sorted(BELT_ANCHORS))
    def test_the_flown_passes_are_reproduced_within_tolerance(self, key: str):
        anchor = BELT_ANCHORS[key]
        predicted = belt_pass_dose_gy(
            anchor.periapsis_radii * JUPITER_RADIUS_KM,
            PIONEER_V_INFINITY_KMS,
            PIONEER_SHIELDING_G_CM2,
        )
        ratio = predicted / anchor.measured_gy
        assert 1.0 / (1.0 + anchor.tolerance) <= ratio <= 1.0 + anchor.tolerance

    def test_pioneer_11_is_never_fitted_to(self):
        """It is the only check this model has that is a pass rather than a
        rate. Fitting to it would leave nothing to be wrong against."""
        assert BELT_ANCHORS["pioneer_11"].role == PREDICTION

    def test_the_polar_pass_is_over_predicted_and_not_by_more_than_it_was(self):
        """Pins the known bias so a change that deepens it fails. Pioneer 11
        went closer than Pioneer 10 and took a quarter as much."""
        anchor = BELT_ANCHORS["pioneer_11"]
        predicted = belt_pass_dose_gy(
            anchor.periapsis_radii * JUPITER_RADIUS_KM,
            PIONEER_V_INFINITY_KMS,
            PIONEER_SHIELDING_G_CM2,
        )
        assert 3.0 < predicted / anchor.measured_gy < 5.0

    def test_speed_is_what_buys_a_pass_down(self):
        """Dose is a time integral, so at one periapsis the faster pass is the
        cheaper one — the mechanism behind Pioneer 11 surviving a closer
        approach than Pioneer 10.

        Only the mechanism, not that result: within this model Pioneer 11 is
        still the worse pass, because it flew inside the peak where the profile
        is held flat and because it went over the pole, which nothing here
        knows about. That gap is `test_the_polar_pass_is_over_predicted`.
        """
        slow = belt_pass_dose_gy(3.0 * JUPITER_RADIUS_KM, 5.0, 0.11)
        fast = belt_pass_dose_gy(3.0 * JUPITER_RADIUS_KM, 20.0, 0.11)
        assert fast < slow

    def test_europa_is_bracketed_rather_than_matched(self):
        """The other out-of-sample check, and it falls the other side of the
        model from Pioneer 11 — which is the honest reading of the spread."""
        under = EUROPA_ORBIT_GY_PER_DAY / jovian_belt_rate_gy_per_day(EUROPA_ORBIT_L)
        assert 1.0 < under < BELT_MODEL_UNCERTAINTY_FACTOR

    def test_a_pass_that_never_arrives_costs_nothing(self):
        assert belt_pass_dose_gy(0.0, 9.5, 0.11) == 0.0
        assert belt_pass_dose_gy(3.0 * JUPITER_RADIUS_KM, 0.0, 0.11) == 0.0

    def test_a_close_pass_is_lethal_by_orders_of_magnitude(self):
        """The finding the anchors were published for, and the one thing the
        planner has to get across whatever the factor of four does."""
        dose = belt_pass_dose_gy(2.0 * JUPITER_RADIUS_KM, 9.5, PIONEER_SHIELDING_G_CM2)
        assert dose > 100.0
