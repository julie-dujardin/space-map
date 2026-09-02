"""The manifest decides what a probe is; a kernel on disk does not.

Horizons publishes an ephemeris for Mir as readily as for Voyager, so the
kernel tree cannot be the test. Only spacecraft the curated records name get
a probe row; the rest fall through to the catalogue of whatever they orbit.
"""

from unittest.mock import patch

import pytest

from space_map_data.ingest.providers.objects import probes
from space_map_data.probes.probe_id import ProbeIdRecord


def _pair(mission: str, naif_id: int, probe_id: int, name: str | None = None):
    """One `(record, assignment)` pair as `run()` builds them."""
    record = {
        "mission": mission,
        "naif_id": naif_id,
        "inception_mjd": 50000,
        "name_hint": None,
        "cospar_hint": None,
    }
    rec = ProbeIdRecord(
        probe_id=probe_id,
        naif_id=naif_id,
        inception_mjd=50000,
        dedupe=0,
        kernel_sources=((mission, naif_id),),
        name=name,
    )
    return record, rec


@pytest.fixture
def mir():
    return _pair("HORIZONS-SYNTH", -116609, 61722624, "Mir")


class TestManifested:
    """Which kernel-bearing spacecraft survive into probe rows."""

    def test_manifested_probe_is_kept(self):
        pair = _pair("VOYAGER", -32, 11, "Voyager 2")
        with patch.object(probes, "manifest_probe_ids", return_value=frozenset({11})):
            assert probes._manifested([pair]) == [pair]

    def test_unmanifested_earth_satellite_is_dropped(self, mir):
        with patch.object(probes, "manifest_probe_ids", return_value=frozenset()):
            assert probes._manifested([mir]) == []

    def test_a_kernel_folder_of_its_own_does_not_vouch_for_a_spacecraft(self):
        # An agency mission dir means an archive published a trajectory, not
        # that we call the thing flying it a probe.
        pair = _pair("GOES", -108366, 7, "GOES-1")
        with patch.object(probes, "manifest_probe_ids", return_value=frozenset({11})):
            assert probes._manifested([pair]) == []

    def test_a_named_drop_is_counted_not_listed(self, mir, caplog):
        with patch.object(probes, "manifest_probe_ids", return_value=frozenset()):
            with caplog.at_level("INFO"):
                probes._manifested([mir])
        levels = {r.levelname for r in caplog.records}
        assert levels == {"INFO"}
        assert "1 spacecraft carry kernels but no manifest record" in caplog.text

    def test_an_identity_less_entry_warns_that_its_kernels_go_unused(self, caplog):
        # `MGN/-18`: an agency folder whose registry row nobody ever curated,
        # so Magellan's own entry never claims these kernels.
        pair = _pair("MGN", -18, 71430144)
        with patch.object(probes, "manifest_probe_ids", return_value=frozenset()):
            with caplog.at_level("INFO"):
                probes._manifested([pair])
        assert "MGN/-18" in caplog.text
        assert "WARNING" in {r.levelname for r in caplog.records}
