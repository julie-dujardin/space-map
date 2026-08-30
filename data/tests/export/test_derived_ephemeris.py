"""Crediting and qualifying a trajectory we derived rather than downloaded.

A catalogue-derived arc must reach the frontend as its own archive with its own
accuracy, or it renders as a NAIF reconstruction and claims a precision nothing
supports.
"""

import json

import pytest

from space_map_data.export import ephemeris
from space_map_data.probes import probe_id
from space_map_data.export.ephemeris import (
    ARCHIVE_GCAT_DEEP,
    ARCHIVE_NAIF,
    EPHEMERIS_ARCHIVES,
    load_probe_ephemeris_accuracy,
    load_probe_kernel_sources,
)
from space_map_data.probes.propagation import AU_KM

NAIF = -90000123
PROBE_ID = 22904832


def _registry(sources):
    return [
        {
            "probe_id": PROBE_ID,
            "name": "Venera 2",
            "naif_id": NAIF,
            "inception_mjd": 39000,
            "dedupe": 0,
            "kernel_sources": sources,
        }
    ]


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A missions tree holding one derived kernel, plus a registry to join."""
    missions = tmp_path / "missions"
    derived = missions / "GCAT-DEEP"
    derived.mkdir(parents=True)
    (derived / "_index.json").write_text(
        json.dumps(
            {
                "server": "GCAT-DEEP",
                "files": [
                    {
                        "name": f"{NAIF}-extrap.bsp",
                        "targets": [NAIF],
                        "deepcat": {
                            "arc_hash": "abc",
                            "arcs": 2,
                            "median_error_au": 0.094,
                        },
                    }
                ],
                "targets": {str(NAIF): [f"{NAIF}-extrap.bsp"]},
            }
        )
    )
    registry_path = tmp_path / "probe_ids.json"
    monkeypatch.setattr(ephemeris, "MISSIONS_DIR", missions)
    monkeypatch.setattr(ephemeris, "LANDED_MISSIONS_DIR", tmp_path / "landed")
    monkeypatch.setattr(probe_id, "REGISTRY_PATH", registry_path)
    return registry_path


class TestAccuracy:
    """The stated error follows the probe, in kilometres."""

    def test_a_derived_probe_carries_its_measured_error(self, tree):
        tree.write_text(
            json.dumps(
                _registry(
                    [
                        {"mission": "EVENTS-DB", "naif_id": NAIF},
                        {"mission": "GCAT-DEEP", "naif_id": NAIF},
                    ]
                )
            )
        )
        accuracy = load_probe_ephemeris_accuracy()
        assert accuracy[PROBE_ID] == pytest.approx(0.094 * AU_KM)

    def test_a_tracked_probe_states_no_error_at_all(self, tree):
        tree.write_text(json.dumps(_registry([{"mission": "MGN", "naif_id": NAIF}])))
        assert load_probe_ephemeris_accuracy() == {}

    def test_an_absent_registry_is_not_an_error(self, tree):
        assert load_probe_ephemeris_accuracy() == {}


class TestCredit:
    """Which archive gets named."""

    def test_a_derived_trajectory_credits_the_catalogue(self, tree):
        tree.write_text(
            json.dumps(
                _registry(
                    [
                        {"mission": "EVENTS-DB", "naif_id": NAIF},
                        {"mission": "GCAT-DEEP", "naif_id": NAIF},
                    ]
                )
            )
        )
        assert load_probe_kernel_sources()[PROBE_ID] == ARCHIVE_GCAT_DEEP

    def test_a_probe_with_no_archived_source_is_left_uncredited(self, tree):
        tree.write_text(
            json.dumps(_registry([{"mission": "EVENTS-DB", "naif_id": NAIF}]))
        )
        assert load_probe_kernel_sources()[PROBE_ID] is None


def test_every_archive_id_is_shipped_for_the_frontend_to_label():
    ids = {a["id"] for a in EPHEMERIS_ARCHIVES}
    assert {ARCHIVE_GCAT_DEEP, ARCHIVE_NAIF} <= ids
    assert all(a["source"].startswith("https://") for a in EPHEMERIS_ARCHIVES)
