"""Tests for space_map_data.utils.convert."""

from datetime import date, datetime

import pytest

from space_map_data.utils.convert import date_to_julian


class TestDateToJulian:
    """JD conversion must be timezone-safe.

    CelesTrak's gp.csv ships EPOCH without a Z suffix or offset (e.g.
    ``2026-04-25T14:51:50.576832``). A naive ``datetime.timestamp()`` would
    treat that as local time and shift the JD by the host's TZ offset —
    moving every Earth satellite off its true ground track.
    """

    def test_naive_iso_string_treated_as_utc(self, monkeypatch):
        # Force a non-UTC local TZ so a naive parse + .timestamp() would diverge.
        monkeypatch.setenv("TZ", "Europe/Paris")
        import time

        time.tzset()
        celestrak_epoch = "2026-04-25T14:51:50.576832"
        # 2026-04-25 14:51:50.576832 UTC = JD 2461156.119335 (within a tiny rounding).
        jd = date_to_julian(celestrak_epoch)
        assert jd is not None
        # Compare to the JD of the same instant explicitly tagged as UTC.
        utc_jd = (
            datetime.fromisoformat(celestrak_epoch + "+00:00").timestamp() / 86400.0
            + 2440587.5
        )
        assert jd == pytest.approx(utc_jd, abs=1e-9)

    def test_z_suffix_string(self):
        jd_z = date_to_julian("2026-04-25T14:51:50.576832Z")
        jd_offset = date_to_julian("2026-04-25T14:51:50.576832+00:00")
        assert jd_z == jd_offset

    def test_explicit_offset_string(self):
        # +02:00 EPOCH means the UTC instant is 2h earlier.
        cest = date_to_julian("2026-04-25T14:51:50.576832+02:00")
        utc = date_to_julian("2026-04-25T12:51:50.576832+00:00")
        assert cest == pytest.approx(utc, abs=1e-9)

    def test_date_input(self):
        # Pure-date inputs land at 0h UTC of the given day.
        assert date_to_julian(date(2000, 1, 1)) == pytest.approx(2451544.5)

    def test_empty_returns_none(self):
        assert date_to_julian("") is None
        assert date_to_julian("   ") is None
