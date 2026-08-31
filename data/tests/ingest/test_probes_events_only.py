"""Object rows for probes the archives publish no kernel for.

A registry entry sourced only from ``EVENTS-DB`` is a mission the curated
events name — Magellan, the Apollo CSMs, every Venera orbiter — and bodies
link to it from their event targets. It gets a row whether or not the export
can ever put it somewhere.
"""

from unittest.mock import patch

from space_map_data.ingest.providers.objects import probes


def _entry(probe_id: int, naif_id: int, missions: list[str], **extra) -> dict:
    return {
        "probe_id": probe_id,
        "name": f"probe {probe_id}",
        "naif_id": naif_id,
        "inception_mjd": 50000,
        "dedupe": 0,
        "wikidata_qid": None,
        "cospar_id": None,
        "norad_cat_id": None,
        "kernel_sources": [{"mission": m, "naif_id": naif_id} for m in missions],
        **extra,
    }


class TestEventsOnlyRecords:
    """Which registry entries turn into ingest records."""

    def test_unplaceable_entry_still_gets_a_record(self):
        registry = [_entry(1, -90000282, ["EVENTS-DB"])]
        with patch.object(probes, "load_registry", return_value=registry):
            records = probes._events_only_records(set())
        assert [rec.probe_id for _, rec in records] == [1]
        assert records[0][0] == {
            "mission": "EVENTS-DB",
            "naif_id": -90000282,
            "inception_mjd": 50000,
            "name_hint": None,
            "cospar_hint": None,
        }

    def test_entry_with_a_real_kernel_source_is_left_to_the_spk_walk(self):
        registry = [_entry(2, -82, ["EVENTS-DB", "CASSINI"])]
        with patch.object(probes, "load_registry", return_value=registry):
            assert probes._events_only_records(set()) == []

    def test_key_already_seen_in_the_spk_walk_is_skipped(self):
        registry = [_entry(3, -31, ["EVENTS-DB"])]
        with patch.object(probes, "load_registry", return_value=registry):
            assert probes._events_only_records({("EVENTS-DB", -31)}) == []
