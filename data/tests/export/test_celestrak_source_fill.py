"""Unit tests for filling snapshot gaps from neighbouring snapshots."""

from space_map_data.export.position.elements.celestrak_source import (
    CelesTrakElements,
    fill_gaps,
)

# 2026-01-05, 2026-01-12 and 2026-02-23 as Julian Dates.
_JD_JAN_05 = 2461045.5
_JD_JAN_12 = 2461052.5
_JD_FEB_23 = 2461094.5


def _elements(epoch_jd: float) -> CelesTrakElements:
    return CelesTrakElements(
        epoch_jd=epoch_jd,
        a=7000.0,
        e=0.001,
        i=51.6,
        om=0.0,
        w=0.0,
        ma=0.0,
        n=15.5,
        BSTAR=0.0,
        MEAN_MOTION_DOT=0.0,
        MEAN_MOTION_DDOT=0.0,
        ELEMENT_SET_NO=999,
        REV_AT_EPOCH=1,
    )


class TestFillGaps:
    """Gaps are filled from the most recent earlier snapshot within the lookback."""

    def test_fills_from_the_previous_week(self):
        days = {
            "2026-01-05": {5: _elements(_JD_JAN_05), 11: _elements(_JD_JAN_05)},
            "2026-01-12": {5: _elements(_JD_JAN_12)},  # 11 went untracked
        }
        fill_gaps(days, {"2026-01-05", "2026-01-12"})
        assert set(days["2026-01-12"]) == {5, 11}
        # The filled row keeps its own epoch, so the frontend can flag its age.
        assert days["2026-01-12"][11]["epoch_jd"] == _JD_JAN_05

    def test_leaves_gaps_beyond_the_window(self):
        days = {
            "2026-01-05": {11: _elements(_JD_JAN_05)},
            "2026-02-23": {5: _elements(_JD_FEB_23)},  # 49 days later
        }
        fill_gaps(days, {"2026-01-05", "2026-02-23"})
        assert set(days["2026-02-23"]) == {5}

    def test_never_fills_from_a_later_snapshot(self):
        """A later element set can encode a manoeuvre that had not happened yet."""
        days = {
            "2026-01-05": {5: _elements(_JD_JAN_05)},  # 11 went untracked
            "2026-01-12": {5: _elements(_JD_JAN_12), 11: _elements(_JD_JAN_12)},
        }
        fill_gaps(days, {"2026-01-05", "2026-01-12"})
        assert set(days["2026-01-05"]) == {5}

    def test_picks_the_most_recent_of_several_earlier_snapshots(self):
        days = {
            "2026-01-05": {11: _elements(_JD_JAN_05)},
            "2026-01-12": {11: _elements(_JD_JAN_12)},
            "2026-01-19": {5: _elements(_JD_JAN_12 + 7)},
        }
        fill_gaps(days, {"2026-01-05", "2026-01-12", "2026-01-19"})
        assert days["2026-01-19"][11]["epoch_jd"] == _JD_JAN_12

    def test_ignores_snapshots_outside_the_eligible_dates(self):
        """CelesTrak's GROUP=active is a subset of Space-Track's catalogue, so it
        must neither donate to nor receive from a Space-Track snapshot."""
        days = {
            "2026-01-05": {5: _elements(_JD_JAN_05), 11: _elements(_JD_JAN_05)},
            "2026-01-12": {5: _elements(_JD_JAN_12)},
        }
        fill_gaps(days, {"2026-01-12"})  # Jan 5 is a CelesTrak day
        assert set(days["2026-01-12"]) == {5}
        assert set(days["2026-01-05"]) == {5, 11}

    def test_no_eligible_dates_is_a_no_op(self):
        days = {"2026-01-05": {5: _elements(_JD_JAN_05)}}
        fill_gaps(days, set())
        assert days == {"2026-01-05": {5: _elements(_JD_JAN_05)}}
