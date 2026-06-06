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
    layout, qid: str, *, p18: Sequence[str] = (), p154: Sequence[str] = ()
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
    (layout["wikidata"] / f"{qid}.json").write_bytes(
        orjson.dumps({"id": qid, "claims": claims})
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
        "imageinfo": {"extmetadata": em},
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
