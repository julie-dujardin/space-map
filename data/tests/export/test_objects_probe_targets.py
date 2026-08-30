"""Tests for the body → probes reverse index built from the events files."""

import json
from pathlib import Path

import pytest

from space_map_data.export.objects import probe_targets
from space_map_data.export.objects.probe_targets import (
    build_probe_targets,
    target_object_ids,
)


@pytest.fixture
def events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "mars.json").write_text(
        json.dumps(
            {
                "probes": [
                    {
                        "probe_id": 2,
                        "name": "Later",
                        "mission_type": "mars_rover",
                        "status": {"where": "landed", "alive": False},
                        "events": [
                            {"type": "launch", "date": "1999-12-31T10:00:00Z"},
                            {
                                "type": "flyby",
                                "date": "2000-06-01",
                                "target": {"naif": 499, "name": "Mars"},
                            },
                            {
                                "type": "landing",
                                "date": "2000-07-01",
                                "outcome": "controlled",
                                "target": {"naif": 499, "name": "Mars"},
                            },
                            {
                                "type": "flyby",
                                "date": "2000-03-01",
                                "target": {"naif": 2000433, "name": "Eros"},
                            },
                            {
                                "type": "stage_separation",
                                "date": "2000-07-01",
                                "target": {"probe_id": 1},
                            },
                            {"type": "observation", "date": "2000-08-01"},
                            {"type": "mission_end", "date": "2003-01-01"},
                        ],
                    },
                    {
                        "probe_id": 1,
                        "name": "Earlier",
                        "events": [
                            {
                                "type": "flyby",
                                "date": "1950-01-01",
                                "target": {"naif": 499},
                            },
                            {
                                "type": "reentry",
                                "date": "1951-01-01",
                                "target": {"naif": 399},
                            },
                            {
                                "type": "flyby",
                                "date": "1949-01-01",
                                "purpose": "gravity_assist",
                                "target": {"naif": 299},
                            },
                            {
                                "type": "flyby",
                                "date": "1952-01-01",
                                "failed": True,
                                "target": {"naif": 199},
                            },
                        ],
                    },
                    {
                        "probe_id": 9,
                        "name": "Unregistered",
                        "events": [
                            {
                                "type": "flyby",
                                "date": "1960-01-01",
                                "target": {"naif": 499},
                            }
                        ],
                    },
                ]
            }
        )
    )
    monkeypatch.setattr(probe_targets, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(
        probe_targets,
        "load_registry",
        lambda: [
            {
                "probe_id": 2,
                "name": "Later",
                "inception_mjd": 40000,
                "wikidata_qid": "Q2",
            },
            {"probe_id": 1, "name": "Earlier", "inception_mjd": 30000},
        ],
    )


def test_target_ids_follow_horizons_convention() -> None:
    assert target_object_ids(499) == ("naif-499",)
    assert target_object_ids(2000433) == ("spkid-20000433", "naif-2000433")
    assert target_object_ids(1000036) == ("spkid-1000036",)


def test_probes_per_body_once_latest_first(events: None) -> None:
    targets = build_probe_targets({"naif-499", "naif-2000433"})
    mars = targets["naif-499"]
    assert [p.object_id for p in mars] == ["probe-2", "probe-1"]
    assert mars[1].first_obs == "1941-01-06"
    assert mars[0].first_obs == "1999-12-31"
    assert mars[0].wikidata_qid == "Q2"
    assert [p.object_id for p in targets["naif-2000433"]] == ["probe-2"]
    assert "probe-9" not in {p.object_id for p in mars}
    assert "naif-399" not in targets
    assert "naif-299" not in targets
    assert "naif-199" not in targets


def test_visit_kind_and_dates(events: None) -> None:
    targets = build_probe_targets({"naif-499", "naif-2000433"})
    later, earlier = targets["naif-499"]
    # A flyby is a single day.
    assert earlier.visit == {
        "kind": "flyby",
        "arrival": "1950-01-01",
        "end": "1950-01-01",
    }
    # Landing outranks the flyby; a rover mission type makes it a rover; the
    # end is the probe's mission_end after arrival.
    assert later.visit == {
        "kind": "rover",
        "arrival": "2000-06-01",
        "end": "2003-01-01",
    }
    assert targets["naif-2000433"][0].visit == {
        "kind": "flyby",
        "arrival": "2000-03-01",
        "end": "2000-03-01",
    }
