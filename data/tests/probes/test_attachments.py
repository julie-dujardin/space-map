"""Tests for the carried-craft resolver."""

import json
from pathlib import Path

import pytest

from space_map_data.probes import attachments
from space_map_data.probes.landing_events import parse_event_jd


def _write(root: Path, name: str, probes: list[dict]) -> None:
    (root / name).write_text(json.dumps({"probes": probes}))


def _setup(
    monkeypatch: pytest.MonkeyPatch,
    registry: list[dict],
    coverage: dict[int, list[tuple[float, float]]],
) -> None:
    monkeypatch.setattr(attachments, "load_registry", lambda: registry)
    monkeypatch.setattr(attachments, "naif_coverage_jd", lambda: coverage)


CARRIER = {"probe_id": 100, "name": "Carrier", "naif_id": -10}
PASSENGER = {"probe_id": 200, "name": "Passenger", "naif_id": -20}


def _pair(events_root: Path, *, separation: str = "2005-01-01") -> None:
    _write(
        events_root,
        "mission.json",
        [
            {"probe_id": 100, "name": "Carrier", "events": []},
            {
                "probe_id": 200,
                "name": "Passenger",
                "parent_mission": "Carrier",
                "events": [
                    {"type": "launch", "date": "2000-01-01"},
                    {
                        "type": "stage_separation",
                        "date": separation,
                        "target": {"name": "Carrier"},
                    },
                ],
            },
        ],
    )


def test_passenger_rides_the_relative_that_has_a_trajectory(
    events_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pair(events_root)
    _setup(
        monkeypatch,
        [CARRIER, PASSENGER],
        {-10: [(parse_event_jd("1999-01-01"), parse_event_jd("2010-01-01"))]},
    )
    (attachment,) = attachments.resolve_attachments()
    assert attachment.probe_id == 200
    assert attachment.carrier_probe_id == 100
    assert attachment.start_jd == pytest.approx(parse_event_jd("2000-01-01"))
    assert attachment.end_jd == pytest.approx(parse_event_jd("2005-01-01"))


def test_direction_follows_the_trajectory_not_the_hierarchy(
    events_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both craft name each other; only the one with a trajectory can carry.

    The Apollo CSM separates from the S-IVB while the registry calls the CSM
    the mission primary, so a hierarchy-driven rule points the wrong way.
    """
    _write(
        events_root,
        "mission.json",
        [
            {
                "probe_id": 100,
                "name": "Carrier",
                "parent_mission": "Passenger",
                "events": [
                    {"type": "launch", "date": "2000-01-01"},
                    {
                        "type": "stage_separation",
                        "date": "2005-01-01",
                        "target": {"name": "Passenger"},
                    },
                ],
            },
            {
                "probe_id": 200,
                "name": "Passenger",
                "parent_mission": "Carrier",
                "events": [
                    {"type": "launch", "date": "2000-01-01"},
                    {
                        "type": "stage_separation",
                        "date": "2005-01-01",
                        "target": {"name": "Carrier"},
                    },
                ],
            },
        ],
    )
    _setup(
        monkeypatch,
        [CARRIER, PASSENGER],
        {-10: [(parse_event_jd("1999-01-01"), parse_event_jd("2010-01-01"))]},
    )
    (attachment,) = attachments.resolve_attachments()
    assert (attachment.probe_id, attachment.carrier_probe_id) == (200, 100)


def test_craft_with_its_own_trajectory_is_not_a_passenger(
    events_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pair(events_root)
    _setup(
        monkeypatch,
        [CARRIER, PASSENGER],
        {
            -10: [(parse_event_jd("1999-01-01"), parse_event_jd("2010-01-01"))],
            -20: [(parse_event_jd("1999-01-01"), parse_event_jd("2010-01-01"))],
        },
    )
    assert attachments.resolve_attachments() == []


def test_no_relative_with_a_trajectory_yields_nothing(
    events_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every Apollo craft names a relative, but none has a kernel to lend."""
    _pair(events_root)
    _setup(monkeypatch, [CARRIER, PASSENGER], {})
    assert attachments.resolve_attachments() == []


def test_carrier_covering_a_sliver_is_not_worth_borrowing(
    events_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pair(events_root)
    _setup(
        monkeypatch,
        [CARRIER, PASSENGER],
        {-10: [(parse_event_jd("2004-12-01"), parse_event_jd("2005-01-01"))]},
    )
    assert attachments.resolve_attachments() == []


def test_same_day_separation_is_not_a_window(
    events_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pair(events_root, separation="2000-01-01")
    _setup(
        monkeypatch,
        [CARRIER, PASSENGER],
        {-10: [(parse_event_jd("1999-01-01"), parse_event_jd("2010-01-01"))]},
    )
    assert attachments.resolve_attachments() == []


def test_no_separation_event_yields_nothing(
    events_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a separation instant there is no end to the ride."""
    _write(
        events_root,
        "mission.json",
        [
            {"probe_id": 100, "name": "Carrier", "events": []},
            {
                "probe_id": 200,
                "name": "Passenger",
                "parent_mission": "Carrier",
                "events": [{"type": "launch", "date": "2000-01-01"}],
            },
        ],
    )
    _setup(
        monkeypatch,
        [CARRIER, PASSENGER],
        {-10: [(parse_event_jd("1999-01-01"), parse_event_jd("2010-01-01"))]},
    )
    assert attachments.resolve_attachments() == []


def test_synthetic_naif_never_indexes_a_kernel(
    events_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EVENTS-DB registry rows carry a synthetic NAIF; it must not be looked
    up as if it were a kernel target."""
    _pair(events_root)
    _setup(
        monkeypatch,
        [{**CARRIER, "naif_id": -90000123}, PASSENGER],
        {-90000123: [(parse_event_jd("1999-01-01"), parse_event_jd("2010-01-01"))]},
    )
    assert attachments.resolve_attachments() == []


def test_passenger_launching_without_its_own_date_starts_at_the_carrier(
    events_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(
        events_root,
        "mission.json",
        [
            {"probe_id": 100, "name": "Carrier", "events": []},
            {
                "probe_id": 200,
                "name": "Passenger",
                "parent_mission": "Carrier",
                "events": [
                    {
                        "type": "stage_separation",
                        "date": "2005-01-01",
                        "target": {"name": "Carrier"},
                    }
                ],
            },
        ],
    )
    _setup(
        monkeypatch,
        [CARRIER, PASSENGER],
        {-10: [(parse_event_jd("2001-06-01"), parse_event_jd("2010-01-01"))]},
    )
    (attachment,) = attachments.resolve_attachments()
    assert attachment.start_jd == pytest.approx(parse_event_jd("2001-06-01"))
