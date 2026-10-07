"""Ranking a body's candidate maps against each other.

The ranking decides which picture is a body's own bundle and which are the
fallbacks beside it, so getting it wrong either loses a map or moves one that
is already published.
"""

from space_map_data.constants.manifests.textures import (
    ALT_INFIX,
    layer_files,
    layer_grid,
    rank_by_body,
)


def _entry(body, file, **kw):
    return {"body": body, "file": file, "type": "cylindrical", **kw}


class TestRankByBody:
    def test_sole_map_of_a_body_keeps_the_body_id(self):
        entries = [_entry("naif-499", "mars.tif")]
        assert rank_by_body(entries) == {"mars.tif": "naif-499"}

    def test_best_takes_the_body_id_and_the_rest_sit_beside_it(self):
        entries = [
            _entry("naif-299", "albers.tif", preference=10),
            _entry("naif-299", "usgs.tif", preference=5, variant="usgs"),
        ]
        assert rank_by_body(entries) == {
            "albers.tif": "naif-299",
            "usgs.tif": f"naif-299{ALT_INFIX}usgs",
        }

    def test_ranking_does_not_depend_on_manifest_order(self):
        entries = [
            _entry("naif-299", "usgs.tif", preference=5, variant="usgs"),
            _entry("naif-299", "albers.tif", preference=10),
        ]
        assert rank_by_body(entries)["albers.tif"] == "naif-299"

    def test_absent_preference_ranks_below_a_stated_one(self):
        entries = [
            _entry("naif-299", "unranked.tif", variant="other"),
            _entry("naif-299", "best.tif", preference=1),
        ]
        assert rank_by_body(entries)["best.tif"] == "naif-299"

    def test_an_alternate_without_a_variant_is_dropped(self):
        entries = [
            _entry("naif-299", "best.tif", preference=10),
            _entry("naif-299", "nameless.tif", preference=5),
        ]
        assert "nameless.tif" not in rank_by_body(entries)

    def test_skipped_entries_never_rank(self):
        entries = [
            _entry("naif-299", "best.tif", preference=10),
            _entry("naif-299", "dropped.tif", preference=99, variant="x", skip=True),
        ]
        assert rank_by_body(entries) == {"best.tif": "naif-299"}

    def test_tile_only_entries_never_rank(self):
        """A pyramid source must not displace the map the tiers come from."""
        entries = [
            _entry("naif-499", "viking-925m.tif"),
            _entry("naif-499", "viking-232m.tif", preference=5, tiles="only"),
        ]
        assert rank_by_body(entries) == {"viking-925m.tif": "naif-499"}

    def test_entry_with_tiers_and_tiles_still_ranks(self):
        entries = [_entry("naif-301", "moon.tif", tiles=True)]
        assert rank_by_body(entries) == {"moon.tif": "naif-301"}

    def test_sibling_layers_do_not_compete_with_the_surface(self):
        entries = [
            _entry("naif-399", "earth.tif"),
            _entry("naif-399", "night.tif", type="cylindrical_night_lights"),
        ]
        assert rank_by_body(entries) == {"earth.tif": "naif-399"}


class TestLayerFiles:
    """The files a pyramid layer names, and where each one is fetched from."""

    QUADS = {
        "dir": "ctx",
        "lat_range": [-8, 8],
        "quads": {
            "step_deg": 4,
            "file": "ctx_E{lon}_N{lat}.tif",
            "archive": "https://maps.test/ctx_E{lon}_N{lat}.zip",
        },
    }

    def test_single_file_and_its_link(self):
        layer = {"file": "dem.tif", "download_url": "https://maps.test/dem.tif"}
        assert layer_files(layer) == [("dem.tif", "https://maps.test/dem.tif")]
        assert layer_grid(layer) == [["dem.tif"]]

    def test_listed_grid_is_fetched_from_one_directory(self):
        layer = {"grid": [["nw.img", "ne.img"]], "download_dir": "https://maps.test/d"}
        assert layer_files(layer) == [
            ("nw.img", "https://maps.test/d/nw.img"),
            ("ne.img", "https://maps.test/d/ne.img"),
        ]

    def test_quads_run_north_to_south_then_west_to_east(self):
        grid = layer_grid(self.QUADS)
        assert (len(grid), len(grid[0])) == (4, 90)
        assert grid[0][:2] == ["ctx/ctx_E-180_N04.tif", "ctx/ctx_E-176_N04.tif"]
        assert grid[-1][-1] == "ctx/ctx_E176_N-08.tif"

    def test_quad_names_pad_the_degrees_and_sign_only_the_negative(self):
        names = dict(layer_files(self.QUADS))
        assert names["ctx/ctx_E000_N00.tif"] == "https://maps.test/ctx_E000_N00.zip"
        assert "ctx/ctx_E-004_N-04.tif" in names and "ctx/ctx_E076_N04.tif" in names
