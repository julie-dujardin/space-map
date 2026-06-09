"""Tests for space_map_data.ingest.providers.image_selection.

The DB-update step is mechanical — these tests cover the pure-function core
(``_select_for_qid``) over a staged tmp-path layout, so the failure-mode
matrix is observable: missing metadata, non-servable parent + servable
sibling, multi-tree object, etc.
"""

import json
from collections.abc import Sequence

import orjson
import pytest

from space_map_data.constants.providers import LANGUAGES
from space_map_data.ingest.providers import image_selection
from space_map_data.utils import commons_images as ci


@pytest.fixture
def layout(tmp_path, monkeypatch):
    """Re-root the various Commons / Wikidata / Wikipedia paths under tmp_path."""
    download_dir = tmp_path / "downloads"
    sources_metadata_dir = download_dir / "sources" / "metadata"
    commons_dir = download_dir / "sources" / "images" / "commons"
    images_dir = commons_dir / "images"
    wikidata_dir = sources_metadata_dir / "wikidata" / "objects"
    wiki_dir = sources_metadata_dir / "wikipedia"
    images_dir.mkdir(parents=True)
    wikidata_dir.mkdir(parents=True)
    wiki_dir.mkdir(parents=True)
    monkeypatch.setattr(image_selection, "SOURCES_METADATA_DIR", sources_metadata_dir)
    monkeypatch.setattr(
        image_selection,
        "OBJECT_IMAGES_PATH",
        commons_dir / "object_images.json",
    )
    monkeypatch.setattr(ci, "IMAGES_DIR", images_dir)
    return {
        "download": download_dir,
        "images": images_dir,
        "wikidata": wikidata_dir,
        "wiki": wiki_dir,
    }


def _stage_wikidata(
    layout,
    qid: str,
    *,
    p18: Sequence[str] = (),
    p154: Sequence[str] = (),
    sitelink_count: int = 0,
):
    """Write a stub Wikidata entity JSON with P18 / P154 claims."""
    claims: dict = {}
    if p18:
        claims["P18"] = [
            {"rank": "normal", "mainsnak": {"datavalue": {"value": f}}} for f in p18
        ]
    if p154:
        claims["P154"] = [
            {"rank": "normal", "mainsnak": {"datavalue": {"value": f}}} for f in p154
        ]
    sitelinks = {
        f"site{i}wiki": {"site": f"site{i}wiki", "title": f"{qid}-t{i}"}
        for i in range(sitelink_count)
    }
    (layout["wikidata"] / f"{qid}.json").write_bytes(
        orjson.dumps({"id": qid, "claims": claims, "sitelinks": sitelinks})
    )


def _stage_pageimage(layout, lang: str, qid: str, filename: str):
    """Write a stub Wikipedia summary that points at a Commons file."""
    lang_dir = layout["wiki"] / lang
    lang_dir.mkdir(exist_ok=True)
    (lang_dir / f"{qid}.json").write_bytes(
        orjson.dumps(
            {
                "original": {
                    "source": (
                        f"https://upload.wikimedia.org/wikipedia/commons/x/y/{filename}"
                    )
                }
            }
        )
    )


def _stage_metadata(
    layout,
    filename: str,
    *,
    license_servable: bool = True,
    derived_from: Sequence[str] = (),
    other_versions: Sequence[str] = (),
    assessments: str | None = None,
    globalusage: int = 0,
    width: int = 2000,
    height: int = 2000,
):
    """Write a metadata.json under ``commons/images/<filename>/``."""
    d = layout["images"] / filename
    d.mkdir(parents=True, exist_ok=True)
    em: dict = {
        "LicenseShortName": {"value": "CC BY-SA 4.0"},
    }
    if assessments is not None:
        em["Assessments"] = {"value": assessments}
    payload = {
        "filename": filename,
        "imageinfo": {"extmetadata": em, "width": width, "height": height},
        "license_servable": license_servable,
        "derived_from": list(derived_from),
        "other_versions": list(other_versions),
        "globalusage": [{"wiki": f"w{i}.example"} for i in range(globalusage)],
    }
    (d / "metadata.json").write_bytes(orjson.dumps(payload))


class TestSelectForQid:
    def test_no_data_returns_empty(self, layout):
        assert (
            image_selection._select_for_qid(
                "Q1234", {}, layout["wikidata"], aux_pid="P154", aux_kind="logo"
            )
            == []
        )

    def test_single_p18_pass_through(self, layout):
        _stage_wikidata(layout, "Q1234", p18=["A.jpg"])
        _stage_metadata(layout, "A.jpg")
        result = image_selection._select_for_qid(
            "Q1234", {}, layout["wikidata"], aux_pid="P154", aux_kind="logo"
        )
        assert result == [{"file": "A.jpg", "kind": "photo"}]

    def test_canonicalizes_space_to_underscore(self, layout):
        _stage_wikidata(layout, "Q1234", p18=["My File.jpg"])
        _stage_metadata(layout, "My_File.jpg")
        result = image_selection._select_for_qid(
            "Q1234", {}, layout["wikidata"], aux_pid="P154", aux_kind="logo"
        )
        assert result == [{"file": "My_File.jpg", "kind": "photo"}]

    def test_p154_logo_kind(self, layout):
        _stage_wikidata(layout, "Q1234", p154=["Logo.svg"])
        _stage_metadata(layout, "Logo.svg")
        result = image_selection._select_for_qid(
            "Q1234", {}, layout["wikidata"], aux_pid="P154", aux_kind="logo"
        )
        assert result == [{"file": "Logo.svg", "kind": "logo"}]

    def test_dedupes_p18_and_pageimage(self, layout):
        _stage_wikidata(layout, "Q1234", p18=["Hero.jpg"])
        _stage_pageimage(layout, LANGUAGES[0], "Q1234", "Hero.jpg")
        _stage_metadata(layout, "Hero.jpg")
        result = image_selection._select_for_qid(
            "Q1234", {}, layout["wikidata"], aux_pid="P154", aux_kind="logo"
        )
        assert result == [{"file": "Hero.jpg", "kind": "photo"}]

    def test_excluded_prefix_skipped(self, layout):
        # Russian-wiki orbit-diagram noise filenames are dropped at discovery.
        _stage_pageimage(layout, "ru", "Q1234", "Орбита_астероида_1234.png")
        _stage_metadata(layout, "Орбита_астероида_1234.png")
        assert (
            image_selection._select_for_qid(
                "Q1234", {}, layout["wikidata"], aux_pid="P154", aux_kind="logo"
            )
            == []
        )

    def test_picks_featured_tree_member_over_direct_pageimage(self, layout):
        # The un-centered raw is the Wikidata pageimage; the centered crop
        # is featured. The crop should win even though it's not a direct
        # candidate.
        _stage_wikidata(layout, "Q308", p18=["Mercury_raw.jpg"])
        _stage_metadata(
            layout, "Mercury_raw.jpg", other_versions=["Mercury_centered.jpg"]
        )
        _stage_metadata(
            layout, "Mercury_centered.jpg", assessments="featured", globalusage=2000
        )
        result = image_selection._select_for_qid(
            "Q308", {}, layout["wikidata"], aux_pid="P154", aux_kind="logo"
        )
        assert result == [{"file": "Mercury_centered.jpg", "kind": "photo"}]

    def test_pageimage_count_breaks_assessment_tie(self, layout):
        # Two unrelated direct candidates in the SAME tree (siblings via
        # shared parent). Both un-assessed; the one chosen by more language
        # wikis wins.
        _stage_wikidata(layout, "Q1234", p18=["primary.jpg"])
        for lang in LANGUAGES[:3]:
            _stage_pageimage(layout, lang, "Q1234", "primary.jpg")
        _stage_pageimage(layout, LANGUAGES[3], "Q1234", "secondary.jpg")
        _stage_metadata(layout, "primary.jpg", derived_from=["common-parent.jpg"])
        _stage_metadata(layout, "secondary.jpg", derived_from=["common-parent.jpg"])
        _stage_metadata(layout, "common-parent.jpg")
        result = image_selection._select_for_qid(
            "Q1234", {}, layout["wikidata"], aux_pid="P154", aux_kind="logo"
        )
        # One tree → one selection; primary.jpg has 4 (P18 + 3 pageimages),
        # secondary 1, common-parent 0. Primary wins.
        assert result == [{"file": "primary.jpg", "kind": "photo"}]

    def test_unrelated_photos_yield_two_entries(self, layout):
        # Two truly unrelated photos: no shared tree, both ship.
        _stage_wikidata(layout, "Q1234", p18=["photo-1.jpg"])
        _stage_pageimage(layout, "en", "Q1234", "photo-2.jpg")
        _stage_metadata(layout, "photo-1.jpg")
        _stage_metadata(layout, "photo-2.jpg")
        result = image_selection._select_for_qid(
            "Q1234", {}, layout["wikidata"], aux_pid="P154", aux_kind="logo"
        )
        assert result == [
            {"file": "photo-1.jpg", "kind": "photo"},
            {"file": "photo-2.jpg", "kind": "photo"},
        ]

    def test_falls_back_to_servable_direct_when_tree_winner_not_servable(self, layout):
        # Featured tree-only crop has a non-free license; the direct
        # candidate is plain CC BY-SA. The export must still receive a
        # servable file — fall back to the next-best in the component.
        _stage_wikidata(layout, "Q1234", p18=["raw.jpg"])
        _stage_metadata(layout, "raw.jpg", other_versions=["fancy_but_nonfree.jpg"])
        _stage_metadata(
            layout,
            "fancy_but_nonfree.jpg",
            assessments="featured",
            license_servable=False,
        )
        result = image_selection._select_for_qid(
            "Q1234", {}, layout["wikidata"], aux_pid="P154", aux_kind="logo"
        )
        assert result == [{"file": "raw.jpg", "kind": "photo"}]


class TestReadObjectImages:
    def test_missing_file_returns_empty(self, layout):
        assert image_selection.read_object_images() == {}

    def test_round_trip_via_write_cache(self, layout):
        selections = {
            "naif-199": [{"file": "Mercury.jpg", "kind": "photo"}],
            "naif-299": [{"file": "Venus.jpg", "kind": "photo"}],
        }
        image_selection._write_cache(
            image_selection.OBJECT_IMAGES_PATH, "objects", selections
        )
        assert image_selection.read_object_images() == selections

    def test_keys_are_full_object_ids(self, layout):
        # Sanity-check the schema: keys carry the namespace prefix
        # (naif-, spkid-, norad-, ...), not bare numeric values.
        image_selection._write_cache(
            image_selection.OBJECT_IMAGES_PATH,
            "objects",
            {"naif-399": [{"file": "Earth.jpg", "kind": "photo"}]},
        )
        payload = json.loads(image_selection.OBJECT_IMAGES_PATH.read_text())
        assert "naif-399" in payload["objects"]
        assert "399" not in payload["objects"]
        assert payload["schema_version"] == image_selection.SCHEMA_VERSION


def _stage_member(
    layout,
    qid: str,
    *,
    photo: str,
    sitelinks: int,
    width: int = 2000,
    height: int = 2000,
):
    """One-call stub: a member with a sitelink count and a single P18 photo."""
    _stage_wikidata(layout, qid, p18=[photo], sitelink_count=sitelinks)
    _stage_metadata(layout, photo, width=width, height=height)


class TestRankMembersBySitelinks:
    def test_sorts_descending_by_sitelinks(self, layout):
        _stage_wikidata(layout, "Q1", sitelink_count=2)
        _stage_wikidata(layout, "Q2", sitelink_count=10)
        _stage_wikidata(layout, "Q3", sitelink_count=5)
        ranked = image_selection._rank_members_by_sitelinks(
            ["Q1", "Q2", "Q3"], layout["wikidata"], {}
        )
        assert ranked == ["Q2", "Q3", "Q1"]

    def test_lex_qid_breaks_ties(self, layout):
        _stage_wikidata(layout, "QB", sitelink_count=3)
        _stage_wikidata(layout, "QA", sitelink_count=3)
        ranked = image_selection._rank_members_by_sitelinks(
            ["QB", "QA"], layout["wikidata"], {}
        )
        assert ranked == ["QA", "QB"]

    def test_missing_entity_treated_as_zero(self, layout):
        _stage_wikidata(layout, "Q1", sitelink_count=5)
        # Q2 has no JSON on disk
        ranked = image_selection._rank_members_by_sitelinks(
            ["Q1", "Q2"], layout["wikidata"], {}
        )
        assert ranked == ["Q1", "Q2"]

    def test_deduplicates_input(self, layout):
        _stage_wikidata(layout, "Q1", sitelink_count=5)
        ranked = image_selection._rank_members_by_sitelinks(
            ["Q1", "Q1", "Q1"], layout["wikidata"], {}
        )
        assert ranked == ["Q1"]


class TestResolutionAtLeast:
    def test_passes_above_floor(self):
        meta = {"imageinfo": {"width": 1000, "height": 900}}
        assert image_selection._resolution_at_least(meta, 800)

    def test_uses_min_axis(self):
        meta = {"imageinfo": {"width": 4000, "height": 600}}
        # min(4000, 600) = 600 < 800 → fail.
        assert not image_selection._resolution_at_least(meta, 800)

    def test_no_metadata(self):
        assert not image_selection._resolution_at_least(None, 800)

    def test_no_imageinfo(self):
        assert not image_selection._resolution_at_least({}, 800)

    def test_non_int_dims(self):
        meta = {"imageinfo": {"width": None, "height": 1000}}
        assert not image_selection._resolution_at_least(meta, 800)


class TestPickFallbackImages:
    def _view(self, metadata_cache):
        return image_selection._MetadataView(metadata_cache)

    def test_empty_members_returns_empty(self, layout):
        meta_cache: dict[str, dict | None] = {}
        assert (
            image_selection._pick_fallback_images(
                [], self._view(meta_cache), meta_cache, layout["wikidata"]
            )
            == []
        )

    def test_per_member_cap_of_three(self, layout):
        # One member contributes four photos; we keep three in the first pass.
        _stage_wikidata(
            layout, "Q1", p18=["a.jpg", "b.jpg", "c.jpg", "d.jpg"], sitelink_count=10
        )
        for f in ("a.jpg", "b.jpg", "c.jpg", "d.jpg"):
            _stage_metadata(layout, f)
        # No second member to backfill, so the second pass drops the cap and
        # the fourth photo gets in. To prove the cap, give it nine candidates.
        # Easier: assert that with a SECOND high-sitelink member supplying
        # extras, the first member contributes exactly 3 before the second
        # starts.
        _stage_wikidata(layout, "Q2", p18=["e.jpg", "f.jpg"], sitelink_count=5)
        for f in ("e.jpg", "f.jpg"):
            _stage_metadata(layout, f)
        meta_cache: dict[str, dict | None] = {}
        out = image_selection._pick_fallback_images(
            ["Q1", "Q2"], self._view(meta_cache), meta_cache, layout["wikidata"]
        )
        files = [p["file"] for p in out]
        # Q1's first three come before any Q2 photo (Q1 has higher sitelink count).
        assert files.index("e.jpg") > 2
        assert files.index("f.jpg") > 2
        # And d.jpg comes after Q2's photos thanks to the per-member cap on Q1.
        assert files.index("d.jpg") > files.index("e.jpg")

    def test_resolution_floor_drops_small_images(self, layout):
        _stage_wikidata(layout, "Q1", p18=["big.jpg", "tiny.jpg"], sitelink_count=10)
        _stage_metadata(layout, "big.jpg", width=2000, height=2000)
        _stage_metadata(layout, "tiny.jpg", width=300, height=300)
        meta_cache: dict[str, dict | None] = {}
        out = image_selection._pick_fallback_images(
            ["Q1"], self._view(meta_cache), meta_cache, layout["wikidata"]
        )
        assert [p["file"] for p in out] == ["big.jpg"]

    def test_cross_member_filename_dedup(self, layout):
        # Two members both list the same Commons file (sometimes a featured
        # asteroid-belt schematic). Surface it once.
        _stage_wikidata(layout, "Q1", p18=["shared.jpg"], sitelink_count=10)
        _stage_wikidata(layout, "Q2", p18=["shared.jpg"], sitelink_count=5)
        _stage_metadata(layout, "shared.jpg")
        meta_cache: dict[str, dict | None] = {}
        out = image_selection._pick_fallback_images(
            ["Q1", "Q2"], self._view(meta_cache), meta_cache, layout["wikidata"]
        )
        assert [p["file"] for p in out] == ["shared.jpg"]

    def test_hero_promoted_to_index_zero(self, layout):
        # Top member has only a gallery-resolution photo; the next member has
        # a hero-resolution photo. The hero leads even though it's a lower-
        # ranked member.
        _stage_member(
            layout, "Q1", photo="leader-small.jpg", sitelinks=10, width=900, height=900
        )
        _stage_member(
            layout, "Q2", photo="hero-big.jpg", sitelinks=5, width=2000, height=2000
        )
        meta_cache: dict[str, dict | None] = {}
        out = image_selection._pick_fallback_images(
            ["Q1", "Q2"], self._view(meta_cache), meta_cache, layout["wikidata"]
        )
        files = [p["file"] for p in out]
        assert files[0] == "hero-big.jpg"
        assert "leader-small.jpg" in files

    def test_no_hero_resolution_falls_back_to_gallery_leader(self, layout):
        # Nobody clears the hero floor; ranking is pure sitelink-order.
        _stage_member(
            layout, "Q1", photo="a.jpg", sitelinks=10, width=1000, height=1000
        )
        _stage_member(layout, "Q2", photo="b.jpg", sitelinks=5, width=1000, height=1000)
        meta_cache: dict[str, dict | None] = {}
        out = image_selection._pick_fallback_images(
            ["Q1", "Q2"], self._view(meta_cache), meta_cache, layout["wikidata"]
        )
        assert [p["file"] for p in out] == ["a.jpg", "b.jpg"]

    def test_drops_member_logo_kind(self, layout):
        # The member's own corporate logo (P154) shouldn't represent the group.
        _stage_wikidata(
            layout, "Q1", p18=["photo.jpg"], p154=["logo.svg"], sitelink_count=10
        )
        _stage_metadata(layout, "photo.jpg")
        _stage_metadata(layout, "logo.svg")
        meta_cache: dict[str, dict | None] = {}
        out = image_selection._pick_fallback_images(
            ["Q1"], self._view(meta_cache), meta_cache, layout["wikidata"]
        )
        assert [(p["file"], p["kind"]) for p in out] == [("photo.jpg", "photo")]

    def test_stops_at_target_count(self, layout):
        # Twenty members each with one photo — gallery caps at 15.
        members = []
        for i in range(20):
            qid = f"Q{i:02d}"
            photo = f"p{i:02d}.jpg"
            _stage_member(layout, qid, photo=photo, sitelinks=100 - i)
            members.append(qid)
        meta_cache: dict[str, dict | None] = {}
        out = image_selection._pick_fallback_images(
            members, self._view(meta_cache), meta_cache, layout["wikidata"]
        )
        assert len(out) == image_selection.GROUP_FALLBACK_TARGET_COUNT

    def test_sub_target_drops_per_member_cap(self, layout):
        # One member with 5 photos, no others. First pass caps at 3; second
        # pass drops the cap and lets the rest through.
        _stage_wikidata(
            layout,
            "Q1",
            p18=["a.jpg", "b.jpg", "c.jpg", "d.jpg", "e.jpg"],
            sitelink_count=10,
        )
        for f in ("a.jpg", "b.jpg", "c.jpg", "d.jpg", "e.jpg"):
            _stage_metadata(layout, f)
        meta_cache: dict[str, dict | None] = {}
        out = image_selection._pick_fallback_images(
            ["Q1"], self._view(meta_cache), meta_cache, layout["wikidata"]
        )
        assert len(out) == 5

    def test_exclude_files_skipped(self, layout):
        # Existing P154 picked shared.jpg; member fallback must not re-emit it.
        _stage_wikidata(
            layout, "Q1", p18=["shared.jpg", "other.jpg"], sitelink_count=10
        )
        _stage_metadata(layout, "shared.jpg")
        _stage_metadata(layout, "other.jpg")
        meta_cache: dict[str, dict | None] = {}
        out = image_selection._pick_fallback_images(
            ["Q1"],
            self._view(meta_cache),
            meta_cache,
            layout["wikidata"],
            exclude_files={"shared.jpg"},
        )
        assert [p["file"] for p in out] == ["other.jpg"]

    def test_target_count_caps_total(self, layout):
        # Augmenting a group with 13 existing entries should add at most 2.
        _stage_wikidata(
            layout, "Q1", p18=["a.jpg", "b.jpg", "c.jpg"], sitelink_count=10
        )
        for f in ("a.jpg", "b.jpg", "c.jpg"):
            _stage_metadata(layout, f)
        meta_cache: dict[str, dict | None] = {}
        out = image_selection._pick_fallback_images(
            ["Q1"],
            self._view(meta_cache),
            meta_cache,
            layout["wikidata"],
            target_count=2,
        )
        assert len(out) == 2

    def test_promote_hero_false_preserves_sitelink_order(self, layout):
        # When promote_hero=False we don't reorder for hero-resolution; the
        # highest-sitelink member's gallery-floor photo leads even if a
        # lower-ranked member has a hero-res shot.
        _stage_member(
            layout, "Q1", photo="leader.jpg", sitelinks=10, width=900, height=900
        )
        _stage_member(
            layout, "Q2", photo="hero-big.jpg", sitelinks=5, width=2000, height=2000
        )
        meta_cache: dict[str, dict | None] = {}
        out = image_selection._pick_fallback_images(
            ["Q1", "Q2"],
            self._view(meta_cache),
            meta_cache,
            layout["wikidata"],
            promote_hero=False,
        )
        assert [p["file"] for p in out] == ["leader.jpg", "hero-big.jpg"]

    def test_target_count_zero_returns_empty(self, layout):
        _stage_member(layout, "Q1", photo="a.jpg", sitelinks=10)
        meta_cache: dict[str, dict | None] = {}
        out = image_selection._pick_fallback_images(
            ["Q1"],
            self._view(meta_cache),
            meta_cache,
            layout["wikidata"],
            target_count=0,
        )
        assert out == []
