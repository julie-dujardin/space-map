"""Checks for the `/about/data` report: ground scales, sizes and grouping."""

import pytest
from PIL import Image

from space_map_data.export.about_data import (
    build_about_data,
    cloud_tier_rows,
    equator_radius_km,
    ground_scale,
    map_row,
    patch_row,
    pyramid_block,
    tier_rows,
)
from space_map_data.models.object import ObjectType
from tests.conftest import make_object

MARS_KM = 3396.19


def _tier(width: int, size: int) -> dict:
    return {"file": "x.webp", "width": width, "height": width // 2, "size_bytes": size}


def _pyramid(**extra) -> dict:
    return {
        "tile_size": 1024,
        "max_level": 2,
        "layers": [{"dimensions": [8000, 4000], "full_width": 8000, "lat_range": None}],
        "levels": [
            {"level": 0, "tiles": 2, "size_bytes": 10},
            {"level": 1, "tiles": 8, "size_bytes": 40},
            {"level": 2, "tiles": 32, "size_bytes": 160},
        ],
        "cap_levels": [
            {"level": 1, "tiles": 2, "size_bytes": 5},
            {"level": 2, "tiles": 8, "size_bytes": 20},
        ],
        **extra,
    }


def _patch(**extra) -> dict:
    return {
        "id": "site",
        "name": "Site",
        "max_level": 16,
        "full_width": 85355564,
        "bounds": {"west": 77.0, "east": 77.5, "south": 18.0, "north": 19.0},
        "levels": [
            {"level": 15, "tiles": 4, "size_bytes": 100},
            {"level": 16, "tiles": 16, "size_bytes": 400},
        ],
        **extra,
    }


class TestGroundScale:
    """Pixels around the equator to metres on the ground."""

    def test_mars_ctx_mosaic_is_five_metres(self):
        assert ground_scale(4267800, MARS_KM) == {"m_per_px": 5.0}

    def test_body_of_unknown_size_gets_no_scale(self):
        assert ground_scale(4096, None) == {}

    def test_equator_radius_ignores_the_polar_axis(self):
        assert equator_radius_km({"a": 10.0, "b": 8.0, "c": 2.0}) == 9.0


class TestTierRows:
    """The whole-globe images of a bundle."""

    def test_coarsest_first(self):
        meta = {
            "type": "cylindrical",
            "exports": {"high": _tier(16383, 30), "low": _tier(2048, 10)},
        }
        assert [row["name"] for row in tier_rows(meta)] == ["low", "high"]

    def test_monthly_frames_add_up(self):
        frame = {"low": _tier(2048, 10), "high": _tier(16383, 30)}
        meta = {"type": "cylindrical_monthly", "exports": {"01": frame, "02": frame}}
        assert [(row["width"], row["size_bytes"]) for row in tier_rows(meta)] == [
            (2048, 20),
            (16383, 60),
        ]

    def test_cloud_images_are_measured_on_disk(self, tmp_path):
        for frame in ("2026031112", "2026031115"):
            Image.new("L", (64, 32)).save(tmp_path / f"low_{frame}.webp")
        meta = {"tiers": ["low", "medium"], "frames": ["2026031112", "2026031115"]}
        (row,) = cloud_tier_rows(tmp_path, meta)
        assert (row["name"], row["width"], row["height"]) == ("low", 64, 32)
        assert row["size_bytes"] == sum(f.stat().st_size for f in tmp_path.iterdir())


class TestPyramidBlock:
    """A tile pyramid, from its descriptor."""

    def test_counts_the_map_and_its_caps(self):
        block = pyramid_block(_pyramid(), MARS_KM)
        assert (block["tiles"], block["size_bytes"]) == (52, 235)
        assert (block["width"], block["height"]) == (8192, 4096)

    def test_source_coarser_than_the_grid_sets_the_scale(self):
        block = pyramid_block(_pyramid(), MARS_KM)
        assert block["m_per_px"] == ground_scale(8000, MARS_KM)["m_per_px"]

    def test_grid_coarser_than_the_source_sets_the_scale(self):
        layers = [{"dimensions": [20000, 10000], "full_width": 20000}]
        block = pyramid_block(_pyramid(layers=layers), MARS_KM)
        assert block["m_per_px"] == ground_scale(8192, MARS_KM)["m_per_px"]

    def test_sources_keep_their_role_and_band(self):
        layers = [
            {"dimensions": [4000, 2000], "full_width": 4000, "lat_range": None},
            {"dimensions": [8000, 2000], "full_width": 8000, "lat_range": [-60, 60]},
            {
                "dimensions": [500, 500],
                "full_width": 8000,
                "lat_range": [60, 90],
                "role": "brightness",
            },
        ]
        sources = pyramid_block(_pyramid(layers=layers), None)["sources"]
        assert sources == [
            {"role": "base", "width": 4000},
            {"role": "inset", "width": 8000, "lat_range": [-60, 60]},
            {"role": "detail", "width": 8000, "lat_range": [60, 90]},
        ]

    def test_height_pyramid_states_its_step(self):
        block = pyramid_block(_pyramid(displacement_scale_km=65.535), MARS_KM)
        assert block["height_step_m"] == 1.0

    def test_pyramid_without_patches_has_no_patch_list(self):
        assert "patches" not in pyramid_block(_pyramid(), MARS_KM)


class TestPatchRow:
    """A patch is a row of its own."""

    def test_mosaic_coarser_than_its_level_sets_the_scale(self):
        row = patch_row(_patch(), 1024, MARS_KM)
        assert row["m_per_px"] == 0.25

    def test_extent_and_centre_come_from_the_bounds(self):
        row = patch_row(_patch(), 1024, MARS_KM)
        assert (row["lat"], row["lon"]) == (18.5, 77.25)
        assert row["height_km"] == pytest.approx(59.27, abs=0.01)
        assert row["width_km"] == pytest.approx(28.11, abs=0.01)

    def test_tiles_of_all_its_levels(self):
        row = patch_row(_patch(), 1024, MARS_KM)
        assert (row["tiles"], row["size_bytes"]) == (20, 500)

    def test_unknown_radius_leaves_out_the_ground_figures(self):
        row = patch_row(_patch(), 1024, None)
        assert not {"m_per_px", "width_km", "height_km"} & set(row)


class TestMapRow:
    """One map of a world."""

    def test_monthly_map_states_its_frames(self):
        meta = {"id": "naif-399", "type": "cylindrical_monthly", "frames": 12}
        assert map_row("surface", meta, [], None)["frames"] == 12

    def test_cloud_overlay_counts_its_snapshots(self):
        meta = {"id": "naif-399_clouds", "frames": ["2026031112", "2026031115"]}
        assert map_row("clouds", meta, [], None)["frames"] == 2

    def test_single_frame_states_none(self):
        meta = {"id": "naif-299_clouds", "frames": ["static"]}
        assert "frames" not in map_row("clouds", meta, [], None)

    def test_tier_scale_follows_its_width(self):
        tier = {"name": "high", "width": 4267800, "height": 2133900, "size_bytes": 1}
        row = map_row("surface", {"id": "naif-499"}, [tier], MARS_KM)
        assert row["tiers"][0]["m_per_px"] == 5.0

    def test_height_image_has_eight_bits(self):
        meta = {"id": "naif-499_displacement", "displacement_scale_km": 25.5}
        assert map_row("topography", meta, [], None)["height_step_m"] == 100.0

    def test_second_map_of_a_body_is_marked(self):
        row = map_row("surface", {"id": "naif-299_alt-usgs"}, [], None, alternate=True)
        assert row["alternate"] is True


class TestBuild:
    """Worlds grouped by system, as on the credits page."""

    @staticmethod
    def _texture(bundle_id: str) -> dict:
        return {
            "id": bundle_id,
            "type": "cylindrical",
            "exports": {"low": _tier(2048, 10)},
        }

    def _build(self, session, tmp_path, textures: dict, radii: dict) -> dict:
        return build_about_data(session, tmp_path, radii, textures, {}, {}, {}, {}, {})

    def test_planet_before_its_moons_and_standalones_last(self, session, tmp_path):
        session.add_all(
            [
                make_object(
                    id="naif-4",
                    name="Mars Barycenter",
                    naif_id=4,
                    object_type=ObjectType.barycenter,
                    parent_id="naif-0",
                ),
                make_object(
                    id="naif-401", name="Phobos", naif_id=401, parent_id="naif-4"
                ),
                make_object(
                    id="naif-499", name="Mars", naif_id=499, parent_id="naif-4"
                ),
                make_object(
                    id="naif-2000001",
                    name="Ceres",
                    naif_id=2000001,
                    parent_id="naif-10",
                ),
            ]
        )
        session.commit()
        textures = {
            body: self._texture(body)
            for body in ("naif-401", "naif-2000001", "naif-499")
        }
        payload = self._build(session, tmp_path, textures, {})
        assert [
            (system["name"], [world["name"] for world in system["worlds"]])
            for system in payload["systems"]
        ] == [("Mars", ["Mars", "Phobos"]), (None, ["Ceres"])]
        assert payload["systems"][0]["primary_id"] == "naif-499"

    def test_radius_gives_the_ground_scale(self, session, tmp_path):
        session.add(make_object(id="naif-499", name="Mars", naif_id=499))
        session.commit()
        radii = {499: {"a": MARS_KM, "b": MARS_KM, "c": 3376.2}}
        payload = self._build(
            session, tmp_path, {"naif-499": self._texture("naif-499")}, radii
        )
        (world,) = payload["systems"][0]["worlds"]
        assert world["radius_km"] == MARS_KM
        assert "m_per_px" in world["maps"][0]["tiers"][0]

    def test_bundle_with_no_object_is_left_out(self, session, tmp_path):
        payload = self._build(session, tmp_path, {"stars": self._texture("stars")}, {})
        assert payload["systems"] == []
