"""Tests for space_map_data.export.systems."""

import json

from space_map_data.export.systems import (
    _tiers_from_meta,
    clouds_block,
    load_clouds_metadata,
    load_texture_metadata,
    texture_attribution,
)


class TestTextureAttribution:
    """texture_attribution extracts the user-facing subset of texture metadata."""

    def test_carries_required_fields(self):
        meta = {
            "source": "https://example.com",
            "organisation": "NASA",
            "type": "cylindrical",
        }
        assert texture_attribution(meta) == meta

    def test_omits_missing_optional_fields(self):
        result = texture_attribution(
            {
                "source": "https://example.com",
                "organisation": "NASA",
                "type": "cylindrical",
                "attribution": None,
                "description": None,
                "frames": None,
            }
        )
        assert "attribution" not in result
        assert "description" not in result
        assert "frames" not in result

    def test_passes_frames_through_for_monthly(self):
        """Renderers need `frames` to format the per-month tier URL."""
        result = texture_attribution(
            {
                "source": "https://example.com",
                "organisation": "NASA",
                "type": "cylindrical_monthly",
                "frames": 12,
            }
        )
        assert result["frames"] == 12
        assert result["type"] == "cylindrical_monthly"


class TestTiersFromMeta:
    """_tiers_from_meta normalises the two on-disk export shapes."""

    def test_flat_exports_return_tier_keys(self):
        meta = {
            "type": "cylindrical",
            "exports": {
                "low": {"size_bytes": 1},
                "medium": {"size_bytes": 1},
                "high": {"size_bytes": 1},
            },
        }
        assert _tiers_from_meta(meta) == ["high", "low", "medium"]

    def test_monthly_exports_return_tier_keys_from_first_frame(self):
        meta = {
            "type": "cylindrical_monthly",
            "exports": {
                "01": {"low": {"size_bytes": 1}, "medium": {"size_bytes": 1}},
                "02": {"low": {"size_bytes": 1}, "medium": {"size_bytes": 1}},
            },
        }
        assert _tiers_from_meta(meta) == ["low", "medium"]

    def test_empty_exports_returns_empty(self):
        assert _tiers_from_meta({"type": "cylindrical", "exports": {}}) == []


class TestCloudsBlock:
    """clouds_block carries the export id, tiers, and attribution fields."""

    def test_carries_export_id_tiers_frames_and_required_fields(self):
        meta = {
            "id": "naif-399_clouds",
            "source": "https://example.com/clouds.png",
            "organisation": "EUMETSAT",
            "type": "clouds_overlay",
            "tiers": ["low", "medium"],
            "frames": ["2026050100", "2026050103"],
        }
        block = clouds_block(meta)
        assert block["id"] == "naif-399_clouds"
        assert block["tiers"] == ["low", "medium"]
        assert block["frames"] == ["2026050100", "2026050103"]
        assert block["source"] == "https://example.com/clouds.png"
        assert block["organisation"] == "EUMETSAT"
        assert block["type"] == "clouds_overlay"
        assert "attribution" not in block
        assert "description" not in block

    def test_carries_optional_attribution_and_description(self):
        block = clouds_block(
            {
                "id": "naif-399_clouds",
                "source": "https://example.com",
                "organisation": "EUMETSAT",
                "type": "clouds_overlay",
                "attribution": "Contains modified EUMETSAT data",
                "description": "3-hour cadence overlay.",
                "tiers": ["low"],
                "frames": ["2026050100"],
            }
        )
        assert block["attribution"] == "Contains modified EUMETSAT data"
        assert block["description"] == "3-hour cadence overlay."


class TestLoadCloudsMetadata:
    """load_clouds_metadata strips the `_clouds` suffix and isolates the bundle."""

    def _seed(self, out_dir, body_dir_name: str, meta: dict) -> None:
        body = out_dir / "textures" / body_dir_name
        body.mkdir(parents=True)
        (body / "metadata.json").write_text(json.dumps(meta))

    def test_keys_by_host_body_id(self, tmp_path):
        self._seed(
            tmp_path,
            "naif-399_clouds",
            {"id": "naif-399_clouds", "type": "clouds_overlay"},
        )
        result = load_clouds_metadata(tmp_path)
        assert set(result.keys()) == {"naif-399"}
        assert result["naif-399"]["id"] == "naif-399_clouds"

    def test_ignores_regular_texture_directories(self, tmp_path):
        self._seed(tmp_path, "naif-499", {"id": "naif-499", "type": "cylindrical"})
        assert load_clouds_metadata(tmp_path) == {}

    def test_missing_textures_dir_returns_empty(self, tmp_path):
        assert load_clouds_metadata(tmp_path) == {}


class TestLoadTextureMetadataFiltersClouds:
    """Surface-texture loader must skip `_clouds` bundles so they're not double-credited."""

    def test_skips_clouds_directory(self, tmp_path):
        (tmp_path / "textures" / "naif-399").mkdir(parents=True)
        (tmp_path / "textures" / "naif-399" / "metadata.json").write_text(
            json.dumps({"id": "naif-399", "type": "cylindrical_monthly"})
        )
        (tmp_path / "textures" / "naif-399_clouds").mkdir(parents=True)
        (tmp_path / "textures" / "naif-399_clouds" / "metadata.json").write_text(
            json.dumps({"id": "naif-399_clouds", "type": "clouds_overlay"})
        )
        result = load_texture_metadata(tmp_path)
        assert set(result.keys()) == {"naif-399"}
