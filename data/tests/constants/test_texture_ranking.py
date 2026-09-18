"""Ranking a body's candidate maps against each other.

The ranking decides which picture is a body's own bundle and which are the
fallbacks beside it, so getting it wrong either loses a map or moves one that
is already published.
"""

from space_map_data.constants.manifests.textures import ALT_INFIX, rank_by_body


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

    def test_sibling_layers_do_not_compete_with_the_surface(self):
        entries = [
            _entry("naif-399", "earth.tif"),
            _entry("naif-399", "night.tif", type="cylindrical_night_lights"),
        ]
        assert rank_by_body(entries) == {"earth.tif": "naif-399"}
