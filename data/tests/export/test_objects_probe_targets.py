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
                        "events": [
                            {"type": "launch", "date": "1999-12-31T10:00:00Z"},
                            {"type": "flyby", "target": {"naif": 499, "name": "Mars"}},
                            {
                                "type": "landing",
                                "target": {"naif": 499, "name": "Mars"},
                            },
                            {
                                "type": "flyby",
                                "target": {"naif": 2000433, "name": "Eros"},
                            },
                            {"type": "stage_separation", "target": {"probe_id": 1}},
                            {"type": "observation"},
                        ],
                    },
                    {
                        "probe_id": 1,
                        "name": "Earlier",
                        "events": [
                            {"type": "flyby", "target": {"naif": 499}},
                            {"type": "reentry", "target": {"naif": 399}},
                            {
                                "type": "flyby",
                                "purpose": "gravity_assist",
                                "target": {"naif": 299},
                            },
                            {"type": "flyby", "failed": True, "target": {"naif": 199}},
                        ],
                    },
                    {
                        "probe_id": 9,
                        "name": "Unregistered",
                        "events": [{"type": "flyby", "target": {"naif": 499}}],
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


def test_probes_per_body_once_by_launch(events: None) -> None:
    targets = build_probe_targets({"naif-499", "naif-2000433"})
    mars = targets["naif-499"]
    assert [p.object_id for p in mars] == ["probe-1", "probe-2"]
    assert mars[0].first_obs == "1941-01-06"
    assert mars[1].first_obs == "1999-12-31"
    assert mars[1].wikidata_qid == "Q2"
    assert [p.object_id for p in targets["naif-2000433"]] == ["probe-2"]
    assert "probe-9" not in {p.object_id for p in mars}
    assert "naif-399" not in targets
    assert "naif-299" not in targets
    assert "naif-199" not in targets
