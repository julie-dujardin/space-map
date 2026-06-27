"""`_inject_probe_coverage` stamps `coverage` onto each probe's global bundle
entry. Pins the key match and the missing-entry warning."""

import logging


from space_map_data.export.pipeline.orchestrator import _inject_probe_coverage


class TestInjectProbeCoverage:
    """Coverage lands on the matching global entry; unknown ids are dropped."""

    def test_stamps_coverage_on_matching_entry(self):
        global_data = {"probe-1111": {"id": "probe-1111", "type": "spacecraft"}}
        _inject_probe_coverage(
            global_data,
            {"probe-1111": {"start_jd": 2450000.0, "end_jd": 2451000.0}},
        )
        assert global_data["probe-1111"]["coverage"] == {
            "start_jd": 2450000.0,
            "end_jd": 2451000.0,
        }

    def test_drops_and_warns_when_no_global_entry(self, caplog):
        global_data: dict[str, dict] = {}
        with caplog.at_level(logging.WARNING):
            _inject_probe_coverage(
                global_data, {"probe-9999": {"start_jd": 0.0, "end_jd": 1.0}}
            )
        assert global_data == {}
        assert "probe-9999" in caplog.text
