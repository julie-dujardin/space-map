"""Tests for space_map_data.utils.image_scoring."""

from space_map_data.utils import image_scoring


def _meta(
    *,
    assessments: str | None = None,
    derived_from: list[str] | None = None,
    other_versions: list[str] | None = None,
    globalusage: int = 0,
) -> dict:
    """Build a minimal metadata.json-shaped dict for tests."""
    em: dict = {}
    if assessments is not None:
        em["Assessments"] = {"value": assessments}
    return {
        "imageinfo": {"extmetadata": em},
        "derived_from": derived_from or [],
        "other_versions": other_versions or [],
        "globalusage": [{"wiki": f"w{i}.example"} for i in range(globalusage)],
    }


class TestAssessmentRank:
    def test_no_assessment_is_zero(self):
        assert image_scoring.assessment_rank({}) == 0
        assert image_scoring.assessment_rank(_meta()) == 0

    def test_featured_outranks_quality_outranks_valued(self):
        assert image_scoring.assessment_rank(_meta(assessments="featured")) == 3
        assert image_scoring.assessment_rank(_meta(assessments="quality")) == 2
        assert image_scoring.assessment_rank(_meta(assessments="valued")) == 1

    def test_multi_tag_takes_highest(self):
        assert image_scoring.assessment_rank(_meta(assessments="valued,featured")) == 3

    def test_unknown_tag_is_zero(self):
        assert image_scoring.assessment_rank(_meta(assessments="random_tag")) == 0

    def test_case_and_whitespace_insensitive(self):
        assert image_scoring.assessment_rank(_meta(assessments="  Featured  ")) == 3


class TestGlobalusageCount:
    def test_missing_is_zero(self):
        assert image_scoring.globalusage_count({}) == 0

    def test_count_is_list_length(self):
        assert image_scoring.globalusage_count(_meta(globalusage=42)) == 42


class TestTreeComponents:
    def test_isolated_files_each_in_own_component(self):
        meta = {"a.jpg": _meta(), "b.jpg": _meta()}
        assert image_scoring.tree_components(["a.jpg", "b.jpg"], meta) == [
            ["a.jpg"],
            ["b.jpg"],
        ]

    def test_parent_and_child_share_component(self):
        meta = {
            "parent.jpg": _meta(),
            "child.jpg": _meta(derived_from=["parent.jpg"]),
        }
        # Linked via derived_from, so both end up in one component.
        assert image_scoring.tree_components(["parent.jpg", "child.jpg"], meta) == [
            ["parent.jpg", "child.jpg"]
        ]

    def test_other_versions_also_links_components(self):
        meta = {
            "a.jpg": _meta(other_versions=["b.jpg"]),
            "b.jpg": _meta(),
        }
        assert image_scoring.tree_components(["a.jpg", "b.jpg"], meta) == [
            ["a.jpg", "b.jpg"]
        ]

    def test_unrelated_files_stay_separate(self):
        meta = {
            "a.jpg": _meta(derived_from=["a-orig.jpg"]),
            "b.jpg": _meta(derived_from=["b-orig.jpg"]),
        }
        assert image_scoring.tree_components(["a.jpg", "b.jpg"], meta) == [
            ["a.jpg"],
            ["b.jpg"],
        ]

    def test_missing_metadata_terminates_walk_cleanly(self):
        # Files missing from the metadata dict are leaves, not a KeyError.
        meta = {"a.jpg": _meta(derived_from=["unknown.jpg"])}
        assert image_scoring.tree_components(["a.jpg"], meta) == [["a.jpg"]]

    def test_siblings_via_shared_parent_in_same_component(self):
        # Siblings share a parent but don't list each other; forward-only BFS would miss this.
        meta = {
            "sib-a.jpg": _meta(derived_from=["common-parent.jpg"]),
            "sib-b.jpg": _meta(derived_from=["common-parent.jpg"]),
            "common-parent.jpg": _meta(),
        }
        assert image_scoring.tree_components(["sib-a.jpg", "sib-b.jpg"], meta) == [
            ["sib-a.jpg", "sib-b.jpg"]
        ]

    def test_empty_input(self):
        assert image_scoring.tree_components([], {}) == []


class TestBestInTree:
    def _scoring_inputs(self, meta_dict, direct_candidates):
        discovery_order = {n: i for i, n in enumerate(direct_candidates)}
        return meta_dict, {}, discovery_order

    def test_assessment_beats_pageimage_count(self):
        # Centered crop is featured; raw is the direct pageimage in 5 langs.
        # Featured wins regardless of the count gap.
        meta = {
            "raw.jpg": _meta(other_versions=["centered.jpg"]),
            "centered.jpg": _meta(assessments="featured"),
        }
        assert (
            image_scoring.best_in_tree(
                ["raw.jpg"], meta, {"raw.jpg": 5}, {"raw.jpg": 0}
            )
            == "centered.jpg"
        )

    def test_pageimage_count_beats_globalusage(self):
        # Tied on assessment (none). Count for THIS object wins over global popularity.
        meta = {
            "this-object-pick.jpg": _meta(
                other_versions=["other-popular.jpg"], globalusage=5
            ),
            "other-popular.jpg": _meta(globalusage=500),
        }
        assert (
            image_scoring.best_in_tree(
                ["this-object-pick.jpg"],
                meta,
                {"this-object-pick.jpg": 3, "other-popular.jpg": 0},
                {"this-object-pick.jpg": 0},
            )
            == "this-object-pick.jpg"
        )

    def test_globalusage_breaks_remaining_tie(self):
        meta = {
            "lo.jpg": _meta(other_versions=["hi.jpg"], globalusage=10),
            "hi.jpg": _meta(globalusage=200),
        }
        # Same assessment, same pageimage count → globalusage decides.
        assert (
            image_scoring.best_in_tree(
                ["lo.jpg"],
                meta,
                pageimage_count_for={},
                discovery_order_of={"lo.jpg": 0},
            )
            == "hi.jpg"
        )

    def test_discovery_order_breaks_total_tie(self):
        # Identical metadata; the earlier-discovered one wins.
        meta = {
            "first.jpg": _meta(other_versions=["second.jpg"]),
            "second.jpg": _meta(),
        }
        result = image_scoring.best_in_tree(
            ["first.jpg", "second.jpg"],
            meta,
            pageimage_count_for={},
            discovery_order_of={"first.jpg": 0, "second.jpg": 1},
        )
        assert result == "first.jpg"

    def test_tree_only_member_can_win(self):
        # A tree-only featured crop can beat a non-assessed direct pageimage.
        meta = {
            "direct.jpg": _meta(other_versions=["tree-only-crop.jpg"]),
            "tree-only-crop.jpg": _meta(assessments="featured"),
        }
        result = image_scoring.best_in_tree(
            ["direct.jpg"],
            meta,
            pageimage_count_for={"direct.jpg": 1},
            discovery_order_of={"direct.jpg": 0},
        )
        assert result == "tree-only-crop.jpg"

    def test_walks_tree_from_each_candidate_in_component(self):
        # The walk must reach all members from any sibling in the component.
        meta = {
            "sibling-a.jpg": _meta(derived_from=["parent.jpg"]),
            "sibling-b.jpg": _meta(derived_from=["parent.jpg"]),
            "parent.jpg": _meta(assessments="featured"),
        }
        result = image_scoring.best_in_tree(
            ["sibling-a.jpg", "sibling-b.jpg"],
            meta,
            pageimage_count_for={},
            discovery_order_of={"sibling-a.jpg": 0, "sibling-b.jpg": 1},
        )
        assert result == "parent.jpg"
