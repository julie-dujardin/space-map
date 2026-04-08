"""Unit tests for CSV value conversion helpers."""

import datetime

import pytest

from space_map_data.ingest.convert import (
    bool_or_none,
    date_or_none,
    datetime_or_none,
    float_or_none,
    int_or_none,
    mean_motion_to_a_km,
    normalize_partial_date,
    string_or_none,
)


class TestStringOrNone:
    def test_normal_string(self):
        assert string_or_none("hello") == "hello"

    def test_strips_whitespace(self):
        assert string_or_none("  hello  ") == "hello"

    def test_empty_string(self):
        assert string_or_none("") is None

    def test_whitespace_only(self):
        assert string_or_none("   ") is None

    def test_none_input(self):
        assert string_or_none(None) is None


class TestFloatOrNone:
    def test_valid_float(self):
        assert float_or_none("3.14") == pytest.approx(3.14)

    def test_integer_string(self):
        assert float_or_none("42") == 42.0

    def test_scientific_notation(self):
        assert float_or_none("4.7766E-12") == pytest.approx(4.7766e-12)

    def test_empty_string(self):
        assert float_or_none("") is None

    def test_whitespace_only(self):
        assert float_or_none("   ") is None

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            float_or_none("abc")


class TestBoolOrNone:
    @pytest.mark.parametrize("val", ["Y", "y", "T", "t", "true", "TRUE", "yes", "YES"])
    def test_truthy(self, val):
        assert bool_or_none(val) is True

    @pytest.mark.parametrize("val", ["N", "n", "F", "f", "false", "FALSE", "no", "NO"])
    def test_falsy(self, val):
        assert bool_or_none(val) is False

    def test_empty_string(self):
        assert bool_or_none("") is None

    def test_whitespace_only(self):
        assert bool_or_none("   ") is None

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Cannot convert"):
            bool_or_none("maybe")


class TestIntOrNone:
    def test_valid_int(self):
        assert int_or_none("42") == 42

    def test_negative(self):
        assert int_or_none("-7") == -7

    def test_empty_string(self):
        assert int_or_none("") is None

    def test_whitespace(self):
        assert int_or_none("  ") is None

    def test_float_raises(self):
        with pytest.raises(ValueError):
            int_or_none("3.14")


class TestNormalizePartialDate:
    def test_full_date(self):
        assert normalize_partial_date("2024-01-15") == "2024-01-15"

    def test_partial_date_with_question_marks(self):
        assert normalize_partial_date("1995-??-??") == "1995"

    def test_bce_full(self):
        assert normalize_partial_date("-146-06-28") == "-146-06-28"

    def test_bce_partial(self):
        assert normalize_partial_date("-200-??-??") == "-200"

    def test_empty(self):
        assert normalize_partial_date("") is None

    def test_whitespace(self):
        assert normalize_partial_date("   ") is None

    def test_strips_whitespace(self):
        assert normalize_partial_date("  2024-01-15  ") == "2024-01-15"


class TestDateOrNone:
    def test_valid_date(self):
        assert date_or_none("2024-01-15") == datetime.date(2024, 1, 15)

    def test_empty(self):
        assert date_or_none("") is None

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            date_or_none("not-a-date")


class TestDatetimeOrNone:
    """Tests for fractional-day datetime parsing (YYYY-MM-DD.DDDDDDD format)."""

    def test_whole_day(self):
        result = datetime_or_none("2025-11-21.0000000")
        assert result == datetime.datetime(2025, 11, 21, 0, 0, 0)

    def test_half_day(self):
        result = datetime_or_none("2025-01-01.5000000")
        assert result is not None
        assert result.hour == 12
        assert result.minute == 0

    def test_no_fractional_part(self):
        result = datetime_or_none("2025-01-01")
        assert result == datetime.datetime(2025, 1, 1)

    def test_empty(self):
        assert datetime_or_none("") is None


class TestMeanMotionToAKm:
    """Tests for deriving semi-major axis from mean motion."""

    def test_geostationary(self):
        # GEO satellites orbit ~1 rev/day, a ≈ 42164 km
        a = mean_motion_to_a_km(1.0)
        assert a == pytest.approx(42164, rel=0.01)

    def test_iss_like(self):
        # ISS orbits ~15.5 rev/day, a ≈ 6780 km
        a = mean_motion_to_a_km(15.5)
        assert a == pytest.approx(6780, rel=0.01)

    def test_higher_mean_motion_gives_smaller_orbit(self):
        a_slow = mean_motion_to_a_km(1.0)
        a_fast = mean_motion_to_a_km(15.0)
        assert a_fast < a_slow
