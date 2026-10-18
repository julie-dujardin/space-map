"""Manifest-field validation for the spacecraft model processor."""

import json
from pathlib import Path
from types import SimpleNamespace

from space_map_data.ingest.providers.models.config import license_distribution
from space_map_data.ingest.providers.models.metadata import convertible_files
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
        p._norads_by_bus = {"ssl-1300": [23051, 25913]}
        p._satcat_norad_to_object_id = {23051: "o-goes8", 25913: "o-echo5"}
        return p

    @staticmethod
    def _spec():
        return SimpleNamespace(slug="ssl-1300", model_excludes=(23051,))

    def test_membership_keeps_the_excluded_craft(self):
        ids = self._processor()._bus_object_ids(self._spec(), {"o-goes8", "o-echo5"})
        assert ids == ["o-goes8", "o-echo5"]

    def test_mesh_drops_the_excluded_craft(self):
        ids = self._processor()._bus_object_ids(
            self._spec(), {"o-goes8", "o-echo5"}, for_model=True
        )
        assert ids == ["o-echo5"]


class TestConvertibleFiles:
    """A candidate needs a convertible type and no `exclude` marker."""

    def test_keeps_convertible_types(self):
        files = [{"path": "a.glb", "type": "glb"}, {"path": "b.blend", "type": "blend"}]
        assert convertible_files(files) == files

    def test_drops_unconvertible_types(self):
        assert convertible_files([{"path": "a.lwo", "type": "lwo"}]) == []

    def test_drops_excluded_file(self):
        files = [
            {"path": "deployed.glb", "type": "glb"},
            {"path": "stowed.glb", "type": "glb", "exclude": True},
        ]
        assert [f["path"] for f in convertible_files(files)] == ["deployed.glb"]


class TestLicenseDistribution:
    """A licence that bars commercial reuse puts its mesh behind the tier."""

    def test_non_commercial_licences(self):
        assert license_distribution("CC BY-NC 4.0") == "non-commercial"
        assert license_distribution("CC BY-NC-SA 4.0") == "non-commercial"

    def test_open_licences(self):
        for license in ("CC BY 4.0", "CC BY-SA 3.0 IGO", "CC0 1.0", "Public domain"):
            assert license_distribution(license) is None

    def test_no_licence_on_record(self):
        assert license_distribution(None) is None

    def test_letters_inside_a_word_are_not_the_element(self):
        assert license_distribution("ESA Standard Licence, NCAR data") is None


class TestCatalogByTier:
    """Each tier says who may serve it, since the two can differ in author."""

    @staticmethod
    def _tiers(high: dict, low: dict) -> dict[str, dict]:
        p = ModelProcessor.__new__(ModelProcessor)
        p._yaml_docs = []
        p._catalog_downloaded_at = {}
        return p._catalog_by_tier(Path("merged.yaml"), high, low)

    def test_a_non_commercial_tier_is_marked_and_an_open_one_is_not(self):
        tiers = self._tiers(
            {
                "path": "mir.glb",
                "source": "Sketchfab",
                "attribution": "tashtego / Sketchfab",
                "license": "CC BY-NC 4.0",
            },
            {"path": "Mir.glb", "source": "NASA-3D-Resources"},
        )
        assert tiers["high"]["distribution"] == "non-commercial"
        assert "distribution" not in tiers["low"]


class TestTierSpan:
    """Each tier carries its own mesh's span, since the two can be different
    meshes: the full LM's high tier has its pads on the box's diagonals, its
    NASA low tier on the axes."""

    @staticmethod
    def _processor():
        p = ModelProcessor.__new__(ModelProcessor)
        p._satcat_norad_to_object_id = {}
        return p

    @staticmethod
    def _pick(tmp_path: Path, name: str, **file):
        glb = tmp_path / name
        glb.write_bytes(b"glb")
        cached = SimpleNamespace(
            file_id=name, source_sha256="0", pose_frame=None, source_type="glb"
        )
        return glb, ({"path": name, **file}, cached)

    def _metadata(self, tmp_path: Path, high_span, low_span) -> dict:
        p = self._processor()
        high_glb, high = self._pick(tmp_path, "high.glb", scale_meters=high_span)
        low_glb, low = self._pick(tmp_path, "low.glb", scale_meters=low_span)
        exports = {
            "high": p._tier_record(high_glb, high, {}),
            "low": p._tier_record(low_glb, low, {}),
        }
        p._write_prod_metadata(
            out_dir=tmp_path / "lm", slug="lm", entry={}, exports=exports
        )
        return json.loads((tmp_path / "lm" / "metadata.json").read_text())

    def test_each_tier_carries_its_own_span(self, tmp_path):
        meta = self._metadata(tmp_path, 6.9, 9.4)
        assert meta["exports"]["high"]["scale_meters"] == 6.9
        assert meta["exports"]["low"]["scale_meters"] == 9.4

    def test_the_top_level_span_is_the_high_tiers(self, tmp_path):
        assert self._metadata(tmp_path, 6.9, 9.4)["scale_meters"] == 6.9

    def test_an_unmeasured_file_gives_its_tier_no_span(self, tmp_path):
        meta = self._metadata(tmp_path, None, 9.4)
        assert "scale_meters" not in meta["exports"]["high"]
        assert "scale_meters" not in meta

    def test_a_picked_files_span_invalidates_the_bundle(self, tmp_path):
        p = self._processor()
        _, high = self._pick(tmp_path, "high.glb", scale_meters=6.9)
        _, low = self._pick(tmp_path, "low.glb", scale_meters=9.4)
        _, relabelled = self._pick(tmp_path, "low.glb", scale_meters=9.5)
        catalog = {"high": {}, "low": {}}
        before = p._cap_hash([high, low], high, low, catalog, {})
        after = p._cap_hash([high, relabelled], high, relabelled, catalog, {})
        assert before != after
