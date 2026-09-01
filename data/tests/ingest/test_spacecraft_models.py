"""Manifest-field validation for the spacecraft model processor."""

from types import SimpleNamespace

from space_map_data.ingest.providers.models.processor import (
    ModelProcessor,
    _validated_frame_map,
)


class TestValidatedFrameMap:
    """`frame_map` must be 1–2 well-formed axis pairs or be dropped whole."""

    def test_absent(self):
        assert _validated_frame_map({}, "s") is None

    def test_single_pair(self):
        assert _validated_frame_map({"frame_map": {"+y": "+z"}}, "s") == {"+y": "+z"}

    def test_two_pairs(self):
        fm = {"+y": "-z", "+z": "-y"}
        assert _validated_frame_map({"frame_map": fm}, "s") == fm

    def test_invalid_axis_dropped(self):
        assert _validated_frame_map({"frame_map": {"+y": "up"}}, "s") is None

    def test_not_a_mapping(self):
        assert _validated_frame_map({"frame_map": "+y"}, "s") is None

    def test_too_many_pairs(self):
        fm = {"+x": "+x", "+y": "+z", "+z": "-y"}
        assert _validated_frame_map({"frame_map": fm}, "s") is None

    def test_parallel_model_axes(self):
        assert (
            _validated_frame_map({"frame_map": {"+y": "+z", "-y": "+x"}}, "s") is None
        )

    def test_parallel_body_axes(self):
        assert (
            _validated_frame_map({"frame_map": {"+x": "+z", "+y": "-z"}}, "s") is None
        )


class TestBusModelExcludes:
    """`model_excludes` drops a craft from the bus mesh, not from the bus group."""

    @staticmethod
    def _processor():
        p = ModelProcessor.__new__(ModelProcessor)
        p._satcat_name_to_norad = {"GOES 8": 23051, "ECHOSTAR 5": 25913}
        p._satcat_norad_to_object_id = {23051: "o-goes8", 25913: "o-echo5"}
        return p

    @staticmethod
    def _spec():
        return SimpleNamespace(
            known_satellites=("GOES 8", "ECHOSTAR 5"),
            model_excludes=("GOES 8",),
        )

    def test_membership_keeps_the_excluded_craft(self):
        ids = self._processor()._bus_object_ids(self._spec(), {"o-goes8", "o-echo5"})
        assert ids == ["o-goes8", "o-echo5"]

    def test_mesh_drops_the_excluded_craft(self):
        ids = self._processor()._bus_object_ids(
            self._spec(), {"o-goes8", "o-echo5"}, for_model=True
        )
        assert ids == ["o-echo5"]
