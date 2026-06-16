"""Tests for space_map_data.export.position.elements.spacetrack_source."""

import pytest

from space_map_data.export.position.elements.celestrak_source import CelesTrakElements
from space_map_data.export.position.elements.spacetrack_source import (
    _decode_exp,
    _week_of,
    parse_tle_pair,
)


def _parse(line1: str, line2: str) -> tuple[int, float, CelesTrakElements]:
    """Parse and assert success, narrowing the Optional for the type checker."""
    result = parse_tle_pair(line1, line2)
    assert result is not None
    return result


class TestDecodeExp:
    """Decode the TLE assumed-decimal exponential fields (BSTAR, n-ddot)."""

    def test_negative_exponent(self):
        assert _decode_exp(" 13035-3") == pytest.approx(0.13035e-3)

    def test_zero(self):
        assert _decode_exp(" 00000-0") == 0.0

    def test_explicit_plus_sign_mantissa(self):
        # 2006-era lines write the sign explicitly: "+10000-3" → 0.10000e-3.
        assert _decode_exp("+10000-3") == pytest.approx(1.0e-4)

    def test_negative_mantissa(self):
        assert _decode_exp("-27028-2") == pytest.approx(-0.27028e-2)

    def test_blank_is_none(self):
        assert _decode_exp("       ") is None


class TestParseTlePair:
    """Fixed-column parse, robust to the archive's format drift across years."""

    # ISS (25544), 2024 day 1 — every field cross-checked against sgp4.twoline2rv.
    ISS_L1 = "1 25544U 98067A   24001.01267188  .00016541  00000-0  29758-3 0  5694"
    ISS_L2 = "2 25544  51.6422  68.6294 0003347 343.4617  78.0593 15.49961425432470"

    def test_iss_fields(self):
        norad, epoch_jd, el = _parse(self.ISS_L1, self.ISS_L2)
        assert norad == 25544
        assert epoch_jd == pytest.approx(2460310.51267188, abs=1e-6)
        assert el["i"] == pytest.approx(51.6422)
        assert el["om"] == pytest.approx(68.6294)
        assert el["e"] == pytest.approx(0.0003347)
        assert el["w"] == pytest.approx(343.4617)
        assert el["ma"] == pytest.approx(78.0593)
        assert el["n"] == pytest.approx(15.49961425)
        assert el["BSTAR"] == pytest.approx(0.29758e-3)
        assert el["MEAN_MOTION_DOT"] == pytest.approx(0.00016541)
        assert el["MEAN_MOTION_DDOT"] == 0.0
        assert el["REV_AT_EPOCH"] == 43247

    def test_trailing_backslash_and_explicit_signs(self):
        # 2006-era format: trailing `\` continuation on line 1 + explicit `+`
        # signs in the exponential fields. Fixed-column slicing ignores both.
        l1 = "1 02864U 67066C   05365.87596669 -.00000097 +00000-0 +10000-3 0 09553\\"
        l2 = "2 02864 010.5726 334.3973 0060639 203.2684 156.5268 01.09786032049590"
        norad, _, el = _parse(l1, l2)
        assert norad == 2864
        assert el["i"] == pytest.approx(10.5726)
        assert el["e"] == pytest.approx(0.0060639)
        assert el["n"] == pytest.approx(1.09786032)
        assert el["MEAN_MOTION_DOT"] == pytest.approx(-0.00000097)
        assert el["BSTAR"] == pytest.approx(1.0e-4)

    def test_semi_major_axis_from_mean_motion(self):
        _, _, el = _parse(self.ISS_L1, self.ISS_L2)
        a = el["a"]
        # ISS orbits at ~6795 km semi-major axis (~420 km altitude).
        assert a is not None and 6750 < a < 6850

    def test_malformed_returns_none(self):
        assert parse_tle_pair("not a tle", "neither is this") is None
        assert parse_tle_pair(self.ISS_L1, self.ISS_L1) is None  # two line-1s


class TestWeekOf:
    """Epoch → (Monday ISO label, week-midpoint JD)."""

    def test_monday_label_and_midpoint(self):
        # 2024-01-01 is itself a Monday; an epoch that day labels that week.
        _, epoch_jd, _ = _parse(TestParseTlePair.ISS_L1, TestParseTlePair.ISS_L2)
        monday, midpoint_jd = _week_of(epoch_jd)
        assert monday == "2024-01-01"
        # Midpoint is Monday 00:00 UTC + 3.5 days.
        assert midpoint_jd - epoch_jd == pytest.approx(3.5 - 0.01267188, abs=1e-4)

    def test_epoch_late_in_year_buckets_into_prior_iso_week(self):
        # 2023-12-31 falls in the ISO week starting Mon 2023-12-25.
        l1 = "1 00005U 58002B   23365.57064688  .00000316  00000-0  43126-3 0  9991"
        l2 = "2 00005  34.2390 206.9464 1841775  48.1863 326.2040 10.85148002345600"
        _, epoch_jd, _ = _parse(l1, l2)
        monday, _ = _week_of(epoch_jd)
        assert monday == "2023-12-25"
