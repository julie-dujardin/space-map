"""Tests for space_map_data.export.objects.compact."""

import tracemalloc

import orjson

from space_map_data.export.objects.compact import CompactMap


class TestStorage:
    """An entry is held as JSON bytes of its own length."""

    def test_holds_no_spare_room(self):
        compact = CompactMap()
        # The first key sizes the dict, so the measure below sees only the entry.
        compact["first"] = {}
        value = {"name": "x" * 400}
        tracing = tracemalloc.is_tracing()
        tracemalloc.start()
        try:
            before, _ = tracemalloc.get_traced_memory()
            compact["second"] = value
            after, _ = tracemalloc.get_traced_memory()
        finally:
            if not tracing:
                tracemalloc.stop()
        held = after - before
        # The bytes of orjson alone hold about 4 KB more than the JSON.
        assert held < len(orjson.dumps(value)) + 200

    def test_raw_is_the_json_of_the_entry(self):
        compact = CompactMap()
        compact["a"] = {"name": "Ceres", "n": 1}
        assert compact.raw("a") == orjson.dumps({"name": "Ceres", "n": 1})


class TestInPlaceChanges:
    """A change to the dict that `map[k]` returns is kept."""

    def test_change_through_getitem_persists(self):
        compact = CompactMap()
        compact["a"] = {"name": "Ceres"}
        compact["a"]["coverage"] = {"windows": []}
        assert compact["a"] == {"name": "Ceres", "coverage": {"windows": []}}
        assert orjson.loads(compact.raw("a")) == compact["a"]

    def test_change_through_get_persists(self):
        compact = CompactMap()
        compact["a"] = {"name": "Ceres"}
        entry = compact.get("a")
        assert entry is not None
        entry["attitude"] = {"chunks": 3}
        assert orjson.loads(compact.raw("a"))["attitude"] == {"chunks": 3}

    def test_items_and_values_yield_copies(self):
        compact = CompactMap()
        compact["a"] = {"name": "Ceres"}
        for _, entry in compact.items():  # noqa: PERF102
            entry["name"] = "changed"
        for entry in compact.values():
            entry["name"] = "changed"
        assert compact["a"] == {"name": "Ceres"}

    def test_update_from_another_map_keeps_its_changes(self):
        source = CompactMap()
        source["a"] = {"name": "Ceres"}
        source["a"]["host_id"] = "naif-10"
        target = CompactMap()
        target.update(source)
        assert orjson.loads(target.raw("a")) == {"name": "Ceres", "host_id": "naif-10"}
