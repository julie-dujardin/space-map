"""Kernels we synthesise attach to the probe they were written for.

A synthesised kernel borrows the NAIF of an entry that already exists, so
without this it would register as a second probe and split one spacecraft into
two objects — one carrying the events, the other the trajectory.
"""

import json

import pytest

from space_map_data.probes import probe_id as probe_id_module
from space_map_data.probes.probe_id import assign, index_by_source


def _entry(probe_id, naif, mission="EVENTS-DB", name="Venera 2"):
    return {
        "probe_id": probe_id,
        "name": name,
        "naif_id": naif,
        "inception_mjd": 39000,
        "dedupe": 0,
        "wikidata_qid": None,
        "cospar_id": None,
        "norad_cat_id": None,
        "kernel_sources": [{"mission": mission, "naif_id": naif}],
    }


class TestSyntheticAttachment:
    """`GCAT-DEEP` and `EVENTS-STATE` join an entry rather than making one."""

    def test_a_synthesised_kernel_joins_the_probe_that_owns_its_naif(self):
        registry = [_entry(22904832, -90000123)]
        record = assign(
            "GCAT-DEEP", -90000123, 39000, registry, index_by_source(registry)
        )
        assert record.probe_id == 22904832
        assert len(registry) == 1
        assert registry[0]["kernel_sources"][-1] == {
            "mission": "GCAT-DEEP",
            "naif_id": -90000123,
        }

    def test_the_curated_state_synthesiser_attaches_the_same_way(self):
        registry = [_entry(22904832, -90000123)]
        record = assign(
            "EVENTS-STATE", -90000123, 39000, registry, index_by_source(registry)
        )
        assert record.probe_id == 22904832
        assert len(registry) == 1

    def test_attaching_twice_is_not_a_second_source(self):
        registry = [_entry(22904832, -90000123)]
        index = index_by_source(registry)
        first = assign("GCAT-DEEP", -90000123, 39000, registry, index)
        second = assign("GCAT-DEEP", -90000123, 39000, registry, index)
        assert first.probe_id == second.probe_id
        assert len(registry[0]["kernel_sources"]) == 2

    def test_a_recycled_naif_is_left_alone(self):
        # -66 is Vega 1 and MarCO-B; grafting a trajectory onto whichever came
        # first would be worse than registering nothing.
        registry = [_entry(1, -66, name="Vega 1"), _entry(2, -66, name="MarCO-B")]
        registry[1]["dedupe"] = 1
        record = assign("GCAT-DEEP", -66, 39000, registry, index_by_source(registry))
        assert record.probe_id not in (1, 2)
        assert all(len(e["kernel_sources"]) == 1 for e in registry[:2])

    def test_an_unknown_naif_still_registers_a_new_probe(self):
        registry = [_entry(22904832, -90000123)]
        record = assign(
            "GCAT-DEEP", -90000999, 39000, registry, index_by_source(registry)
        )
        assert record.probe_id != 22904832
        assert len(registry) == 2

    def test_a_mirrored_archive_never_attaches_to_someone_else(self):
        # Only folders we write ourselves borrow a NAIF; a real mission folder
        # carrying a recycled id must stay its own probe.
        registry = [_entry(22904832, -18)]
        record = assign("MGN", -18, 39000, registry, index_by_source(registry))
        assert record.probe_id != 22904832
        assert len(registry) == 2


class TestStandaloneModeSaves:
    """With no registry passed in, `assign` owns the file."""

    @pytest.fixture
    def registry_file(self, tmp_path, monkeypatch):
        path = tmp_path / "probe_ids.json"
        path.write_text(json.dumps([_entry(22904832, -90000123)]))
        monkeypatch.setattr(probe_id_module, "REGISTRY_PATH", path)
        return path

    def test_the_attachment_is_written_back(self, registry_file):
        assign("GCAT-DEEP", -90000123, 39000)
        entries = json.loads(registry_file.read_text())
        assert len(entries) == 1
        assert [s["mission"] for s in entries[0]["kernel_sources"]] == [
            "EVENTS-DB",
            "GCAT-DEEP",
        ]
