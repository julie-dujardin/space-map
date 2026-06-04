"""Tests for the events-driven landing-phase loader."""

import json
from pathlib import Path

import pytest

from space_map_data.constants.providers import ID_TYPES
from space_map_data.export.position.format import ID_TYPE_ORDINAL
from space_map_data.probes import landing_events
from space_map_data.utils.time import jd_to_et


_NAIF = ID_TYPE_ORDINAL[ID_TYPES.NAIF]
_SPKID = ID_TYPE_ORDINAL[ID_TYPES.SPKID]
_INDEFINITE_END = jd_to_et(3000000.0)  # well past PROBE_EXPORT_END_YEAR


def _et(iso: str) -> float:
    return jd_to_et(landing_events._parse_iso_to_jd(iso))


@pytest.fixture
def events_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the loader at a temp dir so each test owns its event JSONs."""
    root = tmp_path / "events"
    root.mkdir()
    monkeypatch.setattr(landing_events, "EVENTS_DIR", root)
    return root


def _write(root: Path, name: str, probes: list[dict]) -> None:
    (root / name).write_text(json.dumps({"probes": probes}))


def test_apollo_descent_stage_stays_landed_forever(events_root: Path) -> None:
    _write(
        events_root,
        "apollo.json",
        [
            {
                "probe_id": 36904960,
                "name": "Apollo 11 LM Eagle Descent Stage",
                "mission_type": "lunar_module_descent",
                "events": [
                    {
                        "type": "landing",
                        "date": "1969-07-20T20:17:40Z",
                        "metadata": {
                            "landing_coordinates": {
                                "latitude": 0.67408,
                                "longitude": 23.47297,
                            },
                            "landing_site_name": "Tranquility Base",
                        },
                    },
                    {"type": "observation", "date": "1969-07-21"},
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
    assert p.start_et == pytest.approx(_et("1969-07-20T20:17:40"))
    assert p.end_et == _INDEFINITE_END
    assert p.site_name == "Tranquility Base"


def test_hayabusa_two_touchdowns_emit_two_phases_on_itokawa_spkid(
    events_root: Path,
) -> None:
    _write(
        events_root,
        "asteroids.json",
        [
            {
                "probe_id": 87474176,
                "name": "Hayabusa",
                "mission_type": "asteroid_orbiter",
                "events": [
                    {
                        "type": "touchdown",
                        "date": "2005-11-19T21:30:00Z",
                        "metadata": {
                            "target_body_naif": 2025143,
                            "landing_coordinates": {
                                "latitude": 1.0,
                                "longitude": 2.0,
                            },
                        },
                    },
                    {
                        "type": "touchdown",
                        "date": "2005-11-25T22:07:00Z",
                        "metadata": {
                            "target_body_naif": 2025143,
                            "landing_coordinates": {
                                "latitude": 3.0,
                                "longitude": 4.0,
                            },
                        },
                    },
                    {"type": "orbit_departure", "date": "2007-04-25"},
                    {"type": "mission_end", "date": "2010-06-13T13:57:00Z"},
                ],
            }
        ],
    )
    phases = landing_events.load_phases(_INDEFINITE_END)
    assert len(phases) == 2
    a, b = phases
    # Itokawa: Horizons NAIF 2025143 → SBDB SPKID 20025143
    assert a.body_id_type == _SPKID
    assert a.body_id_value == 20025143
    assert b.body_id_type == _SPKID
    assert b.body_id_value == 20025143
    # First phase ends where the second begins (next departure-type event).
    assert a.end_et == pytest.approx(_et("2005-11-25T22:07:00"))
    # Second phase ends at orbit_departure, NOT mission_end (mission_end is
    # excluded from departure types because dying-on-surface keeps the probe
    # pinned — but here orbit_departure precedes it).
    assert b.end_et == pytest.approx(_et("2007-04-25"))


def test_pioneer_venus_uses_end_date(events_root: Path) -> None:
    """`end_date` on the landing event itself wins over next-departure
    scanning — Pioneer Venus day-probe transmitted 67 minutes from the
    surface before dying; end_date is set on the touchdown directly."""
    _write(
        events_root,
        "venus.json",
        [
            {
                "probe_id": 50446339,
                "name": "Pioneer Venus Day Probe",
                "mission_type": "venus_atmospheric_probe",
                "events": [
                    {
                        "type": "touchdown",
                        "date": "1978-12-09T19:47:59Z",
                        "end_date": "1978-12-09T20:55:36Z",
                        "metadata": {
                            "touchdown_coordinates": {
                                "latitude": -31.3,
                                "longitude": 317.0,
                            }
                        },
                    },
                    {"type": "mission_end", "date": "1978-12-09T20:55:36Z"},
                ],
            }
        ],
    )
    phases = landing_events.load_phases(_INDEFINITE_END)
    assert len(phases) == 1
    p = phases[0]
    assert p.start_et == pytest.approx(_et("1978-12-09T19:47:59"))
    assert p.end_et == pytest.approx(_et("1978-12-09T20:55:36"))


def test_missing_coords_is_skipped(events_root: Path) -> None:
    _write(
        events_root,
        "lunar.json",
        [
            {
                "probe_id": 99999000,
                "name": "Chang'e 3",
                "mission_type": "lunar_lander",
                "events": [
                    {
                        "type": "landing",
                        "date": "2013-12-14T13:11Z",
                        "metadata": {},
                    }
                ],
            }
        ],
    )
    assert landing_events.load_phases(_INDEFINITE_END) == []


def test_unresolvable_body_is_skipped(events_root: Path) -> None:
    """Comet landing with `target_body_name` but no `target_body_naif` and an
    unmapped `mission_type` cannot be resolved without a DB lookup; skip + log
    rather than guess."""
    _write(
        events_root,
        "asteroids.json",
        [
            {
                "probe_id": 95000000,
                "name": "Philae",
                "mission_type": "comet_lander",
                "events": [
                    {
                        "type": "landing",
                        "date": "2014-11-12T17:31:17Z",
                        "metadata": {
                            "target_body_name": "67P/Churyumov-Gerasimenko",
                            "landing_coordinates": {
                                "latitude": 12.7,
                                "longitude": -45.0,
                            },
                        },
                    }
                ],
            }
        ],
    )
    assert landing_events.load_phases(_INDEFINITE_END) == []


def test_sample_return_capsule_lands_on_earth(events_root: Path) -> None:
    """`asteroid_sample_return_capsule` with no `target_body_naif` is mapped
    to Earth via the mission_type table (OSIRIS-REx SRC, Hayabusa SRC, …)."""
    _write(
        events_root,
        "sample-return.json",
        [
            {
                "probe_id": 113000000,
                "name": "OSIRIS-REx SRC",
                "mission_type": "asteroid_sample_return_capsule",
                "events": [
                    {
                        "type": "landing",
                        "date": "2023-09-24T14:52Z",
                        "metadata": {
                            "landing_coordinates": {
                                "latitude": 40.4,
                                "longitude": -113.0,
                            },
                            "landing_site_name": "Utah Test and Training Range",
                        },
                    }
                ],
            }
        ],
    )
    phases = landing_events.load_phases(_INDEFINITE_END)
    assert len(phases) == 1
    assert phases[0].body_id_type == _NAIF
    assert phases[0].body_id_value == 399


def test_comet_naif_keeps_value_changes_id_type(events_root: Path) -> None:
    """Comets share the 1_000_000+i scheme between Horizons and SBDB; only
    the id_type byte changes (DB row keyed `spkid-N`)."""
    _write(
        events_root,
        "comet.json",
        [
            {
                "probe_id": 95001000,
                "name": "Imagined Comet Lander",
                "mission_type": "comet_lander",
                "events": [
                    {
                        "type": "landing",
                        "date": "2020-01-01T00:00:00Z",
                        "metadata": {
                            "target_body_naif": 1000012,
                            "landing_coordinates": {
                                "latitude": 10.0,
                                "longitude": 20.0,
                            },
                        },
                    }
                ],
            }
        ],
    )
    phases = landing_events.load_phases(_INDEFINITE_END)
    assert len(phases) == 1
    assert phases[0].body_id_type == _SPKID
    assert phases[0].body_id_value == 1000012


def test_alt_coord_key_lat_deg_lon_deg(events_root: Path) -> None:
    """Some events files (mars.json) use `lat_deg/lon_deg` instead of
    `latitude/longitude`. Both shapes must parse."""
    _write(
        events_root,
        "mars.json",
        [
            {
                "probe_id": 70000000,
                "name": "Spirit (MER-A)",
                "mission_type": "mars_rover",
                "events": [
                    {
                        "type": "landing",
                        "date": "2004-01-04T04:35:00Z",
                        "metadata": {
                            "landing_coordinates": {
                                "lat_deg": -14.5718,
                                "lon_deg": 175.4785,
                            },
                            "target_body_naif": 499,
                        },
                    }
                ],
            }
        ],
    )
    phases = landing_events.load_phases(_INDEFINITE_END)
    assert len(phases) == 1
    assert phases[0].lat_deg == pytest.approx(-14.5718)
    assert phases[0].lng_deg == pytest.approx(175.4785)
    assert phases[0].body_id_value == 499


def test_simultaneous_landing_touchdown_pair_is_treated_as_one_phase(
    events_root: Path,
) -> None:
    """Vega 1 Venus Lander has both `landing` and `touchdown` recorded at the
    same UTC instant; the second must not be picked as a departure marker,
    otherwise end_et collapses to start_et and the phase is dropped."""
    _write(
        events_root,
        "soviet.json",
        [
            {
                "probe_id": 65000000,
                "name": "Vega 1 Venus Lander",
                "mission_type": "venus_lander",
                "events": [
                    {
                        "type": "landing",
                        "date": "1985-06-11T03:02:54Z",
                        "metadata": {
                            "landing_coordinates": {
                                "latitude": 8.5,
                                "longitude": 176.7,
                            }
                        },
                    },
                    {
                        "type": "touchdown",
                        "date": "1985-06-11T03:02:54Z",
                    },
                ],
            }
        ],
    )
    phases = landing_events.load_phases(_INDEFINITE_END)
    assert len(phases) == 1
    assert phases[0].end_et == _INDEFINITE_END


def test_lower_precision_followup_is_skipped(events_root: Path) -> None:
    """Chang'e 6 returner has `landing` with a full timestamp followed by
    `sample_return` recorded only as a date — the date-only event resolves
    to 00:00 (earlier than landing), so it must not be picked as phase-end."""
    _write(
        events_root,
        "sample-return.json",
        [
            {
                "probe_id": 115000000,
                "name": "Chang'e 6 returner module",
                "mission_type": "lunar_sample_return_capsule",
                "events": [
                    {
                        "type": "landing",
                        "date": "2024-06-25T06:07:00Z",
                        "metadata": {
                            "landing_coordinates": {
                                "latitude": 41.6,
                                "longitude": 111.7,
                            }
                        },
                    },
                    {"type": "sample_return", "date": "2024-06-25"},
                ],
            }
        ],
    )
    phases = landing_events.load_phases(_INDEFINITE_END)
    assert len(phases) == 1
    assert phases[0].end_et == _INDEFINITE_END


def test_parse_iso_handles_partial_dates() -> None:
    """Loader must accept YYYY / YYYY-MM / YYYY-MM-DD / full timestamps."""
    assert landing_events._parse_iso_to_jd("2024") == pytest.approx(
        landing_events._parse_iso_to_jd("2024-01-01T00:00:00")
    )
    assert landing_events._parse_iso_to_jd("2024-07") == pytest.approx(
        landing_events._parse_iso_to_jd("2024-07-01T00:00:00")
    )
    # Trailing Z is stripped, microseconds ok.
    a = landing_events._parse_iso_to_jd("2024-07-15T12:00:00Z")
    b = landing_events._parse_iso_to_jd("2024-07-15T12:00:00")
    assert a == b
