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
            {
                "probe-1111": {
                    "start_jd": 2450000.0,
                    "end_jd": 2451000.0,
                    "windows": [(2450000.0, 2451000.0)],
                }
            },
        )
        assert global_data["probe-1111"]["coverage"] == {
            "start_jd": 2450000.0,
            "end_jd": 2451000.0,
            "windows": [(2450000.0, 2451000.0)],
        }

    def test_drops_and_warns_when_no_global_entry(self, caplog):
        global_data: dict[str, dict] = {}
        with caplog.at_level(logging.WARNING):
            _inject_probe_coverage(
                global_data,
                {
                    "probe-9999": {
                        "start_jd": 0.0,
                        "end_jd": 1.0,
                        "windows": [(0.0, 1.0)],
                    }
                },
            )
        assert global_data == {}
        assert "probe-9999" in caplog.text


class TestInjectCarriedBy:
    """A passenger's `position_from` becomes a `carried_by` cross-ref."""

    def _coverage(self):
        return {
            "probe-200": {
                "start_jd": 2450000.0,
                "end_jd": 2450500.0,
                "windows": [(2450000.0, 2450500.0)],
                "position_from": {
                    "object_id": "probe-100",
                    "start_jd": 2450000.0,
                    "end_jd": 2450500.0,
                },
            }
        }

    def test_links_to_the_carrier_by_name(self):
        global_data = {
            "probe-100": {"id": "probe-100", "name": "Cassini Orbiter"},
            "probe-200": {"id": "probe-200", "name": "Huygens"},
        }
        _inject_probe_coverage(global_data, self._coverage())
        assert global_data["probe-200"]["carried_by"] == {
            "name": "Cassini Orbiter",
            "primary_type": "object",
            "primary_id": "probe-100",
        }

    def test_carrier_without_a_global_entry_warns_and_drops_the_link(self, caplog):
        global_data = {"probe-200": {"id": "probe-200", "name": "Huygens"}}
        with caplog.at_level(logging.WARNING):
            _inject_probe_coverage(global_data, self._coverage())
        assert "carried_by" not in global_data["probe-200"]
        assert "probe-100" in caplog.text

    def test_a_craft_flying_itself_gets_no_link(self):
        global_data = {"probe-200": {"id": "probe-200", "name": "Huygens"}}
        _inject_probe_coverage(
            global_data,
            {
                "probe-200": {
                    "start_jd": 0.0,
                    "end_jd": 1.0,
                    "windows": [(0.0, 1.0)],
                }
            },
        )
        assert "carried_by" not in global_data["probe-200"]
