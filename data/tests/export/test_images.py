"""Tests for space_map_data.export.images."""

from pathlib import Path

import orjson
import pytest

from space_map_data.export import images as images_mod
from space_map_data.export.images import (
    _is_acceptable,
    _license_is_servable,
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


class TestLicenseIsServableRealData:
    """_license_is_servable against real Commons metadata fixtures."""

    @pytest.fixture(autouse=True)
    def _point_at_fixtures(self, monkeypatch):
        monkeypatch.setattr(images_mod, "_METADATA_DIR", _FIXTURES)

    @pytest.mark.parametrize(
        "fixture_stem",
        ["pd_asteroid", "cc_by_sa_3", "cc_by_4", "cc_by_sa_4"],
    )
    def test_real_fixtures_pass(self, fixture_stem):
        assert _license_is_servable(fixture_stem)


class TestLicenseIsServableEdgeCases:
    """_license_is_servable with fabricated metadata."""

    @pytest.fixture
    def meta_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(images_mod, "_METADATA_DIR", tmp_path)
        return tmp_path

    def test_no_metadata_file_drops(self, meta_dir):
        assert not _license_is_servable("missing")

    def test_missing_license_key_drops(self, meta_dir):
        _write_meta(meta_dir, "x", None)
        assert not _license_is_servable("x")

    def test_empty_license_drops(self, meta_dir):
        _write_meta(meta_dir, "x", "")
        assert not _license_is_servable("x")

    def test_whitespace_only_license_drops(self, meta_dir):
        _write_meta(meta_dir, "x", "   ")
        assert not _license_is_servable("x")

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
        assert not _license_is_servable("x")

    def test_gfdl_only_drops(self, meta_dir):
        _write_meta(meta_dir, "x", "GFDL")
        assert not _license_is_servable("x")

    def test_gfdl_with_cc_passes(self, meta_dir):
        _write_meta(meta_dir, "a", "CC BY-SA 3.0 or GFDL")
        _write_meta(meta_dir, "b", "GFDL or CC BY-SA 3.0")
        assert _license_is_servable("a")
        assert _license_is_servable("b")

    def test_multi_license_with_free_tag_passes(self, meta_dir):
        _write_meta(meta_dir, "x", "CC BY-SA 4.0 or CC BY-SA 3.0 or GFDL")
        assert _license_is_servable("x")

    def test_nc_in_multi_passes_when_free_sibling_present(self, meta_dir):
        _write_meta(meta_dir, "x", "CC BY-NC 4.0 or CC BY 4.0")
        assert _license_is_servable("x")

    def test_corrupt_json_drops(self, meta_dir):
        (meta_dir / "bad.json").write_text("{not json")
        assert not _license_is_servable("bad")


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
        _write_meta(layout["meta"], "A.jpg", "Public domain")
        assert collect_object_images({"image": ["A.jpg"]}, []) is None

    def test_drops_when_metadata_missing(self, layout):
        (layout["thumb"] / "A.jpg").write_bytes(b"img")
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

    def test_entry_has_only_file_source_url_and_kind(self, layout):
        # Attribution fields are intentionally *not* included; frontend
        # reads them from the separate metadata JSON.
        self._stage(layout, "A.jpg", "CC BY 4.0")
        result = collect_object_images({"image": ["A.jpg"]}, [])
        assert result is not None
        assert set(result[0].keys()) == {"file", "source_url", "kind"}

    def test_excluded_prefix_silently_dropped(self, layout, caplog):
        # Matches the download-time exclusion list; shouldn't emit INFO/WARN
        # noise since we know these aren't on disk by design.
        caplog.set_level("INFO", logger="space_map_data.export.images")
        result = collect_object_images(
            {"image": ["Орбита_астероида_1234.png", "Орбита_кометы_175P.jpg"]}, []
        )
        assert result is None
        assert caplog.records == []
