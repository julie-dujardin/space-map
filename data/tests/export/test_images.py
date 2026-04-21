"""Tests for space_map_data.export.images."""

from pathlib import Path

import orjson
import pytest

from space_map_data.export import images as images_mod
from space_map_data.export.images import (
    _is_acceptable,
    _select_license,
    collect_object_images,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "image_metadata"


def _write_meta(dir_: Path, filename: str, license_value: str | None) -> None:
    em: dict = {}
    if license_value is not None:
        em["LicenseShortName"] = {"value": license_value}
    payload = {"imageinfo": {"extmetadata": em}}
    (dir_ / f"{filename}.json").write_bytes(orjson.dumps(payload))


class TestIsAcceptable:
    """_is_acceptable"""

    @pytest.mark.parametrize(
        "tag",
        [
            "Public domain",
            "CC BY 4.0",
            "CC BY 2.5",
            "CC BY-SA 3.0",
            "CC BY-SA 4.0",
            "CC0",
            "GFDL",
            "OGL",
            "Attribution",
        ],
    )
    def test_free_licenses_accepted(self, tag):
        assert _is_acceptable(tag)

    @pytest.mark.parametrize(
        "tag",
        [
            "Fair use",
            "Non-free media",
            "All rights reserved",
            "CC BY-NC 4.0",
            "CC BY-NC-SA 4.0",
            "CC-BY-NC 2.0",
            "CC BY-ND 3.0",
            "cc by-nd 4.0",
        ],
    )
    def test_restricted_licenses_rejected(self, tag):
        assert not _is_acceptable(tag)


class TestSelectLicenseRealData:
    """_select_license against real Commons metadata fixtures."""

    @pytest.fixture(autouse=True)
    def _point_at_fixtures(self, monkeypatch):
        monkeypatch.setattr(images_mod, "_METADATA_DIR", _FIXTURES)

    @pytest.mark.parametrize(
        "fixture_stem,expected",
        [
            ("pd_asteroid", "Public domain"),
            ("cc_by_sa_3", "CC BY-SA 3.0"),
            ("cc_by_4", "CC BY 4.0"),
            ("cc_by_sa_4", "CC BY-SA 4.0"),
        ],
    )
    def test_returns_real_tag(self, fixture_stem, expected):
        assert _select_license(fixture_stem) == expected


class TestSelectLicenseEdgeCases:
    """_select_license with fabricated license strings."""

    @pytest.fixture
    def meta_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(images_mod, "_METADATA_DIR", tmp_path)
        return tmp_path

    def test_no_metadata_file_drops(self, meta_dir):
        assert _select_license("missing") is None

    def test_missing_license_key_drops(self, meta_dir):
        _write_meta(meta_dir, "x", None)
        assert _select_license("x") is None

    def test_empty_license_drops(self, meta_dir):
        _write_meta(meta_dir, "x", "")
        assert _select_license("x") is None

    def test_whitespace_only_license_drops(self, meta_dir):
        _write_meta(meta_dir, "x", "   ")
        assert _select_license("x") is None

    @pytest.mark.parametrize(
        "license_value",
        [
            "CC BY-NC 4.0",
            "CC BY-NC-SA 4.0",
            "CC BY-ND 3.0",
            "Fair use",
            "Non-free",
            "All rights reserved",
        ],
    )
    def test_restricted_license_drops(self, meta_dir, license_value):
        _write_meta(meta_dir, "x", license_value)
        assert _select_license("x") is None

    def test_gfdl_only_drops(self, meta_dir):
        _write_meta(meta_dir, "x", "GFDL")
        assert _select_license("x") is None

    def test_gfdl_with_cc_picks_cc(self, meta_dir):
        _write_meta(meta_dir, "a", "CC BY-SA 3.0 or GFDL")
        _write_meta(meta_dir, "b", "GFDL or CC BY-SA 3.0")
        assert _select_license("a") == "CC BY-SA 3.0"
        assert _select_license("b") == "CC BY-SA 3.0"

    def test_multi_license_picks_first_non_gfdl_acceptable(self, meta_dir):
        _write_meta(meta_dir, "x", "CC BY-SA 4.0 or CC BY-SA 3.0 or GFDL")
        assert _select_license("x") == "CC BY-SA 4.0"

    def test_nc_in_multi_falls_back_to_free_sibling(self, meta_dir):
        _write_meta(meta_dir, "x", "CC BY-NC 4.0 or CC BY 4.0")
        assert _select_license("x") == "CC BY 4.0"

    def test_corrupt_json_drops(self, meta_dir):
        (meta_dir / "bad.json").write_text("{not json")
        assert _select_license("bad") is None


class TestCollectObjectImages:
    """collect_object_images"""

    @pytest.fixture
    def layout(self, tmp_path, monkeypatch):
        thumb = tmp_path / "thumb"
        full = tmp_path / "full"
        meta = tmp_path / "metadata"
        thumb.mkdir()
        full.mkdir()
        meta.mkdir()
        monkeypatch.setattr(images_mod, "_IMAGES_DIR", tmp_path)
        monkeypatch.setattr(images_mod, "_THUMB_DIR", thumb)
        monkeypatch.setattr(images_mod, "_FULL_DIR", full)
        monkeypatch.setattr(images_mod, "_METADATA_DIR", meta)
        return {"thumb": thumb, "full": full, "meta": meta}

    def _stage(
        self,
        layout: dict[str, Path],
        filename: str,
        license_value: str | None = "Public domain",
        *,
        where: str = "thumb",
    ) -> None:
        (layout[where] / filename).write_bytes(b"img")
        if license_value is not None:
            _write_meta(layout["meta"], filename, license_value)

    def test_canonicalizes_wikidata_space_form_to_underscore(self, layout):
        # Wikidata claim arrives with spaces; disk and metadata use underscores.
        self._stage(layout, "Foo_bar.jpg", "Public domain")
        result = collect_object_images({"image": ["Foo bar.jpg"]}, [])
        assert result is not None
        assert len(result) == 1
        assert result[0]["file"] == "Foo_bar.jpg"

    def test_dedupes_across_p18_and_wikipedia_sources(self, layout):
        self._stage(layout, "A.jpg", "Public domain")
        result = collect_object_images({"image": ["A.jpg"]}, ["A.jpg"])
        assert result is not None
        assert len(result) == 1

    def test_dedupes_space_and_underscore_variants(self, layout):
        self._stage(layout, "A_b.jpg", "Public domain")
        result = collect_object_images({"image": ["A b.jpg", "A_b.jpg"]}, [])
        assert result is not None
        assert len(result) == 1

    def test_drops_when_not_on_disk(self, layout):
        _write_meta(layout["meta"], "A.jpg", "Public domain")  # metadata but no file
        assert collect_object_images({"image": ["A.jpg"]}, []) is None

    def test_drops_when_metadata_missing(self, layout):
        (layout["thumb"] / "A.jpg").write_bytes(b"img")  # file but no metadata
        assert collect_object_images({"image": ["A.jpg"]}, []) is None

    def test_drops_restricted_license(self, layout):
        self._stage(layout, "A.jpg", "CC BY-NC 4.0")
        assert collect_object_images({"image": ["A.jpg"]}, []) is None

    def test_logo_kind_assigned_to_p154(self, layout):
        self._stage(layout, "Logo.png", "Public domain")
        result = collect_object_images({"logo_image": ["Logo.png"]}, [])
        assert result is not None
        assert result[0]["kind"] == "logo"

    def test_photo_kind_assigned_to_p18_and_pageimage(self, layout):
        self._stage(layout, "A.jpg", "Public domain")
        self._stage(layout, "B.jpg", "Public domain")
        result = collect_object_images({"image": ["A.jpg"]}, ["B.jpg"])
        assert result is not None
        assert {e["file"]: e["kind"] for e in result} == {
            "A.jpg": "photo",
            "B.jpg": "photo",
        }

    def test_keeps_acceptable_and_drops_rest_in_same_call(self, layout):
        self._stage(layout, "bad.jpg", "CC BY-NC 4.0")
        self._stage(layout, "good.jpg", "Public domain")
        result = collect_object_images({"image": ["bad.jpg", "good.jpg"]}, [])
        assert result is not None
        assert [e["file"] for e in result] == ["good.jpg"]

    def test_encodes_source_url(self, layout):
        self._stage(layout, "A_(crop).jpg", "Public domain")
        result = collect_object_images({"image": ["A_(crop).jpg"]}, [])
        assert result is not None
        assert (
            result[0]["source_url"]
            == "https://commons.wikimedia.org/wiki/File:A_%28crop%29.jpg"
        )
