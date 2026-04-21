"""Tests for space_map_data.export.images."""

from pathlib import Path

import orjson
import pytest

from space_map_data.export import images as images_mod
from space_map_data.export.images import (
    _is_acceptable,
    _load_attribution,
    _plain_text,
    collect_object_images,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "image_metadata"


def _write_meta(
    dir_: Path,
    filename: str,
    license_value: str | None,
    *,
    artist: str | None = None,
    credit: str | None = None,
    license_url: str | None = None,
) -> None:
    em: dict = {}
    if license_value is not None:
        em["LicenseShortName"] = {"value": license_value}
    if artist is not None:
        em["Artist"] = {"value": artist}
    if credit is not None:
        em["Credit"] = {"value": credit}
    if license_url is not None:
        em["LicenseUrl"] = {"value": license_url}
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


class TestPlainText:
    """_plain_text"""

    def test_returns_none_for_missing_field(self):
        assert _plain_text(None) is None

    def test_returns_none_for_empty_value(self):
        assert _plain_text({"value": ""}) is None

    def test_strips_html_tags(self):
        raw = '<a href="/wiki/User:foo" class="external">foo</a>'
        assert _plain_text({"value": raw}) == "foo"

    def test_decodes_html_entities(self):
        assert _plain_text({"value": "Foo &amp; Bar"}) == "Foo & Bar"

    def test_collapses_whitespace(self):
        raw = "  Hubble Space Telescope  \n  /Michael E. Brown  "
        assert _plain_text({"value": raw}) == "Hubble Space Telescope /Michael E. Brown"

    def test_handles_multilang_shape_prefers_english(self):
        field = {"value": {"_type": "lang", "en": "English name", "ja": "日本語"}}
        assert _plain_text(field) == "English name"

    def test_handles_multilang_falls_back_to_any_language(self):
        field = {"value": {"_type": "lang", "ja": "日本語"}}
        assert _plain_text(field) == "日本語"


class TestLoadAttributionRealData:
    """_load_attribution against real Commons metadata fixtures."""

    @pytest.fixture(autouse=True)
    def _point_at_fixtures(self, monkeypatch):
        monkeypatch.setattr(images_mod, "_METADATA_DIR", _FIXTURES)

    @pytest.mark.parametrize(
        "fixture_stem,expected_license",
        [
            ("pd_asteroid", "Public domain"),
            ("cc_by_sa_3", "CC BY-SA 3.0"),
            ("cc_by_4", "CC BY 4.0"),
            ("cc_by_sa_4", "CC BY-SA 4.0"),
        ],
    )
    def test_license_tag(self, fixture_stem, expected_license):
        result = _load_attribution(fixture_stem)
        assert result is not None
        assert result["license"] == expected_license

    def test_pd_fixture_has_plain_artist(self):
        result = _load_attribution("pd_asteroid")
        assert result is not None
        assert result["artist"] == "Hubble Space Telescope/Michael E. Brown"

    def test_cc_fixture_strips_html_from_artist(self):
        # Artist field in this fixture is an <a> tag wrapping a Japanese username.
        result = _load_attribution("cc_by_sa_4")
        assert result is not None
        assert result["artist"] == "神威・みーちゃん"

    def test_cc_fixture_has_license_url(self):
        result = _load_attribution("cc_by_sa_4")
        assert result is not None
        assert result["license_url"] == "https://creativecommons.org/licenses/by-sa/4.0"

    def test_pd_fixture_has_no_license_url(self):
        result = _load_attribution("pd_asteroid")
        assert result is not None
        assert "license_url" not in result


class TestLoadAttributionEdgeCases:
    """_load_attribution with fabricated metadata."""

    @pytest.fixture
    def meta_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(images_mod, "_METADATA_DIR", tmp_path)
        return tmp_path

    def test_no_metadata_file_drops(self, meta_dir):
        assert _load_attribution("missing") is None

    def test_missing_license_key_drops(self, meta_dir):
        _write_meta(meta_dir, "x", None)
        assert _load_attribution("x") is None

    def test_empty_license_drops(self, meta_dir):
        _write_meta(meta_dir, "x", "")
        assert _load_attribution("x") is None

    def test_whitespace_only_license_drops(self, meta_dir):
        _write_meta(meta_dir, "x", "   ")
        assert _load_attribution("x") is None

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
        assert _load_attribution("x") is None

    def test_gfdl_only_drops(self, meta_dir):
        _write_meta(meta_dir, "x", "GFDL")
        assert _load_attribution("x") is None

    def test_gfdl_with_cc_picks_cc(self, meta_dir):
        _write_meta(meta_dir, "a", "CC BY-SA 3.0 or GFDL")
        _write_meta(meta_dir, "b", "GFDL or CC BY-SA 3.0")
        assert _load_attribution("a") == {"license": "CC BY-SA 3.0"}
        assert _load_attribution("b") == {"license": "CC BY-SA 3.0"}

    def test_multi_license_picks_first_non_gfdl_acceptable(self, meta_dir):
        _write_meta(meta_dir, "x", "CC BY-SA 4.0 or CC BY-SA 3.0 or GFDL")
        result = _load_attribution("x")
        assert result is not None
        assert result["license"] == "CC BY-SA 4.0"

    def test_nc_in_multi_falls_back_to_free_sibling(self, meta_dir):
        _write_meta(meta_dir, "x", "CC BY-NC 4.0 or CC BY 4.0")
        result = _load_attribution("x")
        assert result is not None
        assert result["license"] == "CC BY 4.0"

    def test_corrupt_json_drops(self, meta_dir):
        (meta_dir / "bad.json").write_text("{not json")
        assert _load_attribution("bad") is None

    def test_artist_present(self, meta_dir):
        _write_meta(meta_dir, "x", "CC BY 4.0", artist="NASA/JPL")
        result = _load_attribution("x")
        assert result is not None
        assert result["artist"] == "NASA/JPL"

    def test_artist_absent_falls_back_to_credit(self, meta_dir):
        _write_meta(meta_dir, "x", "CC BY 4.0", credit="ESA/Hubble")
        result = _load_attribution("x")
        assert result is not None
        assert result["artist"] == "ESA/Hubble"

    def test_artist_both_missing_omits_key(self, meta_dir):
        _write_meta(meta_dir, "x", "CC BY 4.0")
        result = _load_attribution("x")
        assert result is not None
        assert "artist" not in result

    def test_license_url_included_when_present(self, meta_dir):
        _write_meta(
            meta_dir,
            "x",
            "CC BY 4.0",
            license_url="https://creativecommons.org/licenses/by/4.0",
        )
        result = _load_attribution("x")
        assert result is not None
        assert result["license_url"] == "https://creativecommons.org/licenses/by/4.0"


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
        artist: str | None = None,
        license_url: str | None = None,
    ) -> None:
        (layout[where] / filename).write_bytes(b"img")
        if license_value is not None:
            _write_meta(
                layout["meta"],
                filename,
                license_value,
                artist=artist,
                license_url=license_url,
            )

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

    def test_entry_carries_attribution_fields(self, layout):
        self._stage(
            layout,
            "A.jpg",
            "CC BY 4.0",
            artist="NASA/JPL",
            license_url="https://creativecommons.org/licenses/by/4.0",
        )
        result = collect_object_images({"image": ["A.jpg"]}, [])
        assert result is not None
        assert result[0]["license"] == "CC BY 4.0"
        assert result[0]["artist"] == "NASA/JPL"
        assert result[0]["license_url"] == "https://creativecommons.org/licenses/by/4.0"
