"""Tests for the events-driven landing-phase loader."""

import json
from pathlib import Path

import pytest

from space_map_data.constants.providers import ID_TYPES
from space_map_data.export.position.format import ID_TYPE_ORDINAL
from space_map_data.probes import events, landing_events
from space_map_data.probes.events import event_jd
from space_map_data.utils.time import jd_to_et


_NAIF = ID_TYPE_ORDINAL[ID_TYPES.NAIF]
_SPKID = ID_TYPE_ORDINAL[ID_TYPES.SPKID]
_INDEFINITE_END = jd_to_et(3000000.0)  # well past PROBE_EXPORT_END_YEAR

_MOON = {"naif": 301, "name": "Moon"}
_EARTH = {"naif": 399, "name": "Earth"}
_VENUS = {"naif": 299, "name": "Venus"}


def _et(iso: str) -> float:
    return jd_to_et(event_jd(iso))


@pytest.fixture
def events_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the loader at a temp dir so each test owns its event JSONs."""
    root = tmp_path / "events"
    root.mkdir()
    monkeypatch.setattr(events, "EVENTS_DIR", root)
    monkeypatch.setattr(landing_events, "_spk_covered_probe_ids", set)
    return root


def _write(root: Path, name: str, probes: list[dict]) -> None:
    for probe in probes:
        probe.setdefault("status", {"where": "landed", "alive": False})
        probe.setdefault("description", "test probe")
    (root / name).write_text(
        json.dumps({"_meta": {"schema_version": "v3"}, "probes": probes})
    )


def test_apollo_descent_stage_stays_landed_forever(events_root: Path) -> None:
    _write(
        events_root,
        "apollo.json",
        [
            {
                "probe_id": 36904960,
                "name": "Apollo 11 LM Eagle Descent Stage",
                "events": [
                    {
                        "type": "landing",
                        "date": "1969-07-20T20:17:40Z",
                        "description": "Touchdown.",
                        "target": _MOON,
                        "outcome": "controlled",
                        "site": {
                            "lat_deg": 0.67408,
                            "lon_deg": 23.47297,
                            "name": "Tranquility Base",
                        },
                    },
                    {
                        "type": "observation",
                        "date": "1969-07-21",
                        "description": "Surface science.",
                    },
                ],
            }
        ],
    )
    phases = landing_events.load_phases(_INDEFINITE_END)
    assert len(phases) == 1
    p = phases[0]
    assert p.probe_id == 36904960
    assert p.body_id_type == _NAIF
    assert p.body_id_value == 301
    assert p.lat_deg == pytest.approx(0.67408)
    assert p.lng_deg == pytest.approx(23.47297)
    assert p.start_et == pytest.approx(_et("1969-07-20T20:17:40Z"))
    assert p.end_et == _INDEFINITE_END
    assert p.site_name == "Tranquility Base"


def test_two_landings_emit_two_phases(events_root: Path) -> None:
    """Two touchdowns on one body emit two phases, each bounded by the next
    departure-type event."""
    itokawa = {"naif": 2025143, "name": "25143 Itokawa"}  # Horizons NAIF
    _write(
        events_root,
        "asteroids.json",
        [
            {
                "probe_id": 87474176,
                "name": "Hayabusa",
                "events": [
                    {
                        "type": "landing",
                        "date": "2005-11-19T21:30:00Z",
                        "description": "First touchdown.",
                        "target": itokawa,
                        "outcome": "controlled",
                        "site": {"lat_deg": 3.0, "lon_deg": 4.0},
                    },
                    {
                        "type": "landing",
                        "date": "2005-11-25T22:07:00Z",
                        "description": "Second touchdown.",
                        "target": itokawa,
                        "outcome": "controlled",
                        "site": {"lat_deg": 3.0, "lon_deg": 4.0},
                    },
                    {
                        "type": "orbit_departure",
                        "date": "2007-04-25",
                        "description": "Left Itokawa.",
                    },
                    {
                        "type": "mission_end",
                        "date": "2010-06-13T13:57:00Z",
                        "description": "Burned up over Australia.",
                    },
                ],
            }
        ],
    )
    phases = landing_events.load_phases(_INDEFINITE_END)
    assert len(phases) == 2
    a, b = phases
    # Itokawa: Horizons NAIF 2025143 → SBDB SPKID 20025143
    assert (a.body_id_type, a.body_id_value) == (_SPKID, 20025143)
    assert (b.body_id_type, b.body_id_value) == (_SPKID, 20025143)
    # First phase ends where the second begins (next departure-type event).
    assert a.end_et == pytest.approx(_et("2005-11-25T22:07:00Z"))
    # Ends at orbit_departure, not mission_end: dying on the surface keeps a
    # probe pinned.
    assert b.end_et == pytest.approx(_et("2007-04-25"))


def test_landing_end_date_wins(events_root: Path) -> None:
    """An `end_date` on the landing itself wins over next-departure scanning."""
    _write(
        events_root,
        "venus.json",
        [
            {
                "probe_id": 50446339,
                "name": "Pioneer Venus Day Probe",
                "events": [
                    {
                        "type": "landing",
                        "date": "1978-12-09T19:47:59Z",
                        "end_date": "1978-12-09T20:55:36Z",
                        "description": "Survived on the surface for an hour.",
                        "target": _VENUS,
                        "outcome": "controlled",
                        "site": {"lat_deg": -31.3, "lon_deg": -43.0},
                    },
                    {
                        "type": "mission_end",
                        "date": "1978-12-09T20:55:36Z",
                        "description": "Signal lost.",
                    },
                ],
            }
        ],
    )
    phases = landing_events.load_phases(_INDEFINITE_END)
    assert len(phases) == 1
    assert phases[0].start_et == pytest.approx(_et("1978-12-09T19:47:59Z"))
    assert phases[0].end_et == pytest.approx(_et("1978-12-09T20:55:36Z"))


def test_landing_without_site_is_skipped(events_root: Path) -> None:
    """An impact whose place was never established pins nothing."""
    _write(
        events_root,
        "lunar.json",
        [
            {
                "probe_id": 99999000,
                "name": "Lunar Orbiter 4",
                "events": [
                    {
                        "type": "landing",
                        "date": "1967-10-31",
                        "description": "Decayed onto the Moon at an unknown place.",
                        "target": _MOON,
                        "outcome": "destroyed_at_landing",
                    }
                ],
            }
        ],
    )
    assert landing_events.load_phases(_INDEFINITE_END) == []


def test_reentry_site_pins_a_failed_probe_to_earth(events_root: Path) -> None:
    """A craft that never left Earth orbit comes down at a `reentry` site
    rather than a `landing` one (Mars 96, Fobos-Grunt, Yinghuo-1)."""
    _write(
        events_root,
        "mars.json",
        [
            {
                "probe_id": 77787136,
                "name": "Mars 96",
                "events": [
                    {"type": "launch", "date": "1996-11-16T20:48:53Z"},
                    {
                        "type": "reentry",
                        "date": "1996-11-17T01:00:00Z",
                        "target": {"naif": 399, "name": "Earth"},
                        "site": {
                            "lat_deg": -20.0,
                            "lon_deg": -75.0,
                            "name": "Pacific Ocean / Atacama region",
                        },
                    },
                ],
            }
        ],
    )
    phases = landing_events.load_phases(_INDEFINITE_END)
    assert len(phases) == 1
    assert phases[0].body_id_value == 399
    assert phases[0].lat_deg == pytest.approx(-20.0)
    assert phases[0].site_name == "Pacific Ocean / Atacama region"


def test_earth_landing_is_capped_to_a_month(events_root: Path) -> None:
    """Sample-return capsules would otherwise clutter Earth forever."""
    _write(
        events_root,
        "sample-return.json",
        [
            {
                "probe_id": 113000000,
                "name": "OSIRIS-REx SRC",
                "events": [
                    {
                        "type": "landing",
                        "date": "2023-09-24T14:52Z",
                        "description": "Touchdown in Utah.",
                        "target": _EARTH,
                        "outcome": "controlled",
                        "site": {
                            "lat_deg": 40.4,
                            "lon_deg": -113.0,
                            "name": "Utah Test and Training Range",
                        },
                    }
                ],
            }
        ],
    )
    phases = landing_events.load_phases(_INDEFINITE_END)
    assert len(phases) == 1
    assert (phases[0].body_id_type, phases[0].body_id_value) == (_NAIF, 399)
    assert phases[0].end_et == pytest.approx(
        phases[0].start_et + landing_events._EARTH_LANDING_MAX_S
    )


def test_short_earth_landing_keeps_real_end(events_root: Path) -> None:
    """The one-month cap only truncates long phases, never extends short ones."""
    _write(
        events_root,
        "capsule.json",
        [
            {
                "probe_id": 113000001,
                "name": "Short-lived Earth capsule",
                "events": [
                    {
                        "type": "landing",
                        "date": "2023-09-24T14:52:00Z",
                        "end_date": "2023-09-24T16:00:00Z",
                        "description": "Recovered the same afternoon.",
                        "target": _EARTH,
                        "outcome": "controlled",
                        "site": {"lat_deg": 0.0, "lon_deg": 0.0},
                    },
                ],
            }
        ],
    )
    phases = landing_events.load_phases(_INDEFINITE_END)
    assert len(phases) == 1
    assert phases[0].end_et == pytest.approx(_et("2023-09-24T16:00:00Z"))


def test_comet_naif_keeps_value_changes_id_type(events_root: Path) -> None:
    """Comets share the 1_000_000+i scheme between Horizons and SBDB; only
    id_type changes."""
    _write(
        events_root,
        "comet.json",
        [
            {
                "probe_id": 95001000,
                "name": "Philae",
                "events": [
                    {
                        "type": "landing",
                        "date": "2014-11-12T17:31:17Z",
                        "description": "Came to rest at Abydos.",
                        "target": {"naif": 1000012, "name": "67P"},
                        "outcome": "controlled",
                        "site": {"lat_deg": 10.0, "lon_deg": 20.0},
                    }
                ],
            }
        ],
    )
    phases = landing_events.load_phases(_INDEFINITE_END)
    assert len(phases) == 1
    assert (phases[0].body_id_type, phases[0].body_id_value) == (_SPKID, 1000012)


def test_lower_precision_followup_is_skipped(events_root: Path) -> None:
    """A date-only follow-up resolves to 00:00, earlier than the landing
    timestamp, so it must not be picked as phase-end."""
    _write(
        events_root,
        "sample-return.json",
        [
            {
                "probe_id": 115000000,
                "name": "Chang'e 6 returner module",
                "events": [
                    {
                        "type": "landing",
                        "date": "2024-06-25T06:07:00Z",
                        "description": "Touchdown in Siziwang Banner.",
                        "target": _EARTH,
                        "outcome": "controlled",
                        "site": {"lat_deg": 41.6, "lon_deg": 111.7},
                    },
                    {
                        "type": "sample_return",
                        "date": "2024-06-25",
                        "description": "Samples handed to the curation lab.",
                    },
                ],
            }
        ],
    )
    phases = landing_events.load_phases(_INDEFINITE_END)
    assert len(phases) == 1
    # Falls through to the one-month Earth cap, not _INDEFINITE_END.
    assert phases[0].end_et == pytest.approx(
        phases[0].start_et + landing_events._EARTH_LANDING_MAX_S
    )


def test_spk_covered_probe_is_skipped(
    events_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A craft a SPICE kernel already flies is left to the SPICE pipeline, so
    it isn't rendered twice."""
    monkeypatch.setattr(landing_events, "_spk_covered_probe_ids", lambda: {46006272})
    _write(
        events_root,
        "mars.json",
        [
            {
                "probe_id": 46006272,
                "name": "Viking 1 Lander",
                "events": [
                    {
                        "type": "landing",
                        "date": "1976-07-20T11:53:06Z",
                        "description": "Touchdown in Chryse Planitia.",
                        "target": {"naif": 499, "name": "Mars"},
                        "outcome": "controlled",
                        "site": {"lat_deg": 22.697, "lon_deg": -48.222},
                    }
                ],
            }
        ],
    )
    assert landing_events.load_phases(_INDEFINITE_END) == []
