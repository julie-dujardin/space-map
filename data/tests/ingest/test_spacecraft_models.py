"""Manifest-field validation for the spacecraft model processor."""

from space_map_data.ingest.providers.models.processor import _validated_frame_map


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
