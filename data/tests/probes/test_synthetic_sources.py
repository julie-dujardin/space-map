"""Kernels we synthesise attach to the probe they were written for.

A synthesised kernel borrows the NAIF of an entry that already exists, so
without this it would register as a second probe and split one spacecraft into
two objects — one carrying the events, the other the trajectory.
"""

import json

import pytest

from space_map_data.probes import probe_id as probe_id_module
from space_map_data.probes.probe_id import (
    assign,
    has_archive_trajectory,
    index_by_source,
)


def _entry(probe_id, naif, mission="EVENTS-DB", name="Venera 2", cospar=None):
    return {
        "probe_id": probe_id,
        "name": name,
        "naif_id": naif,
        "inception_mjd": 39000,
        "dedupe": 0,
        "wikidata_qid": None,
        "cospar_id": cospar,
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


class TestCosparAttachment:
    """A real kernel reaches an events-only probe through its COSPAR.

    That probe's `naif_id` is a synthetic one no kernel is indexed under, so a
    NAIF match cannot find it and the kernel would register a second probe for
    the same spacecraft — DSCOVR carried its L1 trajectory on one page and its
    mission on another for exactly this reason.
    """

    def test_a_kernel_joins_the_events_probe_sharing_its_cospar(self):
        registry = [_entry(105070592, -90000220, name="DSCOVR", cospar="2015-007A")]
        record = assign(
            "HORIZONS-SYNTH",
            -78,
            39000,
            registry,
            index_by_source(registry),
            cospar="2015-007A",
        )
        assert record.probe_id == 105070592
        assert len(registry) == 1

    def test_the_entry_adopts_the_naif_that_indexes_a_kernel(self):
        registry = [_entry(105070592, -90000220, name="DSCOVR", cospar="2015-007A")]
        assign(
            "HORIZONS-SYNTH",
            -78,
            39000,
            registry,
            index_by_source(registry),
            cospar="2015-007A",
        )
        assert registry[0]["naif_id"] == -78
        # `_collect_probes` buckets on the first source, so the one naming a
        # real kernel has to lead — the events source indexes nothing.
        assert registry[0]["kernel_sources"][0] == {
            "mission": "HORIZONS-SYNTH",
            "naif_id": -78,
        }

    def test_a_probe_with_its_own_kernels_keeps_its_naif(self):
        registry = [
            _entry(1, -82, mission="CASSINI", name="Cassini", cospar="1997-061A")
        ]
        assign(
            "HORIZONS-SYNTH",
            -1000,
            39000,
            registry,
            index_by_source(registry),
            cospar="1997-061A",
        )
        assert registry[0]["naif_id"] == -82
        assert registry[0]["kernel_sources"][0]["mission"] == "CASSINI"

    def test_a_cospar_two_probes_share_is_left_alone(self):
        # A joint launch puts several craft under one designator; picking one
        # would graft the trajectory onto whichever sorted first.
        registry = [
            _entry(1, -90000001, name="Chang'e 5 Lander", cospar="2020-087A"),
            _entry(2, -90000002, name="Chang'e 5 Orbiter", cospar="2020-087A"),
        ]
        record = assign(
            "HORIZONS-SYNTH",
            -155,
            39000,
            registry,
            index_by_source(registry),
            cospar="2020-087A",
        )
        assert record.probe_id not in (1, 2)
        assert all(len(e["kernel_sources"]) == 1 for e in registry[:2])

    def test_no_cospar_still_registers_a_new_probe(self):
        registry = [_entry(105070592, -90000220, name="DSCOVR", cospar="2015-007A")]
        record = assign(
            "HORIZONS-SYNTH", -78, 39000, registry, index_by_source(registry)
        )
        assert record.probe_id != 105070592
        assert len(registry) == 2


class TestArchiveTrajectoryCheck:
    """Which probes are left alone.

    The check is asked of the registry entry, not of a NAIF: Stardust is
    registered as -90000165 by the events database and tracked as -29 by
    Horizons, so a NAIF-level test misses that it already has a trajectory and
    drops a derived conic on top of a real one.
    """

    def test_a_probe_with_no_kernels_is_solved(self):
        entry = {"kernel_sources": [{"mission": "EVENTS-DB", "naif_id": -90000123}]}
        assert not has_archive_trajectory(entry)

    def test_a_probe_tracked_under_another_naif_is_left_alone(self):
        entry = {
            "naif_id": -90000165,
            "kernel_sources": [
                {"mission": "EVENTS-DB", "naif_id": -90000165},
                {"mission": "HORIZONS-SYNTH", "naif_id": -29},
            ],
        }
        assert has_archive_trajectory(entry)

    def test_our_own_folders_do_not_count_as_a_trajectory(self):
        entry = {
            "kernel_sources": [
                {"mission": "EVENTS-DB", "naif_id": -90000123},
                {"mission": "GCAT-DEEP", "naif_id": -90000123},
            ]
        }
        assert not has_archive_trajectory(entry)

    def test_an_entry_with_no_sources_has_no_trajectory(self):
        assert not has_archive_trajectory({})


class TestNameSeeding:
    """A kernel's archive name fills an entry the registry left nameless."""

    def test_a_nameless_entry_takes_the_archive_name(self):
        registry = [_entry(22904832, -9, mission="HORIZONS-SYNTH", name=None)]
        record = assign(
            "HORIZONS-SYNTH",
            -9,
            39000,
            registry,
            index_by_source(registry),
            name="ESCAPADE-Blue (spacecraft)",
        )
        assert record.name == "ESCAPADE-Blue (spacecraft)"
        assert registry[0]["name"] == "ESCAPADE-Blue (spacecraft)"

    def test_a_curated_name_wins_over_the_archive(self):
        registry = [_entry(22904832, -9, mission="HORIZONS-SYNTH")]
        record = assign(
            "HORIZONS-SYNTH",
            -9,
            39000,
            registry,
            index_by_source(registry),
            name="ESCAPADE-Blue (spacecraft)",
        )
        assert record.name == "Venera 2"
        assert registry[0]["name"] == "Venera 2"

    def test_a_new_entry_is_born_named(self):
        registry: list[dict] = []
        record = assign(
            "SMILE", -463, 39000, registry, index_by_source(registry), name="SMILE"
        )
        assert record.name == "SMILE"
        assert registry[0]["name"] == "SMILE"

    def test_a_nameless_kernel_leaves_the_entry_nameless(self):
        registry = [_entry(22904832, -463, mission="SMILE", name=None)]
        assign("SMILE", -463, 39000, registry, index_by_source(registry), name=None)
        assert registry[0]["name"] is None
