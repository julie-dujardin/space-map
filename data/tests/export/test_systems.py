"""Tests for space_map_data.export.systems."""

from space_map_data.export.systems import _tiers_from_meta, texture_attribution


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
