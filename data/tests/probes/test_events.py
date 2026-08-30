"""Tests for the probe-events schema: dates, the loader, and the validator."""

import json
from pathlib import Path

import pytest

from space_map_data.probes import events
from space_map_data.probes.events import (
    date_precision,
    event_jd,
    event_jd_range,
    load_event_probes,
)
from space_map_data.probes.events_validate import validate_files


def _probe(**overrides) -> dict:
    probe = {
        "probe_id": 1234,
        "name": "Test Probe",
        "status": {"where": "heliocentric", "alive": False},
        "description": "A craft that exists only here.",
        "source_urls": [],
        "events": [
            {
                "type": "launch",
                "date": "1977-08-20T14:29:00Z",
                "description": "Liftoff.",
            }
        ],
    }
    probe.update(overrides)
    return probe


def _write(root: Path, probes: list[dict], version: str = "v3") -> Path:
    path = root / "batch.json"
    path.write_text(
        json.dumps({"_meta": {"schema_version": version}, "probes": probes})
    )
    return path


@pytest.fixture
def events_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "events"
    root.mkdir()
    monkeypatch.setattr(events, "EVENTS_DIR", root)
    return root


class TestDates:
    """The five ISO forms, and what each of them claims."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("1965", "year"),
            ("1965-03", "month"),
            ("1965-03-21", "day"),
            ("1965-03-21T14:29Z", "minute"),
            ("1965-03-21T14:29:03Z", "second"),
        ],
    )
    def test_legal_forms(self, value: str, expected: str) -> None:
        assert date_precision(value) == expected

    @pytest.mark.parametrize(
        "value",
        [
            "1965-03-21T14:29:03",  # no zone
            "1965-03-21T14:29:03+02:00",  # an offset claims a local clock
            "1965-03-21T14:29:03.500Z",  # a precision no source here has
            "21 March 1965",
        ],
    )
    def test_illegal_forms(self, value: str) -> None:
        assert date_precision(value) is None
        with pytest.raises(ValueError):
            event_jd(value)

    def test_coarse_dates_start_their_period(self) -> None:
        assert event_jd("1965") == event_jd("1965-01-01")
        assert event_jd("1965-03") == event_jd("1965-03-01")

    def test_range_covers_what_a_date_could_mean(self) -> None:
        """A date-only event may follow a timestamp on the same day."""
        start, end = event_jd_range("1969-07-20")
        assert start <= event_jd("1969-07-20T20:17:40Z") <= end


class TestLoader:
    """Reading the files into typed records."""

    def test_reads_events_and_status(self, events_root: Path) -> None:
        _write(events_root, [_probe()])
        (probe,) = load_event_probes()
        assert probe.probe_id == 1234
        assert probe.status.where == "heliocentric"
        assert probe.status.alive is False
        assert probe.events[0].precision == "second"

    def test_span_exposes_both_ends(self, events_root: Path) -> None:
        _write(
            events_root,
            [
                _probe(
                    events=[
                        {
                            "type": "hibernation",
                            "date": "2014-11-15T00:36:00Z",
                            "end_date": "2015-06-13T20:28:00Z",
                            "description": "Asleep on the comet.",
                        }
                    ]
                )
            ],
        )
        (probe,) = load_event_probes()
        event = probe.events[0]
        assert event.end_jd is not None
        assert event.end_jd > event.jd

    def test_probe_without_an_id_is_skipped(self, events_root: Path) -> None:
        """Nothing downstream can join to a craft the registry has no row for."""
        _write(events_root, [_probe(probe_id=None)])
        assert load_event_probes() == []


class TestValidator:
    """Contract breaks are errors; a new figure is drift, and survives."""

    def test_clean_file_passes(self, events_root: Path) -> None:
        path = _write(events_root, [_probe()])
        errors, drift = validate_files([path])
        assert errors == []
        assert drift == []

    @pytest.mark.parametrize(
        ("event", "expected"),
        [
            ({"type": "arrival"}, "unknown type"),
            ({"date": "1977-08-20T14:29:03.5Z"}, "not an ISO form"),
            ({"type": "flyby"}, "flyby with no target"),
            ({"end_date": "1977-09-01"}, "which is a moment"),
            ({"outcome": "controlled"}, "'outcome' on 'launch'"),
        ],
    )
    def test_event_contract(
        self, events_root: Path, event: dict, expected: str
    ) -> None:
        base = {
            "type": "launch",
            "date": "1977-08-20T14:29:00Z",
            "description": "Liftoff.",
        }
        path = _write(events_root, [_probe(events=[{**base, **event}])])
        errors, _ = validate_files([path])
        assert any(expected in e for e in errors), errors

    def test_out_of_order_events(self, events_root: Path) -> None:
        path = _write(
            events_root,
            [
                _probe(
                    events=[
                        {
                            "type": "launch",
                            "date": "1977-08-20T14:29:00Z",
                            "description": "Liftoff.",
                        },
                        {
                            "type": "flyby",
                            "date": "1974-12-03",
                            "description": "Before it launched.",
                            "target": {"naif": 599, "name": "Jupiter"},
                        },
                    ]
                )
            ],
        )
        errors, _ = validate_files([path])
        assert any("out of order" in e for e in errors), errors

    def test_unknown_status_is_an_error(self, events_root: Path) -> None:
        path = _write(events_root, [_probe(status={"where": "somewhere"})])
        errors, _ = validate_files([path])
        assert any("unknown status.where" in e for e in errors), errors

    def test_new_figure_is_drift_not_an_error(self, events_root: Path) -> None:
        path = _write(
            events_root,
            [
                _probe(
                    events=[
                        {
                            "type": "launch",
                            "date": "1977-08-20T14:29:00Z",
                            "description": "Liftoff.",
                            "stated": {"sail_thickness_um": 7.5},
                        }
                    ]
                )
            ],
        )
        errors, drift = validate_files([path])
        assert errors == []
        assert any("stated.sail_thickness_um" in d for d in drift), drift

    def test_old_schema_version_is_an_error(self, events_root: Path) -> None:
        path = _write(events_root, [_probe()], version="v2")
        errors, _ = validate_files([path])
        assert any("schema_version" in e for e in errors), errors


def test_shipped_files_validate() -> None:
    """The curated files themselves, as they stand on disk."""
    errors, _ = validate_files()
    assert errors == []
