"""Tests for space_map_data.export.systems."""

import gzip
import json

import orjson
import pytest

from space_map_data.export.systems import (
    _tiers_from_meta,
    clouds_block,
    displacement_block,
    load_clouds_metadata,
    load_displacement_metadata,
    load_night_metadata,
    load_orientation,
    load_specular_metadata,
    load_texture_metadata,
    night_block,
    patch_object_bundles,
    specular_block,
    texture_attribution,
    tiles_block,
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
    """clouds_block carries the export id, tiers, coverage runs, and
    attribution fields."""

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

    def test_carries_coverage_runs_when_present(self):
        block = clouds_block(
            {
                "id": "naif-399_clouds",
                "source": "https://example.com",
                "organisation": "EUMETSAT",
                "type": "clouds_overlay",
                "tiers": ["low"],
                "frames": ["2026050100", "2026050512"],
                "coverage": [
                    ["2026050100", "2026050121"],
                    ["2026050512", "2026050512"],
                ],
            }
        )
        assert block["coverage"] == [
            ["2026050100", "2026050121"],
            ["2026050512", "2026050512"],
        ]

    def test_omits_coverage_for_a_static_bundle(self):
        # Venus has one frame and no runs, so the key would carry an empty list.
        block = clouds_block(
            {
                "id": "naif-299_clouds",
                "source": "https://example.com",
                "organisation": "Björn Jónsson",
                "type": "clouds_overlay",
                "tiers": ["low"],
                "frames": ["static"],
            }
        )
        assert "coverage" not in block


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


class TestTilesBlock:
    """A bundle's tile pyramid rides inside its texture or displacement block."""

    DESCRIPTOR = {
        "id": "naif-499",
        "type": "cylindrical",
        "source": "https://example.com/232m",
        "organisation": "USGS",
        "license": "Public domain",
        "distribution": None,
        "attribution": "Viking MDIM 2.1",
        "version": "0123456789",
        "tile_size": 1024,
        "max_level": 6,
        "levels": [],
    }

    @staticmethod
    def _write(root, kind: str, bundle_id: str, meta: dict) -> None:
        (root / kind / bundle_id).mkdir(parents=True)
        (root / kind / bundle_id / "metadata.json").write_text(json.dumps(meta))

    def test_texture_block_carries_the_pyramid_and_its_own_credit(self, tmp_path):
        self._write(
            tmp_path,
            "textures",
            "naif-499",
            {
                "id": "naif-499",
                "source": "https://example.com/925m",
                "organisation": "USGS",
                "type": "cylindrical",
            },
        )
        self._write(tmp_path, "tiles", "naif-499", self.DESCRIPTOR)

        block = texture_attribution(load_texture_metadata(tmp_path)["naif-499"])
        assert block["source"] == "https://example.com/925m"
        assert block["tiles"] == {
            "id": "naif-499",
            "tile_size": 1024,
            "max_level": 6,
            "version": "0123456789",
            "source": "https://example.com/232m",
            "organisation": "USGS",
            "license": "Public domain",
            "attribution": "Viking MDIM 2.1",
        }

    def test_bundle_without_a_pyramid_has_no_tiles_key(self, tmp_path):
        self._write(
            tmp_path,
            "textures",
            "naif-499",
            {
                "id": "naif-499",
                "source": "https://example.com",
                "organisation": "USGS",
                "type": "cylindrical",
            },
        )
        block = texture_attribution(load_texture_metadata(tmp_path)["naif-499"])
        assert "tiles" not in block

    def test_monthly_pyramid_states_its_frames(self):
        block = tiles_block({**self.DESCRIPTOR, "frames": 12})
        assert block["frames"] == 12

    @pytest.mark.parametrize(
        ("suffix", "load", "build"),
        [
            ("_night", load_night_metadata, night_block),
            ("_specular", load_specular_metadata, specular_block),
        ],
    )
    def test_sibling_layers_carry_their_pyramid(self, tmp_path, suffix, load, build):
        bundle = f"naif-399{suffix}"
        self._write(
            tmp_path,
            "textures",
            bundle,
            {
                "id": bundle,
                "source": "https://example.com",
                "organisation": "NASA",
                "type": "cylindrical",
                "exports": {"low": {}},
            },
        )
        self._write(tmp_path, "tiles", bundle, {**self.DESCRIPTOR, "id": bundle})
        assert build(load(tmp_path)["naif-399"])["tiles"]["id"] == bundle

    def test_displacement_pyramid_states_its_own_height_scale(self, tmp_path):
        self._write(
            tmp_path,
            "textures",
            "naif-499_displacement",
            {
                "id": "naif-499_displacement",
                "source": "https://example.com/dem",
                "organisation": "USGS",
                "type": "cylindrical_displacement",
                "displacement_bias_km": -8.2,
                "displacement_scale_km": 29.4,
                "exports": {"low": {}},
            },
        )
        self._write(
            tmp_path,
            "tiles",
            "naif-499_displacement",
            {
                **self.DESCRIPTOR,
                "id": "naif-499_displacement",
                "displacement_bias_km": -8.201,
                "displacement_scale_km": 65.535,
            },
        )

        meta = load_displacement_metadata(tmp_path)["naif-499"]
        block = displacement_block(meta)
        assert (block["bias_km"], block["scale_km"]) == (-8.2, 29.4)
        assert block["tiles"]["id"] == "naif-499_displacement"
        assert (block["tiles"]["bias_km"], block["tiles"]["scale_km"]) == (
            -8.201,
            65.535,
        )


class TestPatchObjectBundles:
    """The scoped systems run restates the surface-map blocks on the object
    bundles, which are the only copy for a body outside every system."""

    TEXTURE = {
        "id": "spkid-20000004",
        "source": "https://example.com/vesta",
        "organisation": "NASA",
        "type": "cylindrical",
    }
    HEIGHTS = {
        "id": "spkid-20000004_displacement",
        "source": "https://example.com/dtm",
        "organisation": "DLR",
        "type": "cylindrical_displacement",
        "displacement_bias_km": 200.0,
        "displacement_scale_km": 90.0,
        "exports": {"low": {}},
    }

    @staticmethod
    def _bundle(root, name: str, bodies: dict):
        path = root / "objects" / "__global__" / f"{name}.json.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(orjson.dumps(bodies), mtime=0))
        return path

    @staticmethod
    def _read(path) -> dict:
        return orjson.loads(gzip.decompress(path.read_bytes()))

    def test_blocks_are_restated_with_their_pyramids(self, tmp_path):
        vesta = {"id": "spkid-20000004", "map_texture_available": True, "name": "Vesta"}
        path = self._bundle(tmp_path, "a1", {"spkid-20000004": vesta})
        tiles = {**TestTilesBlock.DESCRIPTOR, "id": "spkid-20000004"}

        rewritten = patch_object_bundles(
            tmp_path,
            {"spkid-20000004": {**self.TEXTURE, "tiles": tiles}},
            {},
            {"spkid-20000004": self.HEIGHTS},
        )

        data = self._read(path)["spkid-20000004"]
        assert rewritten == 1
        assert data["name"] == "Vesta"
        assert data["texture"]["tiles"]["id"] == "spkid-20000004"
        assert data["displacement"]["scale_km"] == 90.0

    def test_bundle_already_current_is_not_rewritten(self, tmp_path):
        body = {
            "id": "spkid-20000004",
            "map_texture_available": True,
            "texture": texture_attribution(self.TEXTURE),
        }
        path = self._bundle(tmp_path, "a1", {"spkid-20000004": body})
        before = path.stat().st_mtime_ns
        assert (
            patch_object_bundles(tmp_path, {"spkid-20000004": self.TEXTURE}, {}, {})
            == 0
        )
        assert path.stat().st_mtime_ns == before

    def test_block_of_a_map_that_is_gone_is_removed(self, tmp_path):
        body = {
            "id": "spkid-20000004",
            "displacement": displacement_block(self.HEIGHTS),
            "alternates": [{"id": "spkid-20000004_alt-old"}],
        }
        path = self._bundle(tmp_path, "a1", {"spkid-20000004": body})
        assert patch_object_bundles(tmp_path, {}, {}, {}) == 1
        assert self._read(path)["spkid-20000004"] == {"id": "spkid-20000004"}

    def test_body_without_the_texture_flag_gets_no_texture_block(self, tmp_path):
        """The flag comes from the database, which this run does not restate."""
        path = self._bundle(
            tmp_path, "a1", {"spkid-20000004": {"id": "spkid-20000004"}}
        )
        assert (
            patch_object_bundles(tmp_path, {"spkid-20000004": self.TEXTURE}, {}, {})
            == 0
        )
        assert "texture" not in self._read(path)["spkid-20000004"]


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
