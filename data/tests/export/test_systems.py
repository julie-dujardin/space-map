"""Tests for space_map_data.export.systems."""

import json

from space_map_data.export.systems import (
    _tiers_from_meta,
    clouds_block,
    load_clouds_metadata,
    load_night_metadata,
    load_orientation,
    load_texture_metadata,
    night_block,
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

    def test_skips_night_directory(self, tmp_path):
        (tmp_path / "textures" / "naif-399").mkdir(parents=True)
        (tmp_path / "textures" / "naif-399" / "metadata.json").write_text(
            json.dumps({"id": "naif-399", "type": "cylindrical"})
        )
        (tmp_path / "textures" / "naif-399_night").mkdir(parents=True)
        (tmp_path / "textures" / "naif-399_night" / "metadata.json").write_text(
            json.dumps({"id": "naif-399_night", "type": "cylindrical_night_lights"})
        )
        result = load_texture_metadata(tmp_path)
        assert set(result.keys()) == {"naif-399"}


class TestNightBlock:
    """night_block carries the export id, tiers, and attribution fields."""

    def test_carries_export_id_tiers_and_required_fields(self):
        meta = {
            "id": "naif-399_night",
            "source": "https://science.nasa.gov/earth/earth-observatory/earth-at-night/maps/",
            "organisation": "NASA",
            "type": "cylindrical_night_lights",
            "exports": {"low": {"size_bytes": 1}, "high": {"size_bytes": 1}},
        }
        block = night_block(meta)
        assert block["id"] == "naif-399_night"
        assert block["tiers"] == ["high", "low"]
        assert block["organisation"] == "NASA"
        assert block["type"] == "cylindrical_night_lights"
        assert "attribution" not in block
        assert "description" not in block

    def test_carries_optional_attribution_and_description(self):
        block = night_block(
            {
                "id": "naif-399_night",
                "source": "https://example.com",
                "organisation": "NASA",
                "type": "cylindrical_night_lights",
                "attribution": "NASA Earth Observatory — Black Marble 2016.",
                "description": "Emissive sibling.",
                "exports": {"low": {"size_bytes": 1}},
            }
        )
        assert block["attribution"].startswith("NASA Earth Observatory")
        assert block["description"] == "Emissive sibling."


class TestLoadNightMetadata:
    """load_night_metadata strips the `_night` suffix and isolates the bundle."""

    def _seed(self, out_dir, body_dir_name: str, meta: dict) -> None:
        body = out_dir / "textures" / body_dir_name
        body.mkdir(parents=True)
        (body / "metadata.json").write_text(json.dumps(meta))

    def test_keys_by_host_body_id(self, tmp_path):
        self._seed(
            tmp_path,
            "naif-399_night",
            {"id": "naif-399_night", "type": "cylindrical_night_lights"},
        )
        result = load_night_metadata(tmp_path)
        assert set(result.keys()) == {"naif-399"}
        assert result["naif-399"]["id"] == "naif-399_night"

    def test_ignores_regular_texture_directories(self, tmp_path):
        self._seed(tmp_path, "naif-499", {"id": "naif-499", "type": "cylindrical"})
        assert load_night_metadata(tmp_path) == {}

    def test_missing_textures_dir_returns_empty(self, tmp_path):
        assert load_night_metadata(tmp_path) == {}


class TestLoadOrientation:
    """The orientation table merges three disjoint publishers into one dict, so
    every record has to say which one it came from."""

    _HEADER = (
        "naif_id,pole_ra_0,pole_ra_1,pole_dec_0,pole_dec_1,w0,w1,w2\n"
        "{naif},10,0,20,0,30,40,0\n"
    )

    def _download_dir(self, tmp_path, *, pck=None, damit=None):
        tables = tmp_path / "derived" / "position" / "tables"
        tables.mkdir(parents=True)
        if pck is not None:
            (tables / "orientation.csv").write_text(self._HEADER.format(naif=pck))
        models = tmp_path / "derived" / "models"
        models.mkdir(parents=True)
        if damit is not None:
            (models / "damit_orientation.csv").write_text(
                self._HEADER.format(naif=damit)
            )
        return tmp_path

    def test_each_set_is_tagged(self, tmp_path):
        result = load_orientation(self._download_dir(tmp_path, pck=599, damit=2000021))
        assert result[599]["source"] == "pck"
        assert result[2000021]["source"] == "lightcurve"
        # Chariklo, from the occultation literature, with its paper attached.
        assert result[2010199]["source"] == "occultation"
        assert result[2010199]["reference"]["url"].startswith("https://doi.org/")

    def test_pck_wins_and_keeps_its_own_tag(self, tmp_path):
        # Same body in both tables: the PCK record must not inherit the DAMIT
        # label, or a visited asteroid would credit DAMIT for a NAIF pole.
        result = load_orientation(
            self._download_dir(tmp_path, pck=2000433, damit=2000433)
        )
        assert result[2000433]["source"] == "pck"

    def test_numeric_fields_survive_the_tag(self, tmp_path):
        (record,) = [
            r
            for naif, r in load_orientation(
                self._download_dir(tmp_path, pck=599)
            ).items()
            if naif == 599
        ]
        assert record["pole_ra_0"] == 10.0
        assert record["w1"] == 40.0
