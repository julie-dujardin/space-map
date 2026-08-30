"""Tests for the curated-events block attached to probe object bundles."""

import json
from pathlib import Path

import pytest

from space_map_data.export.objects.probe_events import attach_probe_events
from space_map_data.export.objects.writer import ChunkObjectData
from space_map_data.probes import events


def _chunk(object_ids: list[str]) -> ChunkObjectData:
    """A chunk holding nothing but the named objects' bundles."""
    chunk = ChunkObjectData()
    for oid in object_ids:
        chunk.global_data[oid] = {"id": oid}
    return chunk


@pytest.fixture
def events_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "events"
    root.mkdir()
    monkeypatch.setattr(events, "EVENTS_DIR", root)
    return root


def _write(root: Path, probes: list[dict]) -> None:
    for probe in probes:
        probe.setdefault("status", {"where": "heliocentric", "alive": True})
    (root / "batch.json").write_text(
        json.dumps({"_meta": {"schema_version": "v3"}, "probes": probes})
    )


def test_events_ride_the_probe_bundle(events_root: Path) -> None:
    _write(
        events_root,
        [
            {
                "probe_id": 1234,
                "name": "Test Probe",
                "status": {"where": "heliocentric", "alive": False, "lost": True},
                "events": [
                    {
                        "type": "launch",
                        "date": "1977-08-20T14:29:00Z",
                        "stated": {"launch_site": "Cape Canaveral"},
                    },
                    {
                        "type": "hibernation",
                        "date": "2014-06-01",
                        "end_date": "2015-03-01",
                        "approximate": True,
                    },
                ],
            }
        ],
    )
    chunk = _chunk(["probe-1234"])
    attach_probe_events(chunk)

    block = chunk.global_data["probe-1234"]["events"]
    assert block["status"] == {"where": "heliocentric", "alive": False, "lost": True}
    launch, hibernation = block["items"]
    assert launch["precision"] == "second"
    assert launch["jd"] == pytest.approx(2443376.103472, abs=1e-5)
    assert launch["stated"] == {"launch_site": "Cape Canaveral"}
    assert "end_date" not in launch
    assert "approximate" not in launch
    assert hibernation["end_jd"] == pytest.approx(2457082.5)
    assert hibernation["approximate"] is True
    assert "description" not in launch


@pytest.mark.parametrize(
    ("target", "object_id", "linked"),
    [
        ({"naif": 299, "name": "Venus"}, "naif-299", True),
        # Horizons NAIF for a numbered asteroid, SBDB SPKID on the object row.
        ({"naif": 2025143, "name": "25143 Itokawa"}, "spkid-20025143", True),
        ({"naif": 1000012, "name": "67P"}, "spkid-1000012", True),
        ({"probe_id": 5678, "name": "Sibling"}, "probe-5678", True),
        # A craft nobody registered stays a bare name rather than a dead link.
        ({"name": "MASCOT"}, None, False),
    ],
)
def test_target_links_where_the_object_exists(
    events_root: Path, target: dict, object_id: str | None, linked: bool
) -> None:
    _write(
        events_root,
        [
            {
                "probe_id": 1234,
                "name": "Test Probe",
                "events": [
                    {
                        "type": "flyby",
                        "date": "2005-11-19",
                        "target": target,
                    }
                ],
            }
        ],
    )
    chunk = _chunk(["probe-1234"] + ([object_id] if object_id else []))
    attach_probe_events(chunk)

    ref = chunk.global_data["probe-1234"]["events"]["items"][0]["target"]
    assert ref["name"] == target["name"]
    if object_id is not None and linked:
        prefix, _, value = object_id.partition("-")
        assert (ref["primary_type"], ref["primary_id"]) == (prefix, value)
    else:
        assert "primary_id" not in ref


def test_target_the_export_left_out_is_not_linked(events_root: Path) -> None:
    """A body the export doesn't carry can't be focused, so the name ships alone."""
    _write(
        events_root,
        [
            {
                "probe_id": 1234,
                "name": "Test Probe",
                "events": [
                    {
                        "type": "flyby",
                        "date": "2005-11-19",
                        "target": {"naif": 2025143, "name": "25143 Itokawa"},
                    }
                ],
            }
        ],
    )
    chunk = _chunk(["probe-1234"])
    attach_probe_events(chunk)
    assert (
        "primary_id"
        not in chunk.global_data["probe-1234"]["events"]["items"][0]["target"]
    )


def test_probe_without_a_bundle_is_skipped(events_root: Path) -> None:
    """Most curated craft have no trajectory and so no object of their own."""
    _write(events_root, [{"probe_id": 1234, "name": "Test Probe"}])
    chunk = _chunk(["probe-9999"])
    attach_probe_events(chunk)
    assert "events" not in chunk.global_data["probe-9999"]
