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
    vague_date_to_iso,
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


class TestVagueDateToIso:
    """A date written to whatever precision its source knew, kept at it."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("1958 Jul 25", "1958-07-25"),
            ("1961 Apr", "1961-04"),
            ("1961", "1961"),
            # Johnston's page footers spell the month out.
            ("2022 April 30", "2022-04-30"),
            # A leading zero on the day, and GCAT's trailing uncertainty mark.
            ("2005 Oct 06", "2005-10-06"),
            ("1966 Feb 03?", "1966-02-03"),
        ],
    )
    def test_precision(self, raw, expected):
        assert vague_date_to_iso(raw) == expected

    def test_fractional_day_becomes_a_utc_time(self):
        assert vague_date_to_iso("2003 Dec 06.5") == "2003-12-06T12:00Z"
        assert vague_date_to_iso("2015 Feb 01.95") == "2015-02-01T22:48Z"

    def test_a_zero_fraction_stays_a_plain_date(self):
        """Midnight is the fraction's absence, not a time the source claimed."""
        assert vague_date_to_iso("2017 Jan 1.0") == "2017-01-01"

    def test_clock_time(self):
        assert vague_date_to_iso("1957 Oct 04 1928:34") == "1957-10-04T19:28:34Z"

    def test_unknown_month_token_keeps_the_year(self):
        """GCAT writes a quarter where it has no month."""
        assert vague_date_to_iso("1961 Q1") == "1961"

    def test_empty(self):
        assert vague_date_to_iso("") is None
        assert vague_date_to_iso(None) is None
