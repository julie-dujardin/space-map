"""`_add_carried_coverage` lends a carrier's windows to its passengers."""

import pytest

from space_map_data.export.position.probes import writer
from space_map_data.export.position.probes.writer import ProbeCoverage, ProbeCoverageMap
from space_map_data.probes.attachments import Attachment


def _carried_from(entry: ProbeCoverage) -> dict:
    """`position_from` is NotRequired, so read it through one narrowing point."""
    carried = entry.get("position_from")
    assert carried is not None
    return dict(carried)


RIDE_START = 2450000.0
RIDE_END = 2450500.0


@pytest.fixture(autouse=True)
def one_attachment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        writer,
        "resolve_attachments",
        lambda: [Attachment(200, 100, RIDE_START, RIDE_END)],
    )


def _carrier(*windows: tuple[float, float]) -> ProbeCoverage:
    spans = list(windows) or [(2449000.0, 2451000.0)]
    return {"start_jd": spans[0][0], "end_jd": spans[-1][1], "windows": spans}


def _own(start_jd: float) -> ProbeCoverage:
    """A craft's own fits, 100 days of them, starting where the caller says."""
    return {
        "start_jd": start_jd,
        "end_jd": start_jd + 100.0,
        "windows": [(start_jd, start_jd + 100.0)],
    }


def test_passenger_borrows_the_carriers_windows() -> None:
    coverage: ProbeCoverageMap = {"probe-100": _carrier()}
    writer._add_carried_coverage(coverage)
    assert coverage["probe-200"] == {
        "start_jd": 2450000.0,
        "end_jd": 2450500.0,
        "windows": [(2450000.0, 2450500.0)],
        "position_from": {
            "object_id": "probe-100",
            "start_jd": 2450000.0,
            "end_jd": 2450500.0,
        },
    }


def test_the_passengers_own_fits_win_over_borrowed_ones() -> None:
    """A lander's descent kernel starts mid-ride; the union covers both."""
    coverage: ProbeCoverageMap = {
        "probe-100": _carrier(),
        "probe-200": {
            "start_jd": 2450400.0,
            "end_jd": 2450600.0,
            "windows": [(2450400.0, 2450600.0)],
        },
    }
    writer._add_carried_coverage(coverage)
    assert coverage["probe-200"]["windows"] == [(2450000.0, 2450600.0)]
    assert _carried_from(coverage["probe-200"])["object_id"] == "probe-100"


def test_carrier_gaps_are_not_papered_over() -> None:
    coverage: ProbeCoverageMap = {
        "probe-100": _carrier((2450000.0, 2450100.0), (2450300.0, 2450500.0))
    }
    writer._add_carried_coverage(coverage)
    assert coverage["probe-200"]["windows"] == [
        (2450000.0, 2450100.0),
        (2450300.0, 2450500.0),
    ]


def test_carrier_without_coverage_is_skipped(caplog) -> None:
    coverage: ProbeCoverageMap = {}
    writer._add_carried_coverage(coverage)
    assert coverage == {}
    assert "probe-100" in caplog.text


def test_the_ride_ends_at_separation() -> None:
    """The stamp is the attachment, nothing more. A craft whose own fits
    start later is carried across that hole by the frontend, which reads the
    sub-chunk grid these whole-chunk windows cannot see."""
    coverage: ProbeCoverageMap = {
        "probe-100": _carrier(),
        "probe-200": _own(RIDE_END + 5.0),
    }
    writer._add_carried_coverage(coverage)
    assert coverage["probe-200"]["windows"] == [
        (RIDE_START, RIDE_END),
        (RIDE_END + 5.0, RIDE_END + 105.0),
    ]
    assert _carried_from(coverage["probe-200"])["end_jd"] == RIDE_END
