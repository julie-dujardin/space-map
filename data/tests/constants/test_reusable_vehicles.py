"""Tests for per-family reusable-vehicle identity extraction."""

from space_map_data.constants.earth_sats.reusable_vehicles import (
    REUSABLE_VEHICLE_EXTRACTORS,
    REUSABLE_VEHICLE_QIDS,
)


class TestShuttleExtractor:
    """Orbiter parsed from the payload name, linked to its Wikidata entity."""

    def _run(self, name):
        return REUSABLE_VEHICLE_EXTRACTORS["space-shuttle"](None, name)

    def test_orbiter_with_qid(self):
        vehicles = self._run("Discovery (STS-26R)")
        assert len(vehicles) == 1
        assert vehicles[0].id == "Discovery"
        assert vehicles[0].qid == "Q54384"

    def test_all_five_orbiters_have_qids(self):
        for orbiter in ("Columbia", "Challenger", "Discovery", "Atlantis", "Endeavour"):
            v = self._run(f"{orbiter} (STS-1)")[0]
            assert v.qid in REUSABLE_VEHICLE_QIDS, orbiter

    def test_non_orbiter_name_skipped(self):
        assert self._run("Some Payload") == []
        assert self._run(None) == []


class TestFalconExtractor:
    """Core serial parsed from the flight id; no QID (cores lack articles)."""

    def _run(self, flight_id):
        return REUSABLE_VEHICLE_EXTRACTORS["falcon"](flight_id, None)

    def test_core_serial(self):
        v = self._run("001/B1033.1")
        assert [r.id for r in v] == ["B1033"]
        assert v[0].qid is None

    def test_expendable_early_flight_has_no_core(self):
        assert self._run("F001") == []

    def test_multiple_cores_dedup_and_sort(self):
        # A flight id listing several cores yields one entry each, sorted.
        v = self._run("B1052.1 B1053.1 B1052.1")
        assert [r.id for r in v] == ["B1052", "B1053"]
