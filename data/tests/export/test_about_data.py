"""Checks for the `/about/data` report: scales, sizes and grouping of the maps,
the rings and the 3D models."""

import pytest
from PIL import Image

from space_map_data.export.about_data import (
    build_about_data,
    cloud_tier_rows,
    craft_groups,
    craft_row,
    craft_sources,
    equator_radius_km,
    ground_scale,
    lightcurve_block,
    map_row,
    model_tiers,
    patch_row,
    pyramid_block,
    ring_row,
    shape_row,
    tier_rows,
)
from space_map_data.models.object import ObjectType
from tests.conftest import make_object

MARS_KM = 3396.19


def _meta(bundle_id: str, **extra) -> dict:
    return {
        "id": bundle_id,
        "source": "https://example.org/map",
        "organisation": "USGS",
        "attribution": "Map credit",
        **extra,
    }


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
        "source": "https://example.org/site",
        "organisation": "NASA",
        "attribution": "Site credit",
        "max_level": 16,
        "full_width": 85355564,
        "bounds": {"west": 77.0, "east": 77.5, "south": 18.0, "north": 19.0},
        "levels": [
            {"level": 15, "tiles": 4, "size_bytes": 100},
            {"level": 16, "tiles": 16, "size_bytes": 400},
        ],
        **extra,
    }


def _ring(bundle: str = "primary", **extra) -> dict:
    return {
        "bundle": bundle,
        "sources": [
            {
                "source": "https://example.org/rings",
                "organisation": "NASA",
                "license": "Public domain",
                "work": "Ring table",
                "contribution": "radii",
            }
        ],
        "inner_radius_km": 74510.0,
        "outer_radius_km": 140390.0,
        "sample_count": 13177,
        "strip": {
            "file": "strip.webp",
            "width": 13177,
            "height": 6,
            "rows": ["transmittance", "color"],
            "size_bytes": 99,
        },
        **extra,
    }


def _mesh(triangles: int, size: int, author: str = "NASA", page: str = "") -> dict:
    return {
        "size_bytes": size,
        "stats": {"triangles": triangles},
        "credit": {"name": author, "url": f"https://example.org/{author}{page}"},
        "catalog": "DAMIT",
    }


def _craft(slug: str, kind: str = "probe", **extra) -> dict:
    return {
        "slug": slug,
        "kind": kind,
        "exports": {
            "high": _mesh(900, 30) | {"scale_meters": 8.3},
            "low": _mesh(300, 10) | {"scale_meters": 6.1},
        },
        **extra,
    }


def _shape(slug: str, object_id: str, provenance: str = "missions", **extra) -> dict:
    return {
        "slug": slug,
        "kind": "shape_model",
        "provenance": provenance,
        "object_id": object_id,
        "credit": {"name": "NASA", "url": "https://example.org/shape"},
        "citation": "Gaskell (2021)",
        "true_scale": {"max_extent_km": 32.67030906677246},
        "exports": {"high": _mesh(900, 30), "low": _mesh(300, 10)},
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

    def test_patch_has_its_own_credit(self):
        row = patch_row(_patch(), 1024, MARS_KM)
        assert (row["source"], row["organisation"], row["attribution"]) == (
            "https://example.org/site",
            "NASA",
            "Site credit",
        )


class TestMapRow:
    """One map of a world."""

    def test_monthly_map_states_its_frames(self):
        meta = _meta("naif-399", type="cylindrical_monthly", frames=12)
        assert map_row("surface", meta, [], None)["frames"] == 12

    def test_cloud_overlay_counts_its_snapshots(self):
        meta = _meta("naif-399_clouds", frames=["2026031112", "2026031115"])
        assert map_row("clouds", meta, [], None)["frames"] == 2

    def test_single_frame_states_none(self):
        meta = _meta("naif-299_clouds", frames=["static"])
        assert "frames" not in map_row("clouds", meta, [], None)

    def test_tier_scale_follows_its_width(self):
        tier = {"name": "high", "width": 4267800, "height": 2133900, "size_bytes": 1}
        row = map_row("surface", _meta("naif-499"), [tier], MARS_KM)
        assert row["tiers"][0]["m_per_px"] == 5.0

    def test_height_image_has_eight_bits(self):
        meta = _meta("naif-499_displacement", displacement_scale_km=25.5)
        assert map_row("topography", meta, [], None)["height_step_m"] == 100.0

    def test_second_map_of_a_body_is_marked(self):
        meta = _meta("naif-299_alt-usgs")
        assert map_row("surface", meta, [], None, alternate=True)["alternate"] is True

    def test_map_without_a_pyramid_has_the_credit_of_its_bundle(self):
        row = map_row("surface", _meta("naif-499"), [], None)
        assert (row["source"], row["organisation"], row["attribution"]) == (
            "https://example.org/map",
            "USGS",
            "Map credit",
        )

    def test_pyramid_from_another_source_gives_the_credit(self):
        pyramid = _pyramid(source="https://example.org/ctx", organisation="NASA")
        row = map_row("surface", _meta("naif-499", tiles=pyramid), [], None)
        assert (row["source"], row["organisation"]) == (
            "https://example.org/ctx",
            "NASA",
        )
        assert "attribution" not in row


class TestRingRow:
    """One ring bundle."""

    def test_samples_span_the_two_edges(self):
        assert ring_row(_ring())["km_per_sample"] == 5.0

    def test_size_is_that_of_the_strip(self):
        row = ring_row(_ring("outer"))
        assert (row["id"], row["samples"], row["size_bytes"]) == ("outer", 13177, 99)

    def test_credit_line_is_the_cited_work(self):
        assert ring_row(_ring())["sources"] == [
            {
                "source": "https://example.org/rings",
                "organisation": "NASA",
                "attribution": "Ring table",
            }
        ]


class TestModelRows:
    """One 3D model."""

    def test_low_file_comes_first(self):
        assert model_tiers(_craft("ace")) == [
            {"name": "low", "triangles": 300, "size_bytes": 10},
            {"name": "high", "triangles": 900, "size_bytes": 30},
        ]

    def test_model_of_one_file(self):
        meta = _craft("ace", exports={"high": _mesh(900, 30)})
        assert [tier["name"] for tier in model_tiers(meta)] == ["high"]

    def test_one_author_has_one_source(self):
        exports = {"high": _mesh(900, 30, page="/fine"), "low": _mesh(300, 10)}
        assert craft_sources(_craft("ace", exports=exports)) == [
            {"organisation": "NASA", "source": "https://example.org/NASA/fine"}
        ]

    def test_two_authors_are_listed_high_file_first(self):
        exports = {"low": _mesh(300, 10), "high": _mesh(900, 30, author="tashtego")}
        sources = craft_sources(_craft("mir", exports=exports))
        assert [source["organisation"] for source in sources] == ["tashtego", "NASA"]

    def test_author_with_no_page_has_no_link(self):
        mesh = _mesh(900, 30)
        mesh["credit"]["url"] = None
        (source,) = craft_sources(_craft("ace", exports={"high": mesh}))
        assert source == {"organisation": "NASA"}

    def test_craft_names_its_only_object(self):
        row = craft_row(_craft("ace"), [("probe-1", "ACE")])
        assert (row["objects"], row["object"]) == (1, {"id": "probe-1", "name": "ACE"})
        assert row["extent_m"] == 8.3

    def test_shared_model_counts_its_objects(self):
        row = craft_row(_craft("starlink"), [("a", "A"), ("b", "B")])
        assert row["objects"] == 2
        assert "object" not in row

    def test_unmeasured_craft_has_no_extent(self):
        row = craft_row(_craft("smile", exports={"high": _mesh(900, 30)}), [])
        assert "extent_m" not in row

    def test_shape_has_its_extent_and_its_citation(self):
        row = shape_row(_shape("eros", "spkid-20000433"))
        assert (row["provenance"], row["extent_m"]) == ("missions", 32670.0)
        assert row["sources"] == [
            {
                "organisation": "NASA",
                "source": "https://example.org/shape",
                "attribution": "Gaskell (2021)",
            }
        ]


class TestLightcurveBlock:
    """The shapes from light curves are one row."""

    def test_models_of_one_world_count_once(self):
        metas = [
            _shape("damit-1", "spkid-1", "lightcurve", exports={"high": _mesh(100, 5)}),
            _shape("damit-2", "spkid-1", "lightcurve", exports={"high": _mesh(200, 7)}),
            _shape("damit-3", "spkid-2", "lightcurve", exports={"high": _mesh(300, 9)}),
        ]
        block = lightcurve_block(metas)
        assert (block["models"], block["worlds"]) == (3, 2)
        assert (block["triangles"], block["size_bytes"]) == (600, 21)

    def test_credit_is_that_of_the_catalogue(self):
        (source,) = lightcurve_block([_shape("damit-1", "spkid-1", "lightcurve")])[
            "sources"
        ]
        assert source == {
            "source": "https://damit.cuni.cz/projects/damit/",
            "organisation": "DAMIT (Ďurech et al.)",
        }


class TestCraftGroups:
    """The models that are not shapes of worlds."""

    def test_kinds_in_the_order_of_the_page(self, session):
        metas = [
            _craft("saturn-v", "rocket"),
            _craft("zeppelin", "aircraft"),
            _craft("voyager", "probe"),
            _craft("ace", "probe"),
        ]
        groups = craft_groups(session, metas)
        assert [
            (group["kind"], [m["slug"] for m in group["models"]]) for group in groups
        ] == [
            ("probe", ["ace", "voyager"]),
            ("rocket", ["saturn-v"]),
            ("aircraft", ["zeppelin"]),
        ]

    def test_model_lists_the_objects_that_draw_it(self, session):
        session.add_all(
            [
                make_object(
                    id="probe-1", name="Voyager 1", naif_id=-31, model_name="voyager"
                ),
                make_object(
                    id="probe-2", name="Voyager 2", naif_id=-32, model_name="voyager"
                ),
                make_object(id="probe-3", name="ACE", naif_id=-33, model_name="ace"),
            ]
        )
        session.commit()
        (group,) = craft_groups(session, [_craft("voyager"), _craft("ace")])
        ace, voyager = group["models"]
        assert ace["object"] == {"id": "probe-3", "name": "ACE"}
        assert voyager["objects"] == 2


class TestBuild:
    """Worlds grouped by system, as on the credits page."""

    @staticmethod
    def _texture(bundle_id: str) -> dict:
        return _meta(bundle_id, type="cylindrical", exports={"low": _tier(2048, 10)})

    def _build(
        self,
        session,
        tmp_path,
        textures: dict,
        radii: dict,
        rings: dict | None = None,
        models: dict | None = None,
    ) -> dict:
        return build_about_data(
            session,
            tmp_path,
            radii,
            textures,
            {},
            {},
            {},
            {},
            {},
            rings or {},
            models or {},
            tmp_path / "space-map-extrasolar",
        )

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

    def test_giant_planet_is_marked_as_a_world_with_no_surface(self, session, tmp_path):
        session.add_all(
            [
                make_object(id="naif-599", name="Jupiter", naif_id=599),
                make_object(id="naif-499", name="Mars", naif_id=499),
            ]
        )
        session.commit()
        textures = {body: self._texture(body) for body in ("naif-599", "naif-499")}
        payload = self._build(session, tmp_path, textures, {})
        marked = {
            world["name"]: world.get("no_surface")
            for system in payload["systems"]
            for world in system["worlds"]
        }
        assert marked == {"Jupiter": True, "Mars": None}

    def test_bundle_with_no_object_is_left_out(self, session, tmp_path):
        payload = self._build(session, tmp_path, {"stars": self._texture("stars")}, {})
        assert payload["systems"] == []

    def test_rings_and_shapes_list_their_worlds_in_page_order(self, session, tmp_path):
        session.add_all(
            [
                make_object(
                    id="naif-6",
                    name="Saturn Barycenter",
                    naif_id=6,
                    object_type=ObjectType.barycenter,
                    parent_id="naif-0",
                ),
                make_object(
                    id="naif-699", name="Saturn", naif_id=699, parent_id="naif-6"
                ),
                make_object(
                    id="naif-601", name="Mimas", naif_id=601, parent_id="naif-6"
                ),
                make_object(
                    id="spkid-20000433",
                    name="433 Eros",
                    naif_id=2000433,
                    parent_id="naif-10",
                ),
            ]
        )
        session.commit()
        models = {
            "eros": _shape("eros", "spkid-20000433"),
            "mimas": _shape("mimas", "naif-601", "radar"),
            "damit-1": _shape("damit-1", "spkid-20000433", "lightcurve"),
            "damit-2": _shape("damit-2", "spkid-20000021", "lightcurve"),
            "ace": _craft("ace"),
        }
        rings = {"naif-699": [_ring("inner"), _ring("primary")]}
        payload = self._build(session, tmp_path, {}, {}, rings, models)
        assert [
            (world["name"], [ring["id"] for ring in world["rings"]])
            for world in payload["rings"]
        ] == [("Saturn", ["inner", "primary"])]
        assert [
            (world["name"], [model["slug"] for model in world["models"]])
            for world in payload["models"]["worlds"]
        ] == [("Mimas", ["mimas"]), ("433 Eros", ["eros"])]
        assert payload["models"]["lightcurve"]["models"] == 2
        assert [group["kind"] for group in payload["models"]["craft"]] == ["probe"]
        # Saturn, Mimas and Eros. A light-curve shape does not count.
        assert payload["worlds"] == 3

    def test_no_light_curve_shapes_gives_no_block(self, session, tmp_path):
        payload = self._build(session, tmp_path, {}, {}, {}, {"ace": _craft("ace")})
        assert "lightcurve" not in payload["models"]
        assert payload["rings"] == []
